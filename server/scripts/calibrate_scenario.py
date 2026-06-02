"""Story 6.15 — `calibrate_scenario`: the one command to validate a scenario.

This is the operator entry-point Walid runs at scenario creation (AC5). It is a
thin CLI over `scripts/calibration_engine.py`; all the logic + tests live there.

    cd server
    # validate one scenario (golden net + calibration):
    python scripts/calibrate_scenario.py waiter_easy_01
    # smart sweep — validate every scenario that's new / changed / rules-changed:
    python scripts/calibrate_scenario.py
    # fast regression-only sweep (no live conversations — "did my prompt break
    # any scenario?", the check that was missing on 2026-05-30):
    python scripts/calibrate_scenario.py --golden-only
    # force a full re-validation regardless of the ledger:
    python scripts/calibrate_scenario.py waiter_easy_01 --force
    # auto-generate the per-checkpoint golden fixture to review:
    python scripts/calibrate_scenario.py waiter_easy_01 --generate-golden

Exit code: **0** iff every evaluated (or ledger-cached) scenario PASSed; **non-zero**
otherwise — so an agent / CI step can branch on it (AC9). Live-LLM runs are gated
behind `GROQ_API_KEY`; this script is never imported by prod (AC6 — dev tooling).

Rough cost (AC6): a full `calibrate_scenario <id>` is ~N×2 conversations × ~K turns
× (character + learner + classifier) Groq calls (≈ a few US cents at N=10).
`--golden-only` is ~one classify per case (cents-fraction). Budget accordingly.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from dotenv import load_dotenv  # noqa: E402

import scripts.calibration_engine as engine  # noqa: E402

_RATE_LIMIT_MSG = (
    "\n[rate limit] Groq returned a rate/token limit that retries can't clear — "
    "most likely the FREE-tier daily token cap (100k tokens/day on the character "
    "model). Throttling fixes the per-MINUTE cap, but NOT the per-DAY cap.\n"
    "  • The cheap `--golden-only` check (off-topic regression net) DOES work on "
    "the free tier — use that.\n"
    "  • The full calibration (difficulty band) needs the Groq Dev tier "
    "(https://console.groq.com/settings/billing) or to wait for the daily reset.\n"
)


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "rate limit" in msg
        or "tokens per" in msg
        or "rate_limit_exceeded" in msg
        or type(exc).__name__ == "RateLimitError"
    )


async def _validate_one(
    scenario_id: str,
    *,
    chat_llm,
    judge,
    n: int,
    max_turns: int,
    golden_only: bool,
) -> engine.ScenarioVerdict:
    data = engine.load_scenario_data(scenario_id)
    scenario_hash = engine.compute_scenario_hash(scenario_id)
    golden = await engine.run_golden(scenario_id=scenario_id, judge=judge, data=data)
    if golden_only:
        # Golden-only mode: the verdict rides on the golden net alone.
        return engine.ScenarioVerdict(
            scenario_id=scenario_id,
            passed=golden.passed,
            golden=golden,
            calibration=None,
            scenario_hash=scenario_hash,
            reason="golden-only",
        )
    calibration = await engine.run_calibration(
        scenario_id=scenario_id,
        character_llm=chat_llm,
        learner_llm=chat_llm,
        judge=judge,
        n=n,
        data=data,
        max_turns=max_turns,
    )
    return engine.combine_verdict(
        scenario_id=scenario_id,
        scenario_hash=scenario_hash,
        golden=golden,
        calibration=calibration,
    )


def _print_verdict_line(verdict: engine.ScenarioVerdict) -> None:
    badge = {"PASS": "✅", "FAIL": "❌", "CACHED PASS": "⏭️ "}.get(verdict.status, "")
    extra = ""
    if verdict.calibration is not None:
        c = verdict.calibration
        extra = (
            f"  coop={c.cooperative_rate:.0f}% band={c.band[0]}-{c.band[1]}% "
            f"({c.band_verdict}) off_topic={c.offtopic_rate:.0f}%"
        )
    if verdict.golden is not None and not verdict.golden.passed:
        g = verdict.golden
        extra += (
            f"  golden: {len(g.negative_failures)} off-topic-accepted, "
            f"{len(g.positive_misses)} genuine-rejected"
        )
    print(f"{badge} {verdict.status:<11} {verdict.scenario_id}{extra}")


async def _run_generate(scenario_ids: list[str], *, chat_llm) -> int:
    for sid in scenario_ids:
        fixture = await engine.generate_golden_fixture(
            scenario_id=sid, generator_llm=chat_llm
        )
        path = engine.write_golden_fixture(fixture)
        print(f"\n📝 Generated golden fixture → {path} (reviewed: false)")
        print(
            "Review the cases below, fix any mislabeled ones, then set "
            '`"reviewed": true` in the file to make them gating:\n'
        )
        for case in fixture["cases"]:
            mark = "＋" if case["kind"] == "positive" else "－"
            print(
                f"  {mark} [{case['checkpoint_id']}] (expect "
                f"{'met' if case['kind'] == 'positive' else 'unmet'}) "
                f"{case['user_text']!r}"
            )
    return 0


async def _amain(args: argparse.Namespace) -> int:
    try:
        settings = engine.load_llm_settings()
    except Exception as exc:  # noqa: BLE001 — surface config errors clearly
        print(f"[config error] {exc}", file=sys.stderr)
        return 2

    # Resolve the scenario list (AC13).
    if args.scenario_id:
        scenario_ids = [args.scenario_id]
    elif args.scenarios:
        scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    else:
        scenario_ids = engine.list_scenarios()

    chat_llm, judge = engine.build_live_clients(settings)
    # Throttle + retry so a batch of calls doesn't trip Groq's requests-per-minute
    # cap (the 429 storm). Judge (Scout) and chat (70B character+learner) are
    # separate rate buckets, so wrap BOTH. Dev-tool only.
    throttle_s = args.throttle_ms / 1000.0
    judge = engine.ResilientJudge(
        judge, min_interval_s=throttle_s, max_retries=args.retries
    )
    chat_llm = engine.ResilientChat(
        chat_llm, min_interval_s=throttle_s, max_retries=args.retries
    )
    try:
        if args.generate_golden:
            return await _run_generate(scenario_ids, chat_llm=chat_llm)

        ledger = engine.load_ledger()
        verdicts: list[engine.ScenarioVerdict] = []
        is_sweep = not args.scenario_id and not args.scenarios

        for sid in scenario_ids:
            scenario_hash = engine.compute_scenario_hash(sid)
            # Smart sweep skip (AC10): only on a no-id sweep, never with --force.
            if (
                is_sweep
                and not args.force
                and engine.is_cached_pass(ledger, sid, scenario_hash)
            ):
                verdict = engine.ScenarioVerdict(
                    scenario_id=sid,
                    passed=True,
                    golden=None,
                    calibration=None,
                    scenario_hash=scenario_hash,
                    skipped=True,
                    reason="unchanged since last PASS",
                )
                verdicts.append(verdict)
                _print_verdict_line(verdict)
                continue

            print(f"\n🔎 Validating {sid} ...", file=sys.stderr)
            try:
                verdict = await _validate_one(
                    sid,
                    chat_llm=chat_llm,
                    judge=judge,
                    n=args.n,
                    max_turns=args.max_turns,
                    golden_only=args.golden_only,
                )
            except Exception as exc:  # noqa: BLE001
                if _is_rate_limit(exc):
                    print(_RATE_LIMIT_MSG, file=sys.stderr)
                    return 3
                raise
            report_path = engine.write_report(verdict)
            # Don't poison the ledger with a partial (golden-only) PASS — a full
            # validation must run before a scenario counts as cached-PASS.
            if not args.no_ledger and not args.golden_only:
                ledger = engine.record_verdict(verdict, report_path=str(report_path))
                engine.save_ledger(ledger)
            verdicts.append(verdict)
            _print_verdict_line(verdict)
            if not verdict.passed:
                md = engine.format_failure_report(verdict, report_path=str(report_path))
                md_path = report_path.with_suffix(".md")
                md_path.write_text(md, encoding="utf-8")
                print("\n" + md)
                print(f"\n(Saved this diagnostic to {md_path})")
    finally:
        await chat_llm.aclose()
        await judge.close()

    # Tally + exit code (AC9 / AC13).
    passed = sum(1 for v in verdicts if v.passed)
    failed = [v for v in verdicts if not v.passed]
    print(
        f"\n=== {passed}/{len(verdicts)} passed "
        f"({sum(1 for v in verdicts if v.skipped)} cached) ==="
    )
    if failed:
        print("FAILED: " + ", ".join(v.scenario_id for v in failed))
    return 0 if not failed else 1


def main() -> None:
    engine.force_utf8_stdio()
    load_dotenv(dotenv_path=_HERE.parent / ".env")
    parser = argparse.ArgumentParser(
        description="Story 6.15 — validate a scenario's conversation logic (text-driven)."
    )
    parser.add_argument(
        "scenario_id",
        nargs="?",
        help="scenario id to validate (omit to sweep every scenario)",
    )
    parser.add_argument(
        "--scenarios",
        default="",
        help="comma-separated scenario ids (alternative to a single positional id)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="revalidate even if the ledger says it's unchanged + already PASS",
    )
    parser.add_argument(
        "--golden-only",
        action="store_true",
        help="run ONLY the cheap deterministic golden net (no live conversations)",
    )
    parser.add_argument(
        "--generate-golden",
        action="store_true",
        help="LLM-generate the per-checkpoint golden fixture (reviewed:false) to review",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=engine.DEFAULT_CALIBRATION_N,
        help=f"conversations per strategy for calibration (default {engine.DEFAULT_CALIBRATION_N})",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=12,
        help="max character/user rounds per simulated conversation (default 12)",
    )
    parser.add_argument(
        "--no-ledger",
        action="store_true",
        help="do not read/update the validation ledger (one-off run)",
    )
    parser.add_argument(
        "--throttle-ms",
        type=int,
        default=2100,
        help="min gap between classifier calls in ms. Default 2100 is safe for "
        "Groq's FREE tier (30 req/min); on a paid Groq tier use e.g. 200 to run "
        "much faster.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=4,
        help="retries when a classifier call fails (e.g. transient 429) (default 4)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
