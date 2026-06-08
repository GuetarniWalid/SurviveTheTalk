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

import copy
from pathlib import Path

import yaml

from pipeline.prompts import NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT

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


# ============================================================
# Story 6.4 — Difficulty presets + PatienceTracker config resolver
# ============================================================

# Source of truth: `difficulty-calibration.md` §4.3 cross-checked
# against the `effective:` comments in each scenario YAML's metadata
# block. Tied to the running schema — every scenario YAML's nullable
# overrides resolve through this table when null. NEVER duplicate the
# preset values inline elsewhere; import this constant.
_DIFFICULTY_PRESETS: dict[str, dict] = {
    "easy": {
        "initial_patience": 100,
        "fail_penalty": -15,
        "silence_penalty": -10,
        "recovery_bonus": 5,
        "silence_prompt_seconds": 6.0,
        "silence_hangup_seconds": 10.0,
        # Story 6.13 AC3 — stage 1 impatience anchor. Easy raises this to
        # 4.5 s to respect natural response time (parse ~0.5-1 s +
        # formulate ~0.5-1 s + articulate); 3.0 s was too aggressive per
        # smoke-gate call_id=148 (2026-05-26).
        "ladder_impatience_seconds": 4.5,
        "escalation_thresholds": [75, 50, 25, 0],
        # Story 6.19 follow-up (2026-06-07 smoke gate) — speech speed is a NARROW
        # band ENTIRELY within natural human bounds; the natural rate (1.0) is the
        # ceiling and is NEVER exceeded. Difficulty is carried by LANGUAGE +
        # INTERACTION (see _DIFFICULTY_PROMPTS), not by a faster voice. Easy is
        # only gently slowed — clear, never robotic or drawled. Cartesia sonic-3
        # `speed` multiplier, 1.0 = the voice's natural recorded rate. Threaded
        # preset → resolve_patience_config → bot.py → build_tts_service(speed=…)
        # → CartesiaTTSService GenerationConfig. The nullable per-scenario
        # `metadata.tts_speed` override still wins (in `_PATIENCE_OVERRIDE_KEYS`).
        "tts_speed": 0.9,
    },
    "medium": {
        "initial_patience": 80,
        "fail_penalty": -20,
        "silence_penalty": -15,
        "recovery_bonus": 3,
        # Turn-taking fix (2026-06-08) — raised from 4.0 s so a B1 learner
        # gets a bit more thinking time before the "Are you still there?"
        # relance fires on genuine silence.
        "silence_prompt_seconds": 5.0,
        "silence_hangup_seconds": 7.0,
        "ladder_impatience_seconds": 3.5,
        "escalation_thresholds": [60, 30, 0],
        # Story 6.19 AC5 — natural speaking rate.
        "tts_speed": 1.0,
    },
    "hard": {
        "initial_patience": 60,
        "fail_penalty": -25,
        "silence_penalty": -20,
        "recovery_bonus": 0,
        # Turn-taking fix (2026-06-08 smoke gate) — raised from 3.0 s: 3 s
        # was too aggressive (the cop fired "Are you still there?" while the
        # learner was still forming the answer). Hard stays the most impatient
        # of the three (easy 6.0 / medium 5.0 / hard 4.5) but no longer cuts
        # off a thinking B1 on genuine silence; the live-speech case is now
        # handled by the interim-cancel in patience_tracker.py.
        "silence_prompt_seconds": 4.5,
        "silence_hangup_seconds": 5.0,
        # Hard scenarios get a visibly more impatient character (faster
        # face-shift = "Mugger should be impatient by design" semantic).
        "ladder_impatience_seconds": 2.5,
        "escalation_thresholds": [30, 0],
        # Story 6.19 follow-up (2026-06-07 smoke gate) — natural rate is the
        # CEILING: hard speaks at the SAME natural pace as medium (1.0), NEVER
        # accelerated. 1.2 read as unnatural/rushed on device; hard's extra
        # difficulty is 100% language + interaction, not speed.
        "tts_speed": 1.0,
    },
}

