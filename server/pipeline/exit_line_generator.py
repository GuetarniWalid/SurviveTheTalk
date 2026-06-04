"""Story 6.18 — dynamic, in-character exit + patience-warning line generation.

The `COHERENCE_CHARTER` (Story 6.8) keeps every GENERATED character turn from
inventing facts, but the hang-up / patience-warning lines were hardcoded YAML
strings (`exit_lines.*` / `patience_warning`) selected purely by the hang-up
REASON — so a `hard` cop hang-up accused the user of "changing his story three
times" (call_id=212, 2026-06-03) when the user never gave a single version.
This module regenerates those lines IN CHARACTER from the ACTUAL transcript +
the reason, charter-governed, so the closing words can only reference what
really happened. The YAML `exit_lines` stay as the fast/safe fallback.

Mirrors `llm_warmup.py`: a standalone, time-boxed `httpx` call to the SAME
OpenAI-compatible provider as the character LLM (Groq) that NEVER raises — any
failure (timeout, HTTP error, non-2xx, parse failure, empty transcript)
returns `None` so the caller (`PatienceTracker`) falls back to the canned line.
No pipeline frames, no pipecat imports — just one short completion. The whole
hang-up sequence is fire-and-forget, so a late/canned line beats no line.

Reuse: the response-parsing/validation discipline mirrors
`exchange_classifier` (defensive `.get()` chain, brace-escaped substitutions).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from loguru import logger

from pipeline.prompts import (
    EXIT_LINE_CONSTRAINT,
    EXIT_LINE_GENERATION_PROMPT,
    EXIT_LINE_GUIDANCE_DEFAULT,
    EXIT_LINE_REASON_GUIDANCE,
)

# AC3 — the generation step is independently time-boxed to ≤1.5 s and runs
# SEQUENTIALLY BEFORE the exit-line TTS, so it is ADDITIVE to (not bounded by)
# the `_HANG_UP_TTS_TIMEOUT_SECONDS = 6.0 s` cap, which covers only the
# TTS-speaking phase. Worst-case pre-`call_end` wall-clock ≈ 0.5 s pre-TTS
# delay + ≤1.5 s generation + ≤6.0 s TTS wait. The inner httpx timeout sits
# just below the outer `asyncio.wait_for`; under normal conditions httpx
# aborts first with a clean HTTP error, but the ~0.2 s margin is tight, so on
# event-loop jitter / a slow connect the outer `wait_for` may win instead —
# both paths return `None` and fall back to the canned line, so neither is
# fatal (only the log-attributed cause differs).
_GENERATION_TIMEOUT_SECONDS = 1.5
_HTTP_TIMEOUT_SECONDS = 1.3

# Last-N transcript turns fed to the generator. Bounded so a long call keeps
# token + latency cost flat; the recent exchanges are what a closing line
# needs to stay coherent.
_MAX_TRANSCRIPT_MESSAGES = 16

# AC3 — defensive ≤2-sentence cap on top of the prompt instruction (a longer
# line risks the 6 s TTS ceiling). The token cap also bounds the model.
_MAX_SENTENCES = 2
_MAX_TOKENS = 80

# AC3 hard backstop — a run-on / comma-spliced line with NO internal sentence
# terminator splits into a single part and would otherwise bypass the
# sentence cap, so a char ceiling (~2 short sentences) trims it on a word
# boundary. Comfortably under the 6 s TTS ceiling.
_MAX_LINE_CHARS = 200

# Mirrors `llm_provider.CHARACTER_TEMPERATURE` (0.7) so the closing line has
# the same in-character warmth as a normal reply. Kept as a local constant
# (not imported) so this module stays dependency-light like `llm_warmup.py`
# (httpx + prompts only, no pipecat).
_TEMPERATURE = 0.7

# Split on sentence-ending punctuation followed by whitespace. Good enough for
# the short lines we cap; over-splitting an abbreviation only trims one extra
# clause off an already-too-long line.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Matched quote PAIRS the model may wrap the line in. ASCII double + both
# smart-quote pairs only — the ASCII single quote `'` is DELIBERATELY excluded
# because it is ambiguous with a content apostrophe (a leading elision like
# 'Cause or a trailing possessive like the kids'), and stripping it would
# mangle the line. Matched pairs (not independent open/close membership) so a
# content apostrophe inside a double-quoted line is never touched.
_QUOTE_PAIRS = (('"', '"'), ("“", "”"), ("‘", "’"))
# Closing-quote glyphs used to peel a trailing sentence-final punctuation char
# the model sometimes places OUTSIDE the closing quote (e.g. `"You're done".`).
_CLOSE_QUOTE_CHARS = '"”’'


def _escape_format_braces(value: str) -> str:
    """Escape `{`/`}` so `str.format()` doesn't read them as placeholders.

    Mirrors `exchange_classifier._escape_format_braces` — STT-transcribed user
    speech (and, defensively, an authored persona) can contain literal braces;
    without escaping, `.format()` raises `KeyError`/`ValueError`.
    """
    return value.replace("{", "{{").replace("}", "}}")


def _extract_text(content: Any) -> str:
    """Pull a plain-text string out of an LLMContext message `content`.

    Mirrors `CheckpointManager._last_character_line`: content is usually a
    str, but multi-part messages (image/audio) carry a list of parts — pick
    the first text part.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                return str(part.get("text", "")).strip()
    return ""


