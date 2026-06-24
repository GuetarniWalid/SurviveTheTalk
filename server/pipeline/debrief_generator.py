"""Story 7.1 — post-call debrief generation (Groq Scout structured output).

After a voice call ends, the per-call bot subprocess distils the conversation
into a structured debrief: the user's language errors, idioms the character
used, contextualised hesitation moments, 2-3 areas to work on, and (only on an
inappropriate-content end) a factual explanation. This module owns the LLM
half — a single, non-streaming Groq call that returns the LLM-CORE dict; the
backend-computed fields (survival %, attempt number, hesitation durations,
encouraging framing) are merged on top by `assemble_debrief` (see
`db.debrief_assembly`).

Two prod patterns reused verbatim (do not reinvent):

  * **Structured output, with a non-strict fallback** — copy the request shape
    from `pipeline.exchange_classifier.classify_multi`:
    `response_format={"type":"json_schema","json_schema":{"name":…,"strict":
    True,"schema":…}}`. But Groq strict mode is all-or-nothing AT THE PROVIDER:
    one wrong-typed field 400s the WHOLE response (`json_validate_failed`)
    before any content returns, so the fence / first-`{...}` / per-item salvage
    below never runs. On that 400 ONLY, `_generate` retries once in json_object
    mode (no strict schema) so the salvage CAN run — call_id=324 2026-06-24
    (areas[0].practice_prompt came back as an object). Requires a structured-
    output-capable Groq model (`Settings.debrief_model` = Scout; 70B HTTP
    400s) — project law in server/CLAUDE.md §4.
  * **Time-boxed standalone call** — copy
    `pipeline.exit_line_generator.generate_exit_line`: an outer
    `asyncio.wait_for` + inner httpx POSTs that NEVER raise. Any failure
    (timeout, HTTP error, non-2xx, malformed body, parse failure) returns
    `None`; the teardown then persists a DEGRADED score-only debrief
    (`degraded_core`) so the client still gets the survival % instead of a
    never-arriving report. Only `CancelledError` propagates.

The debrief is masked by Story 7.2's Call Ended overlay, so the outer budget
(14 s — one strict call ~2-3 s on the happy path, plus the rare non-strict
retry) is non-blocking to the user's `/end` path.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
from loguru import logger

from pipeline.prompts import DEBRIEF_SYSTEM_PROMPT

# AC10 — <5 s target / 10 s ceiling on the HAPPY path (one strict call, ~2-3 s).
# The outer wall-clock budget sits ABOVE a single attempt because a strict
# schema-validation 400 triggers ONE non-strict retry (`_generate` below) — a
# second round-trip. The whole call is masked by the Call Ended overlay, so the
# extra latency on the rare retry path is non-blocking. The inner httpx timeout
# sits below a single attempt's share so httpx aborts a hung attempt first with a
# clean HTTP error instead of an opaque `asyncio.TimeoutError`.
_GENERATION_TIMEOUT_SECONDS = 14.0
_HTTP_TIMEOUT_SECONDS = 7.5

# The v2 debrief JSON is large: up to 5 errors (each with `explanation` + up to
# 2 `examples`), up to 3 areas (each a ~900-char `practice_prompt`), <=2
# better_phrasings, 3 idioms, 3 hesitation contexts, an inappropriate-behavior
# sentence. Groq STRICT mode returns HTTP 400 `json_validate_failed` if the
# document is truncated mid-generation (the Story 6.16 classifier overflow
# class); a maxed-out v2 debrief is on the order of ~2.5-3k tokens, so this
# budget sits CLOSE to the worst case (no longer the old ~4x headroom). If real
# calls hit `finish_reason=="length"` (logged below), raise it — see the AC9
# generation-budget measurement follow-up. Cost is a fraction of a cent per call.
_MAX_TOKENS = 3072

# Low temperature: the debrief is a diagnostic instrument (clinical, factual),
# not creative prose. A touch above the classifier's 0.1 so the correction /
# context fields read as natural English without drifting off-transcript.
_TEMPERATURE = 0.2

# Length/cap rules the model is instructed to obey (system prompt) but that the
# BACKEND enforces as the real guarantee — Groq strict mode rejects min/maxItems
# (see `_build_debrief_schema`), so these clamps in `_normalize_core` are the
# contract (Story 7.5 backend-clamp rules + F3 per-item salvage).
_MAX_AREAS = 3
_MAX_ERRORS = 5
_MAX_BETTER_PHRASINGS = 2
_MAX_EXAMPLES = 2
# Defensive hard cap on the copy-button practice prompt (clipboard-friendly,
# fits an LLM voice-mode context). The prompt asks for ~900; strict schema can't
# bound a string, so the backend truncates.
_MAX_PRACTICE_PROMPT_CHARS = 900

# The five top-level keys the LLM core MUST carry (strict-schema-enforced on
# the happy path). Used to reject a wholly-malformed body (a non-strict
# provider that ignored the schema) vs a sparse-but-valid one.
_CORE_KEYS = (
    "errors",
    "hesitation_contexts",
    "idioms",
    "better_phrasings",
    "areas",
    "inappropriate_behavior",
)

# Reused verbatim from `exchange_classifier` — strip a ```json … ``` fence the
# model may wrap the JSON in before the first-`{...}` fallback.
_FENCE_RE = re.compile(
    r"^```(?:json)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL | re.IGNORECASE,
)


_DEBRIEF_SCHEMA_JSON = """
{
  "type": "object",
  "properties": {
    "errors": {
      "type": "array",
      "description": "Top 0-5 deduplicated language errors, ordered by significance. Empty array if the user made none; never invent an error.",
      "items": {
        "type": "object",
        "properties": {
          "user_said": {
            "type": "string",
            "description": "SURFACE. Exact quote of what the user said, verbatim from the transcript. Max ~100 chars."
          },
          "correction": {
            "type": "string",
            "description": "SURFACE. The correct English form the user should have said; natural native English. Max ~100 chars."
          },
          "context": {
            "type": "string",
            "description": "SURFACE (card). One short situational clause: when in the conversation this error occurred. Max ~80 chars."
          },
          "count": {
            "type": "integer",
            "description": "How many times this error or a functionally identical variant appeared in the transcript (>= 1)."
          },
          "explanation": {
            "type": "string",
            "description": "DEPTH (tap sheet). One factual sentence naming the underlying RULE that makes the correction right - the principle, never the correction restated, never praise. Max ~160 chars."
          },
          "examples": {
            "type": "array",
            "description": "DEPTH (tap sheet). 1-2 short correct example sentences applying the same rule in a fresh context; never a verbatim copy of the correction. Return 1 if a second adds nothing; never more than 2.",
            "items": {
              "type": "string",
              "description": "One short, natural, correct example sentence demonstrating the rule. Max ~80 chars."
            }
          }
        },
        "required": [
          "user_said",
          "correction",
          "context",
          "count",
          "explanation",
          "examples"
        ],
        "additionalProperties": false
      }
    },
    "hesitation_contexts": {
      "type": "array",
      "description": "One object per backend-provided hesitation moment, in the same order. Empty array if none were provided; never invent a hesitation.",
      "items": {
        "type": "object",
        "properties": {
          "hesitation_id": {
            "type": "string",
            "description": "Echo back, UNCHANGED, the exact id the backend gave this hesitation moment, so context pairs to the measured duration by id, never by position. Never invent, renumber, or blank it."
          },
          "context": {
            "type": "string",
            "description": "SURFACE. One factual situational sentence: what was happening when the user hesitated; the situation, not the user's internal state. Max ~80 chars."
          }
        },
        "required": [
          "hesitation_id",
          "context"
        ],
        "additionalProperties": false
      }
    },
    "idioms": {
      "type": "array",
      "description": "Idioms, phrasal verbs, and slang the CHARACTER used that an intermediate learner may not know. Empty array if none; never manufacture one.",
      "items": {
        "type": "object",
        "properties": {
          "expression": {
            "type": "string",
            "description": "SURFACE. The exact idiom or slang expression as the character said it. Max ~50 chars."
          },
          "meaning": {
            "type": "string",
            "description": "SURFACE. Plain English meaning, direct, no hedging. Max ~100 chars."
          },
          "context": {
            "type": "string",
            "description": "SURFACE. When the character used this expression in the conversation. Max ~80 chars."
          }
        },
        "required": [
          "expression",
          "meaning",
          "context"
        ],
        "additionalProperties": false
      }
    },
    "better_phrasings": {
      "type": "array",
      "description": "At most 2. Correct-but-clumsy user utterances rephrased more naturally. Default to an EMPTY array - emit only when a native speaker would clearly phrase it more naturally; never put grammar errors here (those are errors).",
      "items": {
        "type": "object",
        "properties": {
          "original": {
            "type": "string",
            "description": "SURFACE. The user's exact correct-but-clumsy words, verbatim from the transcript. Max ~100 chars."
          },
          "suggestion": {
            "type": "string",
            "description": "SURFACE. The more natural native-speaker phrasing of the same thing. Max ~100 chars."
          },
          "reason": {
            "type": "string",
            "description": "SURFACE. One short factual clause on why the suggestion is more natural (register, idiom, word choice, concision). No praise. Max ~120 chars."
          }
        },
        "required": [
          "original",
          "suggestion",
          "reason"
        ],
        "additionalProperties": false
      }
    },
    "areas": {
      "type": "array",
      "description": "1-3 prioritized, evidence-linked improvement areas, MOST IMPORTANT FIRST. Each MUST cite concrete in-call evidence. Never invent an area not demonstrated by the data; never exceed 3. Order is priority; the backend marks the first as the focus.",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string",
            "description": "SURFACE. Short diagnostic theme, 2-6 words, no parentheses, no baked-in example. e.g. 'Negative sentence structure'."
          },
          "evidence": {
            "type": "string",
            "description": "SURFACE. One factual sentence citing at least one concrete thing from THIS call - a quoted flagged error or a named hesitation moment - that grounds the area. No generic filler. Max ~140 chars."
          },
          "practice_prompt": {
            "type": "string",
            "description": "DEPTH (tap sheet, copy-button payload). A self-contained plain-text coach prompt the user pastes into any external AI (voice or text) to drill THIS ONE area: coach role + this single focus + the user's REAL quoted utterances and corrections from this call + the drill flow + no-drift and no-praise guardrails. Instructions to a COACH, never praise to the user. No markdown, no line breaks, max ~900 chars."
          }
        },
        "required": [
          "title",
          "evidence",
          "practice_prompt"
        ],
        "additionalProperties": false
      }
    },
    "inappropriate_behavior": {
      "type": [
        "string",
        "null"
      ],
      "description": "Factual, non-judgmental explanation IF the call ended due to inappropriate content; null otherwise. The backend re-pins this against the authoritative call-end reason. Max ~200 chars."
    }
  },
  "required": [
    "errors",
    "hesitation_contexts",
    "idioms",
    "better_phrasings",
    "areas",
    "inappropriate_behavior"
  ],
  "additionalProperties": false
}
"""


def _build_debrief_schema() -> dict:
    """The STRICT Groq `json_schema` for the v2 debrief LLM core (Story 7.5).

    Loaded verbatim from the authoritative v2 schema (kept as a JSON constant so
    it stays byte-aligned with `debrief-generation-prompt.md` and never drifts in
    hand-transcription). Groq STRICT demands every object list ALL properties in
    `required` + `additionalProperties:false` and REJECTS min/maxItems - the area
    / better_phrasings / examples / errors length rules live in the system prompt
    + the backend clamps in `_normalize_core`. Returned as the bare schema;
    `_generate` adds the `name`/`strict` wrapper.
    """
    return json.loads(_DEBRIEF_SCHEMA_JSON)


def _speaker_label(role: Any) -> str:
    """Map a TranscriptCollector turn role to the prompt's speaker label."""
    return "USER" if role == "user" else "CHARACTER"