# ============================================================
# Story 6.19 — Per-difficulty character behavior block (AC4)
# ============================================================
#
# Until Story 6.19 the "Difficulty behavior (easy|medium|hard): …" block lived
# INLINE in each scenario YAML's `base_prompt`. That meant a global "hard" pick
# on an "easy"-authored scenario still *spoke* easy (the YAML text was fixed).
# The three blocks now live HERE as the single source of truth; the YAMLs drop
# their inline block (a load-time guard in `load_scenario_base_prompt` rejects
# any YAML that still carries one). `load_scenario_base_prompt(scenario_id,
# difficulty_override=…)` composes the chosen difficulty's block onto the raw
# persona, so the character's vocabulary / idioms / rephrasing / pace actually
# match the selected difficulty.
#
# These are deliberately SCENARIO-AGNOSTIC (they apply to any character): the
# per-scenario flavour lives in the persona/`base_prompt`; this block is the
# difficulty knob. The pace line is also the AC5 fallback if a TTS provider ever
# can't honour a numeric `speed`.
_DIFFICULTY_PROMPTS: dict[str, str] = {
    "easy": (
        "Difficulty behavior (easy):\n"
        "- Speak at a calm, clear pace (natural, never robotic or drawled).\n"
        "- Use only basic, high-frequency everyday vocabulary; keep every word "
        "concrete and literal.\n"
        "- Use short, simple sentences (about 5-8 words), one idea per turn.\n"
        "- Never use idioms, phrasal verbs, slang, or cultural references.\n"
        "- Ask one question at a time, and make it closed or either-or whenever "
        "you can ('Chicken or fish?', 'Were you at work? Yes or no?') so the "
        "answer's shape is obvious.\n"
        "- State plainly what you want from them ('Just tell me where you "
        "were.'); never make them guess your intention.\n"
        "- If they seem confused or don't understand, rephrase more simply and "
        "help them along — stay patient and in character, and never correct "
        "their grammar.\n"
        "- Never interrupt; leave them a few seconds of silence to think.\n"
        "- Stay calm; show only mild frustration after repeated failure, and let "
        "a single good answer noticeably soften you."
    ),
    "medium": (
        "Difficulty behavior (medium):\n"
        "- Speak at a natural conversational pace.\n"
        "- Use everyday vocabulary with the occasional lower-frequency word the "
        "learner can work out from context.\n"
        "- Use natural sentences (about 10-15 words) with at most one subordinate "
        "clause.\n"
        "- Weave in at most one common, transparent phrasal verb or colloquial "
        "expression per turn ('calm down', 'find out', 'come on').\n"
        "- Ask plain open questions one at a time ('Why didn't you call?', "
        "'Where were you?') — no options offered, no hand-holding.\n"
        "- Do not rephrase or simplify on request — repeat the same sentence "
        "once, then show mild impatience instead of helping.\n"
        "- React only to what they MEAN, never to their grammar.\n"
        "- Throw in one unexpected question across the call; you may interrupt "
        "once if they ramble or stall."
    ),
    "hard": (
        "Difficulty behavior (hard):\n"
        "- Be genuinely hard through LANGUAGE and INTERACTION, not speed.\n"
        "- Speak at a normal, natural pace — never rushed or accelerated.\n"
        "- Use rich, lower-frequency and idiomatic vocabulary, including less "
        "common senses of familiar words ('run me through it', a story that "
        "doesn't 'add up').\n"
        "- Weave in 2-3 phrasal verbs or idioms per turn that a non-native "
        "struggles with, mixing British and American expressions ('come clean', "
        "'cut to the chase', 'knock it off') — but never stack two opaque idioms "
        "in one clause.\n"
        "- Vary your turns: either keep them clipped ('And?', 'Go on.', "
        "'That's it?') OR pack two facts into one dense, multi-clause sentence "
        "they must track.\n"
        "- Ask loaded, pointed questions that smuggle in an assumption ('So why "
        "were you weaving all over the road?'); sometimes stack two questions so "
        "they must hold both.\n"
        "- Often IMPLY what you want instead of stating it — use hints, "
        "rhetorical questions, and loaded pauses ('...Interesting.', 'Must be "
        "nice.') and make them infer the response you're demanding.\n"
        "- Never rephrase, never simplify; if they don't understand or stumble, "
        "treat it as their problem and press the same point harder.\n"
        "- Interrupt them if they ramble or stall, and finish their thought for "
        "them, unfavorably; throw curveballs and abrupt topic shifts, and circle "
        "back to an earlier answer to catch inconsistencies.\n"
        "- Show impatience early; a good answer barely registers ('Fine. And?'). "
        "Stay cold and do not help them.\n"
        "- Stay fair: be hard to deal with, but never gibberish — keep each turn "
        "parseable by a determined learner (at most one trap or twist per turn)."
    ),
}