def _normalize_transcript(messages: list, max_messages: int) -> list[str]:
    """Render `llm_context.get_messages()` into `USER:`/`CHARACTER:` lines.

    Keeps only `user`/`assistant` text turns (drops any system/tool message),
    skips empties, and caps to the last `max_messages` so the prompt stays
    bounded. The system instruction is NOT in `get_messages()` (it lives on
    `llm._settings`), so no system turn leaks in.
    """
    rendered: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _extract_text(msg.get("content", ""))
        if not text:
            continue
        speaker = "USER" if role == "user" else "CHARACTER"
        rendered.append(f"{speaker}: {text}")
    return rendered[-max_messages:]


def _truncate_to_sentences(text: str, max_sentences: int) -> str:
    """Trim `text` to at most `max_sentences` sentences (AC3 belt-and-braces).

    A run-on / comma-spliced line with no internal sentence terminator splits
    into ONE part and would otherwise pass uncapped, so a hard `_MAX_LINE_CHARS`
    backstop trims it on a word boundary to stay under the 6 s TTS ceiling.
    """
    parts = [p for p in _SENTENCE_SPLIT_RE.split(text.strip()) if p.strip()]
    capped = (
        text.strip()
        if len(parts) <= max_sentences
        else " ".join(parts[:max_sentences]).strip()
    )
    if len(capped) > _MAX_LINE_CHARS:
        capped = (
            capped[:_MAX_LINE_CHARS].rsplit(" ", 1)[0].rstrip(",;:- ")
            or capped[:_MAX_LINE_CHARS]
        )
    return capped


def _strip_wrapping_quotes(text: str) -> str:
    """Strip up to a few layers of MATCHED surrounding quote pairs.

    Also handles a trailing sentence-final punctuation char the model
    sometimes places OUTSIDE the closing quote (e.g. `"You're done".`). Only
    unwraps on a genuine matched pair, so content apostrophes survive.
    """
    for _ in range(3):
        trailing = ""
        core = text
        if len(core) >= 2 and core[-1] in ".!?" and core[-2] in _CLOSE_QUOTE_CHARS:
            trailing = core[-1]
            core = core[:-1]
        for open_q, close_q in _QUOTE_PAIRS:
            if len(core) >= 2 and core[0] == open_q and core[-1] == close_q:
                text = (core[1:-1] + trailing).strip()
                break
        else:
            break
    return text


def _clean_line(raw: str | None) -> str | None:
    """Validate + normalize the model's raw line, or `None` if unusable.

    Strips matched surrounding quotes the model may have added (without
    mangling content apostrophes), enforces the ≤2-sentence / `_MAX_LINE_CHARS`
    caps, and returns `None` on empty so the caller falls back to the canned
    line.
    """
    text = (raw or "").strip() if isinstance(raw, str) else ""
    if not text:
        return None
    text = _strip_wrapping_quotes(text)
    if not text:
        return None
    text = _truncate_to_sentences(text, _MAX_SENTENCES)
    return text or None


