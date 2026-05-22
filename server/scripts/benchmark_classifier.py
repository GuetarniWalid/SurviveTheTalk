"""Story 6.9b — Classifier provider benchmark harness.

Reads a labeled corpus of `(user_text, last_character_line, success_criteria,
scenario_description, ground_truth)` samples and runs each through one or
more classifier provider configurations. For each provider it measures:

- TTFT (time-to-first-token) — first byte of the response body
- Total latency — request send → verdict parsed
- Verdict accuracy vs `ground_truth` (per sample + per-provider summary)
- Cost-per-classify computed from published per-token rates

Output: a timestamped JSON report under
`_bmad-output/implementation-artifacts/calibration-tests/` with per-provider
summary stats + per-sample raw timings + a `recommendation` block naming the
provider that beats the baseline (Qwen via OpenRouter) on BOTH latency AND
accuracy (or aborts if no provider beats the baseline on both — per
Deviation #1 of the story spec).

## Why this harness exists separately from `ExchangeClassifier`

- The classifier is single-purpose (one provider, one prompt). The harness
  needs to swap providers + headers + request shapes per-call.
- The harness can run WITHOUT all providers' API keys present — providers
  missing a key are skipped with a loud stderr warning. The operator only
  needs keys for the providers being benchmarked in the run.
- The harness is dev-machine-only (never imported by `bot.py`); failure
  modes here are loud (raise / log + skip) instead of the production
  classifier's silent `None`-on-failure conservative path.

## Iteration history (kept for review traceability)

The harness landed in Phase A (2026-05-21) with 4 spec-named providers and
grew to 6 across the 2026-05-22 interactive bench:

- **2026-05-21 v1** — base harness, 4 providers, single-shot per-sample run
  (no retry).
- **2026-05-22 v2** — added `load_dotenv()` so the operator doesn't have
  to source `server/.env` in the shell every run.
- **2026-05-22 v3** — added bounded retry-on-429 honouring `Retry-After`
  after the Groq 8B bench got 63/75 rate-limit failures from sequentially
  hammering the free-tier 6000 TPM budget. The retry sleep is EXCLUDED
  from the latency measurement (timer resets post-sleep) so per-call
  metrics reflect what an appropriately-throttled prod caller would see.
- **2026-05-22 v4** — added 2 DashScope provider configs (Qwen 3.5 + 3.6
  Flash) to test Lever 1 hypothesis ("skip OpenRouter proxy"). Discovered
  DashScope Qwen3+ models default to thinking-mode ON (3-10 s per call);
  the kill-switch flag `enable_thinking: false` MUST sit at top-level of
  the JSON body (not in `extra_body`, which is OpenAI-SDK-only and
  silently dropped by raw HTTP — same gotcha as the Story 6.6 `reasoning`
  smoke fix).
- **2026-05-22 v5** — added Groq Llama 3.3 70B config mid-bench when the
  8B variant aborted on accuracy. This is the eventual winner.

## Usage

    cd server
    python scripts/benchmark_classifier.py \\
        --corpus tests/fixtures/classifier_benchmark_corpus.json \\
        --providers all \\
        --output _bmad-output/implementation-artifacts/calibration-tests/

`--providers` accepts `all` or a comma-separated subset
(e.g. `qwen_via_openrouter,groq_llama_3.3_70b`). Subset is useful for
re-running just the winner from VPS without burning quota on dead-end
providers.

## Deviation #1 — empirical provider selection

This harness produces the data; the operator reads the JSON report and
picks the winner. If no provider beats the baseline on BOTH latency AND
accuracy, the migration is aborted and Story 6.12 falls back to the
visual-first feedback architecture (option F per
`memory/project_story_6_9b_classifier_latency_slash.md`).

The 2026-05-22 bench cycle landed on Groq Llama 3.3 70B as the winner:
121 ms p50 VPS / 320 ms p95 / 98.7 % accuracy / 0 false positives vs Qwen
baseline 587 ms / 859 ms / 94.7 % / 3 FPs. Cost delta +~10 €/mois at
100-user MVP scale.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

# Reuse the production prompt + parser so the benchmark exercises the EXACT
# code path classifier callers exercise. This is load-bearing: a benchmark
# that uses a different prompt is benchmarking a hypothetical, not the prod
# classifier.
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # `server/` on path so `pipeline.*` imports work

# Pick up benchmark-only API keys from `server/.env` without requiring the
# operator to export them in the shell. dotenv default behaviour is
# no-override on already-set env vars — so the prod OPENROUTER_API_KEY in
# the operator's shell still wins if both are set. Silently no-ops if the
# .env file doesn't exist (CI / test environments).
#
# Story 6.9b review P4 — `load_dotenv()` is called from `main()`, NOT at
# module import. Importing this module (e.g. from `test_benchmark_classifier.py`)
# does NOT touch the operator's `.env` so tests stay hermetic and never
# accidentally pick up real keys.
from dotenv import load_dotenv  # noqa: E402

from pipeline.exchange_classifier import _parse_classifier_output  # noqa: E402
from pipeline.prompts import EXCHANGE_CLASSIFIER_PROMPT  # noqa: E402

# ============================================================
# Provider config — single source of truth for endpoints + per-token rates
# ============================================================


@dataclass(frozen=True)
class ProviderConfig:
    """One provider configuration. `request_payload` differs per provider
    (OpenAI-compatible shape for Qwen/Groq/Cerebras via OpenAI-compatible
    endpoints; Anthropic messages API for Haiku 4.5).
    """

    name: str
    url: str
    model: str
    api_key_env: str
    # Cost in USD per 1M tokens (input/output). Pinned at story-draft time
    # (2026-05-21) per `memory/project_story_6_9b_classifier_latency_slash.md`
    # §1; re-verify at benchmark time and update the report with actual
    # invoice-derived numbers if drift is observed.
    input_cost_per_1m: float
    output_cost_per_1m: float
    # Request shape — "openai_compat" for OpenRouter/Groq/Cerebras (chat
    # completions with messages list), "anthropic" for Claude messages API.
    shape: str = "openai_compat"


# Provider catalog. The original Story 6.9b spec named 4 providers (Qwen,
# Groq 8B, Cerebras, Anthropic). The catalog grew to 6 during the
# 2026-05-22 interactive bench session as the data pointed elsewhere:
#
# 1. `qwen_via_openrouter`           — spec baseline, kept
# 2. `qwen3.5_flash_via_dashscope`   — added 2026-05-22 to test Lever 1
#                                      (skip OpenRouter proxy). Result: ABORT
#                                      (591 ms VPS vs 587 ms via OpenRouter
#                                      = zero gain; Qwen is hosted in
#                                      Singapore, OpenRouter overhead ~10 ms).
# 3. `qwen3.6_flash_via_dashscope`   — paired with #2 as a free upgrade test
#                                      (newer Flash variant). Result: 710 ms
#                                      p50 local, slower than 3.5; not worth
#                                      the swap.
# 4. `groq_llama_3.1_8b`             — spec provider, ABORT on the 8B
#                                      variant (12 % accuracy too lenient
#                                      after retry-on-429 fix, Deviation #1
#                                      failed on accuracy axis).
# 5. `groq_llama_3.3_70b`            — added 2026-05-22 mid-bench when 8B
#                                      aborted. Result: WINNER (121 ms VPS,
#                                      98.7 % accuracy, 0 false positives).
#                                      This is the production target.
# 6. `cerebras_llama_3.1_8b`         — spec provider, SKIPPED for the
#                                      benchmark per Walid 2026-05-21 cost
#                                      decision (2× Qwen cost without clear
#                                      latency lead vs Groq). Config kept
#                                      for future re-bench if needed.
# 7. `anthropic_haiku_4.5`           — spec provider, SKIPPED for the
#                                      benchmark per Walid 2026-05-21 cost
#                                      decision (22× Qwen cost; benchmark-
#                                      only quality-ceiling reference per
#                                      spec). Config kept for future re-bench.
#
# Why keep the abort-providers in the catalog: re-running the bench against
# the corpus is a one-line `--providers <name>` change. Removing entries
# means re-coding the config when (not if) we re-test. The runtime skips
# providers whose API key env var is unset (loud stderr warning) — so
# leaving Cerebras + Anthropic here with empty env vars has zero impact on
# routine `--providers all` runs unless the operator explicitly provisions
# those keys.
_PROVIDERS: tuple[ProviderConfig, ...] = (
    ProviderConfig(
        name="qwen_via_openrouter",
        url="https://openrouter.ai/api/v1/chat/completions",
        model="qwen/qwen3.5-flash-02-23",
        api_key_env="OPENROUTER_API_KEY",
        input_cost_per_1m=0.05,
        output_cost_per_1m=0.15,
    ),
    # Story 6.9b — Lever 1 (2026-05-21): direct DashScope (Alibaba) Qwen
    # provider, skipping the OpenRouter proxy layer. OpenRouter is a US-based
    # router; routing EU traffic through it adds geographic hops (Hetzner EU
    # → OpenRouter US → Alibaba → return). Alibaba has EU POPs (Singapore +
    # closer datacenters) so direct DashScope should cut 100-300 ms off the
    # round-trip. Uses the OpenAI-compatible mode endpoint so the request
    # shape stays identical to OpenRouter / Groq calls — no parser changes.
    #
    # We bench TWO model variants:
    # 1. `qwen3.5-flash` — same model snapshot as our current prod
    #    (`qwen/qwen3.5-flash-02-23` on OpenRouter, pinned to 2026-02-23).
    #    Apples-to-apples comparison of "is DashScope-direct faster than
    #    OpenRouter for the SAME model?".
    # 2. `qwen3.6-flash` — the newer (2026-04-17) Flash variant. DashScope
    #    docs claim "significant performance boost over 3.5-Flash". Worth
    #    one bench to see if upgrading the model brings extra latency
    #    OR accuracy gains alongside the provider swap.
    ProviderConfig(
        name="qwen3.5_flash_via_dashscope",
        url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        model="qwen3.5-flash",
        api_key_env="DASHSCOPE_API_KEY",
        input_cost_per_1m=0.05,
        output_cost_per_1m=0.15,
    ),
    ProviderConfig(
        name="qwen3.6_flash_via_dashscope",
        url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        model="qwen3.6-flash",
        api_key_env="DASHSCOPE_API_KEY",
        # Pricing per Alibaba 2026-05 — assumed same as 3.5-flash; validate
        # at benchmark time if recommendation tips on cost.
        input_cost_per_1m=0.05,
        output_cost_per_1m=0.15,
    ),
    ProviderConfig(
        name="groq_llama_3.1_8b",
        url="https://api.groq.com/openai/v1/chat/completions",
        model="llama-3.1-8b-instant",
        api_key_env="GROQ_API_KEY",
        input_cost_per_1m=0.05,
        output_cost_per_1m=0.08,
    ),
    # Story 6.9b — exploration provider added 2026-05-21. The 8B variant
    # was rate-limited but, when given clean run conditions via retry-on-429,
    # came in at 80 % accuracy / 137 ms p50 — Deviation #1 abort (too
    # lenient, -16 pts vs Qwen 96 %). 70B is the next-up Groq model: bigger
    # = stronger on structured-output / instruction-following tasks, still
    # free-tier, slightly higher TTFT (Groq published ~100-200 ms for 70B
    # vs ~50-100 ms for 8B). Worth one bench run before fully closing the
    # provider migration.
    ProviderConfig(
        name="groq_llama_3.3_70b",
        url="https://api.groq.com/openai/v1/chat/completions",
        model="llama-3.3-70b-versatile",
        api_key_env="GROQ_API_KEY",
        # Pricing per Groq publication 2026-05 (validate at benchmark time
        # if the recommendation tips on cost).
        input_cost_per_1m=0.59,
        output_cost_per_1m=0.79,
    ),
    ProviderConfig(
        name="cerebras_llama_3.1_8b",
        url="https://api.cerebras.ai/v1/chat/completions",
        model="llama3.1-8b",
        api_key_env="CEREBRAS_API_KEY",
        input_cost_per_1m=0.10,
        output_cost_per_1m=0.10,
    ),
    ProviderConfig(
        name="anthropic_haiku_4.5",
        url="https://api.anthropic.com/v1/messages",
        model="claude-haiku-4-5-20251001",
        api_key_env="ANTHROPIC_API_KEY",
        input_cost_per_1m=1.00,
        output_cost_per_1m=5.00,
        shape="anthropic",
    ),
)


# ============================================================
# Per-sample result
# ============================================================


@dataclass
class SampleResult:
    sample_id: str
    provider: str
    verdict: bool | None
    ground_truth: bool
    ttft_ms: float | None
    total_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    error: str | None = None

    @property
    def correct(self) -> bool | None:
        if self.verdict is None:
            return None
        return self.verdict == self.ground_truth


# ============================================================
# Per-provider summary
# ============================================================


@dataclass
class ProviderSummary:
    name: str
    samples_total: int
    samples_correct: int
    samples_infra_failure: int  # verdict=None (timeout / HTTP error / parse error)
    accuracy_pct: float
    p50_ttft_ms: float | None
    p95_ttft_ms: float | None
    p50_total_ms: float | None
    p95_total_ms: float | None
    max_total_ms: float | None
    avg_cost_usd_per_classify: float | None
    # Story 6.9b review P19 — surface FP/FN split so the operator can
    # disambiguate "wrong direction" failures. FP = verdict True but
    # ground_truth False (over-permissive — drains patience wrongly).
    # FN = verdict False but ground_truth True (under-permissive — denies
    # advance wrongly). The two have different UX cost — see Principle 5
    # in `prompts.py` (Default to MET) which biases the model toward FP
    # over FN. Defaults to 0.0 so dataclass instantiation in tests
    # without the new kwargs still works.
    false_positive_rate_pct: float = 0.0
    false_negative_rate_pct: float = 0.0
    errors: list[str] = field(default_factory=list)


# ============================================================
# Per-provider request builders
# ============================================================


def _build_request(
    cfg: ProviderConfig,
    *,
    prompt: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return (headers, body) tuple shaped for the provider's API."""
    api_key = os.environ.get(cfg.api_key_env, "")
    if cfg.shape == "anthropic":
        # Anthropic messages API — different auth header name + body shape.
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body = {
            "model": cfg.model,
            "max_tokens": 32,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        return headers, body
    # OpenAI-compatible (OpenRouter, Groq, Cerebras).
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 32,
    }
    # OpenRouter / Qwen: force-disable reasoning so Qwen-Flash doesn't sit
    # in chain-of-thought for 5-15 s per call. Other providers ignore the
    # field silently (it's an OpenRouter extension).
    if "openrouter" in cfg.url:
        body["reasoning"] = {"enabled": False}
    # DashScope (Alibaba) — Qwen3+ models default to "thinking mode" ON
    # which adds 2-10 s of internal chain-of-thought per call (confirmed
    # 2026-05-22 bench: Qwen3.5-flash thinking-ON = 4.4 s p50, Qwen3.6-flash
    # thinking-ON = 2.8 s p50).
    #
    # CRITICAL placement note: `extra_body` is an OpenAI Python SDK
    # convention — the SDK flattens its contents into the request body
    # before sending HTTP. DashScope's raw HTTP API does NOT unwrap
    # `extra_body` (same gotcha as OpenRouter with `reasoning` —
    # `pipeline/emotion_emitter.py` smoke fix). The flag MUST sit at
    # the top level of the JSON body. Verified 2026-05-22 by bench:
    # `extra_body.enable_thinking: false` → still 4.3 s p50 (ignored);
    # top-level `enable_thinking: false` → should drop to sub-second.
    # Without this the model is unusably slow for turn-by-turn classify.
    if "dashscope" in cfg.url:
        body["enable_thinking"] = False
    return headers, body


