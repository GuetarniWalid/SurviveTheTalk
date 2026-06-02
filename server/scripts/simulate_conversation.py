"""Story 6.15 — `simulate_conversation`: drive ONE text conversation, print it.

A debugging companion to `calibrate_scenario.py` for eyeballing how a scenario
plays with a given learner strategy — no audio, no device. Reuses the SAME prod
code paths (judge / advance / patience / character LLM) via `calibration_engine`.

    cd server
    python scripts/simulate_conversation.py waiter_easy_01 --strategy hesitant

Strategies: cooperative | hesitant | off_topic | minimal (AC3). Gated behind
GROQ_API_KEY (live LLM); never imported by prod.
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


async def _amain(args: argparse.Namespace) -> int:
    try:
        settings = engine.load_llm_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"[config error] {exc}", file=sys.stderr)
        return 2

    chat_llm, judge = engine.build_live_clients(settings)
    judge = engine.ResilientJudge(judge)  # throttle + retry (avoid 429 storms)
    chat_llm = engine.ResilientChat(chat_llm)
    try:
        result = await engine.simulate_conversation(
            scenario_id=args.scenario_id,
            strategy=args.strategy,
            character_llm=chat_llm,
            learner_llm=chat_llm,
            judge=judge,
            max_turns=args.max_turns,
        )
    finally:
        await chat_llm.aclose()
        await judge.close()

    print(f"\n=== {args.scenario_id} / {args.strategy} ===")
    for i, turn in enumerate(result.turns, 1):
        print(f"\n[turn {i}] patience={turn.patience} met={turn.goals_met}")
        print(f"  character: {turn.character_reply}")
        print(f"  user:      {turn.user_text}")
        print(f"  verdicts:  {turn.verdicts}")
    print(
        f"\noutcome={result.outcome} "
        f"goals={result.goals_met_count}/{result.total_goals} "
        f"final_patience={result.final_patience}"
    )
    return 0


def main() -> None:
    engine.force_utf8_stdio()
    load_dotenv(dotenv_path=_HERE.parent / ".env")
    parser = argparse.ArgumentParser(
        description="Story 6.15 — simulate one text conversation for a scenario."
    )
    parser.add_argument("scenario_id", help="scenario id (e.g. waiter_easy_01)")
    parser.add_argument(
        "--strategy",
        default="cooperative",
        choices=list(engine._LEARNER_STRATEGIES),
        help="learner strategy (default cooperative)",
    )
    parser.add_argument("--max-turns", type=int, default=12)
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
