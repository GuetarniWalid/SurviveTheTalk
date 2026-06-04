"""Story 6.18 — tests for the dynamic exit/patience-warning line generator.

Mocked-LLM only (AC8): no live LLM call ever runs in `pytest`. Mirrors the
`test_exchange_classifier.py` httpx-mock pattern (a `MockTransport`-routed
`AsyncClient` factory) so the EXACT prod request/parse path is exercised.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

import pipeline.exit_line_generator as elg_mod
from pipeline.exit_line_generator import (
    _clean_line,
    _normalize_transcript,
    generate_exit_line,
)
from pipeline.prompts import (
    EXIT_LINE_CONSTRAINT,
    EXIT_LINE_GUIDANCE_DEFAULT,
    EXIT_LINE_REASON_GUIDANCE,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_http(monkeypatch: pytest.MonkeyPatch, *, handler) -> None:
    """Route the generator's `httpx.AsyncClient` through a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("pipeline.exit_line_generator.httpx.AsyncClient", _factory)


def _ok(content: str):
    """A MockTransport handler returning a 200 with `content` as the line."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    return _handler


_TRANSCRIPT = [
    {"role": "assistant", "content": "Where were you on the night of the break-in?"},
    {"role": "user", "content": "I was at home."},
    {"role": "assistant", "content": "Can anyone confirm that?"},
    {"role": "user", "content": "uh... no."},
]


def _kwargs(**overrides: Any) -> dict[str, Any]:
    base = dict(
        reason="character_hung_up",
        transcript=list(_TRANSCRIPT),
        persona="You are Detective Mercer, a hard-nosed interrogator.",
        charter="CHARTER_MARKER: never invent facts you did not observe.",
        api_key="test-key",
        model="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1/chat/completions",
    )
    base.update(overrides)
    return base


# ---------- happy path ----------------------------------------------------


def test_generate_returns_clean_line_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_http(monkeypatch, handler=_ok("Get out of my interrogation room."))
    out = _run(generate_exit_line(**_kwargs()))
    assert out == "Get out of my interrogation room."


def test_generate_strips_surrounding_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_http(monkeypatch, handler=_ok('"You need to give me real answers."'))
    out = _run(generate_exit_line(**_kwargs()))
    assert out == "You need to give me real answers."


def test_generate_truncates_to_two_sentences(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3 — a 4-sentence over-generation is capped to 2 sentences so the
    line can't blow the 6 s TTS ceiling."""
    _mock_http(
        monkeypatch,
        handler=_ok("First sentence. Second sentence. Third sentence. Fourth one."),
    )
    out = _run(generate_exit_line(**_kwargs()))
    assert out == "First sentence. Second sentence."


# ---------- fallback (returns None) ---------------------------------------


def test_generate_returns_none_on_empty_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_http(monkeypatch, handler=_ok("   "))
    assert _run(generate_exit_line(**_kwargs())) is None


def test_generate_returns_none_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    _mock_http(monkeypatch, handler=_handler)
    assert _run(generate_exit_line(**_kwargs())) is None


def test_generate_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _mock_http(monkeypatch, handler=_handler)
    assert _run(generate_exit_line(**_kwargs())) is None


def test_generate_returns_none_on_malformed_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        # 200 but no `choices` key — defensive parse must return None.
        return httpx.Response(200, json={"unexpected": "shape"})

    _mock_http(monkeypatch, handler=_handler)
    assert _run(generate_exit_line(**_kwargs())) is None


def test_generate_returns_none_on_empty_transcript_without_calling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No real conversation to ground the line → the canned fallback (None)
    is more coherent than inventing one. The LLM must NOT be called."""
    calls: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    _mock_http(monkeypatch, handler=_handler)
    out = _run(generate_exit_line(**_kwargs(transcript=[])))
    assert out is None
    assert calls == [], "must not POST to the LLM when the transcript is empty"


def test_generate_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3 — generation is time-boxed; a slow provider falls back (None)."""

    async def _slow(**kwargs: Any):
        await asyncio.sleep(0.5)
        return "too late"

    monkeypatch.setattr(elg_mod, "_generate", _slow)
    out = _run(generate_exit_line(**_kwargs(timeout=0.05)))
    assert out is None


