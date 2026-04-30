"""Scenario prompt loader.

Story 4.5 hardcoded the tutorial scenario; Story 6.1 widens the loader to
support every YAML in `server/pipeline/scenarios/` by building a
`{scenario_id: yaml_path}` lookup table at module import time.

The lookup is built from each YAML's `metadata.id` field — NOT from the
filename — so a future rename of `the-cop.yaml` does not silently break
the mapping.

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

_SPEAK_FIRST_DIRECTIVE = (
    "\n\nYou will speak first when the call begins. Start with: "
    '"Welcome to The Golden Fork. What can I get you?" '
    "Do NOT wait for the user to speak first."
)

_PROMPT_CACHE: dict[str, str] = {}


def _build_scenario_index() -> dict[str, Path]:
    """Scan `_SCENARIOS_DIR` and return `{scenario_id: yaml_path}`.

    Reads each YAML's top-level `metadata.id` to build the index. Files with
    a missing or empty `metadata.id` are skipped (they're not addressable by
    id anyway — `load_scenario_prompt` would fail with `FileNotFoundError`).

    A malformed YAML (parse error, encoding error, unexpected shape) is
    logged and skipped rather than crashing the module import — a single
    bad file must NOT take the whole `/calls` surface offline at server
    boot. A duplicate `metadata.id` across files raises `RuntimeError` at
    import (silent overwrite would route users to the wrong prompt).
    """
    import logging

    log = logging.getLogger(__name__)
    index: dict[str, Path] = {}
    for path in sorted(_SCENARIOS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
            log.error("scenario_index_skip_malformed file=%s err=%s", path.name, exc)
            continue
        metadata = (data or {}).get("metadata") or {}
        scenario_id = metadata.get("id")
        if not (isinstance(scenario_id, str) and scenario_id):
            continue
        if scenario_id in index:
            raise RuntimeError(
                f"Duplicate scenario_id {scenario_id!r} found in "
                f"{index[scenario_id].name} and {path.name}. Each "
                f"`metadata.id` must be unique across the scenarios dir."
            )
        index[scenario_id] = path
    return index


_SCENARIO_INDEX: dict[str, Path] = _build_scenario_index()


def load_scenario_metadata(scenario_id: str) -> dict:
    """Return the YAML's `metadata` block for `scenario_id`.

    Story 6.3 needs `metadata.rive_character` so `bot.py` can build
    character-aware classifier prompts. Composed prompts are cached but
    the metadata read is a single YAML deserialization per call — the
    file is small and the route handler tolerates the cost on the
    initiate path. Unknown ids raise `FileNotFoundError` (matching
    `load_scenario_prompt`).
    """
    yaml_path = _SCENARIO_INDEX.get(scenario_id)
    if yaml_path is None:
        raise FileNotFoundError(
            f"Unknown scenario_id: {scenario_id!r}. Known ids: "
            f"{sorted(_SCENARIO_INDEX)}."
        )
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    metadata = (data or {}).get("metadata") or {}
    if not isinstance(metadata, dict):
        raise RuntimeError(
            f"Scenario {scenario_id!r} has malformed `metadata` (not a dict)."
        )
    return metadata


def load_scenario_prompt(scenario_id: str) -> str:
    """Return the composed system prompt for `scenario_id`.

    Composition is `base_prompt` + the first checkpoint's `prompt_segment` +
    the "speak first" directive. Unknown ids raise `FileNotFoundError`
    (caught by the route handler and surfaced as `SCENARIO_LOAD_FAILED`).

    The composed prompt is cached after the first successful load so the
    async `/calls/initiate` handler never blocks on disk I/O per request.
    """
    cached = _PROMPT_CACHE.get(scenario_id)
    if cached is not None:
        return cached

    yaml_path = _SCENARIO_INDEX.get(scenario_id)
    if yaml_path is None:
        raise FileNotFoundError(
            f"Unknown scenario_id: {scenario_id!r}. Known ids: "
            f"{sorted(_SCENARIO_INDEX)}."
        )

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
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
