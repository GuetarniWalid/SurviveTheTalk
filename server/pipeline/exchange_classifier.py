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

Timing budget (post-Story 6.9 reliability incident, 2026-05-21): the
classifier MUST resolve within 2.0 s or the conservative fallback path
fires. Story 6.8 had tightened these to 1.0 s outer + 0.8 s HTTP for
latency reasons, but the 0.8 s HTTP budget left zero margin for the
~100-200 ms TLS+TCP cold-start cost paid on EVERY classify call (a new
`httpx.AsyncClient` was instantiated per call — see persistent-client
refactor below). OpenRouter qwen-flash TTFT variance (300-1500 ms)
combined with the cold-start overhead caused ~30 % of classify calls to
timeout, with each timeout incorrectly draining the user's patience
meter — a classifier-side reliability bug that punished the user for
our infra failures (Story 6.9 smoke-test 2026-05-21, call 138 lost on
"Pasta" because of this exact cascade). Story 6.10 prep restores the
2.0 s outer / 1.5 s HTTP budget AND adds persistent client reuse, so
the cold-start cost is paid ONCE at first classify, and subsequent
calls only pay the OpenRouter inference time.

Emotion classification has no UX cost when slow (the character simply
stays in its previous Rive emotion); exchange classification has
direct UX cost (the user's turn either advances the checkpoint or
doesn't, and the next bot reply runs under whichever system prompt is
current). The HTTP timeout (1.5 s) sits under the classifier timeout
(2.0 s) so an HTTP-side abort surfaces a clean log line BEFORE the
async `wait_for` raises `TimeoutError`.

Return contract:
  - `True`  — model said `{"met": true}` AND the response parsed cleanly.
  - `False` — model said `{"met": false}` AND the response parsed cleanly.
  - `None`  — anything else (timeout, HTTP error, malformed JSON, missing
              key, non-bool `met`, unexpected shape). Per Story 6.9
              reliability patch (2026-05-21): the caller
              (CheckpointManager) treats `None` as INFRA FAILURE — does
              NOT advance the checkpoint AND does NOT drain patience
              (the user's turn was lost to our infrastructure, not to
              their performance). `False` means the model actively
              rejected the turn — that IS a user-side failure, drains
              patience, and MUST be logged.
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

# Per epic AC6 line 1196: "fails or times out → checkpoint is NOT
# advanced (conservative — no free progression)". Story 6.9 reliability
# patch (2026-05-21) restored these from Story 6.8's 1.0 s / 0.8 s back
# to 2.0 s / 1.5 s after the "Pasta" classifier-cold-start incident
# (call 138 lost 15 patience because the 0.8 s HTTP budget left zero
# margin for TLS handshake + OpenRouter variance). Paired with the new
# persistent `httpx.AsyncClient` reuse, the cold-start cost is paid
# ONCE at first classify, and the 1.5 s budget comfortably covers the
# OpenRouter qwen-flash 300-1500 ms TTFT variance. The HTTP budget is
# sized below the outer budget so the httpx abort lands first and logs
# a clean HTTP error instead of an opaque `asyncio.TimeoutError`.
_CLASSIFIER_TIMEOUT_SECONDS = 2.0
_HTTP_TIMEOUT_SECONDS = 1.5


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
        # Story 6.9 reliability patch (2026-05-21) — persistent
        # AsyncClient across classify calls. Pre-patch every classify()
        # opened a brand-new client → paid TCP + TLS handshake (~100-200
        # ms) per call → ~30 % of calls timed out against the tight
        # Story 6.8 budget. Lazy-init on first call (deferred so module
        # import doesn't require a running event loop) + protected by
        # an asyncio.Lock so the double-check pattern handles concurrent
        # cold-start races (two classify() calls firing simultaneously
        # at call boot before the LSTM state is warm).
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        # Story 6.9 review patch — closed-flag refuses post-cleanup
        # operations. Without this, a terminal-turn classify task that
        # was already in-flight when `cleanup()` ran (or a stale task
        # spawned after) could call `_get_client()` and create a fresh
        # `httpx.AsyncClient` AFTER teardown, leaking sockets until the
        # process exits. The flag is set inside `close()` under the same
        # lock as the connection-pool release so both client races and
        # post-close re-init races collapse to "raise RuntimeError".
        self._closed: bool = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Return a shared `httpx.AsyncClient`, lazily instantiated on
        first use (deferred from `__init__` because module construction
        doesn't have a running event loop).

        Story 6.9 reliability patch — double-checked locking handles
        the concurrent cold-start race (two classify() calls firing
        simultaneously at call boot). Without the lock both calls
        could create a client each and one would leak.

        Story 6.9 review patch — refuse to create a fresh client if
        `close()` has flipped `_closed`. A terminal-turn classify task
        that was racing with cleanup would otherwise spawn a new
        socket-bound client AFTER the pool was drained.
        """
        if self._closed:
            raise RuntimeError("ExchangeClassifier is closed")
        if self._client is None:
            async with self._client_lock:
                # Re-check post-acquire — `close()` may have flipped the
                # flag while we waited on the lock.
                if self._closed:
                    raise RuntimeError("ExchangeClassifier is closed")
                if self._client is None:
                    self._client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)
        return self._client

    async def close(self) -> None:
        """Release the underlying httpx connection pool.

        Called by `CheckpointManager.cleanup()` on pipeline shutdown so
        the connection pool is properly drained — without this httpx
        emits `Unclosed AsyncClient` warnings at GC time + leaks the
        underlying transport's sockets until the process exits.
        Idempotent — safe to call multiple times.

        Story 6.9 review patch — acquire `_client_lock` so concurrent
        `close()` calls (two cleanup paths racing) and concurrent
        `_get_client()` calls (in-flight classify mid-shutdown) both
        serialize on the same critical section. The `_closed` flag set
        inside the lock blocks any subsequent `_get_client` from
        spawning a fresh client.
        """
        async with self._client_lock:
            self._closed = True
            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:  # pragma: no cover — defensive shutdown
                    logger.exception("ExchangeClassifier client close failed")
                finally:
                    self._client = None

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
            client = await self._get_client()
            response = await client.post(_OPENROUTER_URL, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            # Story 6.9 reliability patch — surface the exception's
            # qualified class name when the str() is empty (httpx
            # TimeoutException sometimes serialises to ""). Without
            # this, operator sees "HTTP error: " and can't tell if it
            # was a timeout / connect failure / response error.
            logger.warning(
                "exchange classifier HTTP error: {} ({})",
                exc or "<no message>",
                type(exc).__name__,
            )
            return None
        except RuntimeError as exc:
            # Story 6.9 review patch — `_get_client()` raises
            # RuntimeError when the classifier is closed (post-cleanup
            # race). Without this branch the exception would bypass the
            # `httpx.HTTPError` handler and propagate up to the
            # `_classify_and_advance` task, killing it with a silent
            # `Task exception was never retrieved` log. Surface it as a
            # normal `None` verdict (the caller already treats `None`
            # as infra failure).
            logger.warning(
                "exchange classifier lifecycle error: {} ({})",
                exc,
                type(exc).__name__,
            )
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
