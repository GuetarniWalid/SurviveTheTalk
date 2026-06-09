# Story 6.27: Checkpoint crediting robustness — superset-overlap back-fill + judge resilience

Status: backlog

> **Surfaced by the Story 7.1 Pixel-9 smoke gate (2026-06-09, call_id=266, scenario `waiter_easy_01`).** Walid completed 5 of 6 checkpoints, but the FIRST checkpoint (`greet`) never credited and the character never "came back" to it — he hung up himself at 5/6. He suspected a regression of Story 6.21 (the character returns to the lowest unmet beat). A 7-agent diagnostic workflow (log-evidence + code-audit + git-history bisect + 3 adversarial verifiers, all run against the prod call-266 journal + current `main`) returned a **HIGH-confidence verdict: NOT a regression** of 6.21 / 6.10 / 6.23 — the engine code is intact. The real cause is a latent **scenario-design fragility** (a superset criteria overlap), amplified by two LLM-behavioural misfires and a difficulty aggravator. This story is the "état des lieux" + the durable fix.

> **⛔ This is NOT a regression-fix story. Do NOT touch the Story 6.21 steer-back or the `judgeable_goals` gating — both were verified correct in current `main` (file:line below).**

---

## Why "two mechanisms both failed" is still NOT a regression (read this first)

The intuition — *"TWO safety mechanisms both failed, so something must have regressed"* — is reasonable, but it treats both mechanisms as deterministic code. They are not; **both are LLM-dependent**:

