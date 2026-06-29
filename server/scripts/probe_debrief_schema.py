"""Story 7.1 — live Groq Scout acceptance probe for the debrief json_schema.

The mocked-LLM tests cover the request SHAPE but cannot prove Groq Scout
actually ACCEPTS the larger debrief `response_format=json_schema` (arrays of
objects, the `["string","null"]` union, per-property descriptions). Run this
ONCE before the Pixel 9 smoke gate — it is the cheap structured-output
validation CLAUDE.md §4 mandates for any structured-output schema on the target
provider.

Usage (from `server/`, with GROQ_API_KEY in env or .env):

    .venv/Scripts/python scripts/probe_debrief_schema.py

Exit 0 = accepted + parsed cleanly. Non-zero = rejected/unparseable (prints the
provider error body). One short paid call (~$0.0001).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # `server/` on path for config/pipeline imports

import httpx  # noqa: E402

from config import Settings  # noqa: E402
from pipeline.debrief_generator import (  # noqa: E402
    _build_debrief_schema,
    _build_user_message,
    _parse_debrief_output,
)
from pipeline.llm_provider import (  # noqa: E402
    resolve_llm_api_key,
    resolve_llm_chat_url,
)
from pipeline.prompts import DEBRIEF_SYSTEM_PROMPT  # noqa: E402

_TRANSCRIPT = (
    "CHARACTER: Oi. Don't make a scene — wallet and phone, now.\n"
    "USER: I am not want problem, please. I am agree."
)


async def _main() -> int:
    settings = Settings()
    user_message = _build_user_message(
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        brief_personality_description="A street mugger demanding your valuables.",
        reason="character_hung_up",
        transcript_text=_TRANSCRIPT,
        hesitation_block="No significant hesitations detected.",
    )
    payload = {
        "model": settings.debrief_model,
        "messages": [
            {"role": "system", "content": DEBRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        # Deliberately a SMALLER budget than prod `_MAX_TOKENS` (4096): this probe
        # isolates *schema acceptance* (does the provider accept the strict
        # json_schema and return parseable JSON). The short probe transcript needs
        # far less than 2048 anyway.
        "max_tokens": 2048,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "debrief_analysis",
                "strict": True,
                "schema": _build_debrief_schema(),
            },
        },
    }
    url = resolve_llm_chat_url(settings)
    headers = {
        "Authorization": f"Bearer {resolve_llm_api_key(settings)}",
        "Content-Type": "application/json",
    }
    print(f"POST {url}  model={settings.debrief_model}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json=payload)

    print(f"HTTP {resp.status_code}")
    if resp.status_code in (413, 429):
        # Story 10.6 R1 — a TPM rate-limit / admission rejection is NOT a schema
        # problem; the request never reached the validator. Distinguish it so a
        # constrained-tier run doesn't read as "schema rejected".
        print("RATE-LIMITED (TPM), not a schema rejection — provider error body:")
        print(resp.text[:2000])
        print(
            "\n[!] Groq returned a TPM rate-limit (Story 10.6 R1). The schema was "
            "NOT evaluated. Re-run after the reset window, or on the Dev tier; the "
            "debrief request (~5k prompt + max_tokens) exceeds the on_demand 8000 "
            "TPM cap. This is an OPERATIONAL ceiling, not a schema failure."
        )
        return 3
    if resp.status_code >= 300:
        print("REJECTED — provider error body:")
        print(resp.text[:2000])
        print(
            "\n[X] Groq did NOT accept the debrief json_schema. Mitigation: drop "
            "the nullable union to a required string normalized in _normalize_core, "
            "and/or move the descriptions into the prompt (see the generator's "
            "_build_debrief_schema deviation note + CLAUDE.md §4)."
        )
        return 1

    content = resp.json()["choices"][0]["message"]["content"]
    core = _parse_debrief_output(content)
    print("\nRaw content (first 2000 chars):\n" + str(content)[:2000])
    if core is None:
        print("\n[X] Accepted (HTTP 200) but the body did not parse into the core.")
        return 2
    print("\nParsed core keys:", sorted(core.keys()))
    print("areas:", core.get("areas"))
    print(
        f"\n[OK] Groq ({settings.debrief_model}) ACCEPTED the debrief json_schema "
        "and returned parseable JSON."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
