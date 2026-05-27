"""Story 6.13 investigation tooling regression tests.

The first version of `_LoggingWebsocket` (committed in `ec97cff`) assumed
that the underlying `websockets.asyncio.client.ClientConnection` exposed
`__anext__` directly. On the production VPS pipecat 0.0.108 +
websockets 13.x, that assumption was wrong: `ClientConnection` implements
iteration only via the `async for` protocol (its `__aiter__` returns
an async generator), and calling `.__anext__()` raised
`AttributeError: 'ClientConnection' object has no attribute '__anext__'`.
pipecat's `WebsocketTTSService._maybe_try_reconnect` caught the exception
and immediately tore down the websocket → reconnect storm → Tina mute.

This test locks the contract: `_LoggingWebsocket` is iterable via
`async for` even when the wrapped websocket only supports the
`async for` protocol (i.e. exposes `__aiter__` but NOT `__anext__`
directly). Mirrors the production websockets library shape.
"""

from __future__ import annotations

import asyncio

from pipeline.cartesia_instrumented import _LoggingWebsocket


class _FakeAsyncOnlyWebsocket:
    """Mimics the prod websockets `ClientConnection` shape: only
    `__aiter__` is implemented (returning a fresh async generator).
    No `__anext__` on the object itself — same trap that broke the
    first commit."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = messages

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for msg in self._messages:
            # Yield control like the real websocket would.
            await asyncio.sleep(0)
            yield msg


def test_logging_websocket_iterates_over_async_only_underlying() -> None:
    """The `_LoggingWebsocket` proxy MUST work when the underlying
    websocket implements iteration via `__aiter__`-only (no
    `__anext__` attribute), which is the prod `websockets` library
    shape."""
    underlying = _FakeAsyncOnlyWebsocket(
        [
            '{"context_id": "ctx-A", "type": "chunk", "data": "AAAA"}',
            '{"context_id": "ctx-A", "type": "done", "done": true}',
        ]
    )
    proxy = _LoggingWebsocket(underlying)

    async def _drive() -> list[str]:
        collected: list[str] = []
        async for msg in proxy:
            collected.append(msg)
        return collected

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_drive())
    finally:
        loop.close()

    assert result == [
        '{"context_id": "ctx-A", "type": "chunk", "data": "AAAA"}',
        '{"context_id": "ctx-A", "type": "done", "done": true}',
    ], "proxy must pass through every message from the underlying ws"


def test_logging_websocket_send_passes_through() -> None:
    """`send()` must forward to the underlying ws and return its result."""
    sent: list[str] = []

    class _FakeSendable:
        async def send(self, msg: str) -> str:
            sent.append(msg)
            return "ok"

    proxy = _LoggingWebsocket(_FakeSendable())

    async def _drive() -> str:
        return await proxy.send('{"context_id": "ctx-A", "transcript": "hi"}')

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_drive())
    finally:
        loop.close()

    assert result == "ok"
    assert sent == ['{"context_id": "ctx-A", "transcript": "hi"}']


def test_logging_websocket_state_attribute_passthrough() -> None:
    """The proxy must forward attribute reads (e.g. `state`) to the
    wrapped websocket so pipecat's `if self._websocket.state is
    State.CLOSED` check keeps working. Identity comparison via `is`
    requires that we return the SAME object the underlying ws holds."""
    sentinel = object()  # Stand-in for `websockets.protocol.State.OPEN`.

    class _FakeStateful:
        state = sentinel

    proxy = _LoggingWebsocket(_FakeStateful())

    assert proxy.state is sentinel, (
        "attribute reads must pass through unchanged so `is` checks work"
    )


# ============================================================
# Story 6.13 Phase 4 Option A — FreshContextCartesiaTTSService
# ============================================================


def test_fresh_context_service_forces_continue_false_in_build_msg() -> None:
    """The Option A fix relies on EVERY send to Cartesia being a
    self-flushing `continue=False` message. Even if the caller passes
    `continue_transcript=True` (which is the default in the parent
    `flush_audio` / `run_tts` paths), the override MUST coerce it
    to False — that's the load-bearing invariant that prevents
    Cartesia from waiting for additional transcript on a context."""
    import json

    from pipeline.cartesia_instrumented import FreshContextCartesiaTTSService

    # Construct without going through the heavy parent __init__ path;
    # we only need _build_msg behaviour. The parent uses these attrs.
    service = FreshContextCartesiaTTSService.__new__(FreshContextCartesiaTTSService)
    service._settings = type("S", (), {})()  # bare namespace
    service._settings.voice = "voice-id"
    service._settings.model = "sonic-3"
    service._settings.language = None
    service._settings.generation_config = None
    service._settings.pronunciation_dict_id = None
    service._output_container = "raw"
    service._output_encoding = "pcm_s16le"
    service._output_sample_rate = 16000

    # Caller asks for continue=True — fix MUST override to False.
    msg_str = service._build_msg(
        text="Hello.",
        continue_transcript=True,
        context_id="ctx-A",
    )
    msg = json.loads(msg_str)
    assert msg["continue"] is False, (
        "FreshContextCartesiaTTSService MUST force continue=False so each "
        "send is single-shot; got continue=True — the fix is inert"
    )
    assert msg["transcript"] == "Hello."
    assert msg["context_id"] == "ctx-A"

    # Caller already says False — still False.
    msg_str2 = service._build_msg(
        text="X",
        continue_transcript=False,
        context_id="ctx-B",
    )
    msg2 = json.loads(msg_str2)
    assert msg2["continue"] is False


def test_fresh_context_service_sets_reuse_context_id_within_turn_false() -> None:
    """The other half of Option A: `reuse_context_id_within_turn=False`
    so `create_context_id()` returns a fresh UUID per sentence.
    Without this, multiple sentences still land on the same context_id
    and the multi-frame race re-emerges."""
    from pipeline.cartesia_instrumented import FreshContextCartesiaTTSService

    # Inspect the constructor signature via the default kwargs path —
    # avoid actually constructing (parent needs real api_key etc.).
    # The class's __init__ sets the default; we can validate by
    # reading the source string.
    import inspect

    src = inspect.getsource(FreshContextCartesiaTTSService.__init__)
    assert 'kwargs.setdefault("reuse_context_id_within_turn", False)' in src, (
        "FreshContextCartesiaTTSService.__init__ must default "
        "reuse_context_id_within_turn=False — the Option A fix is "
        "inert without it"
    )