# ---------- prompt content (AC4 / AC5) ------------------------------------


def _capture_prompt(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Mock the LLM + capture the single user-message prompt that was POSTed."""
    captured: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append(payload["messages"][0]["content"])
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Fine. Goodbye."}}]}
        )

    _mock_http(monkeypatch, handler=_handler)
    return captured


def test_prompt_includes_persona_charter_transcript_and_anti_fabrication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5 — the no-fabrication rule is enforced in the prompt: the persona,
    the charter, the real transcript, and the explicit "do NOT invent ...
    changing their story" clause are all present."""
    captured = _capture_prompt(monkeypatch)
    _run(generate_exit_line(**_kwargs()))
    prompt = captured[0]

    assert "Detective Mercer" in prompt  # persona
    assert "CHARTER_MARKER" in prompt  # the charter arg
    # Transcript rendered as USER:/CHARACTER: lines.
    assert "USER: I was at home." in prompt
    assert "CHARACTER: Can anyone confirm that?" in prompt
    # The heart of the 6.18 fix — the full anti-fabrication constraint is
    # present verbatim (it has no braces, so escaping is a no-op).
    assert EXIT_LINE_CONSTRAINT in prompt
    assert "changing their story" in prompt  # the explicit call-212 anti-example
    assert "TWO SHORT SENTENCES" in prompt


def test_prompt_uses_reason_specific_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4 — each reason injects its own guidance; an unknown reason falls
    back to the default guidance."""
    captured = _capture_prompt(monkeypatch)  # monkeypatch ONCE; accumulate
    reasons = [
        "character_hung_up",
        "inappropriate_content",
        "noisy_environment",
        "survived",
        "patience_warning",
    ]
    for reason in reasons:
        _run(generate_exit_line(**_kwargs(reason=reason)))
    _run(generate_exit_line(**_kwargs(reason="totally_unknown_reason")))

    for i, reason in enumerate(reasons):
        assert EXIT_LINE_REASON_GUIDANCE[reason] in captured[i], reason
    assert EXIT_LINE_GUIDANCE_DEFAULT in captured[len(reasons)]


def test_prompt_does_not_double_brace_a_transcript_with_literal_braces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.9b P14 analog — STT text can contain literal braces; the
    generator must escape them for `.format()` without crashing AND without
    leaking double-braces into the model-visible prompt."""
    captured = _capture_prompt(monkeypatch)
    transcript = [
        {"role": "user", "content": 'I said {"met": true} out loud, weird I know.'}
    ]
    out = _run(generate_exit_line(**_kwargs(transcript=transcript)))
    assert out == "Fine. Goodbye."  # did not crash
    # The literal braces survive single (un-doubled) in the model-visible text.
    assert '{"met": true}' in captured[0]


def test_payload_caps_tokens_and_uses_character_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payload: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_payload.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Done. Bye."}}]}
        )

    _mock_http(monkeypatch, handler=_handler)
    _run(generate_exit_line(**_kwargs(model="my-model")))
    p = captured_payload[0]
    assert p["model"] == "my-model"
    assert p["max_tokens"] == elg_mod._MAX_TOKENS
    assert p["temperature"] == elg_mod._TEMPERATURE


# ---------- pure-helper unit tests ----------------------------------------


def test_normalize_transcript_filters_caps_and_renders() -> None:
    messages = [
        {"role": "system", "content": "ignored system"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": ""},  # empty → skipped
        {"role": "tool", "content": "ignored tool"},
        {"role": "assistant", "content": "reply"},
        "not-a-dict",  # skipped
        {"role": "user", "content": "second"},
    ]
    rendered = _normalize_transcript(messages, max_messages=2)
    # System/tool/empty/non-dict dropped; capped to the last 2 kept turns.
    assert rendered == ["CHARACTER: reply", "USER: second"]


def test_normalize_transcript_handles_multipart_content() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi there"}]},
    ]
    assert _normalize_transcript(messages, max_messages=8) == ["USER: hi there"]


def test_clean_line_handles_quotes_sentences_and_empty() -> None:
    assert _clean_line(None) is None
    assert _clean_line("   ") is None
    assert _clean_line("  Plain line.  ") == "Plain line."
    assert _clean_line('"quoted"') == "quoted"
    assert _clean_line("“smart quoted”") == "smart quoted"
    assert _clean_line("One. Two. Three.") == "One. Two."


