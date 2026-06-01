"""Cartesia diagnostics + always-on error-schema surfacing.

Two layers, both wrapping pipecat 0.0.108's `CartesiaTTSService`
WebSocket:

1. **`ErrorLoggingCartesiaTTSService` (always-on, the prod default).**
   A thin subclass whose ONLY behavioural change is to surface
   Cartesia's documented streaming-error frame at WARNING level. Since
   Story 6.14 (2026-05-30) made Cartesia the launch default, we want its
   errors visible in journalctl on every deploy — not gated behind a
   debug env var.

   Why wrap the websocket instead of observing a downstream `ErrorFrame`:
   pipecat's `CartesiaTTSService._process_messages` SILENTLY DROPS any
   message (errors included) whose `context_id` is no longer in
   `audio_contexts` — the `audio_context_available(...)` guard `continue`s
   before the `type == "error"` branch is reached. That abandoned-context
   case is exactly the freeze we most want visibility into. Logging at the
   websocket boundary, BEFORE that guard, captures the error schema
   regardless of context state.

2. **`InstrumentedCartesiaTTSService` (opt-in via `CARTESIA_INSTRUMENT=1`).**
   Verbose `[CART-INSTR]` logging of every WS send/recv + audio-context
   lifecycle transition. Used during a freeze diagnostic; inherits the
   always-on error surfacing. Switch off with `CARTESIA_INSTRUMENT=0`
   (or remove the env) + `systemctl restart pipecat.service`. No
   production code path changes when off — only additional log lines.

**Cartesia documented error schema** (support reply 2026-05-28, Ege
Tinmaz): `{"type":"error","context_id":"...","status_code":<int>,
"done":true,"error":"<human-readable string>"}`. 5xx `error` strings are
generic. `_log_cartesia_error` logs exactly these fields.

History: the 2026-05-26 multi-frame "freeze" (calls 156/157) that drove
us off Cartesia turned out to be a RESOLVED Cartesia platform incident
(status.cartesia.ai/incidents/1j04yfp4048k) — both reproductions landed
inside the incident window. The earlier `FreshContextCartesiaTTSService`
"fix attempt" (fresh context_id + `continue=False` per sentence) was
confirmed by Cartesia to be unnecessary and counter-productive, and was
removed in Story 6.14.
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


def _log_cartesia_error(parsed: dict[str, Any]) -> None:
    """Surface Cartesia's documented streaming-error schema at WARNING.

    `parsed` is a decoded Cartesia WS message already known to have
    `type == "error"`. Logs the documented fields (`status_code`,
    `error`, `context_id`, `done`) so an operator greps one line instead
    of reconstructing the failure from an opaque `type=error`.
    """
    logger.warning(
        "cartesia_ws_error status_code={} error={!r} context_id={} done={}",
        parsed.get("status_code"),
        parsed.get("error"),
        parsed.get("context_id"),
        parsed.get("done"),
    )


def _maybe_log_cartesia_error(msg: Any) -> None:
    """Parse a raw Cartesia WS message and, if it's an error frame, log
    its documented schema. Silent on non-JSON / non-error messages.

    Story 6.14 review (perf) — cheap substring pre-filter BEFORE the full
    `json.loads`. This runs on EVERY inbound Cartesia message, and Cartesia
    streams audio as `type=chunk` frames carrying a KB-sized base64 `data`
    payload. Fully parsing every audio chunk (throughout Tina's whole
    utterance) needlessly loads the asyncio event loop on the 2-core VPS —
    in exactly the window where the concurrent checkpoint/emotion classifier
    tasks run, so it can delay the `checkpoint_advanced` flip. Only the rare
    error frame contains the substring "error"; scan first, parse only
    candidates. A false-positive substring hit inside a base64 blob just
    falls through to the original parse-and-check (correctness preserved)."""
    if isinstance(msg, str):
        if "error" not in msg:
            return
    elif isinstance(msg, (bytes, bytearray)):
        if b"error" not in msg:
            return
    else:
        return
    try:
        parsed = json.loads(msg)
    except (ValueError, TypeError):
        return
    if isinstance(parsed, dict) and parsed.get("type") == "error":
        _log_cartesia_error(parsed)


class _ErrorLoggingWebsocket:
    """Always-on minimal proxy over the Cartesia WebSocket: passes every
    message through UNCHANGED, but surfaces Cartesia's documented
    `type=error` schema at WARNING before the parent pipecat code (which
    may silently drop it) ever sees it.

    Mirrors the surface the parent `CartesiaTTSService` uses: `send`,
    `__aiter__/__anext__` (for `async for msg in ws:`), `state`, and
    `close`. Other attribute reads fall through via `__getattr__` so a
    future pipecat upgrade that touches other attributes still works.
    """

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    async def send(self, msg: Any) -> Any:
        return await self._ws.send(msg)

    # `websockets`' `ClientConnection` does NOT expose `__anext__`
    # directly even though it supports `async for`. `__aiter__` is a
    # *plain* (non-async) function returning a fresh async generator that
    # delegates to the underlying `async for` — see the regression test
    # `test_logging_websocket_iterates_over_async_only_underlying` for the
    # trap this avoids (an `AttributeError` → pipecat reconnect storm →
    # Tina mute).
    def __aiter__(self) -> Any:
        return self._aiter_messages()

    async def _aiter_messages(self) -> Any:
        async for msg in self._ws:
            _maybe_log_cartesia_error(msg)
            yield msg

    async def close(self) -> Any:
        return await self._ws.close()

    def __getattr__(self, name: str) -> Any:
        # Fall through everything else (`state`, `close_code`,
        # transport-internal hooks) to the wrapped websocket.
        return getattr(self._ws, name)


class _LoggingWebsocket(_ErrorLoggingWebsocket):
    """Verbose `[CART-INSTR]` proxy (gated by `CARTESIA_INSTRUMENT=1`).

    Logs every send + recv on top of the always-on error surfacing
    inherited from `_ErrorLoggingWebsocket`. Authoritative trace of the
    wire protocol for a freeze investigation.
    """

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
        return await super().send(msg)

    async def _aiter_messages(self) -> Any:
        async for msg in self._ws:
            # Always-on error surfacing first (the load-bearing diagnostic).
            _maybe_log_cartesia_error(msg)
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
        return await super().close()


class ErrorLoggingCartesiaTTSService(CartesiaTTSService):
    """Prod-default Cartesia service — always-on error-schema surfacing.

    Drop-in replacement for `CartesiaTTSService`: same constructor
    surface, same Settings type. Only effect on prod behaviour is a
    WARNING log when Cartesia returns its documented `type=error` frame
    (otherwise silent). Wired by `pipeline/tts_factory.build_tts_service`
    whenever `TTS_PROVIDER=cartesia` and no debug env-gate is set.
    """

    async def _connect_websocket(self) -> None:
        await super()._connect_websocket()
        # Wrap AFTER the parent established the raw websocket. If the
        # connection failed (`_websocket is None`), skip wrapping so the
        # parent's reconnect logic stays intact. Idempotent: never
        # double-wrap on a reconnect.
        if self._websocket is not None and not isinstance(
            self._websocket, _ErrorLoggingWebsocket
        ):
            self._websocket = _ErrorLoggingWebsocket(self._websocket)


class InstrumentedCartesiaTTSService(CartesiaTTSService):
    """Verbose-diagnostic Cartesia service (gated by `CARTESIA_INSTRUMENT=1`).

    Wraps the WebSocket with the verbose `_LoggingWebsocket` and overrides
    every method that touches context-lifecycle state, adding
    `[CART-INSTR]` logs. Includes the always-on error surfacing via
    `_LoggingWebsocket`'s base class. Drop-in replacement for
    `CartesiaTTSService` — same constructor surface; only effect on prod
    behaviour is additional log lines (loguru INFO/WARNING).
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
