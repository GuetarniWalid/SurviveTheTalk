"""Story 6.6 — Tests for ExchangeClassifier async LLM service (AC1, AC9 #1)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from pipeline.exchange_classifier import (
    ExchangeClassifier,
    _parse_classifier_output,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_classifier() -> ExchangeClassifier:
    return ExchangeClassifier(openrouter_api_key="test-key")


def _mock_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    handler,
) -> None:
    """Replace `httpx.AsyncClient` with one routed through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("pipeline.exchange_classifier.httpx.AsyncClient", _factory)


def _kwargs(**overrides: Any) -> dict[str, Any]:
    base = dict(
        user_text="I'd like the grilled chicken.",
        last_character_line="What can I get you?",
        success_criteria="User names a specific dish.",
        scenario_description="The Waiter",
    )
    base.update(overrides)
    return base


# ---------- Test 1: met=true happy path -----------------------------------


def test_classify_returns_true_on_met_true_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"met": true}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is True


# ---------- Test 2: met=false happy path ----------------------------------


def test_classify_returns_false_on_met_false_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"met": false}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is False


# ---------- Test 3: timeout returns None ----------------------------------


def test_classify_returns_None_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow classifier that exceeds the 1.0 s budget (Story 6.8 Phase 1
    AC4 — was 2.0 s in Story 6.6) returns None.

    Patches the module-level constant to a short value so the test runs fast.
    """
    import pipeline.exchange_classifier as ec_mod

    monkeypatch.setattr(ec_mod, "_CLASSIFIER_TIMEOUT_SECONDS", 0.05)

    async def _slow_classify(
        self: ExchangeClassifier,
        **kwargs: Any,
    ) -> Any:
        await asyncio.sleep(0.5)
        return True

    monkeypatch.setattr(ExchangeClassifier, "_classify", _slow_classify)

    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is None


# ---------- Test 4: HTTP error returns None -------------------------------


def test_classify_returns_None_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connect error")

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is None


# ---------- Test 5: malformed JSON returns None ---------------------------


def test_classify_returns_None_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not json"}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is None


# ---------- Test 6: missing `met` key returns None ------------------------


def test_classify_returns_None_on_missing_met_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"foo": "bar"}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is None


# ---------- Test 7: non-bool `met` returns None ---------------------------


def test_classify_returns_None_on_non_bool_met(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`{"met": "true"}` (string, not bool) must be rejected — guard against
    a model that decides to verbalise the verdict."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"met": "true"}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is None


# ---------- Test 8: constructor rejects empty API key ---------------------


def test_init_raises_on_empty_api_key() -> None:
    with pytest.raises(ValueError, match="openrouter_api_key"):
        ExchangeClassifier(openrouter_api_key="")


# ---------- Test 9: Markdown-fenced response parses -----------------------


def test_markdown_fenced_response_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Models occasionally wrap JSON in Markdown fences. The parser must strip
    the fence and read the inner JSON cleanly."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '```json\n{"met": true}\n```'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is True


# ---------- Story 6.9 reliability — persistent client + close --------------


def test_persistent_client_reused_across_classify_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.9 reliability patch — the underlying `httpx.AsyncClient` is
    instantiated ONCE per classifier (lazy at first classify) and reused
    across subsequent calls. Pre-patch each classify opened a new client
    → paid TCP + TLS handshake (~100-200 ms) per call → ~30 % of calls
    timed out against Story 6.8's tight 0.8 s HTTP budget.

    Asserts the underlying client identity is stable across 3 classify
    calls — proves the lazy-init + reuse pattern works.

    Story 6.9 review patch — strengthen: also count how many times
    `httpx.AsyncClient` was instantiated and assert it equals exactly 1.
    Object-identity alone is satisfied trivially if the factory always
    returns the same shared mock; tracking instantiation count proves
    the lazy-init didn't accidentally re-fire on subsequent classifies.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"met": true}'}}]},
        )

    # Custom factory that increments a counter on every construction.
    instantiation_count = {"n": 0}
    transport = httpx.MockTransport(_handler)
    real_client = httpx.AsyncClient

    def _counting_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        instantiation_count["n"] += 1
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(
        "pipeline.exchange_classifier.httpx.AsyncClient", _counting_factory
    )

    classifier = _make_classifier()

    async def _drive() -> tuple[Any, Any, Any]:
        await classifier.classify(**_kwargs())
        first = classifier._client
        await classifier.classify(**_kwargs())
        second = classifier._client
        await classifier.classify(**_kwargs())
        third = classifier._client
        await classifier.close()
        return first, second, third

    first, second, third = _run(_drive())
    assert first is not None, "first call must lazy-init the client"
    assert first is second, "second call must reuse the same client (no cold start)"
    assert second is third, "third call must reuse the same client"
    assert instantiation_count["n"] == 1, (
        f"AsyncClient must be constructed exactly once across 3 classifies; "
        f"got {instantiation_count['n']} — handshake-cost savings broken"
    )


def test_close_releases_client_and_is_idempotent() -> None:
    """`close()` must release the connection pool (set `_client` to None)
    AND be idempotent — `CheckpointManager.cleanup()` may call it more
    than once during teardown if the manager is reused across tests."""
    classifier = _make_classifier()

    async def _drive() -> None:
        # Force-init a client by calling _get_client directly (avoids
        # the round-trip to OpenRouter for the test)
        await classifier._get_client()
        assert classifier._client is not None
        await classifier.close()
        assert classifier._client is None
        # Second close must be a no-op
        await classifier.close()
        assert classifier._client is None

    _run(_drive())


# ---------- Test 10: parser handles prose around JSON ---------------------


def test_parser_handles_prose_around_json() -> None:
    out = _parse_classifier_output('Sure: {"met": true}.')
    assert out is True


def test_parser_returns_none_for_pure_prose() -> None:
    assert _parse_classifier_output("I think yes") is None


# ---------- Test 11: HTTP boundary smoke ----------------------------------


def test_classify_uses_httpx_post_with_reasoning_top_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lock in the Story 6.3 / 6.6 smoke fix: `reasoning` MUST sit at the
    top level of the JSON body, NOT nested in `extra_body`. OpenRouter's
    HTTP API doesn't unwrap `extra_body`; the model would stay in default
    reasoning mode and every classification would time out."""

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer test-key"
        sent = json.loads(request.content)
        assert sent["model"] == "qwen/qwen3.5-flash-02-23"
        assert sent["reasoning"] == {"enabled": False}, (
            "reasoning must be at the top level of the body, not in extra_body"
        )
        assert "extra_body" not in sent, (
            "extra_body is OpenAI-SDK-only; would be dropped by OpenRouter"
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"met": true}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is True