def _format_transcript(transcript: list[dict]) -> str:
    """Render the collected turns as alternating `CHARACTER:`/`USER:` lines.

    `transcript` is `TranscriptCollector.transcript` — a list of
    `{"role": "user"|"character", "text": str, "timestamp_ms": int}`. Empty
    text turns are skipped. No `.format()` is used anywhere in this module, so
    literal braces in STT text need no escaping.
    """
    lines: list[str] = []
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("text", "")).strip()
        if not text:
            continue
        lines.append(f"{_speaker_label(turn.get('role'))}: {text}")
    return "\n".join(lines)


def _format_hesitations(hesitations: list[dict]) -> str:
    """Render the backend-measured hesitation block for the user message.

    Each entry is `{"id": str, "duration_sec": float, "preceding_character_line":
    str, "resolved": bool}` (top gaps > 4 s, longest first — measured by the
    bot's hesitation observer). Every line carries its `hesitation_id` so the
    model echoes it back EXACTLY (Story 7.5 C3 id-based pairing, never index).
    A `resolved: false` gap was a freeze the character had to break by speaking
    again (C2). When the list is empty, emit the sentinel so the model returns
    an empty `hesitation_contexts`.
    """
    if not hesitations:
        return "No significant hesitations detected."
    lines: list[str] = []
    for h in hesitations:
        hid = str(h.get("id", "")).strip()
        duration = float(h.get("duration_sec", 0.0))
        preceding = str(h.get("preceding_character_line", "")).strip()
        note = "" if h.get("resolved", True) else " (the character had to speak again)"
        lines.append(
            f'hesitation_id "{hid}": {duration:.1f}s pause{note} — '
            f'after CHARACTER said: "{preceding}"'
        )
    return "\n".join(lines)


