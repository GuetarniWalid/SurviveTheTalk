"""Story 6.13 Phase 2 — Investigation tooling for the Cartesia silent-stall bug.

Wraps pipecat 0.0.108's `CartesiaTTSService` with verbose loguru INFO logs
on every event that matters for diagnosing the 30%-rate freeze surfaced
during Story 6.9b's Pixel 9 smoke gate (2026-05-26, calls 149 + 151).

Three layers of instrumentation, gated by the `CARTESIA_INSTRUMENT=1`
env var so it stays opt-in in prod (the standing watchdog from AC1 is
the always-on safety net; this module is the diagnostic that runs only
when we want to capture a freeze):

  1. **WebSocket-level proxy** — `_LoggingWebsocket` wraps the underlying
     `websockets` connection so every `send()` (text + context_id +
     continue/cancel flags) and every `__anext__()` (Cartesia → us
     reply, with msg type + context_id) is logged BEFORE the parent
     pipecat code sees it. Authoritative trace of the wire protocol.
  2. **Context-lifecycle hooks** — overrides on the methods that
     manipulate audio-context state (`create_audio_context`,
     `remove_audio_context`, `_handle_interruption`,
     `on_audio_context_interrupted`, `on_audio_context_completed`)
     plus the high-level `flush_audio` and `run_tts`. Each logs the
     state of `audio_contexts` + `_turn_context_id` at entry so we can
     reconstruct the per-event sequence and spot the moment the
     pipeline loses track of an open Cartesia context.
  3. **Compact log prefix `[CART-INSTR]`** so an operator can grep the
     journalctl tail without drowning in unrelated pipeline noise.

Diagnostic hypothesis (Story 6.13 investigation, 2026-05-26): the
multi-frame freeze happens when an `InterruptionFrame` arrives
mid-utterance (Silero VAD detects ambient noise or user breath),
which calls `_handle_interruption` and resets `_turn_context_id = None`
WITHOUT first sending `cancel: true` for the in-flight Cartesia
context. The downstream code then opens a NEW context for any
remaining text, and the OLD context never receives its terminal
`continue=false` flush — so Cartesia keeps it open indefinitely,
waiting for more transcript. This module's logs validate (or
invalidate) the hypothesis by showing exactly which context ids
get a `cancel: true` send, which get a `flush` send, and which get
neither.

Switch off by setting `CARTESIA_INSTRUMENT=0` (or removing the env)
and `systemctl restart pipecat.service`. No production code path
changes when off.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger
from pipecat.frames.frames import CancelFrame, Frame, InterruptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.cartesia.tts import CartesiaTTSService


_LOG_PREFIX = "[CART-INSTR]"


def _truncate(value: str, limit: int = 60) -> str:
    """Cap log preview so a 200-token sentence doesn't blow up a journal line."""
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


class _LoggingWebsocket:
    """Transparent proxy over the Cartesia WebSocket connection that
    logs every send + recv before delegating to the wrapped object.

    Mirrors the surface the parent `CartesiaTTSService` actually uses:
    `send`, `__aiter__/__anext__` (for `async for msg in ws:`),
    `state`, and `close`. Other attribute reads fall through to the
    wrapped websocket via `__getattr__` so any future pipecat
    upgrade that touches other attributes still works.
    """

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    async def send(self, msg: Any) -> Any:
        # Cartesia send payloads are JSON strings. Parse them for the
        # human-readable log line; fall back to a raw preview if the
        # message ever turns out to be a non-JSON ping/keepalive.
        try:
            parsed = json.loads(msg)
            ctx = parsed.get("context_id", "?")
            cont = parsed.get("continue", "?")
            cancel = parsed.get("cancel", False)
            text = parsed.get("transcript", "")
            logger.info(
                "{} WS-SEND ctx={} continue={} cancel={} text_len={} text={!r}",
                _LOG_PREFIX,
                ctx,
                cont,
                cancel,
                len(text),
                _truncate(text),
            )
        except (ValueError, TypeError, AttributeError):
            logger.info(
                "{} WS-SEND raw={!r}",
                _LOG_PREFIX,
                _truncate(str(msg), 200),
            )
        return await self._ws.send(msg)

    # Hotfix 2026-05-26 — `websockets`' `ClientConnection` does NOT
    # expose `__anext__` directly even though it supports `async for`.
    # The original implementation called `self._ws.__anext__()` which
    # raised `AttributeError: 'ClientConnection' object has no
    # attribute '__anext__'`, which pipecat's WebsocketTTSService
    # caught and treated as a recv-failure → triggered an immediate
    # reconnect → infinite reconnect storm → Cartesia never sent
    # audio (Tina stayed silent on every call).
    #
    # Correct pattern for proxying an async iterable without making
    # assumptions about the underlying object's iteration internals:
    # `__aiter__` is a *plain* (non-async) function that returns a
    # fresh async generator delegating to the underlying `async for`.
    # This sidesteps the ambiguity of `async def __aiter__: yield`
    # (which Python interprets as an async-generator function — usable,
    # but reader-hostile and version-dependent semantics).
    def __aiter__(self) -> Any:
        return self._aiter_messages()

    async def _aiter_messages(self) -> Any:
        async for msg in self._ws:
            try:
                parsed = json.loads(msg)
                ctx = parsed.get("context_id", "?")
                typ = parsed.get("type", "?")
                done = parsed.get("done", None)
                extras = []
                if done is not None:
                    extras.append(f"done={done}")
                if typ == "chunk":
                    # Avoid logging the base64-encoded audio payload —
                    # signal that audio arrived without the bytes.
                    data_len = len(parsed.get("data", ""))
                    extras.append(f"chunk_b64_len={data_len}")
                extra_str = " " + " ".join(extras) if extras else ""
                logger.info(
                    "{} WS-RECV ctx={} type={}{}",
                    _LOG_PREFIX,
                    ctx,
                    typ,
                    extra_str,
                )
            except (ValueError, TypeError, AttributeError):
                logger.info(
                    "{} WS-RECV raw={!r}",
                    _LOG_PREFIX,
                    _truncate(str(msg), 200),
                )
            yield msg

    async def close(self) -> Any:
        logger.info("{} WS-CLOSE", _LOG_PREFIX)
        return await self._ws.close()

    def __getattr__(self, name: str) -> Any:
        # Fall through everything else (`state`, `close_code`,
        # transport-internal hooks) to the wrapped websocket.
        return getattr(self._ws, name)