# ---------- code-review patches (2026-06-04) ------------------------------


def test_temperature_matches_character_temperature() -> None:
    """Review #11 — the generator's hardcoded temperature must stay in parity
    with the main character LLM so closing lines keep the same in-character
    warmth. Catches a future retune of CHARACTER_TEMPERATURE."""
    from pipeline.llm_provider import CHARACTER_TEMPERATURE

    assert elg_mod._TEMPERATURE == CHARACTER_TEMPERATURE


def test_every_valid_reason_plus_warning_has_guidance() -> None:
    """Review #24 — every hang-up reason (+ patience_warning) must have its own
    exit-line guidance key, else it silently degrades to EXIT_LINE_GUIDANCE_
    DEFAULT (a generic, non-reason-specific line). Derived FROM _VALID_REASONS
    so adding a reason without guidance turns this red."""
    from pipeline import patience_tracker as pt

    required = set(pt._VALID_REASONS) | {pt._REASON_PATIENCE_WARNING}
    missing = required - set(EXIT_LINE_REASON_GUIDANCE)
    assert not missing, (
        f"reasons without exit-line guidance: {sorted(missing)} — add a key to "
        "EXIT_LINE_REASON_GUIDANCE or they fall back to EXIT_LINE_GUIDANCE_DEFAULT"
    )


def test_generate_caps_run_on_line_without_terminator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review #8 — a long run-on line with NO internal sentence terminator
    can't be split by the 2-sentence cap, so the _MAX_LINE_CHARS backstop must
    bound it on a word boundary (else a 60-word line blows the 6 s TTS ceiling)."""
    run_on = (
        "you know I really thought you were going to give me something real "
        "today but instead you just sat there wasting both our time and now I "
        "am completely and utterly done with this whole pointless conversation"
    )
    _mock_http(monkeypatch, handler=_ok(run_on))
    out = _run(generate_exit_line(**_kwargs()))
    assert out is not None
    assert len(out) <= elg_mod._MAX_LINE_CHARS
    assert not out.endswith(" ")  # trimmed on a word boundary


def test_generate_returns_none_on_length_truncated_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review #9 — a token-capped (finish_reason=length) completion is a
    dangling mid-thought fragment, so the generator returns None and the caller
    speaks the canned line instead of a truncated sentence."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "You know, I really thought you were"},
                        "finish_reason": "length",
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    assert _run(generate_exit_line(**_kwargs())) is None


def test_generate_coerces_multipart_text_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review #23 — a multimodal content LIST with a text part is coerced to
    that text (via _extract_text) instead of crashing into the catch-all."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [{"type": "text", "text": "We are done here."}]
                        }
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    assert _run(generate_exit_line(**_kwargs())) == "We are done here."


def test_generate_returns_none_on_unrenderable_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review #23 — a non-string content with no text part coerces to "" and
    returns None (canned fallback) rather than raising an AttributeError."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": [{"foo": "bar"}]}}]}
        )

    _mock_http(monkeypatch, handler=_handler)
    assert _run(generate_exit_line(**_kwargs())) is None


def test_generate_returns_none_on_non_list_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review #21 — a non-list/None transcript must NOT raise (the documented
    never-raises contract); it returns None so the caller uses the canned line."""
    _mock_http(monkeypatch, handler=_ok("should not be reached"))
    assert _run(generate_exit_line(**_kwargs(transcript=None))) is None
    assert _run(generate_exit_line(**_kwargs(transcript="not a list"))) is None


def test_clean_line_matched_pairs_preserve_apostrophes() -> None:
    """Review #10 — matched-pair quote handling: strip a surrounding double /
    smart pair (incl. a trailing period placed outside the close quote), but
    NEVER strip an ASCII single quote (ambiguous with a content apostrophe)."""
    # trailing period OUTSIDE the closing double quote
    assert _clean_line('"You are done here".') == "You are done here."
    # leading elision apostrophe + trailing possessive — must survive intact
    assert _clean_line("'Cause I'm done with the kids'") == (
        "'Cause I'm done with the kids'"
    )
    # smart single pair IS stripped (unambiguous)
    assert _clean_line("‘Get out.’") == "Get out."
