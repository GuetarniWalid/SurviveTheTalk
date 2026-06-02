"""Story 6.16 — `build_scenario`: fuzzy premise → complete scenario YAML.

    cd server
    .venv\\Scripts\\python scripts/build_scenario.py \\
        --id cop_interrogation_01 --character cop --difficulty hard --checkpoints 20 \\
        --description "A cop calls because your fingerprints were at a crime scene; you must
        justify why. He probes your gang ties and where you were at 8:30pm last night; he is
        suspicious you're lying. You succeed if he finds no flaw in your story."

Writes `server/pipeline/scenarios/<id>.yaml`. `--dry-run` prints instead of writing.
`--validate` runs the Story 6.15 golden net on the fresh scenario (cheap sanity check —
the universal off-topic seed); run `calibrate_scenario.py <id>` for the full calibration.

Live generation needs `GROQ_API_KEY` (drives the Groq character LLM); never imported by prod.
On Windows use the `.cmd` wrapper (`scripts\\build.cmd ...`) to avoid the Python Store stub.
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
import scripts.scenario_builder as builder  # noqa: E402

# VPS deploy target (Story 6.17 `--deploy`). Scp the YAML into the live release's
# scenarios dir + restart pipecat → the startup seeder re-seeds → the scenario
# appears in the app's list (the app talks to this VPS). See memory/MEMORY.md
# Infrastructure. The YAML also lives in the repo, so a later real deploy keeps it.
_VPS_HOST = "root@167.235.63.129"
_VPS_SCENARIOS_DIR = "/opt/survive-the-talk/current/server/pipeline/scenarios"


def _deploy_to_vps(local_path: pathlib.Path) -> bool:
    import subprocess

    remote = f"{_VPS_HOST}:{_VPS_SCENARIOS_DIR}/{local_path.name}"
    scp = subprocess.run(
        ["scp", "-o", "StrictHostKeyChecking=no", str(local_path), remote],
        capture_output=True,
        text=True,
    )
    if scp.returncode != 0:
        print(f"   scp failed: {scp.stderr.strip() or scp.stdout.strip()}")
        return False
    restart = subprocess.run(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            _VPS_HOST,
            "systemctl restart pipecat.service",
        ],
        capture_output=True,
        text=True,
    )
    if restart.returncode != 0:
        print(f"   restart failed: {restart.stderr.strip() or restart.stdout.strip()}")
        return False
    return True


async def _amain(args: argparse.Namespace) -> int:
    try:
        settings = engine.load_llm_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"[config error] {exc}", file=sys.stderr)
        return 2

    from pipeline import scenarios

    if args.id in scenarios._SCENARIO_INDEX and not args.overwrite and not args.dry_run:
        print(
            f"[refuse] scenario id {args.id!r} already exists "
            f"({scenarios._SCENARIO_INDEX[args.id].name}). Use --overwrite or a new --id.",
            file=sys.stderr,
        )
        return 2

    chat_llm, judge = engine.build_live_clients(settings)
    # throttle + retry (avoid 429 storms on the free Groq tier)
    judge = engine.ResilientJudge(judge)
    chat_llm = engine.ResilientChat(chat_llm)
    try:
        print(
            f"🛠️  Building {args.id} ({args.character}/{args.difficulty}, "
            f"{args.checkpoints} checkpoints)...",
            file=sys.stderr,
        )
        result = await builder.build_scenario(
            args.description,
            scenario_id=args.id,
            title=args.title,
            difficulty=args.difficulty,
            rive_character=args.character,
            n_checkpoints=args.checkpoints,
            target_minutes=args.minutes,
            critique_rounds=args.critique_rounds,
            cartesia_api_key=(settings.cartesia_api_key or None),
            llm=chat_llm,
        )

        if result.structural_problems:
            print("\n❌ Structural problems — NOT written:")
            for p in result.structural_problems:
                print(f"    - {p}")
            return 1

        print("\n" + builder.format_build_summary(result))
        if result.overlap_pairs:
            print(
                "\n  ⚠️  Lexically-similar success_criteria (possible overlap — review):"
            )
            for a, b, jac in result.overlap_pairs:
                print(f"      {a} ~ {b}  (jaccard {jac})")

        if args.dry_run:
            print("\n--- scenario YAML (dry run, not written) ---\n")
            print(result.yaml_text)
            return 0

        out_path = (
            pathlib.Path(args.out)
            if args.out
            else builder.default_scenario_path(args.id)
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.yaml_text, encoding="utf-8")
        print(f"\n✅ Wrote {out_path}")

        if args.validate:
            # Refresh the index so the just-written scenario is addressable, then
            # run the cheap golden sanity check (universal off-topic seed).
            scenarios._SCENARIO_INDEX = scenarios._build_scenario_index()
            print(
                "\n🔎 Golden sanity check (off-topic must be unmet on every checkpoint)..."
            )
            golden = await engine.run_golden(scenario_id=args.id, judge=judge)
            print(
                f"   golden: {'PASS' if golden.passed else 'FAIL'} — "
                f"{len(golden.negative_failures)} off-topic accepted, "
                f"{golden.negative_total} seed cases"
            )
            print(
                f"   Next: .venv\\Scripts\\python scripts/calibrate_scenario.py {args.id} "
                f"(full calibration — needs the difficulty band check)."
            )

        if args.deploy:
            print(
                "\n🚀 Deploying to the VPS (scp + restart pipecat → re-seed → "
                "appears in the app)..."
            )
            if _deploy_to_vps(out_path):
                print(
                    "   ✅ deployed — it should now be in your app's scenario list "
                    "(test it before the review)."
                )
            else:
                print(
                    "   ❌ deploy failed (see above). The YAML is written locally; "
                    "you can scp it manually or retry --deploy."
                )
                return 1
    finally:
        await chat_llm.aclose()
        await judge.close()
    return 0


def main() -> None:
    engine.force_utf8_stdio()
    load_dotenv(dotenv_path=_HERE.parent / ".env")
    parser = argparse.ArgumentParser(
        description="Story 6.16 — build a complete scenario from a fuzzy description."
    )
    parser.add_argument(
        "--description", "-d", required=True, help="the (fuzzy) scenario premise"
    )
    parser.add_argument("--id", required=True, help="scenario id (snake_case, unique)")
    parser.add_argument(
        "--character",
        required=True,
        choices=list(builder.RIVE_CHARACTERS),
        help="Rive puppet (must be an existing one)",
    )
    parser.add_argument(
        "--difficulty", default="hard", choices=["easy", "medium", "hard"]
    )
    parser.add_argument(
        "--title", default="", help="scenario title (else the AI picks one)"
    )
    parser.add_argument(
        "--checkpoints",
        type=int,
        default=builder.DEFAULT_CHECKPOINTS,
        help=f"number of checkpoints (default {builder.DEFAULT_CHECKPOINTS})",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=builder.DEFAULT_TARGET_MINUTES,
        help=f"target conversation minutes (default {builder.DEFAULT_TARGET_MINUTES})",
    )
    parser.add_argument(
        "--critique-rounds",
        type=int,
        default=1,
        help="adversarial de-overlap/time-advance passes (default 1)",
    )
    parser.add_argument("--out", default="", help="output path (default scenarios dir)")
    parser.add_argument("--dry-run", action="store_true", help="print, don't write")
    parser.add_argument(
        "--overwrite", action="store_true", help="overwrite an existing scenario id"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="after writing, run the Story 6.15 golden sanity check",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="after writing, scp the scenario to the VPS + restart pipecat so it "
        "appears in the app's scenario list (test before review)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
