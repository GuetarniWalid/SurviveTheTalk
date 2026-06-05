"""Story 6.24 — tests for the Cartesia TTS warm-up ping.

The warm-up is a pure optimization (kills the turn-1 Cartesia cold-start that
stalled the opening line on call_id=226). Its load-bearing contract: it MUST
replay pipecat's own `/tts/bytes` call shape (right endpoint, version header,
model + RESOLVED voice) AND it MUST NEVER raise, regardless of network failure —
a crashed warm-up must not break the paid call.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pipeline.tts_warmup import warm_up_tts_cartesia


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeResponse:
    status_code = 200


class _CapturingClient:
    """Stands in for httpx.AsyncClient — records the constructor timeout + the
    POST url/headers/json."""

    def __init__(self, *args: Any, raise_exc: Exception | None = None, **kwargs: Any):
        self.raise_exc = raise_exc
        _CapturingClient.last_timeout = kwargs.get("timeout")
        _CapturingClient.last_post_url = None
        _CapturingClient.last_post_headers = None
        _CapturingClient.last_post_json = None

    async def __aenter__(self) -> "_CapturingClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        _CapturingClient.last_post_url = url
        _CapturingClient.last_post_headers = headers
        _CapturingClient.last_post_json = json
        if self.raise_exc is not None:
            raise self.raise_exc
        return _FakeResponse()


def test_warmup_posts_correct_payload(monkeypatch) -> None:
    """Warm-up replays pipecat's /tts/bytes call: right URL, version header,
    api key, and the sonic-3 + voice + raw/pcm_s16le/24k body."""
    import pipeline.tts_warmup as warmup_mod

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _CapturingClient)

    _run(
        warm_up_tts_cartesia(
            api_key="sk_car_test", model="sonic-3", voice_id="voice-abc"
        )
    )

    assert _CapturingClient.last_post_url == "https://api.cartesia.ai/tts/bytes"
    headers = _CapturingClient.last_post_headers
    assert headers["Cartesia-Version"] == "2026-03-01"
    assert headers["X-API-Key"] == "sk_car_test"
    assert headers["Content-Type"] == "application/json"
    body = _CapturingClient.last_post_json
    assert body == {
        "model_id": "sonic-3",
        "transcript": "Hi.",
        "voice": {"mode": "id", "id": "voice-abc"},
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
        },
    }


def test_warmup_warms_the_resolved_voice(monkeypatch) -> None:
    """A custom (per-scenario) voice id must be the one warmed — proving the
    warmed voice tracks the spoken voice (no drift)."""
    import pipeline.tts_warmup as warmup_mod

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _CapturingClient)

    _run(
        warm_up_tts_cartesia(
            api_key="sk_car_test", model="sonic-3", voice_id="detective-ronald"
        )
    )

    assert _CapturingClient.last_post_json["voice"]["id"] == "detective-ronald"


def test_warmup_uses_8s_timeout(monkeypatch) -> None:
    """8 s timeout (above the LLM warm-up's 5 s) — a cold sonic-3 synthesis is
    exactly the multi-second op being paid down."""
    import pipeline.tts_warmup as warmup_mod

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _CapturingClient)

    _run(warm_up_tts_cartesia(api_key="k", model="sonic-3", voice_id="v"))

    assert _CapturingClient.last_timeout == 8.0


def test_warmup_swallows_connect_error(monkeypatch) -> None:
    """A network failure during warm-up MUST NOT raise — best-effort only."""
    import pipeline.tts_warmup as warmup_mod

    def _failing(*args: Any, **kwargs: Any) -> _CapturingClient:
        return _CapturingClient(raise_exc=ConnectionError("simulated network down"))

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _failing)

    _run(warm_up_tts_cartesia(api_key="k", model="sonic-3", voice_id="v"))


def test_warmup_swallows_timeout(monkeypatch) -> None:
    """A timeout during warm-up MUST NOT raise."""
    import pipeline.tts_warmup as warmup_mod

    def _timeout(*args: Any, **kwargs: Any) -> _CapturingClient:
        return _CapturingClient(raise_exc=TimeoutError("simulated timeout"))

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _timeout)

    _run(warm_up_tts_cartesia(api_key="k", model="sonic-3", voice_id="v"))


def test_warmup_swallows_generic_exception(monkeypatch) -> None:
    """Any unexpected error (e.g. non-2xx handling, bad response) is swallowed."""
    import pipeline.tts_warmup as warmup_mod

    def _boom(*args: Any, **kwargs: Any) -> _CapturingClient:
        return _CapturingClient(raise_exc=RuntimeError("unexpected"))

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _boom)

    _run(warm_up_tts_cartesia(api_key="k", model="sonic-3", voice_id="v"))


def test_warmup_non_2xx_does_not_claim_warmed(monkeypatch) -> None:
    """A non-2xx response (401 bad key / 429 rate-limit / 5xx) means NOTHING was
    warmed: httpx does not raise on 4xx/5xx, so the success breadcrumb MUST be
    suppressed (the smoke gate greps it) and a WARNING with the status emitted —
    and it must still never raise."""
    import pipeline.tts_warmup as warmup_mod
    from loguru import logger as loguru_logger

    class _Resp401:
        status_code = 401

    class _Client401(_CapturingClient):
        async def post(self, url: str, headers: dict, json: dict) -> _Resp401:
            _CapturingClient.last_post_url = url
            _CapturingClient.last_post_headers = headers
            _CapturingClient.last_post_json = json
            return _Resp401()

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _Client401)

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="DEBUG")
    try:
        _run(warm_up_tts_cartesia(api_key="bad-key", model="sonic-3", voice_id="v"))
    finally:
        loguru_logger.remove(sink_id)

    joined = "".join(captured)
    assert "cartesia warmed" not in joined  # no phantom success breadcrumb
    assert "401" in joined  # the WARNING surfaces the real status
