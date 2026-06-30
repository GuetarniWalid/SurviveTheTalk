# Design Brief — "Survival Decoupling" (re-architect the patience/survival mechanic)

> **STATUS: SCOPING BRIEF — NOT A STORY.** Input for a future dedicated
> `/bmad-create-story` session (one agent per workflow). Produced by a 13-agent
> design exploration (2026-06-30, during the Story 10.8 dev session) after two
> live Pixel 9 calls (344/345) showed an ENGAGED learner getting hung up on the
> 20-beat Detective. Walid asked for "une archi forte et solide pour tous les
> cas, pas du rafistolage" + honesty about whether that is even achievable.
> Five competing architectures (engagement-decouple / two-meter / character-
> authority / holistic-rubric / conservative-signal-fix) were each adversarially
> stress-tested against a 12-case battery + the DNA + feasibility, then synthesized.

---

## 1. The problem (one line)

The patience meter **measures BEAT-PROGRESS** ("did you tick a beat?") but it
should **measure ENGAGEMENT** ("are you participating in good faith?"). Today the
drain is welded to `advance_goals().outcome == "fail"` (no flip + ≥1 `unmet`) in
`checkpoint_manager._classify_and_flip_goals` — which conflates *disengaged* with
*engaged-but-didn't-advance-the-pursued-beat*. So an engaged learner who: re-answers
a beat the character circled back to, hits a beat that doesn't fit their path,
asks for clarification, or is just a slow B1 — gets punished and eventually hung up
(calls 344/345). Lowering `fail_penalty` only slows the bleed of a mis-placed wound.

## 2. Verdict — is a "solid for all cases" architecture achievable?

**Yes, mostly — but NOT with a meter tweak; it is a contained signal-and-dispatch
redesign.** Honest caveats (these are real hard edges, not fantasy-killers):
- A mechanic fair to every **engaged** learner AND keeping the DNA (disengagement
  always loses) **is achievable on our exact stack** — no extra LLM call, no DB
  migration — by severing survival from beat-advancement and re-keying the drain on
  a good-faith-engagement signal the existing judge call can emit (the
  `__user_abusive__` precedent proves the wiring is free).
- **"Fair to EVERY case BY CONSTRUCTION" is NOT fully achievable.** Two cases stay
  honest hard problems: **gaming** (engaged-looking filler forever) can only be
  closed with a *bounded* re-coupling (a stall backstop) — acceptable, but it needs
  Walid's explicit blessing; and **STT word-salad garble** that reads as off-topic
  still drains (no survival redesign recovers information STT destroyed).
- **The #1 load-bearing risk:** the judge's accuracy on a NEW engagement axis is
  unproven (the "judge is accurate" grant was earned on `met`/`unmet`, not on
  good-faith/disengaged). Mitigation is mandatory: **ship the signal switched OFF
  first, log it on real calls, measure it on the 344/345 transcripts, THEN flip.**

## 3. Recommended architecture — a clean hybrid (Angle E spine + C's gaming lesson + R10)

**Change WHAT drains, not the meter math.** `patience_tracker.py` is UNTOUCHED.

- **One extra reserved boolean `__engaged__`** on the existing per-turn judge call
  (folded into the strict json_schema exactly like `__user_abusive__`; bump
  `_MULTI_MAX_TOKENS_BASE` 96→~112; missing/garbled parse → `True` = lenient, never
  fabricate disengagement). **No extra LLM call.**
- **New drain rule:** drain `fail_penalty` ONLY when a turn is non-advancing AND
  `__engaged__ == False` (off-topic / refusal / empty filler). Engaged-but-non-
  advancing (slow build, clarify, faithful re-answer, path-misfit, on-topic garble)
  → **patience-NEUTRAL**.
- **The re-answer fix (the only in-frame cure for the cop re-asking a met beat):**
  feed the judge the already-met beats as **read-only prompt context** (not schema
  keys) — "if the user faithfully re-answers a met objective the character circled
  back to, set `__engaged__:true`; emit no key for it."
