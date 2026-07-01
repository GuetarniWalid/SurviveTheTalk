# SPIKE BRIEF — "Character-led conversation" (throwaway experiment, NOT a story)

> **STATUS: EXPERIMENT / SPIKE — NOT a BMAD story.** No sprint-status entry, no story
> lifecycle, no commit to `main`. Work on a **throwaway branch** (`spike/character-led`),
> deploy **temporarily** to the VPS, **revert** when done. Goal = answer one product
> question cheaply (~1h of live calls), then decide. Produced 2026-06-30 after Walid's
> doubt about the per-turn-judge + patience architecture (see
> `survival-decoupling-design-brief.md` and the create-story 10.9 discussion).

## The question this spike answers

Is a **free-flowing character with a life** (unconstrained length, holistic goal) + a
**post-call debrief** *better and simpler to author* than the live per-turn-judge + patience
meter? Specifically:
1. Does the conversation feel **more alive / natural / fluid**?
2. Does it still have **stakes** without the live meter — or does it feel stake-less?
   (This tells us whether character-led hang-up — Phase 2 — is needed.)
3. Is the **debrief** still meaningful when it's the only assessment?
4. (Bonus) Was the scenario **easier to reason about** with the machinery gone?

## What stays UNTOUCHED (the working 80%)
STT (Soniox), the character LLM, TTS, LiveKit transport, the bot pool, the debrief
generator, user-initiated hang-up, abuse detection. **Do not refactor the pipeline.** This
is additive/subtractive at two precise seams only.

## The minimal surgery (server-side, on the branch — gate behind a `SPIKE_*` env flag so it's a one-line revert)

1. **Unchain the character's length + per-beat steering.** Today the character speaks per
   the current beat's `prompt_segment` (short, steered). For the spike, stop injecting the
   per-beat steering and the length constraint; instead give the character ONE holistic
   instruction from its persona: *"You are <persona>. Your goal in this conversation is
   <goal>. Speak and behave naturally — as much or as little as a real person would. Stay
   in character and in-world."* Seams to find: `prompts.py` (character system prompt /
   `COHERENCE_CHARTER` / any length guidance), `checkpoint_manager.py`
   (`format_suggested_focus_block` / `_update_system_instruction` — the per-beat steering
   injection), `reply_sanitizer.py` (keep the never-silent floor; drop any length cap).
2. **Disable the checkpoint-fail patience drain.** In `checkpoint_manager.py` the drain is
   at the `advance.outcome == "fail"` branch (`apply_exchange_outcome(success=False)`,
   ~L1334). Behind the spike flag, make that branch **neutral** (no drain) — so
   non-advancement NEVER hangs up an engaged learner. **Keep** a coarse safety so a dead
   call still ends: the silence ladder (no speech at all) and any max-duration backstop, and
   abuse detection. Do NOT touch `patience_tracker.py` internals — just stop calling the
   checkpoint-fail drain.
3. **Keep the debrief as-is** (it already reads the full transcript). For Phase 1 don't
   change it; just look at whether it's still good when it's the only judge.

## Phasing (keep the FIRST test truly ~1h)
- **Phase 0 (optional, ~10 min, near-free):** feel the unconstrained character in a
  **text-only** playground (just the new character prompt, no pipeline) — does it feel more
  alive when not constrained? Cheapest possible signal before any deploy.
- **Phase 1 (the real test):** changes 1 + 2 on the **waiter** scenario (reuse the existing
  one), temp-deploy, 2–3 Pixel 9 calls. End the call manually (user hang-up) and read the
  debrief. Judge questions 1–4 above. **Do NOT perfect character-led hang-up yet.**