# ---------- Story 6.9 review patches: closed-state + lifecycle ------------


def test_classify_after_close_returns_None(monkeypatch: pytest.MonkeyPatch) -> None:
    """Story 6.9 review patch — once `close()` has been called, any
    subsequent `classify()` must return None (treated as infra failure
    by CheckpointManager) rather than spawning a fresh AsyncClient that
    would leak. The lifecycle error surfaces as a WARNING log and a
    clean None return, not a `RuntimeError` propagated to the caller.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"met": true}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    classifier = _make_classifier()

    async def _drive() -> bool | None:
        await classifier.close()
        # Now try to classify after close — should return None not raise.
        return await classifier.classify(**_kwargs())

    out = _run(_drive())
    assert out is None, (
        f"classify after close must return None (lifecycle error path), got {out!r}"
    )
    # And no client should have been re-created.
    assert classifier._client is None


def test_close_during_in_flight_classify_does_not_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.9 review patch — `close()` racing with an in-flight
    classify must (a) not raise, (b) leave no client behind, (c) the
    in-flight task is allowed to complete or fail cleanly. Mirrors
    `CheckpointManager.cleanup()` ordering (cancel in-flight task →
    close classifier) — this test verifies the classifier-side half of
    that contract.
    """

    arrived_at_handler = asyncio.Event()
    proceed_handler = asyncio.Event()

    def _handler(request: httpx.Request) -> httpx.Response:
        # Block here until the test signals to proceed. We can't await
        # asyncio events from a sync MockTransport handler, so use a
        # small busy-wait via run_coroutine_threadsafe alternative —
        # the simpler path is to return immediately and rely on close
        # racing with the post-classify cleanup of _client.
        arrived_at_handler.set()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"met": true}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    classifier = _make_classifier()

    async def _drive() -> tuple[bool | None, bool | None]:
        # Race close() against a fresh classify(). Both should complete
        # without raising; classify may return True (if it won the
        # race) or None (if close blocked it).
        proceed_handler.set()
        verdict_task = asyncio.create_task(classifier.classify(**_kwargs()))
        # Give the classify task a tick to acquire the client, then
        # close while it might still be in-flight.
        await asyncio.sleep(0)
        await classifier.close()
        verdict = await verdict_task
        return verdict, classifier._client

    verdict, client_after = _run(_drive())
    # Whatever the race outcome, the classifier MUST be in a clean
    # closed state with no leaked client.
    assert client_after is None, (
        f"after close() the persistent client must be released; got {client_after!r}"
    )
    # Verdict is either True (classify won) or None (close won); both
    # are acceptable outcomes — what matters is no exception.
    assert verdict in (True, None), (
        f"race outcome must be True or None, got {verdict!r}"
    )


# ---------- Story 6.9 review patch P21 — default-to-MET regression net ----


def test_classifier_defaults_to_met_on_borderline_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.9 review patch P21 (from D4) — the EXCHANGE_CLASSIFIER_PROMPT
    rewrite added "Default to MET when uncertain" as a guiding principle.
    Lock in this behavior so a future prompt-tightening (e.g. someone
    re-introducing strict matching) would surface as a failed test.

    We test by asserting the prompt text itself contains the
    default-to-MET principle. We can't directly assert the model's
    behavior without hitting OpenRouter; the prompt is the authoritative
    contract that the model is asked to follow. If the principle is
    removed from the prompt, the LLM's default-to-MET behavior would
    silently regress.
    """
    from pipeline.prompts import EXCHANGE_CLASSIFIER_PROMPT

    # The prompt MUST contain the default-to-MET guidance — this is the
    # behavior change documented in Deviation #10. Phrasing may evolve
    # but the SEMANTIC contract (favour MET when uncertain) must remain
    # explicit.
    assert "Default to MET" in EXCHANGE_CLASSIFIER_PROMPT, (
        "EXCHANGE_CLASSIFIER_PROMPT must retain the 'Default to MET when "
        "uncertain' guidance from Deviation #10 — removing it silently "
        "tightens the classifier and breaks the calibration baseline"
    )
    assert "False positives" in EXCHANGE_CLASSIFIER_PROMPT, (
        "the default-to-MET rationale (false positives cost nothing) "
        "must remain in the prompt — the model needs the WHY"
    )