# The 8 nullable override keys the scenario YAML may set in
# `metadata`. When null, the preset wins; when non-null, the YAML wins.
_PATIENCE_OVERRIDE_KEYS = (
    "initial_patience",  # YAML key: patience_start (alias below)
    "fail_penalty",
    "silence_penalty",
    "recovery_bonus",
    "silence_prompt_seconds",
    "silence_hangup_seconds",
    "ladder_impatience_seconds",
    "escalation_thresholds",
    # Story 6.19 AC5 — nullable per-scenario TTS speed override; null → the
    # difficulty preset's `tts_speed` wins. YAML key is `metadata.tts_speed`.
    "tts_speed",
)


def resolve_patience_config(
    scenario_id: str, difficulty_override: str | None = None
) -> dict:
    """Return a non-null PatienceTracker config dict for `scenario_id`.

    Reads the scenario YAML, picks the difficulty preset row, and
    applies nullable overrides from `metadata` (YAML wins when set).
    Also folds in `total_checkpoints` (derived from the
    `checkpoints` list length) so the caller can populate the
    `call_end` envelope's progress field.

    Story 6.19 — `difficulty_override` (the learner's GLOBAL difficulty
    pick, threaded from the client) selects which preset is the base in
    place of the YAML's authored `metadata.difficulty`. Precedence
    (AC3): the chosen difficulty swaps the *preset* (and, via
    `load_scenario_base_prompt`, the behavior block + speech speed);
    explicit per-field YAML overrides still win over individual preset
    values. `None` (legacy `/connect`, older clients) → the authored
    difficulty is used, exactly as before (AC7). The `copy.deepcopy`
    stays FIRST; the override only changes which row we copy.

    Raises:
        FileNotFoundError: Unknown scenario id (parity with the rest
            of this module).
        RuntimeError: `metadata.difficulty` (or `difficulty_override`)
            is missing or not one of `easy` / `medium` / `hard` —
            defensive against future YAML drift / a bad override.
    """
    yaml_path = _SCENARIO_INDEX.get(scenario_id)
    if yaml_path is None:
        raise FileNotFoundError(
            f"Unknown scenario_id: {scenario_id!r}. Known ids: "
            f"{sorted(_SCENARIO_INDEX)}."
        )

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise RuntimeError(
            f"Scenario {scenario_id!r} has malformed `metadata` (not a dict)."
        )

    # Story 6.19 — a chosen global difficulty overrides the authored one for
    # THIS call. Validate the override defensively even though the API boundary
    # (`InitiateCallIn.difficulty`, a Literal) already 422s a bad value: this
    # resolver is also reachable from tests / future callers.
    if difficulty_override is not None:
        if difficulty_override not in _DIFFICULTY_PRESETS:
            raise RuntimeError(
                f"difficulty_override {difficulty_override!r} is not one of "
                f"{sorted(_DIFFICULTY_PRESETS)}."
            )
        difficulty = difficulty_override
    else:
        difficulty = metadata.get("difficulty")
    if difficulty not in _DIFFICULTY_PRESETS:
        raise RuntimeError(
            f"Scenario {scenario_id!r} has unknown difficulty {difficulty!r}; "
            f"expected one of {sorted(_DIFFICULTY_PRESETS)}."
        )

    preset = _DIFFICULTY_PRESETS[difficulty]
    # Story 6.6 / deferred-work line 357 — switch to deepcopy so a
    # downstream mutation of `escalation_thresholds` (or any future
    # nested override) cannot corrupt the shared preset row across
    # concurrent calls. The shallow `dict(preset)` was safe in Story
    # 6.4 because no caller mutated the list, but Story 6.6 now spawns
    # one `CheckpointManager` per call (multiple instances coexisting
    # on the VPS) and a future bug that appends to the list would leak
    # globally.
    config: dict = copy.deepcopy(preset)

    # The YAML names the starting meter `patience_start`; the
    # PatienceTracker constructor names it `initial_patience`. Map
    # the alias before walking the rest of the override keys.
    yaml_aliases = {"initial_patience": "patience_start"}
    for key in _PATIENCE_OVERRIDE_KEYS:
        yaml_key = yaml_aliases.get(key, key)
        override = metadata.get(yaml_key)
        if override is not None:
            config[key] = override

    checkpoints = data.get("checkpoints") or []
    if not isinstance(checkpoints, list):
        raise RuntimeError(
            f"Scenario {scenario_id!r} has malformed `checkpoints` (not a list)."
        )
    config["total_checkpoints"] = len(checkpoints)

    # Story 6.6 — load exit_lines from YAML into the config. Single
    # source of truth: `exit_lines.hangup` is shared by both silence
    # and inappropriate paths today (Deviation #3); `exit_lines.completion`
    # wires the new `hang_up_line_survived` constructor kwarg.
    # A future story that wants per-reason silence/inappropriate lines
    # can extend the YAML schema (`exit_lines.silence`,
    # `exit_lines.inappropriate`) without breaking this contract.
    #
    # Type-check the raw value BEFORE the falsy-coalesce: an
    # `exit_lines: []` (list) YAML override would otherwise silently
    # collapse to `{}` via `or {}` and the malformed-shape check
    # would never fire.
    raw_exit_lines = data.get("exit_lines")
    if raw_exit_lines is None:
        exit_lines: dict = {}
    elif not isinstance(raw_exit_lines, dict):
        raise RuntimeError(
            f"Scenario {scenario_id!r} has malformed `exit_lines` (not a dict)."
        )
    else:
        exit_lines = raw_exit_lines
    hangup_line = exit_lines.get("hangup") or "I don't have time for this. Goodbye."
    completion_line = (
        exit_lines.get("completion") or "Looks like you got what you came for. Goodbye."
    )
    # Story 6.6 post-deploy (Deviation #6) — `exit_lines.patience_warning`
    # is the one-shot "last chance" line spoken when the patience meter
    # falls into the warning band on a failed exchange. Optional in YAML;
    # falls back to a generic in-character line if absent.
    patience_warning_line = (
        exit_lines.get("patience_warning")
        or "*sighs* Look, are you ordering or not? Last chance."
    )
    # Story 6.11 — `exit_lines.noisy_environment` is the in-character line
    # spoken when EnvironmentMonitor detects a parasitic background voice.
    # Optional in YAML; falls back to the generic scenario-agnostic
    # constant (single source of truth in prompts.py) when absent, so the
    # 4 un-overridden scenarios inherit the default for free (AC5).
    noisy_environment_line = (
        exit_lines.get("noisy_environment") or NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT
    )
    config["hang_up_line_silence"] = hangup_line
    config["hang_up_line_inappropriate"] = hangup_line
    config["hang_up_line_survived"] = completion_line
    config["hang_up_line_noisy_environment"] = noisy_environment_line
    config["patience_warning_line"] = patience_warning_line

    # Defensive: a YAML `patience_start: 0` override would silently
    # produce a `survival_pct` denominator of zero in PatienceTracker's
    # arithmetic. Fail loud at config-resolution time so the bug
    # surfaces at process start, not on the first hang-up.
    if (
        not isinstance(config["initial_patience"], int)
        or config["initial_patience"] <= 0
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r} resolved to "
            f"initial_patience={config['initial_patience']!r}; must be a positive int."
        )

    # Story 6.6 / deferred-work line 350 — type/range validation for
    # the previously-dormant override fields. Story 6.4 stored these
    # without validating them because nothing consumed them; Story 6.6
    # is the consumer (`PatienceTracker.apply_exchange_outcome` wires
    # `fail_penalty` and `recovery_bonus` into the meter), so a wrong
    # type or sign would now mutate runtime state.
    #
    # `not isinstance(x, bool)` belt-and-braces every int check —
    # Python's `bool` is a subclass of `int`, so a YAML `fail_penalty:
    # false` (= 0) or `recovery_bonus: true` (= 1) would otherwise pass
    # the `isinstance(x, int)` check silently. Reject explicitly so a
    # YAML author who mistypes a bool sees the error at process start
    # rather than getting silent integer coercion.
    if (
        not isinstance(config["fail_penalty"], int)
        or isinstance(config["fail_penalty"], bool)
        or config["fail_penalty"] > 0
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r}: fail_penalty must be a non-positive int, "
            f"got {config['fail_penalty']!r}"
        )
    if (
        not isinstance(config["recovery_bonus"], int)
        or isinstance(config["recovery_bonus"], bool)
        or config["recovery_bonus"] < 0
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r}: recovery_bonus must be a non-negative int, "
            f"got {config['recovery_bonus']!r}"
        )
    if not isinstance(config["escalation_thresholds"], list) or not all(
        isinstance(x, int) and not isinstance(x, bool)
        for x in config["escalation_thresholds"]
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r}: escalation_thresholds must be a "
            f"list[int], got {config['escalation_thresholds']!r}"
        )
    if (
        not isinstance(config["silence_hangup_seconds"], (int, float))
        or isinstance(config["silence_hangup_seconds"], bool)
        or config["silence_hangup_seconds"] <= 0
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r}: silence_hangup_seconds must be a "
            f"positive number, got {config['silence_hangup_seconds']!r}"
        )
    # Story 6.6 review patch — extend coverage to the two remaining
    # numeric fields (`silence_prompt_seconds` is the ladder-stage-2
    # anchor; `silence_penalty` is the meter deduction at ladder stage
    # 4). Story 6.4 left them un-validated; Story 6.6's preemptive path
    # is now the primary consumer (`PatienceTracker.patience` /
    # `fail_penalty` read via property; a negative `silence_prompt_seconds`
    # would `asyncio.sleep(-x)` and immediately skip stages, silently
    # disabling the ladder).
    if (
        not isinstance(config["silence_prompt_seconds"], (int, float))
        or isinstance(config["silence_prompt_seconds"], bool)
        or config["silence_prompt_seconds"] <= 0
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r}: silence_prompt_seconds must be a "
            f"positive number, got {config['silence_prompt_seconds']!r}"
        )
    if (
        not isinstance(config["silence_penalty"], int)
        or isinstance(config["silence_penalty"], bool)
        or config["silence_penalty"] > 0
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r}: silence_penalty must be a non-positive int, "
            f"got {config['silence_penalty']!r}"
        )
    # Story 6.13 AC3 — range-bound the new `ladder_impatience_seconds`
    # override. 0.5 s is the practical floor below which the impatience
    # face fires before the user has even started parsing the bot's last
    # word; 10.0 s is the ceiling above which the character feels
    # disengaged regardless of difficulty. Bool-reject mirrors the other
    # numeric validators (`isinstance(True, int)` is True in Python).
    if (
        not isinstance(config["ladder_impatience_seconds"], (int, float))
        or isinstance(config["ladder_impatience_seconds"], bool)
        or not (0.5 <= config["ladder_impatience_seconds"] <= 10.0)
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r}: ladder_impatience_seconds must be a "
            f"number in [0.5, 10.0], got "
            f"{config['ladder_impatience_seconds']!r}"
        )
    # Story 6.19 follow-up (2026-06-07 smoke gate) — `tts_speed` (preset or
    # `metadata.tts_speed` override) must be in [0.6, 1.0]. The NATURAL rate (1.0)
    # is the CEILING: a value above natural reads as rushed/unnatural on device
    # (hard at 1.2 was the smoke-gate complaint), so the cap is lowered from the
    # old 1.5 to 1.0 — "above natural" is structurally impossible to ship. The
    # 0.6 floor stays. Bool-reject mirrors the other numeric validators.
    if (
        not isinstance(config["tts_speed"], (int, float))
        or isinstance(config["tts_speed"], bool)
        or not (0.6 <= config["tts_speed"] <= 1.0)
    ):
        raise RuntimeError(
            f"Scenario {scenario_id!r}: tts_speed must be a number in "
            f"[0.6, 1.0] (natural rate is the ceiling), got {config['tts_speed']!r}"
        )

    return config


