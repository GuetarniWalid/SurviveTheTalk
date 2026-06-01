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
# Story 6.14 AC4.1 — always-on Cartesia error-schema surfacing
# ============================================================


def _capture_warnings(action) -> list[str]:
    """Run `action()` (sync) with a temp loguru WARNING sink and return
    the captured lines. Loguru doesn't propagate to pytest's `caplog`
    (server/CLAUDE.md §3), so we add our own sink."""
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="WARNING")
    try:
        action()
    finally:
        loguru_logger.remove(sink_id)
    return captured


def test_log_cartesia_error_formats_documented_fields() -> None:
    """`_log_cartesia_error` logs Cartesia's documented error schema
    (`status_code`, `error`, `context_id`, `done`) at WARNING so an
    operator greps one structured line."""
    from pipeline.cartesia_instrumented import _log_cartesia_error

    captured = _capture_warnings(
        lambda: _log_cartesia_error(
            {
                "type": "error",
                "context_id": "ctx-Z",
                "status_code": 503,
                "done": True,
                "error": "service unavailable",
            }
        )
    )

    line = "\n".join(captured)
    assert "cartesia_ws_error" in line
    assert "status_code=503" in line
    assert "service unavailable" in line
    assert "ctx-Z" in line


def test_maybe_log_skips_json_parse_when_no_error_substring() -> None:
    """Story 6.14 review (perf) — the cheap substring pre-filter must NOT
    even call `json.loads` on an audio chunk that lacks the substring
    "error". We assert it by passing a non-JSON string with no "error":
    the old code path would hit `json.loads` (caught → return); the new
    path returns before parsing. Either way it must stay silent — and a
    `type=chunk` frame whose base64 happens to contain "error" must still
    fall through correctly (parsed, type != error → silent)."""
    from pipeline.cartesia_instrumented import _maybe_log_cartesia_error

    # (a) plain audio chunk, no "error" substring → silent.
    captured = _capture_warnings(
        lambda: _maybe_log_cartesia_error(
            '{"context_id": "ctx-A", "type": "chunk", "data": "AAAABBBB"}'
        )
    )
    assert not any("cartesia_ws_error" in e for e in captured)

    # (b) base64 payload that DOES contain the substring "error" but is a
    # chunk, not an error frame → pre-filter matches, parse falls through,
    # type != "error" → still silent (correctness preserved).
    captured = _capture_warnings(
        lambda: _maybe_log_cartesia_error(
            '{"context_id": "ctx-A", "type": "chunk", "data": "Zerror1234"}'
        )
    )
    assert not any("cartesia_ws_error" in e for e in captured)


def test_error_logging_websocket_surfaces_error_and_passes_through() -> None:
    """`_ErrorLoggingWebsocket` MUST (a) yield every message unchanged
    and (b) log the documented schema on a `type=error` frame — even
    though it is otherwise silent."""
    from pipeline.cartesia_instrumented import _ErrorLoggingWebsocket

    underlying = _FakeAsyncOnlyWebsocket(
        [
            '{"context_id": "ctx-A", "type": "chunk", "data": "AAAA"}',
            '{"context_id": "ctx-A", "type": "error", "status_code": 500, '
            '"done": true, "error": "internal error"}',
            '{"context_id": "ctx-A", "type": "done", "done": true}',
        ]
    )
    proxy = _ErrorLoggingWebsocket(underlying)

    collected: list[str] = []

    def _drive() -> None:
        async def _run() -> None:
            async for msg in proxy:
                collected.append(msg)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    captured = _capture_warnings(_drive)

    # Pass-through: all three messages forwarded unchanged.
    assert len(collected) == 3
    # Error surfaced exactly once with the documented fields.
    line = "\n".join(captured)
    assert line.count("cartesia_ws_error") == 1
    assert "status_code=500" in line
    assert "internal error" in line


def test_error_logging_websocket_silent_on_non_error_messages() -> None:
    """No `cartesia_ws_error` WARNING for chunk/done/timestamps frames —
    the proxy is silent on the happy path."""
    from pipeline.cartesia_instrumented import _ErrorLoggingWebsocket

    underlying = _FakeAsyncOnlyWebsocket(
        [
            '{"context_id": "ctx-A", "type": "chunk", "data": "AAAA"}',
            '{"context_id": "ctx-A", "type": "done", "done": true}',
        ]
    )
    proxy = _ErrorLoggingWebsocket(underlying)

    def _drive() -> None:
        async def _run() -> None:
            async for _ in proxy:
                pass

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    captured = _capture_warnings(_drive)
    assert not any("cartesia_ws_error" in entry for entry in captured)


def test_verbose_logging_websocket_also_surfaces_error_schema() -> None:
    """The verbose `_LoggingWebsocket` (CARTESIA_INSTRUMENT path) inherits
    the always-on error surfacing — an error frame still produces the
    structured WARNING on top of the verbose INFO trace."""
    underlying = _FakeAsyncOnlyWebsocket(
        [
            '{"context_id": "ctx-A", "type": "error", "status_code": 429, '
            '"done": true, "error": "rate limited"}',
        ]
    )
    proxy = _LoggingWebsocket(underlying)

    def _drive() -> None:
        async def _run() -> None:
            async for _ in proxy:
                pass

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    captured = _capture_warnings(_drive)
    line = "\n".join(captured)
    assert "cartesia_ws_error" in line
    assert "status_code=429" in line
