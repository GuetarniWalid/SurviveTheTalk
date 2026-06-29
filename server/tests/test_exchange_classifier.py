"""Story 6.6 — Tests for ExchangeClassifier async LLM service (AC1, AC9 #1)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from pipeline.exchange_classifier import (
    ABUSE_KEY,
    ExchangeClassifier,
    _PROVIDER_MODEL,
    _parse_classifier_output,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_classifier() -> ExchangeClassifier:
    return ExchangeClassifier(api_key="test-key")


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


# ---------- Story 6.9b — Groq-specific failure paths ---------------------
#
# Groq free tier has a 6000 TPM rate limit (~17 of our 340-token classifies
# per minute). At MVP scale (~5 classifies/call × 5 calls/day × 100 users =
# 500/day = 21/hour) we sit comfortably under the cap, but a viral spike or
# concurrent device storms could brush it. The prod classifier MUST treat
# 429s as infra failure (verdict=None — patience-neutral per Story 6.9 D1
# / Deviation #5), NOT as a False verdict (which would drain user patience
# for our infra hiccup). Same contract for 5xx Groq incidents.


def test_classify_returns_None_on_429_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.9b — Groq free-tier 6000 TPM rate-limit response (HTTP 429)
    MUST surface as `verdict=None` (infra failure path), not as a False
    verdict that would unfairly drain user patience. The prod
    `CheckpointManager` treats None as "infra hiccup, don't punish the
    user"; the consecutive-None backstop from Story 6.9 D1 then catches
    sustained degradation at N=5.

    Note: the BENCHMARK harness retries on 429 (because the harness fires
    75 sequential calls in a burst that artificially overruns the per-
    minute cap). The PROD classifier does NOT retry — a 429 in prod
    means real degradation worth surfacing, not a bench-only artifact.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": (
                        "Rate limit reached for model `llama-3.3-70b-versatile` "
                        "on tokens per minute (TPM): Limit 6000"
                    ),
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is None, (
        "HTTP 429 must surface as None (patience-neutral infra failure), "
        "not as False (which would drain user patience for our rate-limit hit)"
    )


def test_classify_returns_None_on_5xx_groq_incident(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.9b — Groq 5xx server errors (provider incident, deploy
    rollover, overloaded model) MUST surface as `verdict=None` (infra
    failure path). Same patience-neutral contract as 429.

    This test guards the prod rollback contract: if Groq has a 30-min
    incident, our app degrades to "classifier stuck" (consecutive-None
    backstop catches the sustained degradation at N=5 forcing soft
    hangup) rather than to "classifier drains patience for every turn"
    (which would force-end every call with reason=character_hung_up
    when nothing the user did was wrong).
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"message": "Service Unavailable", "type": "server_error"}},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is None, (
        "HTTP 503 must surface as None — Groq incident must not drain "
        "user patience for problems the user didn't cause"
    )


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
    with pytest.raises(ValueError, match="api_key"):
        ExchangeClassifier(api_key="")


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
        # the round-trip to the classifier provider for the test)
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


def test_classify_posts_to_openai_with_compat_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 10.6 (2026-06-29) provider witness — locks in the OpenAI request
    shape. The contract this test defends:

    - Target host is `api.openai.com`.
    - Default model is `gpt-4.1-mini` (migrated to OpenAI; native strict
      structured output), no longer Groq gpt-oss / Qwen via OpenRouter.
    - The `reasoning` field is NOT sent (OpenRouter/Qwen chain-of-thought
      hack), AND `reasoning_effort` is NOT sent either (gpt-4.1 is not a
      reasoning model — the gpt-oss/Gemini reasoning gating was removed in 10.6).
    - `extra_body` still must not appear (OpenAI-SDK-only convention,
      raw HTTP APIs ignore it).

    Pre-migration this test was `test_classify_uses_httpx_post_with_
    reasoning_top_level` (the Story 6.3/6.6 smoke witness). It now
    serves as the Story 6.9b migration witness — a future rollback to
    Qwen via OpenRouter MUST re-introduce `reasoning: {enabled: False}`
    at top level, so this test would fail loudly on a partial rollback.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com", (
            "Story 10.6 (2026-06-29) — classifier posts to OpenAI"
        )
        assert request.headers["authorization"] == "Bearer test-key"
        sent = json.loads(request.content)
        # Assert against the module constant, not a literal — if `_PROVIDER_MODEL`
        # flips again the assertion follows it.
        assert sent["model"] == _PROVIDER_MODEL == "gpt-4.1-mini", (
            "default classifier model is gpt-4.1-mini (Story 10.6 — migrated to "
            "OpenAI, native strict structured output)"
        )
        assert "reasoning" not in sent, (
            "the `reasoning` field is OpenRouter-era (Qwen chain-of-thought "
            "disable); it must never appear."
        )
        # gpt-4.1 is NOT a reasoning model, so reasoning_effort is NOT sent
        # (the gpt-oss/Gemini reasoning gating was removed in Story 10.6 review D2).
        assert "reasoning_effort" not in sent, (
            "a non-reasoning model (gpt-4.1) must not receive reasoning_effort"
        )
        assert "extra_body" not in sent, (
            "extra_body is OpenAI-SDK-only convention; raw HTTP API drops it"
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
    behavior without hitting the classifier provider (Groq since the
    Story 6.9b migration); the prompt is the authoritative contract
    that the model is asked to follow. If the principle is removed
    from the prompt, the LLM's default-to-MET behavior would silently
    regress.
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


# ---------- Story 6.9b — 5 principle-regression tests (AC4) ---------------
#
# Pattern mirrors P21 above: assert each of the 6 GUIDING PRINCIPLES (Story
# 6.9 D4) is present in `EXCHANGE_CLASSIFIER_PROMPT` by a stable wording
# marker. Principle 5 (default-to-MET) is covered by the P21 test above; this
# block covers principles 1, 2, 3, 4, 6. The Story 6.9b prompt compression
# (~600-700 → ~340 tokens) trimmed each principle's prose to 1-2 lines, so a
# future tightening that drops a principle entirely surfaces as a failing
# test here BEFORE the call hot path silently regresses on B1-learner messy
# speech. Phrasing may evolve over time; the SEMANTIC contract (each
# principle remains explicit) is what these assertions defend.


def test_classifier_intent_over_literal() -> None:
    """Principle 1 — INTENT over literal words. A user engaging with the
    topic of the current objective MEETS it even if the wording is
    hesitant / partial / loosely related. Removing this principle would
    silently regress the classifier to strict-keyword-match mode and
    fail every paraphrased B1 reply.
    """
    from pipeline.prompts import EXCHANGE_CLASSIFIER_PROMPT

    assert "INTENT" in EXCHANGE_CLASSIFIER_PROMPT, (
        "principle 1 (INTENT over literal words) marker missing — "
        "compression dropped it; classifier will revert to strict-match"
    )
    assert "literal" in EXCHANGE_CLASSIFIER_PROMPT.lower(), (
        "principle 1 must contrast intent vs literal wording"
    )


def test_classifier_accepts_synonym_or_brand() -> None:
    """Principle 2 — Synonyms / brand names / colloquialisms count.
    "Coke"="cola" is the canonical call_id=118 example that prompted
    Story 6.8 Phase 3 (Walid hit 4 consecutive `checkpoint_unmet drink`
    in a row after saying "Coke"). Dropping this marker would re-open
    the same UX regression.
    """
    from pipeline.prompts import EXCHANGE_CLASSIFIER_PROMPT

    assert "Synonyms" in EXCHANGE_CLASSIFIER_PROMPT, (
        "principle 2 (Synonyms count) marker missing"
    )
    assert "brand names" in EXCHANGE_CLASSIFIER_PROMPT, (
        "principle 2 must mention brand names — 'Coke' for 'cola' is "
        "the load-bearing call_id=118 example"
    )
    # Canonical example "Coke"="cola" anchors the principle concretely;
    # paraphrase or removal would weaken it.
    assert (
        '"Coke"="cola"' in EXCHANGE_CLASSIFIER_PROMPT
        or "Coke" in EXCHANGE_CLASSIFIER_PROMPT
    ), "principle 2 should keep the Coke/cola exemplar from Story 6.8 Phase 3"


def test_classifier_accepts_fragmented_response() -> None:
    """Principle 3 — Short or fragmented responses count. B1 learners
    under conversational pressure produce messy English (hesitations,
    missing articles, incomplete sentences). The classifier must not
    penalize the form.
    """
    from pipeline.prompts import EXCHANGE_CLASSIFIER_PROMPT

    assert "fragmented" in EXCHANGE_CLASSIFIER_PROMPT, (
        "principle 3 (fragmented responses count) marker missing"
    )
    # Hesitation marker ("uh", "um") anchors the principle to actual
    # speech-to-text artifacts — removing this would let a future
    # tightening reject disfluent transcriptions.
    assert (
        '"uh"' in EXCHANGE_CLASSIFIER_PROMPT or '"um"' in EXCHANGE_CLASSIFIER_PROMPT
    ), "principle 3 should keep the disfluency exemplars (uh / um)"


def test_classifier_accepts_restatement() -> None:
    """Principle 4 — Re-statements count. "I already said pasta" / "like
    I told you, chicken" should MEET the current objective if the prior
    statement matches. call_id=118 surfaced this when Walid said "I
    already said pasta" and the classifier returned checkpoint_unmet —
    Story 6.8 Phase 3 widened the Waiter `clarify` success_criteria;
    this principle generalises the lenience for every scenario.
    """
    from pipeline.prompts import EXCHANGE_CLASSIFIER_PROMPT

    assert "Re-statements" in EXCHANGE_CLASSIFIER_PROMPT, (
        "principle 4 (Re-statements of prior turns count) marker missing"
    )
    # "I already said" is the canonical call_id=118 phrase.
    assert "I already said" in EXCHANGE_CLASSIFIER_PROMPT, (
        "principle 4 should keep the 'I already said' exemplar from call_id=118"
    )


def test_classifier_evaluates_current_objective_only() -> None:
    """Principle 6 — Evaluate ONLY the current objective. The user must
    address each objective in turn; responses that anticipate future
    objectives must NOT advance the current one. Removing this would
    let users skip checkpoints, breaking calibration bands and the
    survival_pct contract.
    """
    from pipeline.prompts import EXCHANGE_CLASSIFIER_PROMPT

    assert "ONLY the current objective" in EXCHANGE_CLASSIFIER_PROMPT, (
        "principle 6 (current-objective-only) marker missing — without "
        "this the classifier may credit lookahead responses and skip "
        "checkpoints, breaking calibration"
    )
    assert "anticipate future" in EXCHANGE_CLASSIFIER_PROMPT, (
        "principle 6 must explicitly forbid crediting anticipatory responses"
    )


# ============================================================
# Story 6.10 — classify_multi (goal-based dialogue)
# ============================================================


def _multi_pending(*ids: str) -> list[dict]:
    chosen = ids or ("greet", "main", "drink")
    return [{"id": gid, "success_criteria": f"crit {gid}"} for gid in chosen]


def _multi_kwargs(**overrides: Any) -> dict[str, Any]:
    base = dict(
        user_text="hi, a coke please",
        last_character_line="What can I get you?",
        pending_goals=_multi_pending("greet", "main", "drink"),
        scenario_description="The Waiter",
    )
    base.update(overrides)
    return base


def test_multi_prompt_defaults_to_unmet_not_met() -> None:
    """2026-05-30 fix — the multi-goal judge was passing EVERY checkpoint
    regardless of input (smoke call_id=203/204: "there is a lot of people
    here" flipped `greet`). Root cause: the prompt told the model to mark
    "loosely related" input met and to "Default to MET when uncertain".
    Lock the corrected contract: the ACTIVE multi-goal prompt must default
    to UNMET and must NOT carry the old lenient markers. (Behaviour can't be
    asserted without hitting Groq; the prompt is the authoritative contract.)
    """
    from pipeline.prompts import EXCHANGE_CLASSIFIER_MULTI_PROMPT as P

    assert "Default to UNMET" in P, (
        "the multi-goal judge must default to UNMET — a default-to-MET judge "
        "passes every checkpoint and makes the exercise meaningless"
    )
    # The two markers that drove the over-validation must be gone.
    assert "Default to MET" not in P
    assert "loosely related" not in P
    # B1 tolerance (real-but-messy attempts still pass) must be retained so
    # the fix doesn't over-correct into false negatives.
    assert "INTENT" in P
    assert "uh" in P.lower() and "um" in P.lower()  # hesitation tolerance


def test_classify_multi_returns_per_goal_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.10 AC2 — one LLM call returns a per-goal verdict dict.
    A goal answered "met" → True, "unmet" → False, "unsure"/missing →
    None. Also asserts the request carries the STRICT json_schema whose
    keys are exactly the pending goal_ids, and the bare ids reach the
    prompt body (no `goal_id="..."` tag)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        assert "greet:" in prompt, "bare goal ids must reach the prompt"
        assert 'goal_id="greet"' not in prompt, "the tagged id format is the bug"
        # The strict schema must pin exactly the pending ids to the enum.
        schema = body["response_format"]["json_schema"]["schema"]
        assert body["response_format"]["json_schema"]["strict"] is True
        # FR37 — the strict schema also pins the reserved abuse boolean.
        assert set(schema["properties"]) == {"greet", "main", "drink", ABUSE_KEY}
        assert schema["properties"]["greet"]["enum"] == ["met", "unmet", "unsure"]
        assert schema["properties"][ABUSE_KEY]["type"] == "boolean"
        assert set(schema["required"]) == {"greet", "main", "drink", ABUSE_KEY}
        assert schema["additionalProperties"] is False
        assert request.url.host == "api.openai.com"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"greet": "met", "main": "unmet", "drink": "met"}'
                        }
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify_multi(**_multi_kwargs()))
    assert out == {"greet": True, "main": False, "drink": True, ABUSE_KEY: False}


def test_classify_multi_omitted_goal_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A goal answered "unsure", or absent from the object, → None (no
    verdict, stays pending)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"greet": "met", "main": "unsure"}'}}
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify_multi(**_multi_kwargs()))
    assert out == {"greet": True, "main": None, "drink": None, ABUSE_KEY: False}


def test_classify_multi_returns_none_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wholesale HTTP failure → `classify_multi` returns None (the
    INFRA-FAILURE sentinel; the caller feeds the consecutive-None backstop,
    distinct from a parsed all-"unsure" dict). Review D3 (2026-05-29)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connect error")

    _mock_http(monkeypatch, handler=_handler)
    out = _run(
        _make_classifier().classify_multi(
            **_multi_kwargs(pending_goals=_multi_pending("a", "b"))
        )
    )
    assert out is None


def test_classify_multi_returns_none_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pipeline.exchange_classifier as ec_mod

    monkeypatch.setattr(ec_mod, "_CLASSIFIER_TIMEOUT_SECONDS", 0.05)

    async def _slow(self: ExchangeClassifier, **kwargs: Any) -> Any:
        await asyncio.sleep(0.5)
        return {"a": True}

    monkeypatch.setattr(ExchangeClassifier, "_classify_multi", _slow)
    out = _run(
        _make_classifier().classify_multi(
            **_multi_kwargs(pending_goals=_multi_pending("a", "b"))
        )
    )
    assert out is None


def test_multi_max_tokens_scales_with_goal_count() -> None:
    """Story 6.16 regression — the multi-goal completion budget MUST grow with
    the goal count, else a long (e.g. 20-checkpoint) scenario overflows it and
    Groq returns 400 `json_validate_failed` on every classify. A fixed 128 was
    the bug."""
    from pipeline.exchange_classifier import _multi_max_tokens

    assert _multi_max_tokens(1) < _multi_max_tokens(6) < _multi_max_tokens(20)
    # 20 goals need real headroom (the old fixed 128 truncated the JSON).
    assert _multi_max_tokens(20) >= 500


def test_classify_multi_never_sends_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 10.6 review (D2) — the gpt-oss/Gemini reasoning_effort gating was
    removed. The shipped judge (OpenAI gpt-4.1-mini) is not a reasoning model, so
    `classify_multi` must NEVER put `reasoning_effort` on the payload (a
    non-reasoning model 400s on the unknown field)."""
    seen: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"a": "met", "b": "unmet"}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    clf = ExchangeClassifier(api_key="k", model="gpt-4.1-mini")
    _run(clf.classify_multi(**_multi_kwargs(pending_goals=_multi_pending("a", "b"))))
    assert "reasoning_effort" not in seen["payload"]