def _build_user_message(
    *,
    character_name: str,
    scenario_title: str,
    brief_personality_description: str,
    reason: str,
    transcript_text: str,
    hesitation_block: str,
) -> str:
    """Assemble the user message from the documented template.

    `debrief-generation-prompt.md` §"User Message Template": a scenario header,
    the alternating transcript fenced by `=== TRANSCRIPT ===`, and the
    hesitation data fenced by `=== HESITATION DATA ===`. `reason` is passed
    through verbatim (the system prompt's Inappropriate-Behavior rules key on
    it — AC7).
    """
    return (
        f"Scenario: {character_name} — {scenario_title}\n"
        f"Character personality: {brief_personality_description}\n"
        f"Call end reason: {reason}\n"
        "\n"
        "=== TRANSCRIPT ===\n"
        f"{transcript_text}\n"
        "=== END TRANSCRIPT ===\n"
        "\n"
        "=== HESITATION DATA ===\n"
        f"{hesitation_block}\n"
        "=== END HESITATION DATA ==="
    )


def _clean_str(value: Any) -> str:
    """A trimmed string, or '' for anything non-string/blank."""
    return value.strip() if isinstance(value, str) else ""


def _clamp_examples(raw: Any, correction: str) -> list[str]:
    """≤2 model example sentences; drop blanks/non-str and any entry equal
    (case-insensitive) to the correction (an example must generalise, not echo
    the fix)."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    corr = correction.casefold()
    for item in raw:
        s = _clean_str(item)
        if not s or s.casefold() == corr:
            continue
        out.append(s)
        if len(out) >= _MAX_EXAMPLES:
            break
    return out


def _clamp_errors(raw: Any) -> list[dict]:
    """Top-5 errors with per-item salvage (Story 7.5 F3): drop an item missing
    user_said/correction/context; default the v2 depth fields. A single
    malformed item is dropped, never the whole debrief."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        user_said = _clean_str(item.get("user_said"))
        correction = _clean_str(item.get("correction"))
        context = _clean_str(item.get("context"))
        if not user_said or not correction or not context:
            continue
        count = item.get("count")
        count = (
            count
            if isinstance(count, int)
            and not isinstance(count, bool)
            and 1 <= count <= 99
            else 1
        )
        out.append(
            {
                "user_said": user_said,
                "correction": correction,
                "context": context,
                "count": count,
                "explanation": _clean_str(item.get("explanation")) or None,
                "examples": _clamp_examples(item.get("examples"), correction),
            }
        )
        if len(out) >= _MAX_ERRORS:
            break
    return out


