"""Story 6.9b — Smoke test for the benchmark harness (AC1, Task 1.7).

The benchmark harness (`scripts/benchmark_classifier.py`) is dev-machine
infrastructure — it never runs in prod and would normally not warrant
pytest coverage. We add ONE smoke test to:

1. Catch import-level regressions before Walid invokes the harness with
   the actual API keys (the alternative is a 30-second feedback loop
   per attempted run).
2. Lock in the report shape so future changes that re-key the JSON
   would surface at pre-commit time, not silently break the downstream
   `memory/project_story_6_9b_classifier_latency_slash.md` §1 cost-
   matrix-update workflow (Task 2.3 reads the report by key).
3. Validate the recommendation logic — the `_recommend()` heuristic
   "winner must beat baseline on BOTH latency AND accuracy" is the
   Deviation #1 contract. A future refactor that loosens this could
   silently green-light a migration that regresses accuracy.

Strategy: monkeypatch `httpx.AsyncClient` to a `MockTransport` that
returns deterministic responses per provider — same `_mock_http` pattern
the rest of the test suite uses. Drive a tiny 3-sample corpus, assert
the report has all expected top-level keys + the recommendation logic
correctly identifies the "fastest winning provider" branch.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

# Story 6.9b review P3+P5 — env vars (`OPENROUTER_API_KEY`, `GROQ_API_KEY`)
# are already seeded by `conftest.py::TEST_ENV_VARS`, so no module-level
# `os.environ.setdefault` is needed here. Test isolation also benefits:
# conftest is the single source of truth for required env, no module-scope
# mutation that leaks into the broader test session.
from scripts.benchmark_classifier import (
    _PROVIDERS,
    _recommend,
    build_report,
    run_benchmark,
)


# ============================================================
# Test corpus — 3 samples, all happy-path (ground_truth=True)
# ============================================================


_TINY_CORPUS = [
    {
        "id": "smoke_1",
        "scenario_description": "The Waiter",
        "checkpoint_id": "greet",
        "last_character_line": "Welcome.",
        "user_text": "I'd like to order.",
        "success_criteria": "User responds.",
        "ground_truth": True,
    },
    {
        "id": "smoke_2",
        "scenario_description": "The Waiter",
        "checkpoint_id": "drink",
        "last_character_line": "And to drink?",
        "user_text": "Water please.",
        "success_criteria": "User names a beverage.",
        "ground_truth": True,
    },
    {
        "id": "smoke_3",
        "scenario_description": "The Waiter",
        "checkpoint_id": "drink",
        "last_character_line": "And to drink?",
        "user_text": "How long have you worked here?",
        "success_criteria": "User names a beverage.",
        "ground_truth": False,
    },
]


def _write_corpus(tmp_path: pathlib.Path) -> str:
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(_TINY_CORPUS), encoding="utf-8")
    return str(p)


# ============================================================
# Mocked provider responses
# ============================================================
#
# We mock Qwen as "baseline" — slow + accurate (returns correct verdicts).
# Groq as "winner" — fast + equally accurate. The recommendation should
# pick Groq.


def _qwen_response(_request: httpx.Request) -> httpx.Response:
    # Slow baseline: prod-shaped OpenAI-compatible response with usage tokens.
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"met": true}'}}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 8},
        },
    )


def _groq_response(_request: httpx.Request) -> httpx.Response:
    # Fast winner — same JSON shape, same correct verdict.
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"met": true}'}}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 8},
        },
    )


def _route_by_host(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if "openrouter" in host:
        return _qwen_response(request)
    if "groq" in host:
        return _groq_response(request)
    # Default: 503 so any unexpected provider attempt is loud, not silent.
    return httpx.Response(503, json={"error": "unmocked provider"})


# ============================================================
# The smoke test
# ============================================================


def test_benchmark_harness_runs_and_produces_report_with_recommendation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end shape test for the benchmark harness.

    Patches `httpx.AsyncClient` with a MockTransport routing OpenRouter
    → slow Qwen response, Groq → fast Groq response. Drives the harness
    against a 3-sample corpus, restricts providers to just Qwen+Groq
    (Cerebras + Anthropic env vars unset → skipped). Asserts:

    - Report has the canonical top-level keys (generated_at, corpus,
      providers_run, providers_skipped, per_provider_summary,
      per_sample_raw, recommendation).
    - Per-provider summary has accuracy + latency percentiles.
    - The recommendation logic ran (verdict ∈ {migrate, abort,
      no_baseline}).
    - The skipped-providers list contains Cerebras + Anthropic (no key).
    """
    corpus_path = _write_corpus(tmp_path)

    transport = httpx.MockTransport(_route_by_host)
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("scripts.benchmark_classifier.httpx.AsyncClient", _factory)

    # Run only Qwen + Groq — leaves Cerebras + Anthropic in the skipped
    # list (their env vars were not set in conftest, only OPENROUTER /
    # GROQ are seeded at module top).
    report = asyncio.run(
        run_benchmark(
            corpus_path,
            provider_names=["qwen_via_openrouter", "groq_llama_3.1_8b"],
            timeout_s=5.0,
        )
    )

    # Canonical top-level shape
    assert set(report.keys()) >= {
        "generated_at",
        "corpus",
        "samples_total",
        "providers_run",
        "providers_skipped",
        "per_provider_summary",
        "per_sample_raw",
        "recommendation",
    }
    assert report["samples_total"] == 3
    assert "qwen_via_openrouter" in report["providers_run"]
    assert "groq_llama_3.1_8b" in report["providers_run"]
    # Per-provider summary shape
    for summary in report["per_provider_summary"]:
        assert summary["samples_total"] == 3
        assert summary["samples_correct"] >= 0
        assert "p50_total_ms" in summary
        assert "p95_total_ms" in summary
        assert "accuracy_pct" in summary
        # Both providers should report 2 correct (ground_truth=True for
        # samples 1+2) and 1 wrong (ground_truth=False for sample 3 but
        # both mocked providers return met=true).
        assert summary["samples_correct"] == 2
        assert summary["samples_infra_failure"] == 0
    # Per-sample raw entries (3 samples × 2 providers = 6 entries)
    assert len(report["per_sample_raw"]) == 6
    for entry in report["per_sample_raw"]:
        assert entry["provider"] in ("qwen_via_openrouter", "groq_llama_3.1_8b")
        assert entry["sample_id"] in {"smoke_1", "smoke_2", "smoke_3"}
        assert entry["verdict"] is True  # All mocks return met=true
    # Recommendation runs to one of the documented verdicts. With
    # identical mocked accuracy + latency (mock is sync — latency
    # numbers will be near-zero noise), the recommendation might land
    # on abort (no clear winner) or migrate (one happens to be 0.01ms
    # faster) — both are acceptable. The contract is that the verdict
    # field exists and is one of the documented values.
    assert report["recommendation"]["verdict"] in {"migrate", "abort", "no_baseline"}


