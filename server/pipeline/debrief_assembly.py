"""Story 7.1 — pure backend assembly of the client-facing debrief.

The LLM produces only the analysis core (errors / hesitation_contexts / idioms
/ areas_to_work_on / inappropriate_behavior — see `debrief_generator`). The
backend owns everything deterministic and computable: the survival %, the
hero fields (character + scenario title, attempt number, previous best), the
hesitation DURATIONS (measured from frame timing, merged onto the LLM's
contexts by index), and the encouraging framing (FR15b). These functions are
PURE (no I/O) so they unit-test directly.

Assembly happens once, in the bot's call-end teardown — the fully-assembled
debrief is stored in `debriefs.debrief_json` and `GET /debriefs/{call_id}`
returns it verbatim. `previous_best` / `attempt_number` / the framing are all
fixed at call time (they describe THIS attempt), so freezing them in storage
is correct and keeps the read path a trivial lookup.
"""

from __future__ import annotations

import math
from typing import Any

# FR15b — the encouraging-framing section is shown ONLY above this survival
# threshold; at or below it the field is omitted entirely (null fields omitted
# convention) so the client hides the section.
_ENCOURAGING_FRAMING_MIN_PCT = 40


def compute_survival_pct(checkpoints_passed: int, total_checkpoints: int) -> int:
    """Backend-authoritative survival %: `floor(passed / total * 100)` (AC4).

    `floor()` (NOT round) so a green 100% appears only on a TRULY complete
    scenario. `total_checkpoints == 0` ⇒ 0 (no division-by-zero). Clamped to
    0-100 so a malformed (passed > total) count can never violate the
    `debriefs.survival_pct` CHECK.
    """
    if total_checkpoints <= 0:
        return 0
    pct = math.floor(checkpoints_passed / total_checkpoints * 100)
    return max(0, min(100, pct))


def compute_encouraging_framing(
    survival_pct: int,
    previous_best: int | None,
    character_name: str,
) -> dict | None:
    """Build the FR15b `{proximity, improvement}` framing, or `None`.

    Returns `None` (→ omitted from the debrief) when `survival_pct <= 40`. The
    framing is data-driven, never praise (per debrief-content-strategy Q1/Q9):

    - `proximity`: distance to a full survival (100% = every checkpoint met).
      Always present when framing is shown.
    - `improvement`: present ONLY when this attempt beat a prior best (a
      strictly-positive delta) — first attempts and non-improvements omit it
      rather than show a flat/negative number.

    NOTE: the exact copy is provisional — Story 7.3 owns the final debrief UX
    wording. The CONTRACT this enforces (present only when survival > 40, shape
    `{proximity, improvement}`, improvement optional) is what 7.3 consumes.
    """
    if survival_pct <= _ENCOURAGING_FRAMING_MIN_PCT:
        return None
    framing: dict[str, str] = {}
    gap = 100 - survival_pct
    framing["proximity"] = (
        f"{gap}% away from surviving {character_name}"
        if gap > 0
        else f"You survived {character_name}"
    )
    if previous_best is not None and survival_pct > previous_best:
        framing["improvement"] = f"+{survival_pct - previous_best}% since last attempt"
    return framing


def _merge_hesitations(hesitations: list[dict], hesitation_contexts: Any) -> list[dict]:
    """Merge backend-measured durations with the LLM's contexts BY INDEX.

    The bot passes the top-3 gaps (longest first) to the LLM, which returns
    `hesitation_contexts` in the SAME order; element i pairs with backend gap
    i. The client field is renamed `hesitations` (from the LLM's
    `hesitation_contexts`) and carries `{duration_sec, context}`. A missing /
    short contexts list degrades to an empty context rather than dropping the
    measured gap.
    """
    contexts = hesitation_contexts if isinstance(hesitation_contexts, list) else []
    merged: list[dict] = []
    for i, gap in enumerate(hesitations):
        context = ""
        if i < len(contexts) and isinstance(contexts[i], dict):
            # `or ""` (not a .get default) so an explicit null `context` on the
            # non-strict fallback path degrades to "" instead of the string "None".
            context = str(contexts[i].get("context") or "").strip()
        merged.append(
            {
                "duration_sec": round(float(gap.get("duration_sec", 0.0)), 1),
                "context": context,
            }
        )
    return merged


def assemble_debrief(
    *,
    core: dict,
    survival_pct: int,
    character_name: str,
    scenario_title: str,
    attempt_number: int,
    previous_best: int | None,
    hesitations: list[dict],
) -> dict:
    """Merge the LLM core + backend fields into the client-facing debrief (AC5).

    `core` is the validated `generate_debrief` output. `hesitations` is the
    backend-measured gap list `[{duration_sec, preceding_character_line}]`
    (top 3, longest first) — its durations merge by index onto
    `core["hesitation_contexts"]`. Shape mirrors
    `debrief-content-strategy.md` §"Complete Client-Facing Response":
    `encouraging_framing` is present only when `survival_pct > 40`.
    """
    debrief: dict[str, Any] = {
        "survival_pct": survival_pct,
        "character_name": character_name,
        "scenario_title": scenario_title,
        "attempt_number": attempt_number,
        "previous_best": previous_best,
        "errors": core.get("errors") or [],
        "hesitations": _merge_hesitations(hesitations, core.get("hesitation_contexts")),
        "idioms": core.get("idioms") or [],
        "areas_to_work_on": core.get("areas_to_work_on") or [],
        "inappropriate_behavior": core.get("inappropriate_behavior"),
    }
    framing = compute_encouraging_framing(survival_pct, previous_best, character_name)
    if framing is not None:
        debrief["encouraging_framing"] = framing
    return debrief