def _clamp_idioms(raw: Any) -> list[dict]:
    """Per-item salvage for idioms (F3) — every item must satisfy the
    `DebriefIdiom` contract or it is dropped (not the whole debrief)."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        expression = _clean_str(item.get("expression"))
        meaning = _clean_str(item.get("meaning"))
        context = _clean_str(item.get("context"))
        if not expression or not meaning or not context:
            continue
        out.append({"expression": expression, "meaning": meaning, "context": context})
    return out


def _clamp_better_phrasings(raw: Any) -> list[dict]:
    """≤2 better-phrasing suggestions (Story 7.5 B2); each needs a non-blank
    original + suggestion + reason or it is dropped."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        original = _clean_str(item.get("original"))
        suggestion = _clean_str(item.get("suggestion"))
        reason = _clean_str(item.get("reason"))
        if not original or not suggestion or not reason:
            continue
        out.append({"original": original, "suggestion": suggestion, "reason": reason})
        if len(out) >= _MAX_BETTER_PHRASINGS:
            break
    return out


def _clamp_areas(raw: Any) -> list[dict]:
    """Top-3 rich, evidence-linked areas (Story 7.5 D-a/B5). Drop an area
    missing title/evidence/practice_prompt — evidence is MANDATORY (an area
    with no in-call evidence is the generic filler this rewrite kills).
    `practice_prompt` is hard-truncated to 900 chars with whitespace collapsed
    (strict schema can't bound a string). `is_focus` is pinned by the assembler,
    never authored here."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _clean_str(item.get("title"))
        evidence = _clean_str(item.get("evidence"))
        practice = _clean_str(item.get("practice_prompt"))
        if not title or not evidence or not practice:
            continue
        practice = " ".join(practice.split())[:_MAX_PRACTICE_PROMPT_CHARS]
        out.append({"title": title, "evidence": evidence, "practice_prompt": practice})
        if len(out) >= _MAX_AREAS:
            break
    return out


def _clamp_hesitation_contexts(raw: Any) -> list[dict]:
    """Keep `{hesitation_id, context}` items; the assembler pairs them to the
    measured gaps BY ID (Story 7.5 C3). An item without an id is unpairable and
    dropped."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        hid = _clean_str(item.get("hesitation_id"))
        if not hid:
            continue
        out.append({"hesitation_id": hid, "context": _clean_str(item.get("context"))})
    return out


