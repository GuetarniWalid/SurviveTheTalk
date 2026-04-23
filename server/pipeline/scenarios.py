"""Scenario prompt loader for the tutorial call.

Story 4.5 needs the `/calls/initiate` endpoint to spawn the Pipecat bot with
Tina the Waitress's scenario prompt — built by concatenating `base_prompt` and
`checkpoints[0].prompt_segment` from the canonical YAML.

Full scenario selection (a DB-backed scenarios table, checkpoint-aware prompt
composition) lands in Story 5.1 + 6.1 + 6.6. Until then, Story 4.5 hardcodes
the tutorial id and reads the YAML once per process lifetime.

**YAML source-of-truth:** the canonical scenarios live in
`_bmad-output/planning-artifacts/scenarios/` (Epic 3 authoring), but the
server ships a self-contained copy next to this module so production deploys
never depend on the planning folder being present. When a scenario file is
updated in `_bmad-output/`, copy it into `server/pipeline/scenarios/` so both
stay in sync.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TUTORIAL_SCENARIO_ID = "waiter_easy_01"

_SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
_TUTORIAL_SCENARIO_YAML = _SCENARIOS_DIR / "the-waiter.yaml"

_SPEAK_FIRST_DIRECTIVE = (
    "\n\nYou will speak first when the call begins. Start with: "
    '"Welcome to The Golden Fork. What can I get you?" '
    "Do NOT wait for the user to speak first."
)

_PROMPT_CACHE: dict[str, str] = {}


def load_scenario_prompt(scenario_id: str) -> str:
    """Return the composed system prompt for `scenario_id`.

    Composition is `base_prompt` + the first checkpoint's `prompt_segment` +
    the "speak first" directive (AC3). Only `waiter_easy_01` is supported in
    Story 4.5; unknown ids raise `ValueError` rather than silently falling
    back to the waiter prompt, because a wrong-scenario bot spawn would be
    a confusing class of bug to debug in production.

    The composed prompt is cached after the first successful load so the
    async `/calls/initiate` handler never blocks on disk I/O per request.
    """
    if scenario_id != TUTORIAL_SCENARIO_ID:
        raise ValueError(
            f"Unknown scenario_id: {scenario_id!r}. Story 4.5 only supports "
            f"{TUTORIAL_SCENARIO_ID!r}; full scenario selection arrives in "
            "Story 5.1 / 6.1."
        )

    cached = _PROMPT_CACHE.get(scenario_id)
    if cached is not None:
        return cached

    data = yaml.safe_load(_TUTORIAL_SCENARIO_YAML.read_text(encoding="utf-8"))
    base_prompt = data["base_prompt"].rstrip()
    checkpoints = data["checkpoints"]
    if not checkpoints:
        raise RuntimeError(
            f"Scenario {scenario_id!r} has no checkpoints — cannot compose prompt."
        )
    first_segment = checkpoints[0]["prompt_segment"].rstrip()

    composed = f"{base_prompt}\n\n{first_segment}{_SPEAK_FIRST_DIRECTIVE}"
    _PROMPT_CACHE[scenario_id] = composed
    return composed
