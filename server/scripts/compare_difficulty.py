"""Dev tool — A/B the GLOBAL difficulty blocks' behavioral effect on a scenario.

Runs the REAL character LLM with the prod-composed system prompt for EACH
GLOBAL difficulty level (the only difficulty cursor since Story 6.28) on the
SAME fixed user turns, then prints the replies side by side — so we can verify
the `_DIFFICULTY_PROMPTS` blocks produce a flagrantly different register
(vocabulary, idioms, willingness to help, demand for precision) WITHOUT making
on-device calls. The turns deliberately probe the locked design's levers: a vague answer
(does HARD demand precision while EASY accepts the gist?) and a "can you
repeat?" (does HARD refuse to help while EASY rephrases?).

Live tool: needs GROQ_API_KEY (or LLM_API_KEY) in the environment; never
imported by prod. Mirrors the prod composition in `bot.py::run_bot`
(base_prompt + difficulty block + COHERENCE_CHARTER + goal blocks).

Usage:
    cd server
    export GROQ_API_KEY=$(grep -E '^GROQ_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '\\r')
    python scripts/compare_difficulty.py [scenario_id] [easy hard ...]
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import httpx

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from pipeline.checkpoint_manager import (  # noqa: E402
    format_remaining_goals_block,
    format_suggested_focus_block,
)
from pipeline.prompts import COHERENCE_CHARTER  # noqa: E402
from pipeline.scenarios import (  # noqa: E402
    load_scenario_base_prompt,
    load_scenario_checkpoints,
)

# The character LLM the bot ACTUALLY runs on. Defaults to Scout — the current
# prod model (the VPS .env sets CHARACTER_MODEL=Scout since 2026-06-08; the 70B
# free tier is capacity-walled). Validating on a STRONGER model than prod hides
# the exact failure this tool exists to catch: a weak model ignoring a soft or
# self-contradicting difficulty signal (the 2026-06-08 cop smoke gate). Override
# CHARACTER_MODEL to match prod if prod changes.
MODEL = os.environ.get("CHARACTER_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
BASE = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
URL = BASE + "/chat/completions"
KEY = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY") or ""

# Turns chosen to probe the locked design's felt levers (accommodation +
# precision-demand), not just vocabulary.
FIXED_TURNS = [
    "Good evening officer. No, I'm not really sure why you're calling me.",
    "I was at home, I think.",
    "Sorry? Can you repeat that, please?",
    "Uh, I don't remember exactly... around eight, maybe?",
]


def compose_system(scenario_id: str, difficulty: str) -> str:
    """Mirror bot.py::run_bot: persona + difficulty block + charter + goals."""
    base = load_scenario_base_prompt(scenario_id, difficulty=difficulty)
    cps = load_scenario_checkpoints(scenario_id)
    return "\n\n".join(
        [
            base.rstrip(),
            COHERENCE_CHARTER,
            format_remaining_goals_block(cps),
            format_suggested_focus_block(cps[0]),
        ]
    )


# Free-tier Groq is ~30 req/min; a burst 429s. Throttle every call + retry on
# 429 honouring Retry-After (matches the Story 6.15/6.16 calibration tools).
THROTTLE_S = float(os.environ.get("COMPARE_THROTTLE_S", "2.5"))


async def ask(
    client: httpx.AsyncClient,
    system: str,
    messages: list[dict],
    *,
    max_retries: int = 6,
) -> str:
    for attempt in range(max_retries):
        await asyncio.sleep(THROTTLE_S)
        resp = await client.post(
            URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "model": MODEL,
                "messages": [{"role": "system", "content": system}, *messages],
                "temperature": 0.7,
                "max_tokens": 220,
            },
        )
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", "0")) or (4 * (attempt + 1))
            print(f"  (429 rate-limit — waiting {wait:.0f}s)", file=sys.stderr)
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError(
        "Groq kept returning 429 after retries — try later or a paid key"
    )


async def run_difficulty(
    client: httpx.AsyncClient, scenario_id: str, difficulty: str
) -> list[str]:
    system = compose_system(scenario_id, difficulty)
    convo: list[dict] = []
    replies: list[str] = []
    for turn in FIXED_TURNS:
        convo.append({"role": "user", "content": turn})
        reply = await ask(client, system, convo)
        convo.append({"role": "assistant", "content": reply})
        replies.append(reply)
    return replies


async def main() -> None:
    if not KEY:
        print("ERROR: set GROQ_API_KEY (or LLM_API_KEY) in the environment.")
        sys.exit(1)
    scenario_id = sys.argv[1] if len(sys.argv) > 1 else "cop_interrogation_01"
    # Default to all three: the extremes (easy vs hard) are the EASY case to
    # differentiate — the adjacent pairs (easy/medium, medium/hard) are where a
    # weak model collapses the register, so probe medium too.
    difficulties = sys.argv[2:] or ["easy", "medium", "hard"]
    print(f"scenario={scenario_id}  model={MODEL}  difficulties={difficulties}\n")
    async with httpx.AsyncClient(timeout=40.0) as client:
        results = {
            d: await run_difficulty(client, scenario_id, d) for d in difficulties
        }
    for i, turn in enumerate(FIXED_TURNS):
        print("=" * 88)
        print(f"USER: {turn}")
        for d in difficulties:
            print(f"  [{d.upper()}] {results[d][i]}")
    print("=" * 88)


if __name__ == "__main__":
    asyncio.run(main())
