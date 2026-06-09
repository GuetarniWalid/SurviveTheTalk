"""Story 6.6 — ExchangeClassifier async LLM service.

Single-purpose judge that returns `{met: bool}` per user turn, evaluated
against the CURRENT checkpoint's `success_criteria` only (per
`difficulty-calibration.md` §3.1 D-5 review note line 48 — the classifier
is current-checkpoint-only; no look-ahead, no caching of future intent).

Provider: **Groq Llama 3.3 70B** (since Story 6.9b migration, 2026-05-22).
Migrated from Qwen 3.5 Flash via OpenRouter after the bench at
`_bmad-output/implementation-artifacts/calibration-tests/
classifier_benchmark_2026-05-22T09-29-19Z.json` measured Groq from the
VPS as 4.8× faster (p50 121 ms vs 587 ms), 2.7× faster on p95 (320 ms vs
859 ms), and 4 pts more accurate (98.7 % vs 94.7 %) with ZERO false
positives (Qwen had 3) on the 75-sample classifier corpus. Cost delta
is +~10 €/mois at 100-user MVP scale (Groq Llama 3.3 70B priced $0.59/M
input + $0.79/M output vs Qwen $0.05/$0.15). The sub-300 ms p95 from
VPS unblocks Story 6.12 "Reactive Character Mood" sync-verdict-everywhere
architecture (which needed classifier < 300 ms to keep total perceived
latency under the PRD 800 ms target).

EmotionEmitter stays on Qwen via OpenRouter (out of scope for this
migration — emotion latency has zero UX cost when slow, the character
just stays in its prior Rive pose). A future Story 6.9c may unify both
classifiers under Groq for vendor reduction.

Request shape: Groq is OpenAI-compatible at
`https://api.groq.com/openai/v1/chat/completions`, so the body shape
(messages list, max_tokens, temperature) matches what we sent to
OpenRouter. The `reasoning` field from the OpenRouter era is NOT sent
to Groq — Llama 3.3 70B doesn't have a thinking mode to disable, and
sending unknown fields risks 400 errors with stricter providers.

Streaming skipped — gain <100 ms. Groq's measured TTFT from the VPS is
~70-90 ms with total `_classify()` p50 = 121 ms / p95 = 320 ms. Activating
streaming would save at most the (total - TTFT) tail (~30-200 ms), but
the verdict cannot be acted on until the full `{"met": ...}` JSON is
parsed — there is no incremental UX win to harvest. Buffered POST is
preserved per AC3 / Deviation #2 (streaming activation contingent on
≥100 ms measured gain, which Groq's TTFT already invalidates).

Timing budget (kept from Story 6.9): 2.0 s outer / 1.5 s HTTP. With
Groq's measured p95 320 ms from VPS the budget is now ~6× larger than
the actual classify latency, so the safety belt sits unused on the
happy path. It still fires on degraded-Groq (rate-limit 429 storms,
upstream outages) so the consecutive-None backstop in
`checkpoint_manager.py:106` (Story 6.9 review D1) stays in place.

Persistent client lifecycle (Story 6.9 Deviations #5-#10) is preserved
unchanged — `_get_client()` double-checked locking, `_closed` flag,
lock-guarded `close()`, RuntimeError handling for post-cleanup races.
The lifecycle contract is provider-agnostic.

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

Story 6.10 (goal-based dialogue) adds `classify_multi`, which judges a
single user turn against ALL pending objectives in ONE LLM call and
returns a `{goal_id: True | False | None}` dict. The original
single-objective `classify` is preserved unchanged as a thin
compatibility wrapper for the legacy `/connect` PoC path + existing
tests. Both paths share `_post_for_content` for the provider request +
failure-mode handling; only the verdict-parsing layer differs
(`_parse_classifier_output` vs `_parse_multi_classifier_output`).

2026-05-29 structured-output fix — `classify_multi` now requests Groq
STRICT structured outputs (`response_format=json_schema`): the verdict is
a schema-pinned object `{goal_id: "met"|"unmet"|"unsure"}` validated by
Groq server-side (constrained decoding). This replaces the free-form
`{"goals_met":[...],"goals_unmet":[...]}` contract, which let the model
intermittently echo the literal id tag (`goal_id="greet"`) — breaking id
matching and silently yielding all-None (no checkpoint flipped) for an
input that had worked moments before. Because 70B does NOT support
`json_schema` (HTTP 400), the classifier model defaults to Llama 4 Scout
(`config.Settings.classifier_model`); the single-goal legacy `classify`
keeps its prose-tolerant `_parse_classifier_output` and sends no
`response_format`. The character + emotion paths are unaffected — both
still run 70B and neither uses structured outputs.
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
from loguru import logger

from pipeline.prompts import (
    EXCHANGE_CLASSIFIER_MULTI_PROMPT,
    EXCHANGE_CLASSIFIER_PROMPT,
)

_PROVIDER_URL = "https://api.groq.com/openai/v1/chat/completions"
# 2026-05-29 — Llama 4 Scout (NOT 70B): the multi-goal path uses Groq
# STRICT structured outputs (`response_format=json_schema`), which 70B
# does not support (HTTP 400). Scout does, and is ~4-5x cheaper at the
# same latency. See `config.Settings.classifier_model`. bot.py always
# passes the resolved `Settings.classifier_model`; this default only
# governs direct/test construction.
_PROVIDER_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Story 6.10 follow-up (2026-05-29) — the multi-goal verdict is now a
# schema-pinned object `{goal_id: "met"|"unmet"|"unsure"}`. Groq validates
# it server-side (constrained decoding) so the model can neither mangle a
# goal_id nor omit a key — killing the intermittent `goal_id="greet"`
# echo bug that silently produced all-None (no checkpoint flipped).
_VERDICT_VALUES = ("met", "unmet", "unsure")
_VERDICT_TO_BOOL: dict[str, bool | None] = {"met": True, "unmet": False, "unsure": None}

# FR37 — reserved key for the abuse flag folded into the multi-goal verdict
# object. `__`-wrapped so it can never collide with a YAML checkpoint id (which
# are plain snake_case). The model returns it as a strict boolean; the caller
# (`CheckpointManager`) pops it before the goal-advance rule.
ABUSE_KEY = "__user_abusive__"

# Story 6.10 (2026-05-29 structured-output) — the multi-goal classifier emits a
# schema-pinned JSON object with ONE key per pending goal_id, each valued
# `"met"|"unmet"|"unsure"`. The output length grows with the objective count
# (each entry is the goal_id key + a short enum value + punctuation), so the
# completion-token budget MUST scale with the number of goals.
#
# Story 6.16 surfaced the failure mode: a 20-checkpoint scenario with all 20
# goals pending overflowed the old FIXED `128` budget → Groq returned HTTP 400
# `json_validate_failed` ("max completion tokens reached before generating a
# valid document") on EVERY classify, so NO checkpoint ever advanced and the
# call drained patience unfairly. (1 and 5 goals were fine; 20 was not.) We size
# base + per-goal with headroom for long snake_case ids — still a fraction of a
# cent per classify even at 20 goals.
# FR37 — base bumped 64 → 96 to cover the extra `"__user_abusive__": false`
# entry (~12 tokens) so the schema-pinned document can't truncate (Groq returns
# HTTP 400 json_validate_failed on truncation — Story 6.16).
_MULTI_MAX_TOKENS_BASE = 96
_MULTI_MAX_TOKENS_PER_GOAL = 24


def _multi_max_tokens(num_goals: int) -> int:
    """Completion-token budget for `classify_multi`, scaled to the pending-goal
    count so the schema-pinned verdict object can't be truncated mid-document
    (Story 6.16). At 6 goals → 240; at 20 goals → 576."""
    return _MULTI_MAX_TOKENS_BASE + _MULTI_MAX_TOKENS_PER_GOAL * max(1, num_goals)


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


def _escape_format_braces(value: str) -> str:
    """Escape `{` and `}` so `str.format()` doesn't interpret them as
    placeholders. Story 6.9b review P14: STT-transcribed user text or
    upstream character lines can contain literal braces (e.g. the user
    reads JSON aloud, or the character line includes our own slot
    markers verbatim). Without escaping, `.format()` raises `KeyError`
    or `ValueError` and the verdict task dies silently.
    """
    return value.replace("{", "{{").replace("}", "}}")


class ExchangeClassifier:
    """Async Groq-backed judge that returns `{met: bool}` per user turn.

    Single-purpose; one instance per call, owned by `CheckpointManager`.
    Never blocks the main pipeline — every classify wrapped in
    `asyncio.wait_for(_CLASSIFIER_TIMEOUT_SECONDS)`.

    Args:
        api_key: API key for the classifier provider (Groq since the
            Story 6.9b migration). Required — passed in by `bot.py`
            from `Settings.groq_api_key`. Empty/None raises `ValueError`
            so the bug surfaces at process start, not on every classify
            with a silent 401. The kwarg is provider-neutrally named
            `api_key` (was `openrouter_api_key` pre-migration) so a
            future provider swap doesn't require a parameter rename.
        model: Provider-specific model id (default `llama-3.3-70b-
            versatile`). Sourced from `Settings.classifier_model` in
            `bot.py` so the model can be flipped via the
            `CLASSIFIER_MODEL` env override at deploy time without a
            code release — useful for rollback to Qwen
            (`qwen/qwen3.5-flash-02-23` via OpenRouter) if Groq has
            an incident. Retires `deferred-work.md` line 450 (Story 6.9
            Defer #3).
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = _PROVIDER_MODEL,
        base_url: str = _PROVIDER_URL,
    ) -> None:
        if not api_key:
            raise ValueError("ExchangeClassifier requires a non-empty api_key")
        self._api_key = api_key
        self._model = model
        # 2026-05-29 — provider endpoint is injectable (from
        # `Settings.llm_base_url` in `bot.py`) so a provider switch is an
        # env change, not a code edit. Defaults to Groq.
        self._base_url = base_url
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

    async def classify_multi(
        self,
        *,
        user_text: str,
        last_character_line: str,
        pending_goals: list[dict],
        scenario_description: str,
    ) -> dict[str, bool | None] | None:
        """Evaluate a single user turn against ALL pending objectives in
        one LLM call (Story 6.10 goal-based dialogue).

        Returns EITHER:
          - a `{goal_id: True | False | None}` dict keyed by EVERY pending
            goal_id (a PARSED verdict) — the call succeeded and the model
            answered:
              * True  — that objective is met.
              * False — that objective is actively NOT met.
              * None  — the model was "unsure" about that objective (no
                        verdict; the caller keeps it pending). An all-None
                        DICT is genuine model ambiguity, NOT infra failure.
          - `None` (the whole return value) — INFRA FAILURE: timeout, HTTP
            error, closed-client race, non-2xx, empty content-filter
            choices, or an unparseable body. The caller (CheckpointManager)
            treats a `None` return as patience-neutral infra failure and
            feeds the consecutive-None backstop — distinct from a parsed
            all-None (all-"unsure") dict, which it treats as benign
            ambiguity (review D3, 2026-05-29).

        Args:
            user_text: The user's most-recent finalized transcription.
            last_character_line: The previous character utterance.
            pending_goals: List of `{"id": str, "success_criteria": str}`
                dicts (extra keys ignored). Only goals still pending
                should be passed — already-met goals must not be re-judged.
            scenario_description: Short scenario context.
        """
        try:
            return await asyncio.wait_for(
                self._classify_multi(
                    user_text=user_text,
                    last_character_line=last_character_line,
                    pending_goals=pending_goals,
                    scenario_description=scenario_description,
                ),
                timeout=_CLASSIFIER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("exchange classifier multi timeout")
            return None
        except asyncio.CancelledError:
            raise

    async def _post_for_content(self, payload: dict) -> str | None:
        """Issue the chat-completion POST and extract the assistant
        message content, or return None on ANY failure.

        Shared by the single-goal `_classify` and the multi-goal
        `_classify_multi` paths (Story 6.10) so the provider request
        shape + the full failure-mode handling (HTTP error, closed-
        client lifecycle race, non-2xx, non-JSON body, malformed
        envelope, empty content-filter choices) live in ONE place. Each
        caller layers its own JSON-verdict parser on top of the returned
        content string.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            client = await self._get_client()
            response = await client.post(self._base_url, headers=headers, json=payload)
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
            # Story 6.9b review P9 — narrow to lifecycle "closed" errors
            # only. Re-raise any other RuntimeError (e.g. event-loop
            # mismatch, unexpected library bug) so the real defect isn't
            # silently degraded to `verdict=None`.
            if "closed" not in str(exc).lower():
                raise
            logger.warning(
                "exchange classifier lifecycle error: {} ({})",
                exc,
                type(exc).__name__,
            )
            return None

        if response.status_code >= 300:
            # Story 6.16 — include a body preview so a 4xx/5xx is diagnosable
            # (a bare status hid WHY a 400 fired — e.g. an unsupported
            # response_format, a schema the provider rejects, or a rate-limit
            # detail). Cheap + safe; the body is provider error JSON, not PII.
            body_preview = response.text[:300] if response.text else "<empty>"
            logger.warning(
                "exchange classifier non-2xx: {} body={!r}",
                response.status_code,
                body_preview,
            )
            return None

        try:
            body = response.json()
        except ValueError as exc:
            # Story 6.9b review P16 — 2xx with non-JSON body usually
            # means Cloudflare/Groq interstitial or a bot-protection
            # challenge page. Log content-type + first 200 chars of the
            # body so the operator can disambiguate vs malformed JSON.
            content_type = response.headers.get("content-type", "<missing>")
            preview = response.text[:200] if response.text else "<empty>"
            logger.warning(
                "exchange classifier non-JSON body: {} (content-type={!r}, preview={!r})",
                exc,
                content_type,
                preview,
            )
            return None
        try:
            choices = body["choices"]
        except (KeyError, TypeError) as exc:
            logger.warning("exchange classifier malformed envelope: {}", exc)
            return None
        if not choices:
            # Story 6.9b review P22 — empty choices list at HTTP 200 is
            # usually a Groq content-filter refusal (the model declined
            # to respond on adversarial input). Log it distinctly so the
            # operator can monitor it; verdict stays None (conservative
            # — caller treats as infra failure, no patience drain). A
            # future iteration could treat empty-choices as `False`
            # (NOT MET) to drain patience on adversarial users, but
            # changing the contract requires care: a transient Groq bug
            # that returns empty choices on legit content would wrongly
            # penalise patience.
            logger.warning(
                "exchange classifier empty choices — possible content filter (usage={})",
                body.get("usage", "<missing>"),
            )
            return None
        try:
            return choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("exchange classifier malformed envelope: {}", exc)
            return None

    async def _classify(
        self,
        *,
        user_text: str,
        last_character_line: str,
        success_criteria: str,
        scenario_description: str,
    ) -> bool | None:
        prompt = EXCHANGE_CLASSIFIER_PROMPT.format(
            scenario_description=_escape_format_braces(scenario_description),
            last_character_line=_escape_format_braces(last_character_line),
            user_text=_escape_format_braces(user_text),
            success_criteria=_escape_format_braces(success_criteria),
        )
        # Story 6.9b — Groq is OpenAI-compatible: same body shape as the
        # OpenRouter request we sent pre-migration. The `reasoning` field
        # (which forced-disabled Qwen's chain-of-thought via OpenRouter)
        # is NOT sent — Llama 3.3 70B has no thinking mode to disable,
        # and sending unknown fields risks 400 errors on stricter
        # providers. EmotionEmitter still sends `reasoning` because it
        # stays on Qwen via OpenRouter (out of scope for this migration).
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            # Story 6.9b review P15 — raised 32 → 64. Llama 3.3 70B can
            # prepend whitespace/leading-newline tokens before the JSON
            # body, and `{"met": true}` is already ~10 tokens; 32 left
            # zero margin for verbose framing. 64 stays well below any
            # cost concern (~0.02 ¢ per 1000 classifies) while making
            # truncation-mid-JSON essentially impossible.
            "max_tokens": 64,
        }
        content = await self._post_for_content(payload)
        if content is None:
            return None
        return _parse_classifier_output(content)

    async def _classify_multi(
        self,
        *,
        user_text: str,
        last_character_line: str,
        pending_goals: list[dict],
        scenario_description: str,
    ) -> dict[str, bool | None] | None:
        goal_ids = [g["id"] for g in pending_goals]
        prompt = EXCHANGE_CLASSIFIER_MULTI_PROMPT.format(
            scenario_description=_escape_format_braces(scenario_description),
            last_character_line=_escape_format_braces(last_character_line),
            user_text=_escape_format_braces(user_text),
            # The block is a pre-built format ARGUMENT — `str.format()`
            # does not re-parse substituted values, so any literal braces
            # in a success_criteria pass through unharmed (no escaping
            # needed, and escaping here would double-brace the LLM-
            # visible text). Verified 2026-05-28.
            pending_goals_block=_format_pending_goals_block(pending_goals),
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": _multi_max_tokens(len(goal_ids)),
            # STRICT structured output — Groq constrains generation to this
            # schema, guaranteeing an exactly-keyed `{goal_id: enum}` object.
            # Requires a structured-output-capable model (Scout, NOT 70B).
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "goal_verdicts",
                    "strict": True,
                    "schema": _build_verdict_schema(goal_ids),
                },
            },
        }
        content = await self._post_for_content(payload)
        if content is None:
            # Infra failure (HTTP error / non-2xx / closed client / empty
            # choices). Signal it distinctly as `None` so the caller can
            # tell it apart from a parsed all-"unsure" dict.
            return None
        # `_parse_multi_classifier_output` returns None on a parse failure
        # (malformed / non-dict body) — also infra-grade, propagated as None.
        return _parse_multi_classifier_output(content, goal_ids)


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


def _build_verdict_schema(goal_ids: list[str]) -> dict:
    """Build the STRICT JSON schema for `classify_multi`'s structured
    output: one property per pending goal_id, each constrained to the
    met/unmet/unsure enum, ALL required, no extra keys.

    Groq enforces this server-side via constrained decoding, so the model
    physically cannot (a) echo a mangled id like `goal_id="greet"`, (b)
    omit a goal, or (c) emit a value outside the enum. That removes the
    entire format-instability class of bug at the source — the previous
    free-form `{"goals_met":[...],"goals_unmet":[...]}` contract let 70B
    intermittently return the literal tag text, which broke id matching
    and produced a silent all-None (no checkpoint flipped) for the SAME
    input that worked moments earlier.
    """
    properties: dict = {
        gid: {"type": "string", "enum": list(_VERDICT_VALUES)} for gid in goal_ids
    }
    # FR37 — fold abuse detection into the SAME structured call (no extra LLM
    # call, no added latency/cost beyond ~one boolean). `ABUSE_KEY` is a
    # reserved boolean the caller (`CheckpointManager`) pops BEFORE the
    # goal-advance rule, so it never pollutes goal judging; its `__`-wrapped
    # name can never collide with a checkpoint id.
    properties[ABUSE_KEY] = {"type": "boolean"}
    return {
        "type": "object",
        "properties": properties,
        "required": list(goal_ids) + [ABUSE_KEY],
        "additionalProperties": False,
    }


def _format_pending_goals_block(pending_goals: list[dict]) -> str:
    """Render the pending objectives as a bare `- <goal_id>: <criteria>`
    list for the `{pending_goals_block}` placeholder in
    `EXCHANGE_CLASSIFIER_MULTI_PROMPT`.

    The goal_id is shown plainly (no `goal_id="..."` tag) because it is the
    JSON KEY the model fills under the strict schema, NOT a value it echoes.
    The old tagged format invited the model to copy the literal tag
    `goal_id="greet"` into its answer, breaking id matching (the 2026-05-29
    silent-no-flip bug). We use the YAML checkpoint id verbatim so it lines
    up with the schema keys built by `_build_verdict_schema`.
    """
    lines = []
    for goal in pending_goals:
        lines.append(f"- {goal['id']}: {goal['success_criteria']}")
    return "\n".join(lines)


def _parse_multi_classifier_output(
    content: str, valid_ids: list[str]
) -> dict[str, bool | None] | None:
    """Parse the multi-goal verdict object into a `{goal_id: bool|None}`
    dict keyed by EVERY id in `valid_ids`, or `None` on a parse failure.

    Expected (strict-schema-enforced) shape:
    `{"<goal_id>": "met"|"unmet"|"unsure", ...}`. met → True, unmet →
    False, unsure (or a missing key / unknown value) → None (per-goal "no
    verdict"). A whole PARSE failure (non-JSON / non-dict body) returns
    `None` (the whole value) so the caller treats it as infra failure —
    NOT to be confused with a successfully-parsed dict whose values happen
    to all be None ("unsure"), which is benign model ambiguity (review D3,
    2026-05-29). The fence-strip + first-`{...}` fallback is retained as
    defensive belt-and-suspenders for a non-strict provider / model that
    wraps the JSON, even though Groq strict mode returns clean JSON on the
    happy path.
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
            logger.warning("exchange classifier multi non-JSON output")
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("exchange classifier multi non-JSON output")
            return None

    if not isinstance(data, dict):
        logger.warning("exchange classifier multi output not a dict")
        return None

    verdicts: dict[str, bool | None] = {
        gid: _VERDICT_TO_BOOL.get(data.get(gid), None) for gid in valid_ids
    }
    # FR37 — surface the reserved abuse flag (strict bool) alongside the goal
    # verdicts. The caller pops `ABUSE_KEY` before `advance_goals`, so it never
    # reaches the goal-advance/outcome rule. A missing/non-bool value → False
    # (conservative: never hang up on an ambiguous classifier output).
    verdicts[ABUSE_KEY] = data.get(ABUSE_KEY) is True
    return verdicts
