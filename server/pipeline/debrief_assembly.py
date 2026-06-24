"""Story 7.1 — pure backend assembly of the client-facing debrief.

The LLM produces only the analysis core (errors / hesitation_contexts / idioms
/ areas_to_work_on / inappropriate_behavior — see `debrief_generator`). The
backend owns everything deterministic and computable: the survival %, the
hero fields (character + scenario title, attempt number, previous best), the
hesitation DURATIONS (measured from frame timing, merged onto the LLM's
contexts by id, Story 7.5 C3), and the encouraging framing (FR15b). These
functions are PURE (no I/O) so they unit-test directly.

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
    """Pair each backend-measured gap to the LLM's situational context BY ID.

    Story 7.5 C3 — the bot feeds each gap's `id` to the LLM, which echoes it
    back as `hesitation_id`; we pair on that id, NEVER on list position (the v1
    by-index pairing mis-paired on a reordered/short contexts list). A gap with
    no matching context degrades to an empty context (the measured duration
    still shows); a context whose id matches no gap is dropped. Carries the
    client shape `{id, duration_sec, context, resolved, source}` — `source`
    defaults to "server" (the observer path; a device-measured gap arrives
    pre-tagged "device" per D3-c).
    """
    contexts_by_id: dict[str, str] = {}
    if isinstance(hesitation_contexts, list):
        for c in hesitation_contexts:
            if isinstance(c, dict):
                hid = c.get("hesitation_id")
                if isinstance(hid, str) and hid:
                    # `or ""` (not a .get default) so an explicit null context
                    # degrades to "" instead of the string "None".
                    contexts_by_id[hid] = str(c.get("context") or "").strip()
    merged: list[dict] = []
    for gap in hesitations:
        gid = gap.get("id")
        merged.append(
            {
                "id": gid if isinstance(gid, str) else None,
                "duration_sec": round(float(gap.get("duration_sec", 0.0)), 1),
                "context": contexts_by_id.get(gid, "") if isinstance(gid, str) else "",
                "resolved": bool(gap.get("resolved", True)),
                "source": str(gap.get("source") or "server"),
            }
        )
    return merged


def _pin_focus(areas: list[dict]) -> list[dict]:
    """Story 7.5 D-c/B5 — the BACKEND marks area #0 as the focus-first area
    (`is_focus`), never the weak model. Priority order is the LLM's order."""
    return [{**area, "is_focus": index == 0} for index, area in enumerate(areas)]


def assemble_debrief(
    *,
    core: dict,
    survival_pct: int,
    character_name: str,
    scenario_title: str,
    attempt_number: int,
    previous_best: int | None,
    hesitations: list[dict],
    checkpoints: list[dict] | None = None,
    degraded: bool = False,
) -> dict:
    """Merge the LLM core + backend fields into the client-facing debrief (v2).

    `core` is the validated `generate_debrief` output (v2 shape: errors with
    `explanation`/`examples`, `better_phrasings`, rich `areas`,
    `hesitation_contexts` keyed by `hesitation_id`). `hesitations` is the
    backend-measured gap list `[{id, duration_sec, preceding_character_line,
    resolved, source?}]` — paired to the LLM contexts BY ID. `checkpoints` is
    the bot's teardown goals state `[{id, hint, met}]` (Story 7.5 B7 — the
    factual decomposition of the survival %, NOT LLM-generated); defaults to
    `[]` until the teardown threads it (Task 3.2).

    Story 7.5 v2 is additive: `debrief_version: 2`, `checkpoints`,
    `better_phrasings`, and the rich `areas` (with backend-pinned `is_focus`)
    ride alongside the retained `areas_to_work_on` (DERIVED from the area
    titles so old clients keep a flat list). `encouraging_framing` stays present
    only when `survival_pct > 40` (key omitted otherwise).

    `degraded=True` (the teardown's never-blank fallback — `core` is the empty
    `debrief_generator.degraded_core`) adds the `degraded: true` marker so the
    client renders a score-only report ('detailed analysis unavailable') instead
    of implying a flawless call. The key is OMITTED when False so a normal
    debrief's stored JSON is byte-identical to pre-fallback.
    """
    areas = _pin_focus(core.get("areas") or [])
    debrief: dict[str, Any] = {
        "debrief_version": 2,
        "survival_pct": survival_pct,
        "character_name": character_name,
        "scenario_title": scenario_title,
        "attempt_number": attempt_number,
        "previous_best": previous_best,
        "errors": core.get("errors") or [],
        "hesitations": _merge_hesitations(hesitations, core.get("hesitation_contexts")),
        "idioms": core.get("idioms") or [],
        "better_phrasings": core.get("better_phrasings") or [],
        "areas": areas,
        # Back-compat: old clients + old-row readers key on the flat title list.
        "areas_to_work_on": [area["title"] for area in areas],
        "checkpoints": list(checkpoints or []),
        "inappropriate_behavior": core.get("inappropriate_behavior"),
    }
    framing = compute_encouraging_framing(survival_pct, previous_best, character_name)
    if framing is not None:
        debrief["encouraging_framing"] = framing
    if degraded:
        debrief["degraded"] = True
    return debrief