def test_classify_multi_returns_none_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """Groq rate-limit (429) on the multi path → None (patience-neutral
    infra failure), same contract as the single-goal path."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    _mock_http(monkeypatch, handler=_handler)
    out = _run(
        _make_classifier().classify_multi(
            **_multi_kwargs(pending_goals=_multi_pending("a", "b"))
        )
    )
    assert out is None


def test_classify_multi_returns_none_on_unparseable_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 200 whose assistant content is not JSON → parse failure → None
    (infra-grade), NOT a parsed all-"unsure" dict. Review D3 (2026-05-29)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "I cannot answer that."}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(
        _make_classifier().classify_multi(
            **_multi_kwargs(pending_goals=_multi_pending("a", "b"))
        )
    )
    assert out is None


def test_classify_multi_parsed_all_unsure_returns_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SUCCESSFULLY-PARSED response where every goal is "unsure" returns
    a dict of all-None — NOT the None infra sentinel. This is the case the
    caller must treat as benign ambiguity (no backstop). Review D3."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"a": "unsure", "b": "unsure"}'}}]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(
        _make_classifier().classify_multi(
            **_multi_kwargs(pending_goals=_multi_pending("a", "b"))
        )
    )
    assert out == {"a": None, "b": None, ABUSE_KEY: False}


def test_classify_multi_markdown_fenced_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive fence-strip fallback — a non-strict provider that wraps
    the verdict object in a Markdown fence still parses."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '```json\n{"a": "met", "b": "unmet"}\n```'}}
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(
        _make_classifier().classify_multi(
            **_multi_kwargs(pending_goals=_multi_pending("a", "b"))
        )
    )
    assert out == {"a": True, "b": False, ABUSE_KEY: False}


def test_classify_multi_surfaces_abuse_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR37 — the SAME multi call carries the abuse flag. The strict schema pins
    it, and classify_multi surfaces it alongside the goal verdicts (the caller
    pops + acts on it). No extra LLM call."""

    def _handler(request: httpx.Request) -> httpx.Response:
        schema = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        assert ABUSE_KEY in schema["properties"]
        assert ABUSE_KEY in schema["required"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"a": "unmet", "b": "unmet", '
                            '"__user_abusive__": true}'
                        }
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(
        _make_classifier().classify_multi(
            **_multi_kwargs(pending_goals=_multi_pending("a", "b"))
        )
    )
    assert out == {"a": False, "b": False, ABUSE_KEY: True}