async def generate_exit_line(
    *,
    reason: str,
    transcript: list,
    persona: str,
    charter: str,
    api_key: str,
    model: str,
    base_url: str,
    timeout: float = _GENERATION_TIMEOUT_SECONDS,
) -> str | None:
    """Generate ONE short, in-character closing/warning line, or `None`.

    Safe to `await` from the fire-and-forget hang-up sequence — NEVER raises
    (every failure is logged and returns `None` so the caller speaks the
    canned fallback). Returns `None` immediately when the transcript has no
    real conversation to ground the line (the canned line is more coherent
    than one invented from nothing).

    Args:
        reason: PatienceTracker reason token (`character_hung_up`,
            `inappropriate_content`, `noisy_environment`, `survived`) or
            `patience_warning`. Selects the per-reason guidance.
        transcript: The raw `llm_context.get_messages()` list.
        persona: The character's base persona (scenario `base_prompt`),
            without the goal decoration — keeps the line in-voice.
        charter: The `COHERENCE_CHARTER` — the no-fabrication guarantee.
        api_key / model / base_url: Resolved via `pipeline.llm_provider`;
            `base_url` is the FULL chat-completions endpoint (raw httpx POST).
        timeout: Outer wall-clock budget (default ≤1.5 s, AC3).
    """
    if not isinstance(transcript, list):
        # Honor the never-raises contract even if a future caller passes a
        # non-list (today the only caller passes `context.get_messages()`,
        # always a list). `_normalize_transcript` runs before the try below,
        # so an unguarded non-iterable would propagate out of this function.
        logger.info(
            "exit_line_generation skipped (transcript not a list) reason={}", reason
        )
        return None
    rendered = _normalize_transcript(transcript, _MAX_TRANSCRIPT_MESSAGES)
    if not rendered:
        logger.info("exit_line_generation skipped (empty transcript) reason={}", reason)
        return None
    try:
        return await asyncio.wait_for(
            _generate(
                reason=reason,
                transcript_text="\n".join(rendered),
                persona=persona,
                charter=charter,
                api_key=api_key,
                model=model,
                base_url=base_url,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "exit_line_generation timeout after {}s reason={}", timeout, reason
        )
        return None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Best-effort: a canned line beats a crashed hang-up. Swallow all.
        logger.warning(
            "exit_line_generation failed (non-fatal): {} ({}) reason={}",
            exc,
            type(exc).__name__,
            reason,
        )
        return None


async def _generate(
    *,
    reason: str,
    transcript_text: str,
    persona: str,
    charter: str,
    api_key: str,
    model: str,
    base_url: str,
) -> str | None:
    guidance = EXIT_LINE_REASON_GUIDANCE.get(reason, EXIT_LINE_GUIDANCE_DEFAULT)
    prompt = EXIT_LINE_GENERATION_PROMPT.format(
        persona=_escape_format_braces(persona.rstrip()),
        charter=_escape_format_braces(charter.rstrip()),
        reason_guidance=_escape_format_braces(guidance),
        transcript=_escape_format_braces(transcript_text),
        constraint=_escape_format_braces(EXIT_LINE_CONSTRAINT),
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": _TEMPERATURE,
        "max_tokens": _MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(base_url, headers=headers, json=payload)

    if response.status_code >= 300:
        body_preview = response.text[:200] if response.text else "<empty>"
        logger.warning(
            "exit_line_generation non-2xx: {} body={!r} reason={}",
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
            "exit_line_generation malformed response: {} ({}) reason={}",
            exc,
            type(exc).__name__,
            reason,
        )
        return None
    if choice.get("finish_reason") == "length":
        # Token-capped mid-thought: a dangling, grammatically-incomplete
        # fragment is worse than the canned line, so fall back rather than
        # speak a truncated sentence.
        logger.info(
            "exit_line_generation truncated (finish_reason=length) → fallback "
            "reason={}",
            reason,
        )
        return None
    if not isinstance(content, str):
        # Some OpenAI-compatible providers return multi-part content; coerce
        # to text (mirrors `_extract_text`) rather than crashing into the
        # outer catch-all with a misleading "failed (non-fatal)" category.
        content = _extract_text(content)
    return _clean_line(content)
