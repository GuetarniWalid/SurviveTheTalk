"""Story 6.13 follow-up — tests for the LLM warm-up ping.

The warm-up is a pure optimization (kills the turn-1 OpenRouter
cold-start). Its load-bearing contract is: it MUST send a minimal
request to the right model AND it MUST NEVER raise, regardless of
network failure — a crashed warm-up must not break the call.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pipeline.llm_warmup import warm_up_llm


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeResponse:
    status_code = 200


class _CapturingClient:
    """Stands in for httpx.AsyncClient — records the POST args."""

    def __init__(self, *args: Any, raise_exc: Exception | None = None, **kwargs: Any):
        self.raise_exc = raise_exc
        _CapturingClient.last_post_url = None
        _CapturingClient.last_post_json = None

    async def __aenter__(self) -> "_CapturingClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        _CapturingClient.last_post_url = url
        _CapturingClient.last_post_json = json
        if self.raise_exc is not None:
            raise self.raise_exc
        return _FakeResponse()


def test_warm_up_sends_minimal_request_to_correct_model(monkeypatch) -> None:
    """Warm-up posts to Groq with the given model + max_tokens=1."""
    import pipeline.llm_warmup as warmup_mod

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _CapturingClient)

    _run(warm_up_llm(api_key="test-key", model="llama-3.3-70b-versatile"))

    assert _CapturingClient.last_post_url == warmup_mod._PROVIDER_URL
    payload = _CapturingClient.last_post_json
    assert payload["model"] == "llama-3.3-70b-versatile"
    assert payload["max_tokens"] == 1, (
        "warm-up must request a single token — it's a connection primer, "
        "not a real inference"
    )
    # Sanity: the payload is JSON-serializable (would be sent on the wire).
    json.dumps(payload)


def test_warm_up_swallows_network_errors(monkeypatch) -> None:
    """A network failure during warm-up MUST NOT raise — the warm-up is
    best-effort and a crash here would break the call it's meant to
    optimize."""
    import pipeline.llm_warmup as warmup_mod

    def _failing_client(*args: Any, **kwargs: Any) -> _CapturingClient:
        return _CapturingClient(raise_exc=ConnectionError("simulated network down"))

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _failing_client)

    # Must complete without raising.
    _run(warm_up_llm(api_key="test-key", model="llama-3.3-70b-versatile"))


def test_warm_up_swallows_timeout(monkeypatch) -> None:
    """A timeout during warm-up MUST NOT raise."""
    import pipeline.llm_warmup as warmup_mod

    def _timeout_client(*args: Any, **kwargs: Any) -> _CapturingClient:
        return _CapturingClient(raise_exc=TimeoutError("simulated timeout"))

    monkeypatch.setattr(warmup_mod.httpx, "AsyncClient", _timeout_client)

    _run(warm_up_llm(api_key="test-key", model="llama-3.3-70b-versatile"))
