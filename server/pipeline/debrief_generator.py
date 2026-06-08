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

  * **Structured output** — copy the request shape from
    `pipeline.exchange_classifier.classify_multi`:
    `response_format={"type":"json_schema","json_schema":{"name":…,"strict":
    True,"schema":…}}`. Groq validates server-side (constrained decoding), so
    clean JSON normally arrives; the fence / first-`{...}` fallback below is
    belt-and-suspenders for a non-strict provider. Requires a structured-
    output-capable Groq model (`Settings.debrief_model` = Scout; 70B HTTP
    400s) — project law in server/CLAUDE.md §4.
  * **Time-boxed standalone call** — copy
    `pipeline.exit_line_generator.generate_exit_line`: an outer
    `asyncio.wait_for` + an inner httpx POST that NEVER raises. Any failure
    (timeout, HTTP error, non-2xx, malformed body, parse failure) returns
    `None` so the teardown caller simply skips persisting a debrief (the
    client then sees `DEBRIEF_NOT_READY`). Only `CancelledError` propagates.

The debrief is masked by Story 7.2's Call Ended overlay (3-4 s hold), so the
≤8 s budget (AC10: <5 s target / 10 s hard ceiling) is non-blocking to the
user's `/end` path.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
from loguru import logger

from pipeline.prompts import DEBRIEF_SYSTEM_PROMPT

# AC10 — <5 s target / 10 s hard ceiling. The outer wall-clock budget sits at
# 8 s (recommended); the inner httpx timeout sits just below it so httpx aborts
# first with a clean HTTP error instead of an opaque `asyncio.TimeoutError`.
_GENERATION_TIMEOUT_SECONDS = 8.0
_HTTP_TIMEOUT_SECONDS = 7.5

# The debrief JSON is far larger than a checkpoint verdict — up to 5 errors
# (4 fields each), 3 hesitations, 3 idioms, 2-3 areas, an inappropriate-
# behavior sentence. Groq STRICT mode returns HTTP 400 `json_validate_failed`
# if the document is truncated mid-generation (the Story 6.16 classifier
# overflow class), so the budget is sized with generous headroom (~4× the
# ~525-token worst case). Cost is a fraction of a cent per call (one per call).
_MAX_TOKENS = 2048

# Low temperature: the debrief is a diagnostic instrument (clinical, factual),
# not creative prose. A touch above the classifier's 0.1 so the correction /
# context fields read as natural English without drifting off-transcript.
_TEMPERATURE = 0.2

# AC3 — exactly 2-3 areas. The model is instructed to obey (system prompt) but
# the backend clamp is the real guarantee (Groq strict mode does not enforce
# array length — see `_build_debrief_schema`). 1 is kept as-is; 4+ truncates.
_MAX_AREAS = 3

# The five top-level keys the LLM core MUST carry (strict-schema-enforced on
# the happy path). Used to reject a wholly-malformed body (a non-strict
# provider that ignored the schema) vs a sparse-but-valid one.
_CORE_KEYS = (
    "errors",
    "hesitation_contexts",
    "idioms",
    "areas_to_work_on",
    "inappropriate_behavior",
)