def test_legacy_classify_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Story 6.10 AC2 — the single-objective `classify` wrapper is
    preserved unchanged for the legacy `/connect` PoC path."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"met": true}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(_make_classifier().classify(**_kwargs()))
    assert out is True


def test_multi_output_parser_helpers() -> None:
    from pipeline.exchange_classifier import (
        ABUSE_KEY,
        _build_verdict_schema,
        _format_pending_goals_block,
        _parse_multi_classifier_output,
    )

    block = _format_pending_goals_block(
        [
            {"id": "greet", "success_criteria": "say hi"},
            {"id": "drink", "success_criteria": "pick a drink"},
        ]
    )
    # Bare `- <id>: <criteria>` — the tagged `goal_id="..."` form is the
    # 2026-05-29 silent-no-flip bug and must NOT appear.
    assert "- greet: say hi" in block
    assert "- drink: pick a drink" in block
    assert 'goal_id="greet"' not in block

    # Strict schema: one enum-constrained property per id, all required, PLUS the
    # FR37 reserved abuse boolean. No other extras.
    schema = _build_verdict_schema(["a", "b"])
    assert set(schema["properties"]) == {"a", "b", ABUSE_KEY}
    assert schema["properties"]["a"]["enum"] == ["met", "unmet", "unsure"]
    assert schema["properties"][ABUSE_KEY]["type"] == "boolean"
    assert set(schema["required"]) == {"a", "b", ABUSE_KEY}
    assert schema["additionalProperties"] is False

    # A PARSE failure (non-JSON / non-dict body) → None (infra-grade,
    # review D3 2026-05-29), NOT a parsed all-None dict.
    assert _parse_multi_classifier_output("no json here", ["a"], model="m") is None
    # met → True, unmet → False, unsure / missing key / unknown value → None.
    # Every parsed dict ALSO carries the abuse flag (default False).
    assert _parse_multi_classifier_output('{"a": "met"}', ["a"], model="m") == {
        "a": True,
        ABUSE_KEY: False,
    }
    assert _parse_multi_classifier_output('{"a": "unmet"}', ["a"], model="m") == {
        "a": False,
        ABUSE_KEY: False,
    }
    assert _parse_multi_classifier_output('{"a": "unsure"}', ["a"], model="m") == {
        "a": None,
        ABUSE_KEY: False,
    }
    # Missing key → None; unknown extra key ignored; abuse flag default False.
    assert _parse_multi_classifier_output(
        '{"x": "met", "b": "unmet"}', ["a", "b"], model="m"
    ) == {
        "a": None,
        "b": False,
        ABUSE_KEY: False,
    }
    # FR37 — the abuse flag is surfaced when the model sets it true (and only a
    # strict `true` boolean counts — a non-bool is treated as not-abusive).
    assert _parse_multi_classifier_output(
        '{"a": "unmet", "__user_abusive__": true}', ["a"], model="m"
    ) == {"a": False, ABUSE_KEY: True}
    assert _parse_multi_classifier_output(
        '{"a": "met", "__user_abusive__": "true"}', ["a"], model="m"
    ) == {"a": True, ABUSE_KEY: False}


