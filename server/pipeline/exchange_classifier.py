"""Story 6.6 — ExchangeClassifier async LLM service.

Single-purpose judge that returns `{met: bool}` per user turn, evaluated
against the CURRENT checkpoint's `success_criteria` only (per
`difficulty-calibration.md` §3.1 D-5 review note line 48 — the classifier
is current-checkpoint-only; no look-ahead, no caching of future intent).

Mirrors the `pipeline/emotion_emitter.py` HTTPX + OpenRouter pattern:
  - `qwen/qwen3.5-flash-02-23` model.
  - `reasoning.enabled = False` at the **top level** of the request body
    (NOT nested in `extra_body` — the OpenRouter HTTP API doesn't unwrap
    `extra_body`; that key is only respected by the OpenAI Python SDK).
  - JSON-strict response with Markdown-fence + first-`{...}` fallbacks.

Timing divergence from EmotionEmitter (epic AC6 line 1196): the
classifier MUST resolve within 2.0 s or the manager treats the exchange
as a failed turn ("conservative fallback — no free progression"). Emotion
classification has no UX cost when slow (the character simply stays in
its previous Rive emotion); exchange classification has direct UX cost
(the user's turn either advances the checkpoint or doesn't, and the next
bot reply runs under whichever system prompt is current). The HTTP
timeout (1.8 s) sits just under the classifier timeout (2.0 s) so an
HTTP-side abort surfaces a clean log line BEFORE the async wait_for
raises `TimeoutError`.

Return contract:
  - `True`  — model said `{"met": true}` AND the response parsed cleanly.
  - `False` — model said `{"met": false}` AND the response parsed cleanly.
  - `None`  — anything else (timeout, HTTP error, malformed JSON, missing
              key, non-bool `met`, unexpected shape). The caller
              (CheckpointManager) treats `None` as "failed exchange for
              the patience meter, but DON'T log the verdict noise" —
              `False` means the model actively rejected the turn and
              MUST be logged.
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
from loguru import logger

from pipeline.prompts import EXCHANGE_CLASSIFIER_PROMPT

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_MODEL = "qwen/qwen3.5-flash-02-23"

# Per epic AC6 line 1196: "fails or times out (>2s) → checkpoint is NOT
# advanced (conservative — no free progression)". 2.0 s outer budget;
# 1.8 s HTTP budget so the httpx abort lands first and we get a clean
# HTTP error log line instead of an opaque asyncio.TimeoutError.
_CLASSIFIER_TIMEOUT_SECONDS = 2.0
_HTTP_TIMEOUT_SECONDS = 1.8


_FENCE_RE = re.compile(
    r"^```(?:json)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL | re.IGNORECASE,
)


class ExchangeClassifier:
    """Async OpenRouter-backed judge that returns `{met: bool}` per user turn.

    Single-purpose; one instance per call, owned by `CheckpointManager`.
    Never blocks the main pipeline — every classify wrapped in
    `asyncio.wait_for(_CLASSIFIER_TIMEOUT_SECONDS)`.

    Args:
        openrouter_api_key: API key for OpenRouter. Required — passed in
            by `bot.py` from `Settings.openrouter_api_key`. Empty/None
            raises `ValueError` so the bug surfaces at process start, not
            on every classify with a silent 401.
    """

    def __init__(self, *, openrouter_api_key: str) -> None:
        if not openrouter_api_key:
            raise ValueError(
                "ExchangeClassifier requires a non-empty openrouter_api_key"
            )
        self._api_key = openrouter_api_key

    async def classify(
        self,
        *,
        user_text: str,
        last_character_line: str,
        success_criteria: str,
        scenario_description: str,
    ) -> bool | None:
        """Return True if the user met the current objective, False if not,
        None on timeout / parse-error / HTTP failure.

        Args:
            user_text: The user's most-recent finalized transcription.
            last_character_line: The previous character utterance — gives
                the judge LLM "what was just said" context. Empty string
                is acceptable on the very first user turn (no prior
                character line yet).
            success_criteria: The current checkpoint's `success_criteria`
                YAML string.
            scenario_description: Short scenario context (e.g. the
                metadata title "The Waiter"). Kept short so the prompt
                stays single-shot.
        """
        try:
            return await asyncio.wait_for(
                self._classify(
                    user_text=user_text,
                    last_character_line=last_character_line,
                    success_criteria=success_criteria,
                    scenario_description=scenario_description,
                ),
                timeout=_CLASSIFIER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("exchange classifier timeout")
            return None
        except asyncio.CancelledError:
            raise

    async def _classify(
        self,
        *,
        user_text: str,
        last_character_line: str,
        success_criteria: str,
        scenario_description: str,
    ) -> bool | None:
        prompt = EXCHANGE_CLASSIFIER_PROMPT.format(
            scenario_description=scenario_description,
            last_character_line=last_character_line,
            user_text=user_text,
            success_criteria=success_criteria,
        )
        # `reasoning` MUST sit at the top level of the JSON body. See
        # `pipeline/emotion_emitter.py` for the original smoke-gate
        # rationale: `extra_body` is an OpenAI-SDK convention that the
        # SDK flattens into the request body before sending; OpenRouter's
        # HTTP API doesn't know the `extra_body` key and silently drops
        # it. Putting `reasoning` there leaves Qwen in default reasoning
        # mode (5-15 s per call) and every classification times out.
        payload = {
            "model": _OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 32,
            "reasoning": {"enabled": False},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    _OPENROUTER_URL, headers=headers, json=payload
                )
        except httpx.HTTPError as exc:
            logger.warning("exchange classifier HTTP error: {}", exc)
            return None

        if response.status_code >= 300:
            logger.warning("exchange classifier non-2xx: {}", response.status_code)
            return None

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning("exchange classifier malformed envelope: {}", exc)
            return None

        return _parse_classifier_output(content)


def _parse_classifier_output(content: str) -> bool | None:
    """Defensively parse the model's response into a `met` bool.

    Models occasionally wrap JSON in prose or Markdown fences. Try a
    strict `json.loads` first, then strip a Markdown fence, then fall
    back to extracting the first `{...}` substring. Any value outside
    `{True, False}` (missing key, non-bool, unexpected shape) returns
    `None` — the caller (CheckpointManager) treats `None` as the
    conservative "failed exchange, no advance" fallback.
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
            logger.warning("exchange classifier non-JSON output")
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("exchange classifier non-JSON output")
            return None

    if not isinstance(data, dict):
        logger.warning("exchange classifier output not a dict")
        return None
    met = data.get("met")
    if not isinstance(met, bool):
        logger.warning("exchange classifier missing/non-bool 'met': {!r}", met)
        return None
    return met
