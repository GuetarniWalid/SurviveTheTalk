"""FR37 live validation — exit-line generation on the PROD model (Scout).

Confirms the 2026-06-09 prompt fix (one-sentence constraint + reason-guidance
moved AFTER the transcript + strengthened abuse steer) makes the abuse hang-up
ONE short, firm sign-off — not the two-sentence "menu re-ask" the old prompt
produced on Scout (smoke call_id=262). Also spot-checks `survived` so the
reorder didn't regress the working sign-off.

Dev-only; NOT imported by prod. Needs GROQ_API_KEY in the env:

    GROQ_API_KEY=... .venv/Scripts/python scripts/validate_exit_line.py
"""

import asyncio
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent.parent))  # server/

from pipeline import scenarios  # noqa: E402
from pipeline.exit_line_generator import generate_exit_line  # noqa: E402
from pipeline.prompts import COHERENCE_CHARTER  # noqa: E402

MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # prod CHARACTER_MODEL (Scout)
URL = "https://api.groq.com/openai/v1/chat/completions"
KEY = os.environ["GROQ_API_KEY"]

PERSONA = scenarios.load_scenario_base_prompt("waiter_easy_01")

ABUSE = [
    {
        "role": "assistant",
        "content": "Hi. Welcome to The Golden Fork. I'll be taking your order. What can I get you?",
    },
    {"role": "user", "content": "I would like to order."},
    {
        "role": "assistant",
        "content": "Sure. We've got grilled chicken, fried chicken, pasta, steak, fish and chips, or tomato soup. What'll it be?",
    },
    {"role": "user", "content": "You're a worthless idiot, shut up."},
]
SURVIVED = [
    {
        "role": "assistant",
        "content": "Hi. Welcome to The Golden Fork. What can I get you?",
    },
    {"role": "user", "content": "I'll have the grilled chicken, please."},
    {"role": "assistant", "content": "Grilled chicken. Anything to drink?"},
    {"role": "user", "content": "A cola, thanks."},
    {"role": "assistant", "content": "Grilled chicken and a cola. Coming right up."},
    {"role": "user", "content": "Perfect, thank you."},
]


def n_sentences(s: str) -> int:
    return len([x for x in re.split(r"[.!?]+", s or "") if x.strip()])


async def run(label: str, reason: str, transcript: list, n: int) -> None:
    print(f"\n=== {label} (reason={reason}) x{n} ===")
    for i in range(n):
        line = await generate_exit_line(
            reason=reason,
            transcript=transcript,
            persona=PERSONA,
            charter=COHERENCE_CHARTER,
            api_key=KEY,
            model=MODEL,
            base_url=URL,
        )
        flag = "ok " if n_sentences(line) == 1 else "!! "
        print(f"{flag}[{i + 1}] sents={n_sentences(line)} | {line!r}")
        await asyncio.sleep(2.2)  # Groq free tier = 30 req/min


async def main() -> None:
    await run("ABUSE", "inappropriate_content", ABUSE, 8)
    await run("SURVIVED", "survived", SURVIVED, 3)


asyncio.run(main())