# Reused verbatim from `exchange_classifier` — strip a ```json … ``` fence the
# model may wrap the JSON in before the first-`{...}` fallback.
_FENCE_RE = re.compile(
    r"^```(?:json)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def _build_debrief_schema() -> dict:
    """The STRICT `json_schema` for the debrief LLM core (AC3).

    Matches `debrief-generation-prompt.md` §"JSON Schema": top-level
    `errors[]` / `hesitation_contexts[]` / `idioms[]` (objects with all fields
    required + `additionalProperties:false`), `areas_to_work_on` (string
    array), and a nullable `inappropriate_behavior`. Every object lists ALL
    its properties in `required` and sets `additionalProperties:false`, as
    Groq/OpenAI strict mode demands.

    DELIBERATE DEVIATION from the doc: the doc puts `minItems:2`/`maxItems:3`
    on `areas_to_work_on`. Groq STRICT structured outputs (like OpenAI's)
    reject array length/number constraints — including them would HTTP 400
    the whole call. The 2-3 guarantee instead comes from (1) the system
    prompt's explicit "Exactly 2 or 3 items — never 1, never 4+" and (2) the
    backend `_clamp_areas` (AC3's own clamp provision). Returned as the bare
    `schema` object; the `name`/`strict` wrapper is added in `_generate`,
    mirroring `exchange_classifier._build_verdict_schema`.
    """
    return {
        "type": "object",
        "properties": {
            "errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "user_said": {
                            "type": "string",
                            "description": (
                                "Exact quote of what the user said, verbatim "
                                "from transcript"
                            ),
                        },
                        "correction": {
                            "type": "string",
                            "description": (
                                "The correct English form — what the user "
                                "should have said"
                            ),
                        },
                        "context": {
                            "type": "string",
                            "description": (
                                "One sentence: when in the conversation this "
                                "error occurred"
                            ),
                        },
                        "count": {
                            "type": "integer",
                            "description": (
                                "Number of times this error appeared in the "
                                "transcript (>= 1)"
                            ),
                        },
                    },
                    "required": ["user_said", "correction", "context", "count"],
                    "additionalProperties": False,
                },
                "description": (
                    "Top 0-5 language errors, deduplicated, ordered by significance"
                ),
            },
            "hesitation_contexts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "context": {
                            "type": "string",
                            "description": (
                                "One sentence: what was happening when the "
                                "user hesitated"
                            ),
                        },
                    },
                    "required": ["context"],
                    "additionalProperties": False,
                },
                "description": (
                    "Context for each hesitation moment provided in the input "
                    "(0-3 items)"
                ),
            },
            "idioms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": (
                                "The exact idiom or slang expression as the "
                                "character said it"
                            ),
                        },
                        "meaning": {
                            "type": "string",
                            "description": "Plain English meaning of the expression",
                        },
                        "context": {
                            "type": "string",
                            "description": (
                                "When the character used this expression in the "
                                "conversation"
                            ),
                        },
                    },
                    "required": ["expression", "meaning", "context"],
                    "additionalProperties": False,
                },
                "description": (
                    "Idioms and slang the character used that the user may not "
                    "know. Empty array if none."
                ),
            },
            "areas_to_work_on": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": (
                        "Theme with specific example: 'Negative sentence "
                        "structure (don't/doesn't)'"
                    ),
                },
                "description": (
                    "2-3 thematic improvement areas synthesized from errors "
                    "and hesitations"
                ),
            },
            "inappropriate_behavior": {
                "type": ["string", "null"],
                "description": (
                    "Factual explanation if call ended due to inappropriate "
                    "content. null otherwise."
                ),
            },
        },
        "required": list(_CORE_KEYS),
        "additionalProperties": False,
    }


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

    Each entry is `{"duration_sec": float, "preceding_character_line": str}`
    (top 3 gaps > 3 s, longest first — measured by the bot's hesitation
    observer). When the list is empty, emit the sentinel the prompt expects so
    the model returns an empty `hesitation_contexts`.
    """
    if not hesitations:
        return "No significant hesitations detected."
    lines: list[str] = []
    for idx, h in enumerate(hesitations, start=1):
        duration = float(h.get("duration_sec", 0.0))
        preceding = str(h.get("preceding_character_line", "")).strip()
        lines.append(
            f'Silence #{idx}: {duration:.1f}s — after CHARACTER said: "{preceding}"'
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


def _clamp_areas(areas: Any) -> list[str]:
    """Clamp `areas_to_work_on` to AC3's 2-3 contract (the real guarantee).

    Drops non-string / blank entries, then truncates to the first 3. A model
    that returned 1 keeps 1 (display-as-is per AC3); 4+ becomes the first 3.
    """
    if not isinstance(areas, list):
        return []
    cleaned = [a.strip() for a in areas if isinstance(a, str) and a.strip()]
    return cleaned[:_MAX_AREAS]


def _normalize_core(data: dict) -> dict:
    """Coerce a parsed body into the canonical LLM-core shape.

    Fills each of the five keys with a type-safe default if absent, and clamps
    `areas_to_work_on`. The caller has already confirmed `data` is a dict that
    carries at least one expected key, so this never invents a debrief from a
    wholly-unrelated body.
    """
    errors = data.get("errors")
    hes = data.get("hesitation_contexts")
    idioms = data.get("idioms")
    inappropriate = data.get("inappropriate_behavior")
    return {
        "errors": errors if isinstance(errors, list) else [],
        "hesitation_contexts": hes if isinstance(hes, list) else [],
        "idioms": idioms if isinstance(idioms, list) else [],
        "areas_to_work_on": _clamp_areas(data.get("areas_to_work_on")),
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
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": DEBRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": _TEMPERATURE,
        "max_tokens": _MAX_TOKENS,
        # STRICT structured output — Groq constrains generation to this schema
        # (clean, exactly-keyed JSON). Requires a structured-output-capable
        # model (Scout, NOT 70B). Mirrors `exchange_classifier.classify_multi`.
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "debrief_analysis",
                "strict": True,
                "schema": _build_debrief_schema(),
            },
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(base_url, headers=headers, json=payload)

    if response.status_code >= 300:
        body_preview = response.text[:300] if response.text else "<empty>"
        logger.warning(
            "debrief_generation non-2xx: {} body={!r} reason={}",
            response.status_code,
            body_preview,
            reason,
        )
        return None
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
        return None
    if choice.get("finish_reason") == "length":
        # Token-capped mid-document: the JSON is truncated and would fail to
        # parse anyway. Surface it distinctly so an under-sized budget is
        # diagnosable, then fall back to no debrief.
        logger.warning(
            "debrief_generation truncated (finish_reason=length) → no debrief "
            "reason={}",
            reason,
        )
        return None
    if not isinstance(content, str):
        logger.warning(
            "debrief_generation non-string content ({}) reason={}",
            type(content).__name__,
            reason,
        )
        return None
    core = _parse_debrief_output(content)
    if core is None:
        return None
    # AC7/FR37 — backend-enforce the reason↔inappropriate_behavior invariant.
    return _enforce_inappropriate_behavior(core, reason)