def load_scenario_checkpoints(scenario_id: str) -> list[dict]:
    """Return the ordered checkpoints list for `scenario_id`.

    Story 6.6 — `CheckpointManager` needs the full ordered list (not just
    the first entry that `load_scenario_prompt` consumes). Each entry is
    a dict with at minimum: `id`, `hint_text`, `prompt_segment`,
    `success_criteria`. Shape-validated so a malformed entry surfaces at
    call init, not mid-call.

    Raises:
        FileNotFoundError: Unknown scenario id (parity with the rest of
            this module).
        RuntimeError: `checkpoints` is missing/empty or any entry has a
            missing or non-string required field.
    """
    yaml_path = _SCENARIO_INDEX.get(scenario_id)
    if yaml_path is None:
        raise FileNotFoundError(
            f"Unknown scenario_id: {scenario_id!r}. Known ids: "
            f"{sorted(_SCENARIO_INDEX)}."
        )

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    checkpoints = data.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise RuntimeError(
            f"Scenario {scenario_id!r}: `checkpoints` must be a non-empty list."
        )
    required = ("id", "hint_text", "prompt_segment", "success_criteria")
    for idx, entry in enumerate(checkpoints):
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"Scenario {scenario_id!r}: checkpoint[{idx}] is not a dict."
            )
        for field in required:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError(
                    f"Scenario {scenario_id!r}: checkpoint[{idx}] missing/empty "
                    f"required string field {field!r}."
                )
    # Story 6.10 review patch — checkpoint ids MUST be unique. The
    # goal-tracking engine keys state by id (`CheckpointManager._goals` /
    # `_id_to_index`), so a duplicate id silently collapses two goals into
    # one map entry while `len(checkpoints)` still counts both — the client
    # HUD `metCount` then can never reach `total` and the call never shows
    # all-met. The pre-6.10 linear engine indexed positionally and was
    # immune; this validation closes the new sensitivity at load time.
    ids = [entry["id"] for entry in checkpoints]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise RuntimeError(
            f"Scenario {scenario_id!r}: duplicate checkpoint id(s) {duplicates}. "
            f"Checkpoint ids must be unique (goal state is keyed by id)."
        )
    # Story 6.23 — validate the optional `requires` reactive-gating edge.
    # A beat carrying `requires: <id>` is judged/credited only after that
    # required beat is `met` (the engine gate in `checkpoint_manager.
    # judgeable_goals`). The edge MUST point at an EXISTING checkpoint that
    # comes STRICTLY EARLIER in author order — which makes the dependency
    # graph acyclic by construction (a beat can only wait on a beat that
    # precedes it). Same fail-fast posture as the duplicate-id guard above:
    # a malformed edge raises at call init, not mid-call.
    id_to_index = {entry["id"]: i for i, entry in enumerate(checkpoints)}
    for idx, entry in enumerate(checkpoints):
        required = entry.get("requires")
        if required is None:
            continue
        if not isinstance(required, str) or not required.strip():
            raise RuntimeError(
                f"Scenario {scenario_id!r}: checkpoint[{idx}] ({entry['id']!r}) has "
                f"a non-string/empty `requires` value {required!r}."
            )
        if required not in id_to_index:
            raise RuntimeError(
                f"Scenario {scenario_id!r}: checkpoint[{idx}] ({entry['id']!r}) "
                f"`requires` points at unknown checkpoint id {required!r}. It must "
                f"name an existing, earlier checkpoint."
            )
        if id_to_index[required] >= idx:
            raise RuntimeError(
                f"Scenario {scenario_id!r}: checkpoint[{idx}] ({entry['id']!r}) "
                f"`requires` {required!r} must reference an EARLIER checkpoint "
                f"(a reactive beat cannot depend on itself or a later beat)."
            )
    return checkpoints