- **Mechanism 1 — the checkpoint judge** is an **LLM verdict** (Groq Scout, `classify_multi`). The *code* that feeds `greet` to the judge every turn worked perfectly — greet was in the judge payload on every pending turn (verified). The judge *model* simply returned the wrong/ambiguous answer for `greet` on a sentence that should arguably pass it. An LLM judge giving an imperfect verdict is not a code regression — Scout benches ~92%, never 100%.
- **Mechanism 2 — "return to the lowest unmet beat" (Story 6.21)** is a **steering PROMPT**, not a hard control. The *code* that composes the steering correctly pinned the character on `greet` (verified: the boot `system_instruction` literally targeted greet's `prompt_segment`). But the steering can only *ask* the character LLM to pursue greet — it cannot *force* it. The character *model* ignored the pull and kept advancing.

So **both mechanisms did their coded job; the two LLMs behind them made imperfect calls.** A regression = code that used to work and now does not. Here the code is unchanged and correct — `greet`'s success_criteria is **byte-identical in git from before Story 6.21 to HEAD**. Nothing changed; this failure path was always possible. The 7.1 smoke gate is simply the first time it was *seen*, because Epic 7 finally surfaces the checkpoint outcome in a debrief.

**The deeper structural cause that made BOTH LLMs fail on the SAME beat:** `greet`'s criteria is a strict logical **SUPERSET** of `main_course`'s (below). That overlap sets the trap; the two LLM misfires just walked into it.

---

## État des lieux — exactly what happened on call_id=266 (`waiter_easy_01`)

STT was clean on every turn (no garbling). Turn-by-turn, reconstructed from the prod journal (process `python[1144623]`):

| Turn | User said (clean STT) | Judge result | Cumulative met set |
|---|---|---|---|
| 1 | "Hi, good evening. Could I see the menu, please?" *(satisfies `greet`: "asks for the menu")* | ⚠️ classifier **ReadTimeout** → inconclusive, **nothing judged** | `[]` |
| 2 | "Hmm, I have the grilled chicken, please." | credits `main_course`(1) + `clarify`(2) **but NOT `greet`(0)** | `[1,2]` |
| 3 | "Grilled." | no flip | `[1,2]` |
| 4 | "Water." | credits `drink`(3) | `[1,2,3]` |
| 5 | "No, it's right." | credits `confirm`(4) | `[1,2,3,4]` |
| 6 | "Okay." | credits `close`(5) | `[1,2,3,4,5]` |
| 7 | "Thank you." | no flip (only `greet`(0) remains) | `[1,2,3,4,5]` |

Final: **5/6, `greet` (index 0) permanently unmet.** Walid hung up. The **same turn-1 ReadTimeout on the identical opening line also occurred on the prior attempt call_id=265** → reproducible, not a one-off.

---

## Root cause — three compounding factors + one aggravator (none is an engine regression)

1. **🟠 PRIMARY — the superset criteria overlap (scenario design; predates 6.21).**
   `greet` criteria = *"...states they want to order, asks for the menu, ... **or names a food item**."* `main_course` criteria = *"**names a specific dish**."* So *naming a dish satisfies BOTH* — `greet` ⊇ `main_course`. On "grilled chicken," the judge (applying the MULTI prompt's "must satisfy the SPECIFIC objective" + "default to UNMET in doubt") credited the **narrower** beat (`main_course`) and declined the **broader** one (`greet`) on the same text. Reproduced **2/2** (calls 265 + 266) → **deterministic**, not flaky. This clause is **byte-identical in git** from before Story 6.21 to HEAD (`git show 0a55283^ == 0a55283 == HEAD`) → a latent design fragility, not introduced by any story. Once a later beat is credited, `greet` can only recover if the user re-volunteers ordering intent while the already-moved-on character circles back — practically unwinnable.

2. **🟢 First-turn judge timeout.** The one turn that cleanest-satisfied `greet` ("Could I see the menu") hit an exchange-classifier ReadTimeout → patience-neutral, nothing judged. Same timeout on the same opening line in call 265 → a **cold-classifier slow-first-call** pattern. (Even without it, factor 1 would likely still strand greet — but this guaranteed greet got no verdict on its single strongest turn.)

3. **🟢 Character-LLM non-compliance.** The 6.21 steer-back fired (the boot prompt pinned the character on greet), but Scout ignored it and advanced ("Grilled or fried?", "And to drink?"); the generated hang-up line pursued sides, not a greeting. Steering "back to greet" is also semantically incoherent once the user has ordered everything — greet's `prompt_segment` is "reel off the menu so they can pick," which Tina already did on turn 1.

4. **🔧 AGGRAVATOR (config, working-as-designed) — hard difficulty on an easy scenario.** The call ran the **HARD** patience preset (initial 60 / fail −25 / recovery 0) because Walid picked **hard** globally — Story 6.19 *intentionally* lets a global pick override an easy-authored scenario. That is the difficulty selector working, **NOT a bug** — but on a "tutorial" easy scenario it left no runway (two −25 fails drove patience 60→35→10), converting a recoverable miss into a forced 5/6 hang-up.

---

## What is verified INTACT (do NOT touch)

- **Story 6.10 any-order judging** — `judgeable_goals` keeps every ungated pending beat (incl. `greet`, index 0, no `requires`) in the judge payload every turn (`checkpoint_manager.py:264-303`; payload build `:1033,1057-1060`). `greet` WAS judged each turn, not dropped.
- **Story 6.21 return-to-lowest-unmet** — steering composes from `pending_goals` (author order) and targets `pending_goals[0]` = the lowest unmet beat (`checkpoint_manager.py:255`, `:566-570`; recompose on every success turn `:1204/1329`; boot `bot.py:172`). Confirmed firing in the call-266 journal (boot prompt targeted greet).
- **Story 6.23 reactive gating** — irrelevant here (greet is index 0, cannot have a `requires`).
- The git-history "regression" nomination (echo-guard commit `04078d6`) was **FALSIFIED** by reading the journal: **zero** `checkpoint_echo_skip_while_bot_speaking` lines in call 266.

---

## Design Decisions — OPEN (Walid to resolve before `/bmad-dev-story`)

**D1 — the crediting fix (primary).** Stop a superset-earlier beat from being stranded when a subset-later beat is credited:
- **Option A (RECOMMENDED) — deterministic back-fill in `advance_goals`.** When a later beat B flips to met and an earlier still-pending beat A is logically *implied / subsumed* by B, auto-credit A by construction (code, not LLM). Robust, general, kills the whole class. Needs a declarative "B implies A" signal — e.g. an optional `implies: [earlier_id]` / `subsumes` edge on the later beat (a mirror of 6.23's `requires`), or a safe heuristic. `golden==prod` must adopt the same helper.
- **Option B — re-author `greet`'s criteria** so a bare dish name does NOT satisfy it (greet = pure intent-to-order / menu-request, EXCLUDING a dish name). Narrow (waiter-only); the superset class can recur in any builder-generated scenario.
- **Option C — a builder-time lint** flagging any earlier beat whose criteria is a superset of a later beat's, forcing the author to disambiguate at authoring time. Prevention, not cure (pairs well with A).

**D2 — judge resilience (secondary).** The first `classify_multi` call timed out on both attempts on the same opening text. Options: a **classifier warm-up ping at call start** (mirror `llm_warmup` / `tts_warmup`), and/or a **one-shot retry on the FIRST classify ReadTimeout**, so the opening turn is never silently lost.

**D3 — difficulty-on-tutorial UX (design conversation, NOT a bug).** Should a global "hard" pick apply to easy/tutorial scenarios, or should tutorials clamp to a gentler floor? Pure UX/product call.

---

## Acceptance Criteria (DRAFT — finalise after D1 is chosen)

- **AC1 (D1)** — On a dish-naming turn that credits `main_course` while `greet ⊇ main_course`, `greet` is credited the SAME turn (no manual re-engagement needed). Replaying the call-266 transcript ends **6/6** (or `greet` credited), pinned by a regression test.
- **AC2 (D1)** — `golden==prod`: the Story 6.15 calibration harness exercises the back-fill identically (same crediting choke point), and the golden net gains a superset-overlap assertion.
- **AC3 (D1 Option C)** — The scenario builder lints + flags any earlier beat whose criteria is a logical superset of a later beat's.
- **AC4 (D2)** — A first-turn classifier timeout no longer silently strands a beat (warm-up and/or one-shot retry), proven by a test that injects a single first-call ReadTimeout.
- **AC5 (D3, optional)** — Decision recorded on whether tutorial/easy scenarios clamp the difficulty floor.

---

## Evidence appendix

- **Diagnostic workflow (2026-06-09):** 7 agents — log-evidence + code-audit + git-history bisect + synthesis + 3 adversarial verifiers (scenario-design / code-actually-broken / evidence-gap lenses). Verdict: **HIGH-confidence "not a regression."** All three adversarial lenses confirmed the top-line; the scenario-design lens argued (correctly) that the superset overlap is the PRIMARY frame, which this story adopts.
- **Honest confidence caveat (from the evidence-gap verifier):** there is **NO per-goal verdict logging** anywhere in the codebase, so whether the turn-2 `greet` verdict was "unmet" vs "unsure" is *unknowable from logs* (it is an inference). This does NOT change the fix — the superset overlap is the lever either way — but **shipping classifier per-goal verdict logging** (a small add) would let `calibrate_scenario waiter_easy_01` reproduce this deterministically and confirm the exact judge behaviour. Worth folding into D2.
- **Key journal lines (call 266 / process `python[1144623]`):** turn-1 `exchange classifier HTTP error: (ReadTimeout)` → `checkpoint_classifier_inconclusive ... pending=6 (infra failure)`; turn-2 `checkpoint_advanced ... goals_met_indices=[1, 2]` (greet absent); final `checkpoint_unmet no_goal_flipped met_count=5 pending=1`. Hard preset confirmed in the boot log (`initial_patience=60 / fail_penalty=-25 / escalation=[30,0]` = `_DIFFICULTY_PRESETS['hard']`).

## References

- Story 7.1 smoke gate (call_id=266) — where this surfaced; the 7.1 debrief backend itself was confirmed working.
- Stories **6.10** (any-order crediting), **6.21** (return-to-lowest-unmet, commit `0a55283`), **6.23** (`requires` reactive gating, the pattern Option A would mirror) — all verified intact.
- `server/pipeline/scenarios/the-waiter.yaml` — `greet` vs `main_course` criteria (the superset).
- `server/pipeline/checkpoint_manager.py` — `judgeable_goals`, `pending_goals`, `advance_goals`, steering compose; `server/pipeline/exchange_classifier.py` — `classify_multi`, `_multi_max_tokens`, the ReadTimeout path; `server/pipeline/scenarios.py` — `_DIFFICULTY_PRESETS`.
- Memory: `feedback_latency_kill_criterion_exceeded` (PRD 2 s ceiling), `infra_groq_capacity_and_scout_fallback` (Scout judge limits), `project_reactive_checkpoint_gating` (the 6.23 `requires` model Option A would mirror).