class InstrumentedCartesiaTTSService(CartesiaTTSService):
    """Subclass that wraps the WebSocket and overrides every method
    that touches context-lifecycle state, adding [CART-INSTR] logs.

    Drop-in replacement for `CartesiaTTSService` — same constructor
    surface, same Settings type. Only effect on prod behaviour is
    additional log lines (loguru INFO level).
    """

    async def _connect_websocket(self) -> None:
        await super()._connect_websocket()
        # Wrap AFTER the parent established the raw websocket. If
        # the connection failed (`_websocket is None`), skip wrapping
        # so the parent's reconnect logic stays intact.
        if self._websocket is not None and not isinstance(
            self._websocket, _LoggingWebsocket
        ):
            logger.info(
                "{} websocket connected — installing logging proxy", _LOG_PREFIX
            )
            self._websocket = _LoggingWebsocket(self._websocket)

    async def run_tts(
        self, text: str, context_id: str
    ) -> AsyncGenerator[Frame | None, None]:
        logger.info(
            "{} run_tts ENTER ctx={} text_len={} text={!r} turn_ctx={}",
            _LOG_PREFIX,
            context_id,
            len(text),
            _truncate(text),
            self._turn_context_id,
        )
        try:
            async for frame in super().run_tts(text, context_id):
                if frame is not None:
                    logger.info(
                        "{} run_tts YIELD ctx={} frame_type={}",
                        _LOG_PREFIX,
                        context_id,
                        type(frame).__name__,
                    )
                yield frame
        finally:
            logger.info("{} run_tts EXIT ctx={}", _LOG_PREFIX, context_id)

    async def flush_audio(self, context_id: str | None = None) -> None:
        # `audio_context_available` is the gate used by the parent
        # `on_turn_context_completed` to decide whether to flush. If
        # this returns False on a context we EXPECTED to be flushed,
        # we've found the bug-class.
        avail = self.audio_context_available(context_id) if context_id else None
        active = (
            list(self.get_audio_contexts())
            if hasattr(self, "get_audio_contexts")
            else []
        )
        logger.info(
            "{} flush_audio ENTER ctx={} available={} active_ctxs={} turn_ctx={}",
            _LOG_PREFIX,
            context_id,
            avail,
            active,
            self._turn_context_id,
        )
        await super().flush_audio(context_id=context_id)
        logger.info("{} flush_audio EXIT ctx={}", _LOG_PREFIX, context_id)

    async def _handle_interruption(
        self, frame: InterruptionFrame, direction: FrameDirection
    ) -> None:
        active = (
            list(self.get_audio_contexts())
            if hasattr(self, "get_audio_contexts")
            else []
        )
        logger.info(
            "{} _handle_interruption ENTER active_ctxs={} turn_ctx={}",
            _LOG_PREFIX,
            active,
            self._turn_context_id,
        )
        await super()._handle_interruption(frame, direction)
        post_active = (
            list(self.get_audio_contexts())
            if hasattr(self, "get_audio_contexts")
            else []
        )
        logger.info(
            "{} _handle_interruption EXIT post_active_ctxs={} turn_ctx={}",
            _LOG_PREFIX,
            post_active,
            self._turn_context_id,
        )

    async def on_audio_context_interrupted(self, context_id: str) -> None:
        logger.info("{} on_audio_context_interrupted ctx={}", _LOG_PREFIX, context_id)
        await super().on_audio_context_interrupted(context_id)

    async def on_audio_context_completed(self, context_id: str) -> None:
        logger.info("{} on_audio_context_completed ctx={}", _LOG_PREFIX, context_id)
        await super().on_audio_context_completed(context_id)

    async def remove_audio_context(self, context_id: str) -> Any:
        logger.info("{} remove_audio_context ctx={}", _LOG_PREFIX, context_id)
        return await super().remove_audio_context(context_id)

    async def create_audio_context(self, context_id: str) -> Any:
        logger.info(
            "{} create_audio_context ctx={} turn_ctx={}",
            _LOG_PREFIX,
            context_id,
            self._turn_context_id,
        )
        return await super().create_audio_context(context_id)

    async def on_turn_context_completed(self) -> None:
        active = (
            list(self.get_audio_contexts())
            if hasattr(self, "get_audio_contexts")
            else []
        )
        logger.info(
            "{} on_turn_context_completed ENTER turn_ctx={} active_ctxs={}",
            _LOG_PREFIX,
            self._turn_context_id,
            active,
        )
        await super().on_turn_context_completed()
        logger.info("{} on_turn_context_completed EXIT", _LOG_PREFIX)

    async def on_turn_context_created(self, context_id: str) -> None:
        logger.info(
            "{} on_turn_context_created ctx={} previous_turn_ctx={}",
            _LOG_PREFIX,
            context_id,
            self._turn_context_id,
        )
        await super().on_turn_context_created(context_id)

    async def cancel(self, frame: CancelFrame) -> None:
        logger.info("{} cancel ENTER", _LOG_PREFIX)
        await super().cancel(frame)
        logger.info("{} cancel EXIT", _LOG_PREFIX)