def load_scenario_base_prompt(
    scenario_id: str, difficulty_override: str | None = None
) -> str:
    """Return the persona `base_prompt` composed with its difficulty behavior block.

    Story 6.6 — `CheckpointManager` composes the live system message as
    `base_prompt + "\\n\\n" + checkpoints[index].prompt_segment` after
    each advance. The `_SPEAK_FIRST_DIRECTIVE` is intentionally NOT
    included here — it applies only to the very first turn (composed
    once by `load_scenario_prompt`); the second checkpoint onwards must
    NOT re-instruct the bot to deliver the canned opening line.

    Story 6.19 AC4 — the "Difficulty behavior (…)" block used to live
    INLINE in each YAML's `base_prompt`, which froze a scenario's spoken
    difficulty to its authored level. The three blocks now live in the
    `_DIFFICULTY_PROMPTS` code constant (single source of truth); this
    function appends the block for the *resolved* difficulty —
    `difficulty_override` (the learner's global pick) when given, else
    the YAML's authored `metadata.difficulty`. So a global "hard" pick on
    an "easy"-authored scenario now actually SPEAKS hard. A load-time
    guard rejects any YAML that still carries an inline block.

    Raises:
        FileNotFoundError: Unknown scenario id.
        RuntimeError: `base_prompt` is missing/not a string, still carries
            an inline difficulty block, or the resolved difficulty is not
            one of `easy` / `medium` / `hard`.
    """
    yaml_path = _SCENARIO_INDEX.get(scenario_id)
    if yaml_path is None:
        raise FileNotFoundError(
            f"Unknown scenario_id: {scenario_id!r}. Known ids: "
            f"{sorted(_SCENARIO_INDEX)}."
        )

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    base_prompt = data.get("base_prompt")
    if not isinstance(base_prompt, str) or not base_prompt.strip():
        raise RuntimeError(
            f"Scenario {scenario_id!r}: `base_prompt` must be a non-empty string."
        )
    # Story 6.6 review patch — guard against a YAML author pasting the
    # composed prompt (which includes `_SPEAK_FIRST_DIRECTIVE`) into the
    # `base_prompt` field. Every checkpoint advance re-uses this string
    # as the new system instruction; if it contains the speak-first
    # directive, the bot would re-deliver the canned opening line on
    # every advance — a bug that would surface mid-call, not at boot.
    if "You will speak first when the call begins" in base_prompt:
        raise RuntimeError(
            f"Scenario {scenario_id!r}: `base_prompt` must NOT include the "
            f"speak-first directive. It is composed exactly once for the "
            f"initial call setup by `load_scenario_prompt`; checkpoint "
            f"advances re-use the raw `base_prompt` and must not re-issue "
            f"the canned opening line."
        )
    # Story 6.19 AC4 — the behavior block lives in `_DIFFICULTY_PROMPTS` now.
    # Reject a YAML that still carries an inline one: two blocks (the stale
    # inline one + the composed one) would contradict each other and a global
    # difficulty pick could no longer override the spoken difficulty.
    if "Difficulty behavior (" in base_prompt:
        raise RuntimeError(
            f"Scenario {scenario_id!r}: `base_prompt` must NOT contain an inline "
            f"'Difficulty behavior (…)' block. Story 6.19 moved the three blocks "
            f"into the `_DIFFICULTY_PROMPTS` code constant (single source of "
            f"truth); remove the inline block from the YAML."
        )

    # Resolve the difficulty: the learner's global pick wins, else the YAML's
    # authored value. Validate defensively (the API Literal already 422s a bad
    # override; this also guards a malformed YAML / a future direct caller).
    metadata = data.get("metadata")
    authored = metadata.get("difficulty") if isinstance(metadata, dict) else None
    difficulty = difficulty_override if difficulty_override is not None else authored
    if difficulty not in _DIFFICULTY_PROMPTS:
        raise RuntimeError(
            f"Scenario {scenario_id!r}: cannot compose base prompt — resolved "
            f"difficulty {difficulty!r} is not one of "
            f"{sorted(_DIFFICULTY_PROMPTS)}."
        )

    return f"{base_prompt.rstrip()}\n\n{_DIFFICULTY_PROMPTS[difficulty]}"


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