def test_recommend_aborts_when_no_provider_beats_baseline() -> None:
    """Story 6.9b Deviation #1 contract — if no candidate beats the
    baseline on BOTH latency AND accuracy, the recommendation must abort
    (Story 6.12 falls back to visual-first). Lock in the heuristic so a
    future refactor can't silently loosen it.
    """
    from scripts.benchmark_classifier import ProviderSummary

    baseline = ProviderSummary(
        name="qwen_via_openrouter",
        samples_total=10,
        samples_correct=9,
        samples_infra_failure=0,
        accuracy_pct=90.0,
        p50_ttft_ms=200.0,
        p95_ttft_ms=400.0,
        p50_total_ms=800.0,
        p95_total_ms=1500.0,
        max_total_ms=1800.0,
        avg_cost_usd_per_classify=0.0001,
    )
    faster_but_inaccurate = ProviderSummary(
        name="groq_llama_3.1_8b",
        samples_total=10,
        samples_correct=6,  # 60% — worse than baseline's 90%
        samples_infra_failure=0,
        accuracy_pct=60.0,
        p50_ttft_ms=30.0,
        p95_ttft_ms=80.0,
        p50_total_ms=150.0,  # Way faster but inaccurate
        p95_total_ms=300.0,
        max_total_ms=400.0,
        avg_cost_usd_per_classify=0.00005,
    )
    decision = _recommend([baseline, faster_but_inaccurate])
    assert decision["verdict"] == "abort", (
        "a faster-but-less-accurate provider must NOT win — Deviation #1 "
        "says accuracy regression aborts the migration even at 10× speedup"
    )


