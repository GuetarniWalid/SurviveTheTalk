"""Story 7.1 — tests for the debrief generator (mocked-LLM only, AC12).

No live Groq call ever runs in pytest. Mirrors the `test_exit_line_generator`
httpx-`MockTransport` pattern so the EXACT prod request/parse path runs. Also
guards the verbatim system prompt against drift from the authoritative design
doc, and pins the strict-schema shape (incl. the deliberate minItems/maxItems
omission for Groq strict compatibility).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

import pipeline.debrief_generator as dg_mod
from pipeline.debrief_generator import (
    _build_debrief_schema,
    _build_user_message,
    _clamp_areas,
    _format_hesitations,
    _format_transcript,
    _parse_debrief_output,
    generate_debrief,
)
from pipeline.prompts import DEBRIEF_PROMPT_VERSION, DEBRIEF_SYSTEM_PROMPT

_DOC = (
    Path(__file__).resolve().parent.parent.parent
    / "_bmad-output"
    / "planning-artifacts"
    / "debrief-generation-prompt.md"
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_http(monkeypatch, *, handler, captured=None) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("pipeline.debrief_generator.httpx.AsyncClient", _factory)


_VALID_CORE = {
    "errors": [
        {
            "user_said": "I am agree",
            "correction": "I agree",
            "context": "Responding to the demand",
            "count": 3,
            "explanation": "'agree' is not used with 'be'; it stands alone.",
            "examples": ["I agree with you."],
        }
    ],
    "hesitation_contexts": [
        {"hesitation_id": "h1", "context": "After the threat escalated"}
    ],
    "idioms": [
        {
            "expression": "Pull the other one",
            "meaning": "I don't believe you",
            "context": "When you claimed to have no wallet",
        }
    ],
    "better_phrasings": [],
    "areas": [
        {
            "title": "Negative sentence structure",
            "evidence": 'You said "I am not want"',
            "practice_prompt": "You are an English coach. Drill negative sentences.",
        },
        {
            "title": "Articles",
            "evidence": 'You dropped "a" before "wallet"',
            "practice_prompt": "You are an English coach. Drill articles.",
        },
    ],
    "inappropriate_behavior": None,
}

_TRANSCRIPT = [
    {"role": "character", "text": "Give me your wallet.", "timestamp_ms": 0},
    {"role": "user", "text": "I am not want problem.", "timestamp_ms": 1500},
    {"role": "character", "text": "Talk properly.", "timestamp_ms": 3000},
]


def _kwargs(**overrides: Any) -> dict[str, Any]:
    base = dict(
        transcript=list(_TRANSCRIPT),
        reason="character_hung_up",
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        brief_personality_description="A street mugger demanding your valuables.",
        hesitations=[
            {"duration_sec": 4.2, "preceding_character_line": "Talk properly."}
        ],
        api_key="test-key",
        model="openai/gpt-oss-120b",
        base_url="https://api.groq.com/openai/v1/chat/completions",
    )
    base.update(overrides)
    return base


def _resp(content: str, *, finish_reason: str = "stop", status: int = 200):
    def _handler(request: httpx.Request) -> httpx.Response:
        if status >= 300:
            return httpx.Response(status, json={"error": "boom"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": content}, "finish_reason": finish_reason}
                ]
            },
        )

    return _handler


# ---------- verbatim prompt drift guard -----------------------------------


def test_system_prompt_matches_authoritative_doc():
    """DEBRIEF_SYSTEM_PROMPT must stay byte-identical (modulo trailing newline)
    to the v1.0 block in debrief-generation-prompt.md — the doc is the single
    source of truth and a change requires a content-strategy review."""
    doc = _DOC.read_text(encoding="utf-8")
    i = doc.index("## System Prompt")
    m = re.search(r"```\s*\n(.*?)\n```", doc[i:], re.DOTALL)
    block = m.group(1).replace("\r\n", "\n").replace("\r", "\n")
    assert DEBRIEF_SYSTEM_PROMPT.strip() == block.strip()
    assert DEBRIEF_PROMPT_VERSION == "2.2"


# ---------- schema builder (AC3) ------------------------------------------


def test_schema_top_level_shape():
    schema = _build_debrief_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "errors",
        "hesitation_contexts",
        "idioms",
        "better_phrasings",
        "areas",
        "inappropriate_behavior",
    }


def test_schema_error_item_all_required_no_extra():
    item = _build_debrief_schema()["properties"]["errors"]["items"]
    assert item["additionalProperties"] is False
    # v2 adds the tap-sheet depth fields; strict mode requires ALL listed.
    assert set(item["required"]) == {
        "user_said",
        "correction",
        "context",
        "count",
        "explanation",
        "examples",
    }
    assert item["properties"]["count"]["type"] == "integer"


def test_schema_areas_item_is_evidence_linked():
    item = _build_debrief_schema()["properties"]["areas"]["items"]
    assert item["additionalProperties"] is False
    # is_focus is NOT in the LLM schema — the backend pins it.
    assert set(item["required"]) == {"title", "evidence", "practice_prompt"}
    assert "is_focus" not in item["properties"]


def test_schema_hesitation_context_echoes_id():
    item = _build_debrief_schema()["properties"]["hesitation_contexts"]["items"]
    assert set(item["required"]) == {"hesitation_id", "context"}


def test_schema_inappropriate_behavior_is_nullable():
    prop = _build_debrief_schema()["properties"]["inappropriate_behavior"]
    assert prop["type"] == ["string", "null"]


def test_schema_omits_array_length_constraints_for_groq_strict():
    # minItems/maxItems are rejected by Groq strict mode — the cap guarantees
    # come from the prompt + the backend clamps, not the schema.
    schema = _build_debrief_schema()
    for key in ("errors", "areas", "better_phrasings"):
        node = schema["properties"][key]
        assert "minItems" not in node and "maxItems" not in node
        assert node["items"]["type"] == "object"
    assert (
        schema["properties"]["errors"]["items"]["properties"]["examples"]["type"]
        == "array"
    )


# ---------- user message + helpers ----------------------------------------


def test_format_transcript_alternates_labels():
    out = _format_transcript(_TRANSCRIPT)
    assert out == (
        "CHARACTER: Give me your wallet.\n"
        "USER: I am not want problem.\n"
        "CHARACTER: Talk properly."
    )


def test_format_hesitations_renders_silences():
    out = _format_hesitations(
        [
            {
                "id": "h1",
                "duration_sec": 4.23,
                "preceding_character_line": "Talk properly.",
                "resolved": True,
            }
        ]
    )
    assert out == (
        'hesitation_id "h1": 4.2s pause — after CHARACTER said: "Talk properly."'
    )


def test_format_hesitations_flags_unresolved_freeze():
    out = _format_hesitations(
        [
            {
                "id": "h2",
                "duration_sec": 7.0,
                "preceding_character_line": "Answer me.",
                "resolved": False,
            }
        ]
    )
    assert "the character had to speak again" in out
    assert 'hesitation_id "h2"' in out


def test_format_hesitations_empty_sentinel():
    assert _format_hesitations([]) == "No significant hesitations detected."


def test_user_message_contains_header_and_fences():
    msg = _build_user_message(
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        brief_personality_description="A mugger.",
        reason="inappropriate_content",
        transcript_text="CHARACTER: hi\nUSER: hello",
        hesitation_block="No significant hesitations detected.",
    )
    assert "Scenario: The Mugger — Give me your wallet" in msg
    assert "Call end reason: inappropriate_content" in msg
    assert "=== TRANSCRIPT ===" in msg and "=== END TRANSCRIPT ===" in msg
    assert "=== HESITATION DATA ===" in msg


def _area(title, *, evidence="In-call evidence.", practice="Coach prompt."):
    return {"title": title, "evidence": evidence, "practice_prompt": practice}


def test_clamp_areas_keeps_first_three_and_drops_evidence_free():
    four = [_area("a"), _area("b"), _area("c"), _area("d")]
    assert _clamp_areas(four) == [_area("a"), _area("b"), _area("c")]
    # evidence is mandatory — an area with blank evidence is generic filler.
    assert _clamp_areas([_area("x", evidence="")]) == []
    # missing practice_prompt → dropped; non-list → empty.
    assert _clamp_areas([{"title": "y", "evidence": "e"}]) == []
    assert _clamp_areas("not a list") == []


def test_clamp_areas_truncates_practice_prompt_and_collapses_whitespace():
    long_prompt = "word " * 400  # ~2000 chars with newlines collapsed
    out = _clamp_areas([_area("a", practice="line1\n\nline2 " + long_prompt)])
    assert len(out) == 1
    assert len(out[0]["practice_prompt"]) <= 900
    assert "\n" not in out[0]["practice_prompt"]


def test_parse_strips_markdown_fence():
    fenced = "```json\n" + json.dumps(_VALID_CORE) + "\n```"
    out = _parse_debrief_output(fenced)
    assert out is not None and out["errors"][0]["count"] == 3


def test_parse_rejects_body_with_no_core_keys():
    assert _parse_debrief_output('{"totally": "unrelated"}') is None


def test_parse_rejects_non_json():
    assert _parse_debrief_output("not json at all") is None


# ---------- generate_debrief: happy path ----------------------------------


def test_generate_returns_core_and_sends_strict_schema(monkeypatch):
    seen: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(_VALID_CORE)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(generate_debrief(**_kwargs()))
    assert out is not None
    assert out["errors"][0]["user_said"] == "I am agree"
    # request carried a strict json_schema response_format + the gpt-oss model.
    rf = seen["payload"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "debrief_analysis"
    assert rf["json_schema"]["strict"] is True
    assert seen["payload"]["model"] == "openai/gpt-oss-120b"
    # Story 10.6 — gpt-oss reasoning model → reasoning_effort=low on the request.
    assert seen["payload"]["reasoning_effort"] == "low"
    # system + user messages both sent.
    roles = [m["role"] for m in seen["payload"]["messages"]]
    assert roles == ["system", "user"]


def test_generate_omits_reasoning_effort_for_non_gpt_oss(monkeypatch):
    """Story 10.6 — reasoning_effort is GATED to gpt-oss: a non-gpt-oss
    debrief_model (e.g. a rollback) must never receive the field (it 400s on the
    unknown param)."""
    seen: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(_VALID_CORE)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(generate_debrief(**_kwargs(model="llama-3.3-70b-versatile")))
    assert out is not None
    assert "reasoning_effort" not in seen["payload"]


def test_generate_clamps_areas_to_three(monkeypatch):
    core = dict(_VALID_CORE)
    core["areas"] = [_area(t) for t in ("a", "b", "c", "d", "e")]
    _mock_http(monkeypatch, handler=_resp(json.dumps(core)))
    out = _run(generate_debrief(**_kwargs()))
    assert [a["title"] for a in out["areas"]] == ["a", "b", "c"]


# ---------- generate_debrief: None / failure paths ------------------------


def test_generate_none_on_empty_transcript(monkeypatch):
    # No HTTP call should even fire.
    _mock_http(monkeypatch, handler=_resp(json.dumps(_VALID_CORE)))
    assert _run(generate_debrief(**_kwargs(transcript=[]))) is None


def test_generate_none_on_non_2xx(monkeypatch):
    _mock_http(monkeypatch, handler=_resp("{}", status=400))
    assert _run(generate_debrief(**_kwargs())) is None


def test_generate_none_on_truncated_length(monkeypatch):
    _mock_http(
        monkeypatch,
        handler=_resp(json.dumps(_VALID_CORE), finish_reason="length"),
    )
    assert _run(generate_debrief(**_kwargs())) is None


def test_generate_none_on_garbage_body(monkeypatch):
    _mock_http(monkeypatch, handler=_resp("not json"))
    assert _run(generate_debrief(**_kwargs())) is None


# ---------- generate_debrief: non-strict retry on a schema 400 -------------
# call_id=324 (2026-06-24): Groq strict mode 400'd the WHOLE debrief because the
# model emitted areas[0].practice_prompt as an object, so no report was stored.
# The fix retries once in json_object mode and salvages what parses.


def test_generate_retries_without_strict_on_schema_400(monkeypatch):
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Generated JSON does not match the expected "
                        "schema. ...practice_prompt... expected string, but got "
                        "object",
                        "code": "json_validate_failed",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(_VALID_CORE)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(generate_debrief(**_kwargs()))
    assert out is not None
    assert out["errors"][0]["user_said"] == "I am agree"
    # Exactly two round-trips: strict json_schema, then non-strict json_object.
    assert len(calls) == 2
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[1]["response_format"] == {"type": "json_object"}
    # Story 10.6 — reasoning_effort=low rides BOTH the strict and the fallback
    # payloads for a gpt-oss model (the fallback still hits the same model).
    assert calls[0]["reasoning_effort"] == "low"
    assert calls[1]["reasoning_effort"] == "low"
    # The fallback system message carries the "json" token (json_object mode
    # requires it) AND pins the string-not-object rule that caused the 400.
    fallback_system = calls[1]["messages"][0]["content"]
    assert "PLAIN JSON STRING" in fallback_system
    assert "json" in fallback_system.lower()


def test_generate_retry_salvages_object_typed_practice_prompt(monkeypatch):
    # The EXACT call_id=324 shape: the retry's core still has an object-typed
    # areas[0].practice_prompt. The non-strict salvage (_clamp_areas via
    # _clean_str) drops that one area and keeps the rest — a usable debrief.
    calls: list[dict] = []
    bad_core = json.loads(json.dumps(_VALID_CORE))
    bad_core["areas"][0]["practice_prompt"] = {"role": "coach", "focus": "x"}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": json.dumps(bad_core)},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    _mock_http(monkeypatch, handler=_handler)
    out = _run(generate_debrief(**_kwargs()))
    assert out is not None
    # The object-typed area was dropped; the valid second area survived.
    assert [a["title"] for a in out["areas"]] == ["Articles"]


def test_generate_no_retry_on_5xx(monkeypatch):
    # A 5xx / connection failure is NOT a schema rejection — re-rolling a broken
    # provider buys nothing, so there is exactly ONE round-trip and None.
    calls: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"error": "upstream"})

    _mock_http(monkeypatch, handler=_handler)
    assert _run(generate_debrief(**_kwargs())) is None
    assert len(calls) == 1


def test_degraded_core_is_empty_and_enforces_inappropriate():
    core = dg_mod.degraded_core("character_hung_up")
    assert core == {
        "errors": [],
        "hesitation_contexts": [],
        "idioms": [],
        "better_phrasings": [],
        "areas": [],
        "inappropriate_behavior": None,
    }
    # On an inappropriate end the canonical factual fallback fills the field.
    flagged = dg_mod.degraded_core("inappropriate_content")
    assert flagged["inappropriate_behavior"] == dg_mod._INAPPROPRIATE_FALLBACK


def test_generate_none_on_timeout(monkeypatch):
    async def _slow(**_kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(dg_mod, "_generate", _slow)
    assert _run(generate_debrief(**_kwargs(timeout=0.05))) is None


def test_generate_none_on_unexpected_exception(monkeypatch):
    async def _boom(**_kwargs):
        raise ValueError("kaboom")

    monkeypatch.setattr(dg_mod, "_generate", _boom)
    assert _run(generate_debrief(**_kwargs())) is None


def test_generate_reraises_cancelled(monkeypatch):
    async def _cancel(**_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(dg_mod, "_generate", _cancel)
    with pytest.raises(asyncio.CancelledError):
        _run(generate_debrief(**_kwargs()))


# ---------- AC7/FR37: backend-enforced inappropriate_behavior --------------


def test_inappropriate_behavior_forced_null_on_normal_end(monkeypatch):
    # Model hallucinated a non-null sentence on a NON-inappropriate end → the
    # backend must overwrite it with null (the invariant is server-owned).
    core = dict(_VALID_CORE)
    core["inappropriate_behavior"] = "You were rude."  # model noise
    _mock_http(monkeypatch, handler=_resp(json.dumps(core)))
    out = _run(generate_debrief(**_kwargs(reason="character_hung_up")))
    assert out["inappropriate_behavior"] is None


def test_inappropriate_behavior_filled_when_model_omits_on_inappropriate_end(
    monkeypatch,
):
    # Call ended on inappropriate content but the model returned null → the
    # backend substitutes the canonical factual fallback (section never empty).
    core = dict(_VALID_CORE)
    core["inappropriate_behavior"] = None
    _mock_http(monkeypatch, handler=_resp(json.dumps(core)))
    out = _run(generate_debrief(**_kwargs(reason="inappropriate_content")))
    assert out["inappropriate_behavior"] == dg_mod._INAPPROPRIATE_FALLBACK


def test_inappropriate_behavior_kept_when_model_provides_it(monkeypatch):
    core = dict(_VALID_CORE)
    core["inappropriate_behavior"] = "The user directed a slur at the character."
    _mock_http(monkeypatch, handler=_resp(json.dumps(core)))
    out = _run(generate_debrief(**_kwargs(reason="inappropriate_content")))
    assert out["inappropriate_behavior"] == "The user directed a slur at the character."