# ============================================================
# Story 6.27 — classifier warm-up + first-call retry + verdict logging
# ============================================================


def test_warm_up_posts_once_through_instance_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2a — `warm_up()` fires exactly ONE `max_tokens=1` completion through
    the instance's own `_get_client()` (the whole point: warming THIS
    instance's connection, not a throwaway one) and logs INFO only on a
    confirmed 2xx (Story 6.24 review lesson — no phantom warm-up logs)."""
    from loguru import logger as loguru_logger

    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "h"}}]})

    _mock_http(monkeypatch, handler=_handler)
    classifier = _make_classifier()

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="INFO")
    try:
        _run(classifier.warm_up())
    finally:
        loguru_logger.remove(sink_id)

    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 1
    assert "response_format" not in calls[0]  # connection warmth, not a verdict
    assert any("exchange_classifier_warmup" in entry for entry in captured)
    assert any("connection warmed" in entry for entry in captured)


def test_warm_up_never_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """D2a — the warm-up contract mirrors `warm_up_llm`: every failure is
    swallowed (DEBUG), never raised — a cold first classify is a one-turn UX
    nit, a crashed call is not."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    _mock_http(monkeypatch, handler=_handler)
    _run(_make_classifier().warm_up())  # must not raise


def test_warm_up_non_2xx_does_not_log_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.24 review lesson — a non-2xx warm-up is NOT a real warm-up;
    it must not emit the INFO success line (phantom-warm-up class)."""
    from loguru import logger as loguru_logger

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    _mock_http(monkeypatch, handler=_handler)

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="INFO")
    try:
        _run(_make_classifier().warm_up())
    finally:
        loguru_logger.remove(sink_id)

    assert not any("connection warmed" in entry for entry in captured)


def test_first_call_retry_recovers_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    """D2b / AC4 — the instance's FIRST `classify_multi` hitting an infra
    failure (the calls-265/266 cold-start ReadTimeout) retries ONCE and the
    verdicts still land. The opening turn is no longer silently stranded."""
    from loguru import logger as loguru_logger

    attempts: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("simulated cold-start timeout")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"greet": "met", "main": "unmet"}'}}
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="INFO")
    try:
        out = _run(
            _make_classifier().classify_multi(
                **_multi_kwargs(pending_goals=_multi_pending("greet", "main"))
            )
        )
    finally:
        loguru_logger.remove(sink_id)

    assert len(attempts) == 2
    assert out == {"greet": True, "main": False, ABUSE_KEY: False}
    assert any("first-call retry" in entry for entry in captured)


def test_no_retry_after_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """D2b — once the instance has completed one parsed verdict, a later
    failure is NOT retried (the retry is a cold-start measure only; steady-
    state failures stay single-attempt + consecutive-None backstop)."""
    attempts: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"greet": "met"}'}}]},
            )
        raise httpx.ReadTimeout("simulated mid-call timeout")

    _mock_http(monkeypatch, handler=_handler)
    classifier = _make_classifier()
    kwargs = _multi_kwargs(pending_goals=_multi_pending("greet"))

    first = _run(classifier.classify_multi(**kwargs))
    assert first == {"greet": True, ABUSE_KEY: False}

    second = _run(classifier.classify_multi(**kwargs))
    assert second is None
    assert len(attempts) == 2  # no third POST — the failure was NOT retried


def test_first_call_retry_never_retries_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2b — the retry is one-shot: first attempt + one retry, never a third
    attempt within the same call."""
    attempts: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ReadTimeout("simulated persistent outage")

    _mock_http(monkeypatch, handler=_handler)
    out = _run(
        _make_classifier().classify_multi(
            **_multi_kwargs(pending_goals=_multi_pending("greet"))
        )
    )
    assert out is None
    assert len(attempts) == 2  # exactly one retry, then give up