def _normalize_core(data: dict) -> dict:
    """Coerce a parsed body into the canonical v2 LLM-core shape, applying the
    backend clamps strict json_schema cannot enforce + per-item salvage (Story
    7.5 F3). The caller has confirmed `data` is a dict carrying at least one
    expected key, so this never invents a debrief from a wholly-unrelated body.
    """
    inappropriate = data.get("inappropriate_behavior")
    return {
        "errors": _clamp_errors(data.get("errors")),
        "hesitation_contexts": _clamp_hesitation_contexts(
            data.get("hesitation_contexts")
        ),
        "idioms": _clamp_idioms(data.get("idioms")),
        "better_phrasings": _clamp_better_phrasings(data.get("better_phrasings")),
        "areas": _clamp_areas(data.get("areas")),
        "inappropriate_behavior": (
            inappropriate
            if isinstance(inappropriate, str) and inappropriate.strip()
            else None
        ),
    }


# AC7 / FR37 — the inappropriate_behavior field is BACKEND-enforced against the
# server-authoritative call-end reason, NOT left to the model: it must be
# non-null IFF the call ended on inappropriate content. The reason token comes
# from PatienceTracker.call_end_reason (validated server-side). This mirrors
# AC3's "the backend is the real guarantee" stance — the weak prod model (Scout
# @ temp 0.2) could otherwise hallucinate a non-null sentence on a normal end or
# a null on an inappropriate end.
_INAPPROPRIATE_REASON = "inappropriate_content"
# Canonical factual fallback (debrief-generation-prompt.md §"Inappropriate
# Behavior Rules" GOOD example) used when the call ended inappropriately but the
# model returned null — the section must never be empty in that case.
_INAPPROPRIATE_FALLBACK = (
    "The call ended because the conversation moved outside the scenario's "
    "boundaries. The character ended the interaction."
)


def _enforce_inappropriate_behavior(core: dict, reason: str) -> dict:
    """Pin `inappropriate_behavior` to the AC7 invariant (non-null IFF
    reason == 'inappropriate_content'). Mutates and returns `core`."""
    if reason == _INAPPROPRIATE_REASON:
        if not core.get("inappropriate_behavior"):
            core["inappropriate_behavior"] = _INAPPROPRIATE_FALLBACK
    else:
        core["inappropriate_behavior"] = None
    return core


def degraded_core(reason: str) -> dict:
    """The all-empty LLM core (every analysis section empty), with the AC7
    `inappropriate_behavior` invariant applied for `reason`.

    The teardown's never-blank fallback uses this when generation yields no core
    even after the non-strict retry below (call_id=324, 2026-06-24): assembling +
    persisting a score-only debrief makes `GET /debriefs/{id}` return 200 with the
    survival % immediately, instead of a permanent `DEBRIEF_NOT_READY` the client
    polls for ~40 s before giving up on a report that will never arrive. The
    teardown marks the assembled blob `degraded` so the client shows 'detailed
    analysis unavailable' rather than implying a flawless call.
    """
    core = {
        "errors": [],
        "hesitation_contexts": [],
        "idioms": [],
        "better_phrasings": [],
        "areas": [],
        "inappropriate_behavior": None,
    }
    return _enforce_inappropriate_behavior(core, reason)