class FreshContextCartesiaTTSService(InstrumentedCartesiaTTSService):
    """Story 6.13 Phase 4 Option A fix — eliminates the Cartesia multi-send
    freeze by sending each sentence as a self-contained single-shot
    request (fresh context_id + `continue=False`) instead of accumulating
    multiple `continue=True` sends on the same context.

    Root cause confirmed via call 156 (2026-05-26): Cartesia hangs when
    it receives 4+ rapid sends (<300 ms apart) on the same `context_id`.
    Pattern: 4 transcript sends + 1 flush in 281 ms → ZERO audio chunks
    + ZERO `done` response from Cartesia for ~5 s until the watchdog
    fires. Reproduced 3 times in one call on different contexts; ~30 %
    of calls overall.

    Two complementary changes are BOTH required:

    1. `reuse_context_id_within_turn=False` — Pipecat's `TTSService`
       has a built-in knob that, when False, makes every call to
       `create_context_id()` return a fresh UUID instead of reusing
       the per-turn one. Each `AggregatedTextFrame` therefore goes to
       its own Cartesia context. No more 4-sends-on-same-context race.

    2. Force `continue=False` in `_build_msg` — Cartesia's protocol
       treats `continue=True` as "more transcript will follow on this
       context_id". Without a final `continue=False` flush, Cartesia
       waits indefinitely. Pipecat's flush path
       (`on_turn_context_completed → flush_audio(self._turn_context_id)`)
       targets the *turn* context (a fresh UUID that was never
       actually opened when `reuse=False`), so the flush never reaches
       the per-sentence contexts. By forcing `continue=False` on every
       send, each per-sentence context is self-flushing: Cartesia
       receives `text + immediate end-of-transcript`, generates audio,
       closes the context. No race possible because each context only
       ever sees one message.

    Inherits from `InstrumentedCartesiaTTSService` so the `[CART-INSTR]`
    logs are still emitted — operators can validate the fix is firing
    correctly via journalctl. Once we have shipped this fix and
    confirmed it sticks, a follow-up story should:
      - Promote this class to the default in `bot.py` (drop the env gate)
      - Either delete the `InstrumentedCartesiaTTSService` instrumentation
        OR keep it permanently gated for future Cartesia investigations.

    Gated by `CARTESIA_FRESH_CTX=1` (default off). Coexists with
    `CARTESIA_INSTRUMENT=1` — `bot.py` picks `FreshContext` if both
    are set, since `FreshContext` already includes the instrumentation.
    """

    def __init__(self, **kwargs: Any) -> None:
        # Force fresh context_id per sentence. `setdefault` so an
        # explicit caller-override (e.g. a future test that wants the
        # legacy behaviour) still works.
        kwargs.setdefault("reuse_context_id_within_turn", False)
        super().__init__(**kwargs)
        logger.info(
            "{} FreshContextCartesiaTTSService active — single-shot per sentence",
            _LOG_PREFIX,
        )

    def _build_msg(
        self,
        text: str = "",
        continue_transcript: bool = True,
        add_timestamps: bool = True,
        context_id: str = "",
    ) -> str:
        # ALWAYS `continue=False` so every send to Cartesia is
        # self-flushing. The redundant flush from
        # `on_turn_context_completed` later targets `_turn_context_id`
        # which (with `reuse=False`) never matched a real audio
        # context, so it's already a no-op via the existing
        # `audio_context_available(...)` guard — no further override
        # needed in `flush_audio`.
        return super()._build_msg(
            text=text,
            continue_transcript=False,
            add_timestamps=add_timestamps,
            context_id=context_id,
        )