def _parse_response(
    cfg: ProviderConfig, raw_body: dict[str, Any]
) -> tuple[bool | None, int | None, int | None]:
    """Return (verdict, input_tokens, output_tokens). Mirrors the prod
    classifier's parser tolerance — Markdown fences + first `{...}`
    substring fallback. Verdict is None on any parse failure (treated as
    infra failure in accuracy stats).
    """
    if cfg.shape == "anthropic":
        # Anthropic shape: {"content": [{"type": "text", "text": "..."}], "usage": {...}}
        try:
            content = raw_body["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return None, None, None
        usage = raw_body.get("usage") or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
    else:
        # OpenAI-compatible shape.
        try:
            content = raw_body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None, None, None
        usage = raw_body.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
    verdict = _parse_classifier_output(content)
    return verdict, input_tokens, output_tokens


# ============================================================
# Run one sample through one provider
# ============================================================


# Story 6.9b — bench methodology fix (2026-05-21): respect Retry-After on
# 429 with bounded retries. Groq free tier is 6000 TPM (~17 of our 340-token
# requests per minute); the bench fires 75 sequential calls in ~30 s so the
# free-tier TPM budget is blown in the first ~30 s and every subsequent call
# returns 429 — making "infra failure" stats meaningless. The retry honours
# the Retry-After header (in seconds; if absent, falls back to _BACKOFF_S);
# we cap retries at _MAX_RETRIES so a permanently-degraded provider still
# surfaces as infra_failure in the report instead of looping forever.
_MAX_RETRIES = 3
_BACKOFF_S = 5.0

# Story 6.9b review P7 — cap streamed response body so an adversarial /
# misconfigured provider URL (e.g. accidentally pointing at a static CDN)
# can't OOM the dev machine. Real classifier responses are <2 KiB; 64 KiB
# leaves comfortable headroom for verbose error envelopes.
_MAX_RESPONSE_BYTES = 64 * 1024


async def _run_one(
    client: httpx.AsyncClient,
    cfg: ProviderConfig,
    sample: dict[str, Any],
) -> SampleResult:
    """Run one sample through one provider. Measures TTFT (first byte) and
    total time. Returns SampleResult with either a verdict or an error
    string.

    Story 6.9b methodology fix: bounded retry-on-429 with Retry-After
    honoured. The retry latency is EXCLUDED from `ttft_ms` / `total_ms` —
    we restart the timer post-sleep so the metrics reflect what an
    appropriately-throttled prod caller would see, not the bench's
    artificial burst pattern.
    """
    prompt = EXCHANGE_CLASSIFIER_PROMPT.format(
        scenario_description=sample["scenario_description"],
        last_character_line=sample["last_character_line"],
        user_text=sample["user_text"],
        success_criteria=sample["success_criteria"],
    )
    headers, body = _build_request(cfg, prompt=prompt)
    retries_used = 0
    raw: bytes | None = None
    ttft_ms: float | None = None
    total_ms: float | None = None
    start = time.perf_counter()
    while raw is None:
        start = time.perf_counter()
        ttft_ms = None
        try:
            async with client.stream(
                "POST", cfg.url, headers=headers, json=body
            ) as response:
                # Story 6.9b review P8 — retry on 5xx too (transient Groq
                # incidents / Cloudflare 502/503/504 should not throw out
                # a real winner). Same Retry-After / backoff logic as 429.
                is_retryable = (
                    response.status_code == 429 or 500 <= response.status_code < 600
                )
                if is_retryable and retries_used < _MAX_RETRIES:
                    # Honour Retry-After header (Groq + most providers send
                    # seconds-since-now). Fall back to fixed backoff.
                    retry_after_header = response.headers.get("Retry-After", "")
                    try:
                        wait_s = float(retry_after_header)
                    except (TypeError, ValueError):
                        wait_s = _BACKOFF_S
                    # Drain the body to free the connection back to the pool
                    # before we sleep, otherwise we hold a slot open.
                    await response.aread()
                    print(
                        f"  [retry {retries_used + 1}/{_MAX_RETRIES}] {cfg.name} "
                        f"{sample['id']}: HTTP {response.status_code} → "
                        f"sleeping {wait_s:.1f}s",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(wait_s)
                    retries_used += 1
                    continue
                if response.status_code >= 300:
                    err_body = await response.aread()
                    return SampleResult(
                        sample_id=sample["id"],
                        provider=cfg.name,
                        verdict=None,
                        ground_truth=sample["ground_truth"],
                        ttft_ms=None,
                        total_ms=(time.perf_counter() - start) * 1000,
                        input_tokens=None,
                        output_tokens=None,
                        cost_usd=None,
                        error=f"HTTP {response.status_code}: {err_body[:200]!r}",
                    )
                chunks: list[bytes] = []
                total_bytes = 0
                oversized = False
                async for chunk in response.aiter_bytes():
                    if ttft_ms is None and chunk:
                        ttft_ms = (time.perf_counter() - start) * 1000
                    chunks.append(chunk)
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_RESPONSE_BYTES:
                        # Story 6.9b review P7 — bail out before the
                        # body OOMs the dev machine.
                        oversized = True
                        break
                total_ms = (time.perf_counter() - start) * 1000
                if oversized:
                    return SampleResult(
                        sample_id=sample["id"],
                        provider=cfg.name,
                        verdict=None,
                        ground_truth=sample["ground_truth"],
                        ttft_ms=ttft_ms,
                        total_ms=total_ms,
                        input_tokens=None,
                        output_tokens=None,
                        cost_usd=None,
                        error=(
                            f"response body exceeded {_MAX_RESPONSE_BYTES} bytes"
                            f" (got >{total_bytes} bytes)"
                        ),
                    )
                raw = b"".join(chunks)
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            return SampleResult(
                sample_id=sample["id"],
                provider=cfg.name,
                verdict=None,
                ground_truth=sample["ground_truth"],
                ttft_ms=ttft_ms,
                total_ms=(time.perf_counter() - start) * 1000,
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                error=f"{type(exc).__name__}: {exc}",
            )

    # Success path: parse the response body into a verdict.
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return SampleResult(
            sample_id=sample["id"],
            provider=cfg.name,
            verdict=None,
            ground_truth=sample["ground_truth"],
            ttft_ms=ttft_ms,
            total_ms=total_ms,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            error=f"non-JSON response body: {exc}",
        )
    verdict, in_tok, out_tok = _parse_response(cfg, parsed)
    cost: float | None
    if in_tok is not None and out_tok is not None:
        cost = (
            in_tok * cfg.input_cost_per_1m / 1_000_000
            + out_tok * cfg.output_cost_per_1m / 1_000_000
        )
    else:
        cost = None
    return SampleResult(
        sample_id=sample["id"],
        provider=cfg.name,
        verdict=verdict,
        ground_truth=sample["ground_truth"],
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
    )


# ============================================================
# Per-provider sweep
# ============================================================


async def _run_provider(
    cfg: ProviderConfig,
    corpus: list[dict[str, Any]],
    *,
    timeout_s: float = 10.0,
) -> tuple[ProviderSummary, list[SampleResult]]:
    """Run the full corpus through one provider, return summary + raw
    results. Single shared `httpx.AsyncClient` mirrors the prod
    persistent-client lifecycle (Story 6.9 Deviation #7) — so TTFT/total
    numbers reflect the warm-pool case, NOT the cold-start case that the
    prod classifier paid pre-Story-6.9.
    """
    results: list[SampleResult] = []
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for sample in corpus:
            results.append(await _run_one(client, cfg, sample))

    ttfts = [r.ttft_ms for r in results if r.ttft_ms is not None]
    totals = [r.total_ms for r in results if r.total_ms is not None]
    correct = sum(1 for r in results if r.correct is True)
    infra_fail = sum(1 for r in results if r.verdict is None)
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    errors = [f"{r.sample_id}: {r.error}" for r in results if r.error]

    # Story 6.9b review P19 — FP/FN split. Only count over the samples
    # that actually returned a verdict (infra failures get verdict=None
    # and are neither FP nor FN — they're just noise).
    verdict_returned = [r for r in results if r.verdict is not None]
    false_positives = sum(
        1 for r in verdict_returned if r.verdict is True and r.ground_truth is False
    )
    false_negatives = sum(
        1 for r in verdict_returned if r.verdict is False and r.ground_truth is True
    )
    fp_rate = (
        (false_positives / len(verdict_returned) * 100) if verdict_returned else 0.0
    )
    fn_rate = (
        (false_negatives / len(verdict_returned) * 100) if verdict_returned else 0.0
    )

    summary = ProviderSummary(
        name=cfg.name,
        samples_total=len(results),
        samples_correct=correct,
        samples_infra_failure=infra_fail,
        accuracy_pct=(correct / len(results) * 100) if results else 0.0,
        p50_ttft_ms=_percentile(ttfts, 50),
        p95_ttft_ms=_percentile(ttfts, 95),
        p50_total_ms=_percentile(totals, 50),
        p95_total_ms=_percentile(totals, 95),
        max_total_ms=max(totals) if totals else None,
        avg_cost_usd_per_classify=(sum(costs) / len(costs)) if costs else None,
        false_positive_rate_pct=fp_rate,
        false_negative_rate_pct=fn_rate,
        errors=errors,
    )
    return summary, results


def _percentile(values: list[float], pct: int) -> float | None:
    """Conservative percentile — returns None for empty input. Uses the
    `statistics.quantiles` interpolation for stability across small N.
    """
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    # `quantiles` with n=100 gives the standard 1-100 percentile boundaries.
    qs = statistics.quantiles(values, n=100, method="inclusive")
    # qs has 99 entries (q_1 ... q_99); index pct-1 selects the pct-th.
    return qs[pct - 1]


# ============================================================
# Recommendation
# ============================================================


def _recommend(
    summaries: list[ProviderSummary],
    *,
    baseline_name: str = "qwen_via_openrouter",
) -> dict[str, Any]:
    """Pick a winner that beats the baseline on BOTH p50 total latency AND
    accuracy. Per Deviation #1: if no provider beats Qwen on both, abort —
    Story 6.12 falls back to visual-first feedback (option F).
    """
    by_name = {s.name: s for s in summaries}
    baseline = by_name.get(baseline_name)
    if baseline is None:
        return {
            "verdict": "no_baseline",
            "reason": (
                f"baseline provider {baseline_name!r} missing from summaries; "
                "cannot rank winners without a reference. Ensure "
                f"{baseline_name.upper()}_API_KEY is set."
            ),
        }
    # Story 6.9b review P13 — fail loudly if baseline itself produced no
    # usable percentile (e.g. baseline_p50 is None because ALL baseline
    # samples infra-failed). Otherwise the qualifier filter quietly
    # rejects every candidate (`s.p50_total_ms < None` raises before
    # reaching here, but the `is not None` guard skips them all silently)
    # and the operator wastes time debugging the candidates instead of
    # the baseline.
    if baseline.p50_total_ms is None:
        return {
            "verdict": "baseline_failed",
            "reason": (
                f"baseline {baseline.name!r} returned no successful samples "
                f"(p50_total_ms is None — {baseline.samples_infra_failure}/"
                f"{baseline.samples_total} infra failures). Re-run the "
                "baseline before evaluating candidates."
            ),
            "baseline": baseline.name,
            "baseline_infra_failure": baseline.samples_infra_failure,
            "baseline_samples_total": baseline.samples_total,
        }
    candidates = [s for s in summaries if s.name != baseline_name]
    qualifying = [
        s
        for s in candidates
        if s.p50_total_ms is not None
        and s.p50_total_ms < baseline.p50_total_ms
        and s.accuracy_pct >= baseline.accuracy_pct
    ]
    if not qualifying:
        return {
            "verdict": "abort",
            "reason": (
                "no candidate beats baseline on BOTH latency and accuracy. "
                "Per Story 6.9b Deviation #1, this aborts the provider "
                "migration; Story 6.12 falls back to visual-first feedback "
                "architecture (option F per memory). Inspect per-sample "
                "raw timings + errors to understand which providers came "
                "close — may inform a future re-run with prompt tweaks."
            ),
            "baseline": baseline.name,
            "baseline_p50_ms": baseline.p50_total_ms,
            "baseline_accuracy_pct": baseline.accuracy_pct,
        }
    # Story 6.9b review P12 — pick the fastest qualifier deterministically.
    # Tiebreak chain: faster p50 first, then higher accuracy (negated for
    # ascending sort), then alphabetic name. Removes order-dependence on
    # _PROVIDERS insertion order if two candidates share p50 + accuracy.
    winner = min(
        qualifying,
        key=lambda s: (
            s.p50_total_ms if s.p50_total_ms is not None else float("inf"),
            -s.accuracy_pct,
            s.name,
        ),
    )
    winner_p50 = winner.p50_total_ms if winner.p50_total_ms is not None else 0.0
    return {
        "verdict": "migrate",
        "winner": winner.name,
        "reason": (
            f"{winner.name} beats {baseline.name} on both latency "
            f"({winner_p50:.0f}ms vs {baseline.p50_total_ms:.0f}ms "
            f"p50) and accuracy ({winner.accuracy_pct:.1f}% vs "
            f"{baseline.accuracy_pct:.1f}%). Update Settings.classifier_model "
            "default + Task 3 of Story 6.9b proceeds."
        ),
        "baseline": baseline.name,
        "baseline_p50_ms": baseline.p50_total_ms,
        "baseline_accuracy_pct": baseline.accuracy_pct,
        "winner_p50_ms": winner.p50_total_ms,
        "winner_accuracy_pct": winner.accuracy_pct,
    }


# ============================================================
# Report writer
# ============================================================


def _summary_to_dict(s: ProviderSummary) -> dict[str, Any]:
    return {
        "name": s.name,
        "samples_total": s.samples_total,
        "samples_correct": s.samples_correct,
        "samples_infra_failure": s.samples_infra_failure,
        "accuracy_pct": round(s.accuracy_pct, 2),
        # Story 6.9b review P19 — surfaced separately from `accuracy_pct`.
        "false_positive_rate_pct": round(s.false_positive_rate_pct, 2),
        "false_negative_rate_pct": round(s.false_negative_rate_pct, 2),
        "p50_ttft_ms": _round(s.p50_ttft_ms),
        "p95_ttft_ms": _round(s.p95_ttft_ms),
        "p50_total_ms": _round(s.p50_total_ms),
        "p95_total_ms": _round(s.p95_total_ms),
        "max_total_ms": _round(s.max_total_ms),
        "avg_cost_usd_per_classify": (
            round(s.avg_cost_usd_per_classify, 8)
            if s.avg_cost_usd_per_classify is not None
            else None
        ),
        "errors_count": len(s.errors),
        "errors_sample": s.errors[:5],
    }


def _result_to_dict(r: SampleResult) -> dict[str, Any]:
    return {
        "sample_id": r.sample_id,
        "provider": r.provider,
        "verdict": r.verdict,
        "ground_truth": r.ground_truth,
        "correct": r.correct,
        "ttft_ms": _round(r.ttft_ms),
        "total_ms": _round(r.total_ms),
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cost_usd": (round(r.cost_usd, 8) if r.cost_usd is not None else None),
        "error": r.error,
    }


def _round(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None


def build_report(
    corpus_path: str,
    summaries: list[ProviderSummary],
    per_sample: dict[str, list[SampleResult]],
    skipped_providers: list[str],
) -> dict[str, Any]:
    """Pure function — given the run inputs + per-provider results,
    produce the canonical report dict ready for `json.dump`. Exposed for
    the smoke test in `tests/test_benchmark_classifier.py`.
    """
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus_path,
        # Story 6.9b review P18 — take the max across providers in case
        # a future run truncates one provider (e.g. cost-capped Anthropic
        # ran 10 samples while Groq ran 75). `summaries[0]` would lie.
        "samples_total": max((s.samples_total for s in summaries), default=0),
        "providers_run": [s.name for s in summaries],
        "providers_skipped": skipped_providers,
        "per_provider_summary": [_summary_to_dict(s) for s in summaries],
        "per_sample_raw": [
            _result_to_dict(r)
            for provider_results in per_sample.values()
            for r in provider_results
        ],
        "recommendation": _recommend(summaries),
    }


# ============================================================
# Main
# ============================================================


async def run_benchmark(
    corpus_path: str,
    *,
    provider_names: list[str] | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """Run the benchmark and return the report dict. Pulled out of `main()`
    so the test suite can drive the harness against a mocked corpus +
    `httpx.MockTransport` without re-invoking argparse.
    """
    corpus = json.loads(pathlib.Path(corpus_path).read_text(encoding="utf-8"))
    targets = (
        [p for p in _PROVIDERS if p.name in provider_names]
        if provider_names is not None
        else list(_PROVIDERS)
    )
    summaries: list[ProviderSummary] = []
    per_sample: dict[str, list[SampleResult]] = {}
    skipped: list[str] = []
    for cfg in targets:
        # Story 6.9b review P6 — treat empty / whitespace-only as unset
        # so an operator who exports `GROQ_API_KEY=` to "blank" their
        # shell still gets the skip message (instead of going on to
        # invoke the provider with an empty bearer token and a confusing
        # 401).
        if not os.environ.get(cfg.api_key_env, "").strip():
            print(
                f"[skip] {cfg.name}: env var {cfg.api_key_env} not set",
                file=sys.stderr,
            )
            skipped.append(cfg.name)
            continue
        print(f"[run] {cfg.name} against {len(corpus)} samples...", file=sys.stderr)
        summary, results = await _run_provider(cfg, corpus, timeout_s=timeout_s)
        summaries.append(summary)
        per_sample[cfg.name] = results
        print(
            f"  → accuracy {summary.accuracy_pct:.1f}% / "
            f"p50 {summary.p50_total_ms}ms / p95 {summary.p95_total_ms}ms / "
            f"infra-fail {summary.samples_infra_failure}",
            file=sys.stderr,
        )
    return build_report(corpus_path, summaries, per_sample, skipped)


def main() -> None:
    # Story 6.9b review P4 — load_dotenv at main-time only (NOT at module
    # import) so tests stay hermetic. Pulls keys from `server/.env`.
    load_dotenv(dotenv_path=_HERE.parent / ".env")
    parser = argparse.ArgumentParser(
        description="Story 6.9b classifier provider benchmark harness"
    )
    parser.add_argument(
        "--corpus",
        required=True,
        help="path to labeled corpus JSON (see tests/fixtures/classifier_benchmark_corpus.json)",
    )
    parser.add_argument(
        "--providers",
        default="all",
        help=(
            "comma-separated provider names, or 'all'. "
            f"Choices: {', '.join(p.name for p in _PROVIDERS)}"
        ),
    )
    parser.add_argument(
        "--output",
        default="_bmad-output/implementation-artifacts/calibration-tests/",
        help="output directory for the timestamped report JSON",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="per-request timeout in seconds (default 10 — wider than the prod 2s ceiling)",
    )
    args = parser.parse_args()

    provider_names: list[str] | None
    if args.providers.strip().lower() == "all":
        provider_names = None
    else:
        provider_names = [p.strip() for p in args.providers.split(",") if p.strip()]

    report = asyncio.run(
        run_benchmark(
            args.corpus,
            provider_names=provider_names,
            timeout_s=args.timeout,
        )
    )
    out_dir = pathlib.Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_path = out_dir / f"classifier_benchmark_{ts}.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[done] report written to {out_path}")
    print(f"[recommendation] {report['recommendation'].get('verdict')}")
    if report["recommendation"].get("reason"):
        print(f"  {report['recommendation']['reason']}")


if __name__ == "__main__":
    main()