# On a strict schema-validation 400 we retry ONCE in json_object mode (no strict
# schema). Groq's json_object mode requires the literal token "json" somewhere in
# the messages; this suffix supplies it AND pins the exact failure that triggers
# the retry — a field emitted as a nested object where a JSON string is required
# (call_id=324, 2026-06-24: areas[0].practice_prompt came back as an object, so
# Groq 400'd the WHOLE response and the per-item salvage never ran).
_FALLBACK_SYSTEM_SUFFIX = (
    "\n\n## Output format\n"
    "Return a SINGLE JSON object with exactly these top-level keys: errors, "
    "hesitation_contexts, idioms, better_phrasings, areas, "
    "inappropriate_behavior. Every field value MUST be its documented scalar "
    "type — each practice_prompt, explanation, evidence, context, correction, "
    "and every other text field is a PLAIN JSON STRING, never a nested object or "
    "array. Output only the JSON object: no prose, no markdown fences."
)


def _parse_debrief_output(content: str) -> dict | None:
    """Parse the model's response into the LLM-core dict, or `None`.

    Strict-schema-enforced JSON normally arrives clean; we still try a strict
    `json.loads`, then strip a Markdown fence, then fall back to the first
    `{...}` substring (mirrors `exchange_classifier._parse_multi_classifier_
    output`). Returns `None` on non-JSON, a non-dict body, or a body that
    carries NONE of the expected keys (a provider that ignored the schema).
    """
    text = content.strip()
    fence_match = _FENCE_RE.match(text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning("debrief_generation non-JSON output")
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("debrief_generation non-JSON output")
            return None

    if not isinstance(data, dict):
        logger.warning("debrief_generation output not a dict")
        return None
    if not any(key in data for key in _CORE_KEYS):
        logger.warning("debrief_generation output missing all core keys")
        return None
    return _normalize_core(data)


async def generate_debrief(
    *,
    transcript: list[dict],
    reason: str,
    character_name: str,
    scenario_title: str,
    brief_personality_description: str,
    hesitations: list[dict],
    api_key: str,
    model: str,
    base_url: str,
    timeout: float = _GENERATION_TIMEOUT_SECONDS,
) -> dict | None:
    """Generate the debrief LLM core, or `None` on any failure.

    Safe to `await` from the bot's call-end teardown — NEVER raises (every
    failure is logged and returns `None`, so teardown simply skips persisting
    a debrief). Returns `None` immediately on an empty transcript (nothing to
    analyse).

    Returns the validated LLM-core dict
    `{errors, hesitation_contexts, idioms, areas_to_work_on,
    inappropriate_behavior}` (with `areas_to_work_on` clamped to ≤3) — NOT the
    assembled client debrief; `assemble_debrief` merges the backend fields on
    top.

    Args:
        transcript: `TranscriptCollector.transcript` — `[{role, text, …}]`.
        reason: The call-end reason token (`survived`, `character_hung_up`,
            `inappropriate_content`, `noisy_environment`, `user_hangup`, …).
            Drives the inappropriate-behavior field (AC7).
        character_name: `scenarios.title` (e.g. "The Mugger").
        scenario_title: the dedicated mission title (e.g. "Give me your wallet").
        brief_personality_description: first 1-2 sentences of the persona.
        hesitations: backend-measured gaps `[{duration_sec, preceding_character_line}]`.
        api_key / model / base_url: resolved via `pipeline.llm_provider`;
            `base_url` is the FULL chat-completions endpoint (raw httpx POST).
        timeout: outer wall-clock budget (default 8 s, AC10).
    """
    if not isinstance(transcript, list) or not transcript:
        logger.info("debrief_generation skipped (empty transcript) reason={}", reason)
        return None
    transcript_text = _format_transcript(transcript)
    if not transcript_text:
        logger.info("debrief_generation skipped (no usable turns) reason={}", reason)
        return None
    try:
        return await asyncio.wait_for(
            _generate(
                transcript_text=transcript_text,
                reason=reason,
                character_name=character_name,
                scenario_title=scenario_title,
                brief_personality_description=brief_personality_description,
                hesitations=hesitations,
                api_key=api_key,
                model=model,
                base_url=base_url,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "debrief_generation timeout after {}s reason={}", timeout, reason
        )
        return None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Best-effort: a missing debrief is degraded UX, a crashed teardown is
        # a lost call. Swallow all.
        logger.warning(
            "debrief_generation failed (non-fatal): {} ({}) reason={}",
            exc,
            type(exc).__name__,
            reason,
        )
        return None


async def _post_and_parse(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict,
    payload: dict,
    reason: str,
) -> tuple[dict | None, int]:
    """One LLM round-trip + parse. Returns `(core_or_None, status_code)`.

    The status code lets `_generate` decide whether the non-strict retry is worth
    it (only a clean schema-validation 400 is). NEVER raises for an HTTP/parse
    failure — those return `(None, status)`; httpx transport errors propagate to
    `generate_debrief`'s outer handler, and timeouts to its `wait_for`.
    """
    response = await client.post(base_url, headers=headers, json=payload)
    status = response.status_code
    if status >= 300:
        body_preview = response.text[:300] if response.text else "<empty>"
        logger.warning(
            "debrief_generation non-2xx: {} body={!r} reason={}",
            status,
            body_preview,
            reason,
        )
        return None, status
    try:
        choice = response.json()["choices"][0]
        content = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning(
            "debrief_generation malformed response: {} ({}) reason={}",
            exc,
            type(exc).__name__,
            reason,
        )
        return None, status
    if choice.get("finish_reason") == "length":
        # Token-capped mid-document: the JSON is truncated and would fail to
        # parse anyway. Surface it distinctly so an under-sized budget is
        # diagnosable, then fall back to no debrief.
        logger.warning(
            "debrief_generation truncated (finish_reason=length) → no debrief "
            "reason={}",
            reason,
        )
        return None, status
    if not isinstance(content, str):
        logger.warning(
            "debrief_generation non-string content ({}) reason={}",
            type(content).__name__,
            reason,
        )
        return None, status
    core = _parse_debrief_output(content)
    if core is None:
        return None, status
    # AC7/FR37 — backend-enforce the reason↔inappropriate_behavior invariant.
    return _enforce_inappropriate_behavior(core, reason), status


async def _generate(
    *,
    transcript_text: str,
    reason: str,
    character_name: str,
    scenario_title: str,
    brief_personality_description: str,
    hesitations: list[dict],
    api_key: str,
    model: str,
    base_url: str,
) -> dict | None:
    user_message = _build_user_message(
        character_name=character_name,
        scenario_title=scenario_title,
        brief_personality_description=brief_personality_description,
        reason=reason,
        transcript_text=transcript_text,
        hesitation_block=_format_hesitations(hesitations),
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # STRICT structured output — Groq constrains generation to this schema
    # (clean, exactly-keyed JSON) on the happy path. Requires a structured-
    # output-capable model (Scout, NOT 70B). Mirrors `exchange_classifier`.
    strict_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": DEBRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": _TEMPERATURE,
        "max_tokens": _MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "debrief_analysis",
                "strict": True,
                "schema": _build_debrief_schema(),
            },
        },
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        core, status = await _post_and_parse(
            client=client,
            base_url=base_url,
            headers=headers,
            payload=strict_payload,
            reason=reason,
        )
        if core is not None:
            return core
        # Strict json_schema is all-or-nothing AT THE PROVIDER: one wrong-typed
        # field makes Groq 400 the WHOLE response (json_validate_failed) before
        # any content is returned, so the per-item salvage in `_normalize_core`
        # never runs. On that 400 ONLY, retry once in json_object mode (no strict
        # schema): Groq returns the content and `_parse_debrief_output` / the
        # `_clamp_*` salvage drop just the malformed item, keeping the rest. A
        # timeout / connection error / 5xx does NOT retry — re-rolling a hung or
        # broken provider buys nothing and would burn the wall-clock budget.
        if status != 400:
            return None
        logger.info(
            "debrief_generation retrying without strict schema (json_object) reason={}",
            reason,
        )
        fallback_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": DEBRIEF_SYSTEM_PROMPT + _FALLBACK_SYSTEM_SUFFIX,
                },
                {"role": "user", "content": user_message},
            ],
            "temperature": _TEMPERATURE,
            "max_tokens": _MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }
        core, _ = await _post_and_parse(
            client=client,
            base_url=base_url,
            headers=headers,
            payload=fallback_payload,
            reason=reason,
        )
        return core