- **Phase 1b (optional):** also rewrite the waiter in the NEW prose style (persona + goal +
  when-they'd-hang-up + debrief rubric, no `success_criteria`/checkpoints) to feel the
  *authoring-simplicity* sub-question.
- **Phase 2 (only if Phase 1 feels right):** add **character-led in-character hang-up** — the
  character ends the call (existing exit-line mechanism) when satisfied / when the user
  wastes its time / on abuse. That's where "stakes without a meter" gets proven.

## Reversibility / safety (non-negotiable — the working pipeline must stay safe)
- Branch `spike/character-led` off `main`; **never commit the spike to `main`.**
- DB backup before any deploy (the standard pre-deploy snapshot).
- Everything gated behind `SPIKE_*` env flags → flip OFF to restore today's behaviour without
  a code change.
- Revert = redeploy `main` (one CI run). Confirm `/health` SHA back on `main` after.
- Walid approves the temporary VPS deploy (it's the live server) before it goes out.

## Out of scope (do NOT pull in)
Story 10.9's `__engaged__` signal, R10, the calibration/golden treadmill, any migration, any
client/HUD redesign. If the spike validates the direction, the *real* re-architecture becomes
a proper BMAD story afterward — this brief is just to get a cheap yes/no.

---

# SPIKE RESULTS (2026-07-01) — CONCLUDED. Verdict: PIVOT. → feeds a dedicated BMAD story (10.9).

Ran on a throwaway branch `spike/character-led`, temp-deployed to the VPS behind
`SPIKE_CHARACTER_LED` / `SPIKE_NO_FAIL_DRAIN` (both default OFF). **Reverted: VPS redeployed to
`main` 2026-07-01; spike code never merged.** Deploy history (spike-branch SHAs): 52a305c (P1) →
2ef4b27/3caa706 (P2) → 615a3d9 → 06385ed → f3234c0 → 976684f. Live-call evidence: calls 347–355.

## Phase 1 — VALIDATED (keep this)
Dropping the per-beat steering (`format_*_block`) + the checkpoint-fail patience drain made the
character feel clearly **more natural / alive / free-flowing** (Walid, multiple calls). This is
the keeper. Q1 = yes. Q2 (stakes) → see below.

## Phase 2 — character SELF-JUDGED hang-up: NOT VIABLE (this is the pivot)
Gave the character a self-emitted `<end_call>` marker to end the call itself when
satisfied / time-wasted / disrespected. Took **5 prompt iterations**, each chasing a live
failure: (1) cop never ends [persona "relentless" beats the rule] → (2) general OVERRIDE rule →
(3) thin-skinned on insults → (4) fabricated-accusation fix → (5) bare teardown (use the
character's OWN line). **Still failed** on call 355: user says "Shut up. It wasn't me." then
"Shut up." to the cop; the cop (authored "dry, patient, RELENTLESS… ALWAYS keeps the
interrogation moving, never argues") **absorbs both insults and never emits `<end_call>`.**

**Root cause (4 independent expert lenses converged):** asking the character to self-judge WHEN
to end is asking one forward pass to stay in a vivid, role-defining persona AND step out of it to
make a meta-decision that CONTRADICTS the persona AND emit a control token — all at once, on a
fuzzy probabilistic threshold. On a mid-tier model (gpt-4.1-mini) that resolves prompt conflicts
by **salience, not instruction hierarchy**, the thick concrete persona always outweighs the
abstract appended override. The 5 patches were nudging a distribution, not setting a rule — hence
"band-aid on a band-aid." No 6th wording fixes it. (The character writing the closing LINE — the
HOW — works fine; keep it.)

## THE PIVOT (Walid decided 2026-07-01) — split WHEN from HOW → this IS Story 10.9
- **The judge decides WHEN.** The per-turn checkpoint judge (`exchange_classifier.classify_multi`,
  already runs every turn, already emits `__user_abusive__` via `_build_verdict_schema`) gets ONE
  cheap added field — a disrespect/should-end score (e.g. `0=fine, 1=clearly dismissive ("shut
  up"), 2=genuine abuse`). The judge is a COLD third-person observer with no persona to defend, so
  it scores "Shut up" reliably where the in-character model won't.
- **The engine ENFORCES a countable threshold.** A per-character **"respect/patience budget"**
  (small integer in the scenario YAML: waiter≈1, detective≈2-3) is spent by the engine on each
  disrespectful turn; when it hits zero the engine fires the EXISTING `schedule_character_led_bail`
  (same wiring as the abuse path: `verdicts.pop(...)` in `checkpoint_manager`). "Two shut-ups to a
  cop → end" becomes a hard, **unit-testable** rule, not a prose hope.
- **The character keeps the HOW.** The bail already tears down using the character's OWN punchy
  sign-off (spike iteration 5). Keep that.
- **Learner protection is BETTER, not worse:** a narrow "was this dismissive?" classification
  separates a fumbling B1 from real contempt better than a role-player can; + per-character grace
  budget + a mandatory WARNING turn before any hang-up + count only CLEAR dismissal. Fail-OPEN on
  the ~2% judge timeout (a missed turn keeps the call alive — never a wrongful hang-up).

**Trade-off to state out loud (surface-tradeoffs rule):** the character does NOT decide
everything — **the ENGINE owns WHEN, the character owns HOW.** The budget is a small cousin of the
old patience meter, but it is a **respect/engagement** budget, NOT the beat-progress fail-drain
Phase 1 removed. This is exactly the [[project_survival_decoupling_10_9]] direction.

**Cost:** ~1 field on an LLM call already paid for (negligible latency/$); reuses the
abuse-flag→`schedule_character_led_bail` plumbing that already ships. The real work is
CALIBRATION: shadow-launch flag-OFF, log the disrespect score on real transcripts (353/354/355),
tune per-character budgets, then flip ON — plus a golden fixture ("two shut-ups to the cop → bail
fires") + fail-fast lint so it can't silently rot.

## NEXT STEP (one-agent-per-workflow) — NOT done in the spike session
Open a **dedicated `/bmad-create-story`** for Story 10.9 (judge-scored disrespect field +
engine-counted per-character respect budget + character-delivered sign-off, shadow-then-flip).
Full expert synthesis + 4-lens assessment archived in the spike session workflow
(`spike-pivot-assessment`, run wf_dd18f293-891). The `spike/character-led` branch stays on origin
as a throwaway reference (safe to delete); never merge it.