- **Gaming defense (bounded, needs Walid's OK):** a `_no_progress_streak` counter,
  resets on ANY flip; below a per-difficulty `stall_grace` (easy 8 / med 6 / hard 4)
  → no drain on engaged turns; past grace → resume draining until a flip resets it.
  This *gates the ONSET* of drain (only ever touches engaged-no-flip turns) — it is
  NOT the rejected grace-counter (which softened an existing drain on good faith).
- **R10 construction lint:** a `success_criteria` must not demand a fact a COMMON
  coherent path makes non-existent (the cop's `lock_arrival_and_departure` two-clock-
  times beat is unsatisfiable for a stay-home alibi). Mechanically-detectable slice
  (paired motion-time demands) → builder reject + loader warn + commit test; the
  broader class stays builder guidance + smoke (same posture as R3/R7/R9). The
  engagement split stops the *drain* at runtime; R10 stops the *badgering* at build.

**Rejected:** the full two-meter rebuild (B — doubles the calibration surface, needs
client plumbing, worse degradation) and character-authority-as-spine (C — an
LLM-self-reported survival float breaks the model-agnostic law + golden-testability;
its gaming lesson is borrowed deterministically instead).

## 4. All 12 cases (synthesis verdict)

9 hold outright; case 3 holds at runtime (R10 finishes it at build time); case 5
mostly holds (word-salad-garble residual); case 10 (gaming) holds via the backstop.
No case loses that should hold; no case wins that should lose. **The headline win:
the drain no longer integrates beat-non-advancement, so arc LENGTH stops being a
death-multiplier — the exact call-344/345 fix, made structural (short 6-beat AND
long 20-beat both fair).** HUD ("X of N beats") = zero change; survival_pct formulas
unchanged (the number on a good-faith hang-up simply rises — more honest); debrief
breakdown unchanged.

## 5. Honest trade-offs / hard problems

1. `__engaged__` accuracy unproven & load-bearing → **shadow-launch + measure first** (mandatory).
2. Gaming re-couples non-advancement to an end-state (bounded) → needs explicit sign-off; `stall_grace` is a new load-bearing knob to calibrate.
3. STT word-salad garble stays partly open (orthogonal STT-confidence story); the 8s force-finalize truncation is untouched.
4. survival_pct semantics shift silently (good-faith partials end higher) — intended, but a deliberate product change.
5. Calibration/golden surface is REAL work (not free): a stateful `_no_progress_streak` is no longer a pure replay → `calibration_engine.py` must learn the engaged split + the streak (a dedicated streak-replay harness test), bump `ENGINE_VERSION`, ~5 new golden fixtures, a paid live sweep.
6. Glacial-but-nonzero gaming (refill-on-any-flip) named & deferred (a wall-clock term is the cure if it ever bites).

## 6. Scope for the eventual story (10.9) — server-only, zero client change

- **`exchange_classifier.py`** — `ENGAGED_KEY` constant; add to `_build_verdict_schema` properties+required; thread `met_goals`/`recently_met_block`; bump max-tokens; surface through `_parse_multi_classifier_output` (default `True`).
- **`prompts.py`** — `EXCHANGE_CLASSIFIER_MULTI_PROMPT`: the `__engaged__` good-faith-vs-disengaged principle (reuse the principle-7 anti-permissive wall so "engaged" can't be claimed for empty content) + `{recently_met_block}` + the re-answer principle.
- **`checkpoint_manager.py`** — de-weld the `outcome=="fail"` branch: pop `__engaged__` (next to `ABUSE_KEY`); engaged → neutral + `_no_progress_streak += 1` + stall-backstop drain only past grace; else → existing drain; reset streak on success. `advance_goals` / `judgeable_goals` stay byte-identical (golden==prod / no call-336 regression).
- **`scenarios.py`** — `stall_grace_turns` per-difficulty preset + override key + validator; the R10 lint helper (`find_path_dependent_criteria`) wired builder+loader+test.
- **Migration:** (1) add signal flag-OFF (`ENGAGEMENT_GATING_ENABLED=False`) → emit + log only; (2) shadow-validate on real calls; (3) flip ON + backstop; (4) R10 as a follow-up commit; (5) rollback = env flag, full revert = one commit. **No DB migration.**
- **Tests:** ~5 new golden fixtures (off-topic→`false`, re-answer→`true`/no-drain, clarify→`true`, path-misfit→`true`, refusal→`false`/drain, filler→`false`); `calibration_engine` engaged-split + streak replay; `ENGINE_VERSION` bump; re-confirm off-topic still loses + re-tune `stall_grace`; Pixel 9 smoke (slow-engaged cop must HOLD, off-topic must LOSE fast, gaming must END after grace, 6-beat waiter).

## 7. Explicitly OUT of scope / deferred

No second meter / no client change; no character-authority float; no `objective_group` HUD rollup; STT garble/truncation fixes (orthogonal); glacial-nonzero gaming; `fail_penalty` re-hardening (propose separately once good faith is exempt); debrief engagement-narrative polish.

---

**Reminder:** create the story in a DEDICATED `/bmad-create-story` session (one agent
per workflow). This brief is the springboard, not the spec — Walid still owes an
explicit decision on the gaming stall-backstop, and the shadow-measure-before-flip
sequence is non-negotiable.