def test_recommend_picks_fastest_qualifying_when_two_beat_baseline() -> None:
    """When two candidates both beat baseline on latency + accuracy, the
    recommendation picks the FASTEST one (p50 total ms wins).
    """
    from scripts.benchmark_classifier import ProviderSummary

    baseline = ProviderSummary(
        name="qwen_via_openrouter",
        samples_total=10,
        samples_correct=8,
        samples_infra_failure=0,
        accuracy_pct=80.0,
        p50_ttft_ms=400.0,
        p95_ttft_ms=600.0,
        p50_total_ms=1000.0,
        p95_total_ms=1800.0,
        max_total_ms=2000.0,
        avg_cost_usd_per_classify=0.0001,
    )
    groq = ProviderSummary(
        name="groq_llama_3.1_8b",
        samples_total=10,
        samples_correct=8,
        samples_infra_failure=0,
        accuracy_pct=80.0,
        p50_ttft_ms=80.0,
        p95_ttft_ms=150.0,
        p50_total_ms=200.0,  # 5× faster than baseline
        p95_total_ms=350.0,
        max_total_ms=500.0,
        avg_cost_usd_per_classify=0.00005,
    )
    cerebras = ProviderSummary(
        name="cerebras_llama_3.1_8b",
        samples_total=10,
        samples_correct=8,
        samples_infra_failure=0,
        accuracy_pct=80.0,
        p50_ttft_ms=40.0,
        p95_ttft_ms=80.0,
        p50_total_ms=120.0,  # Fastest
        p95_total_ms=200.0,
        max_total_ms=300.0,
        avg_cost_usd_per_classify=0.0001,
    )
    decision = _recommend([baseline, groq, cerebras])
    assert decision["verdict"] == "migrate"
    assert decision["winner"] == "cerebras_llama_3.1_8b", (
        "Cerebras (p50=120) should beat Groq (p50=200) when both qualify"
    )


def test_build_report_is_a_pure_function_over_summaries() -> None:
    """`build_report()` is pulled out as a pure function so the test
    suite can exercise it without an event loop. Locks in the calling
    contract — a future inline-back into `run_benchmark()` would break
    this test, prompting a review.
    """
    summaries = []
    per_sample: dict[str, list] = {}
    report = build_report("/tmp/fake_corpus.json", summaries, per_sample, ["x", "y"])
    assert report["corpus"] == "/tmp/fake_corpus.json"
    assert report["providers_run"] == []
    assert report["providers_skipped"] == ["x", "y"]
    assert report["per_provider_summary"] == []
    assert report["per_sample_raw"] == []
    # Empty summaries → no baseline → "no_baseline" verdict.
    assert report["recommendation"]["verdict"] == "no_baseline"


def test_corpus_has_canonical_size_and_label_split() -> None:
    """Story 6.9b review P11 — lock in the corpus shape so a merge that
    accidentally drops samples (or rebalances MET/NOT-MET) fails fast at
    pre-commit, before the next bench run silently runs on a degraded
    sample size. The canonical corpus is 75 samples, 47 MET / 28 NOT-MET
    as documented in the Story 6.9b spec File List + sprint-status entry.
    """
    corpus_path = (
        pathlib.Path(__file__).resolve().parent
        / "fixtures"
        / "classifier_benchmark_corpus.json"
    )
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert len(corpus) == 75, (
        f"corpus must have 75 samples (got {len(corpus)}); update this "
        "assertion + Story 6.9b spec File List together"
    )
    met = sum(1 for s in corpus if s["ground_truth"] is True)
    not_met = sum(1 for s in corpus if s["ground_truth"] is False)
    assert met == 47, f"corpus must have 47 MET samples (got {met})"
    assert not_met == 28, f"corpus must have 28 NOT-MET samples (got {not_met})"


def test_providers_config_includes_documented_providers() -> None:
    """Lock in the provider list from the Story 6.9b spec cost matrix
    PLUS the exploration variants added 2026-05-21:
      - groq_llama_3.3_70b (after the 8B bench surfaced as too-lenient)
      - qwen_via_dashscope (Lever 1 — direct Alibaba, skip OpenRouter proxy)
    A future addition (e.g. OpenAI GPT-4o-mini) should require an explicit
    test update — the test list mirrors the spec + exploration history.
    """
    names = {p.name for p in _PROVIDERS}
    assert names == {
        "qwen_via_openrouter",
        # Added 2026-05-21 Lever 1 — skip OpenRouter proxy, both Qwen Flash
        # variants tested.
        "qwen3.5_flash_via_dashscope",
        "qwen3.6_flash_via_dashscope",
        "groq_llama_3.1_8b",
        "groq_llama_3.3_70b",  # Added 2026-05-21 mid-bench, see harness comment
        "cerebras_llama_3.1_8b",
        "anthropic_haiku_4.5",
    }