def test_retry_rearms_on_next_call_until_first_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2b disclosed semantics (6.27 review) — the one-shot retry re-arms on
    EVERY call until the instance's first PARSED verdict: if turn 1 + its
    retry both fail, turn 2 still gets its own single retry (the connection
    may still be cold). Bounded: one retry per call, none after the first
    success. Pins the Dev Agent Record's documented reading of D2b."""
    attempts: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) <= 3:
            raise httpx.ReadTimeout("simulated cold start outlasting turn 1")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"greet": "met"}'}}]},
        )

    _mock_http(monkeypatch, handler=_handler)
    classifier = _make_classifier()
    kwargs = _multi_kwargs(pending_goals=_multi_pending("greet"))

    # Turn 1: attempt + its one retry both fail → None (exactly 2 POSTs).
    assert _run(classifier.classify_multi(**kwargs)) is None
    assert len(attempts) == 2
    # Turn 2: still no success ever → the retry re-arms (attempt 3 fails,
    # retry 4 parses) — the verdicts land instead of stranding the turn.
    assert _run(classifier.classify_multi(**kwargs)) == {
        "greet": True,
        ABUSE_KEY: False,
    }
    assert len(attempts) == 4


def test_checkpoint_verdicts_log_caps_pathological_values() -> None:
    """6.27 review — the fence-fallback parse path accepts arbitrary JSON
    values for a goal id; the forensic `checkpoint_verdicts` line caps them
    (repr, 32 chars) instead of ballooning a journal line. Strict-schema
    prod values are short enums and render verbatim."""
    from loguru import logger as loguru_logger

    from pipeline.exchange_classifier import _parse_multi_classifier_output

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="INFO")
    try:
        out = _parse_multi_classifier_output(
            '{"greet": {"deep": "' + "x" * 200 + '"}}', ["greet"], model="m"
        )
    finally:
        loguru_logger.remove(sink_id)

    # An unknown (non-enum) value still maps to None — no verdict.
    assert out == {"greet": None, ABUSE_KEY: False}
    line = next(e for e in captured if "checkpoint_verdicts" in e)
    assert "x" * 50 not in line  # the 200-char payload was capped, not echoed


def test_checkpoint_verdicts_logged_with_raw_enum_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5 — every successful `classify_multi` logs ONE INFO
    `checkpoint_verdicts` line with the RAW per-goal enum values (so the
    journal distinguishes `unsure` from `unmet` — the exact distinction the
    call-266 forensics could not recover). Loguru temp-sink per
    server/CLAUDE.md §3 (`caplog` does not capture loguru)."""
    from loguru import logger as loguru_logger

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"greet": "unsure", "main": "met", '
                            '"drink": "unmet"}'
                        }
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="INFO")
    try:
        out = _run(_make_classifier().classify_multi(**_multi_kwargs()))
    finally:
        loguru_logger.remove(sink_id)

    assert out == {"greet": None, "main": True, "drink": False, ABUSE_KEY: False}
    verdict_lines = [e for e in captured if "checkpoint_verdicts" in e]
    assert len(verdict_lines) == 1  # ONE line per successful classify
    line = verdict_lines[0]
    assert f"model={_PROVIDER_MODEL}" in line
    # Raw enums, not the bool mapping: unsure and unmet must be distinct.
    assert "'greet': 'unsure'" in line
    assert "'main': 'met'" in line
    assert "'drink': 'unmet'" in line
