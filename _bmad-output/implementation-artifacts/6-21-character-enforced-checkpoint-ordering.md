# Story 6.21: Character-enforced checkpoint ordering (universal guided flow)

Status: review

> Design decisions RESOLVED with Walid 2026-06-04 — see `## Design Decisions`. This is **THE** fix for the consigne↔character desync. Story 6.20 is reduced to its independent robustness items (the HUD "frontier" idea was dropped — see below). Nothing coded yet.

## Story

As the learner,
I want the character to keep guiding me through the scenario **in order** — crediting anything I answer ahead of time (so it never repeats itself) but always bringing me back to the **next step I still have to do** —
so that the on-screen step always matches what the character is actually asking.

## Background

**The app's purpose is to guide the user through a WRITTEN, ORDERED scenario.** There is no free-roam / storyless mode — every scenario follows its script. Story 6.10's "any order" was **only ever meant to stop the character from re-asking something the user already answered** (e.g. the user orders a glass of water early → we credit that checkpoint so the character doesn't dumbly re-ask "and to drink?"). It was **never** meant to let the conversation wander out of narrative order.

**The desync (call_id=216) — correctly diagnosed.** The on-screen consigne (the lowest still-unmet step) was actually **right**. The bug was the **character**: it is only *softly* steered (`format_suggested_focus_block` says "the natural next focus is X… if the conversation flows toward another remaining objective, accept that and circle back later"), so it roamed ahead of the step the consigne showed. So the fix is NOT to move the display forward (that was the wrong direction — dropped from Story 6.20); the fix is to make the **character follow the order** the consigne already reflects.

**The fix (Walid).** Universally, for every scenario: the character **credits** any step the user volunteers ahead of time (keep 6.10's anti-repetition win — the met goal leaves the pending set so the recomposed prompt won't pursue it) **but pursues strictly in order** — after acknowledging what the user just gave, it **returns to the lowest still-unmet step and does not advance until it is addressed**, firmly but fluidly (in-character, not a robotic refusal). The HUD keeps showing the lowest unmet step (today's behavior). Then **consigne == what the character pursues, by construction.**

**Out of scope:** difficulty/patience calibration; the any-order **crediting** logic (`classify_multi` / `advance_goals`) — UNCHANGED; the Story 6.20 robustness items (separate). This is a **character-steering** change.

## Design Decisions (RESOLVED 2026-06-04 with Walid)

1. **Ordering is UNIVERSAL and STRICT — no flag, no mode.** Every scenario is guided in order. There is no `any | strict` choice (my earlier per-scenario-flag framing was wrong): the app always guides through a written script. (This retires the D1/D5 "granularity/default" questions entirely.)
2. **Crediting stays any-order (anti-repetition).** If the user volunteers a later step's info, it is credited (flipped `met`) and the character must NOT re-ask it. `classify_multi` / `advance_goals` are untouched; the COHERENCE_CHARTER's "don't re-ask confirmed items" rule already backs this.
3. **Enforcement = FIRM but FLUID.** The character acknowledges what the user just gave, then redirects back to the lowest unmet step and holds there — in-character, conversational, NOT a flat robotic refusal (avoids the robot/loop feel + bad patience interplay).
4. **HUD shows the lowest unmet step (unchanged).** Because the character now pursues exactly that, the displayed consigne matches the character. **Story 6.20's "frontier" display change is DROPPED** (it pushed the display the wrong way — forward — when the character should go back).
5. **Completion / "missed" objective.** Since the character always returns to the lowest unmet step, steps are completed in order and `all_met` stays reachable. A user who never complies despite repeated redirects simply runs the meter down → existing patience hang-up. No special "skipped-objective" handling needed; the future Epic 7 debrief can report met/total.

## Acceptance Criteria (BDD)

### AC1 — Universal ordered pursuit (firm but fluid)
Given any scenario (all are guided/ordered)
When the system instruction is (re)composed for a turn
Then the character is steered to pursue its objectives **in author order**: address the **lowest still-unmet** objective next, and — if the user has volunteered a later objective — **acknowledge it briefly then bring the conversation back to the lowest unmet one, not advancing until it is addressed.** The steering is firm but in-character (no robotic refusal), and `COHERENCE_CHARTER`-governed.

### AC2 — Credit-ahead preserved (anti-repetition)
Given the user volunteers information for a later checkpoint
When the classifier credits it
Then that checkpoint flips to `met` (any-order crediting UNCHANGED) and drops out of the pending set, so the recomposed prompt no longer pursues it and **the character never re-asks it** (the 6.10 "no dumb repetition" win is preserved).

### AC3 — Consigne matches the character (no frontier)
Given the character now pursues the lowest unmet step
When the HUD renders the active step
Then it shows the **lowest unmet** checkpoint (today's behavior) + the ticks of any out-of-order completed steps — and this matches what the character is asking. **No frontier / skip-ahead display is applied** (Story 6.20's frontier change is not shipped).

### AC4 — No regression
Given the existing goal-based engine
Then `classify_multi` / `advance_goals` (crediting), the per-flip `checkpoint_advanced` envelope, the terminal-turn sync (Deviation #7), `survival_pct` (Deviation #1), and the COHERENCE_CHARTER composition all behave as today; existing server + client checkpoint tests stay green. Scenarios now guide coherently in order while still crediting ahead.

### AC5 — Pre-commit gates
Server: `ruff check . && ruff format --check . && pytest` green. Client (only if the HUD rule is touched to confirm lowest-unmet): `flutter analyze` + `flutter test` green.

### AC6 — Validation (smoke gate)
On a cop call: answer a **later** beat first → it ticks (credited) **and** the cop acknowledges it then **returns to the skipped earlier beat** (firm but fluid), not moving on; the consigne tracks the lowest unmet beat throughout. On a Waiter call: ordering the drink early is credited and **never re-asked**, while the character still walks the order in sequence. An in-order run flows normally and can reach `survived`.

## Tasks / Subtasks

- [x] **Task 1 — Firm-but-fluid ordered steering (AC1, AC3)** — rewrite `format_suggested_focus_block` (`checkpoint_manager.py:140-151`) and the header of `format_remaining_goals_block` (`:129-137`) from the soft "any order / circle back later" into a FIRM, universal instruction: *"Address your objectives in order. The next one to cover is `<pending_goals[0]>`. If the user has already given information for a later objective, treat it as noted (do not ask it again) and bring the conversation back to `<pending_goals[0]>` now — do not move on until it is addressed."* In-character, charter-governed, no robotic refusal. Uses `pending_goals[0]` (already available); relies on the charter for "don't re-ask."
- [x] **Task 2 — Confirm crediting unchanged (AC2)** — leave `classify_multi` / `advance_goals` untouched; add/keep a test proving an out-of-order met goal is credited + removed from `pending_goals` (so the recomposed prompt can't re-ask it).
- [x] **Task 3 — HUD shows lowest unmet (AC3)** — confirm `checkpoint_snapshot.dart` `activeIndex` = lowest unmet (today's behavior). Coordinate with Story 6.20: ensure 6.20 does NOT ship a frontier rule; if it somehow did, revert to lowest-unmet. Likely **no client change needed**.
- [x] **Task 4 — Tests (AC1, AC2, AC4)** — server: the recomposed system instruction contains the firm ordered-pursuit + "don't re-ask" framing and names `pending_goals[0]`; crediting-ahead drops the goal from pending. Mirror existing `test_checkpoint_manager` / `test_bot_pipeline_wiring` patterns.
- [x] **Task 5 — Pre-commit gates + smoke gate (AC5, AC6).** — Server pre-commit gates GREEN (ruff check + ruff format clean, full pytest 616 passed). AC6 device smoke gate (the "Smoke Test Gate" section below) is the Walid-owned Pixel 9 cop call — reserved for `review → done` per Story 6.5 D6.

## Dev Notes

**Code references:**
- `server/pipeline/checkpoint_manager.py:140-151` `format_suggested_focus_block` (the soft block → make firm + ordered), `:129-137` `format_remaining_goals_block` ("any order" header → "in order"), `:154-186` `compose_goal_system_instruction` (composition; charter slots between base and objectives — unchanged position), `:418-422` `pending_goals` (author order; `pending_goals[0]` = lowest unmet), `:235-257` `advance_goals` + `classify_multi` (crediting — **DO NOT change**), `:873-897` `_last_character_line` (available if the prompt needs "what was just said").
- `client/lib/features/call/views/widgets/checkpoint_snapshot.dart` `activeIndex` — must remain "lowest unmet" (do NOT adopt a frontier rule).
- `server/pipeline/prompts.py` `COHERENCE_CHARTER` — already enforces "don't re-ask confirmed items" (backs AC2).

**Reuse / do-not-reinvent:**
- The any-order **crediting** already prevents re-asking (a met goal leaves `pending_goals`, so the recomposed prompt won't pursue it) — reuse it untouched; this story only firms up the **pursuit** steering.
- The COHERENCE_CHARTER already carries the "no repetition / history-wins" rules — the firm ordered-pursuit line rides through the existing composition (no new charter, no position change).

**Gotchas (do NOT trip these):**
- **Do NOT change the crediting (`classify_multi`/`advance_goals`)** — that would re-introduce the 6.10 LLM-drift / unfair-fail problem AND break anti-repetition. Only the *pursuit* prompt changes.
- **Firm ≠ robotic.** The character must acknowledge what the user gave (so it doesn't feel deaf) before redirecting — otherwise it reads as a broken loop and interacts badly with patience.
- **Patience interplay** — a "held" beat the user keeps not-hitting must re-ask in-character, not silently fail every turn. Validate on the smoke gate that a held beat doesn't drain patience faster than a normal off-topic turn.
- **No frontier display** — keep the HUD on lowest-unmet; do not let Story 6.20 introduce a forward-jumping active step (the two must not fight).
- Relates to but is distinct from Story 6.12 "Reactive Character Mood" (async reaction lag) — don't conflate.

### Project Structure Notes
- Server-side prompt/steering only (`checkpoint_manager.py`); client likely untouched (HUD already shows lowest-unmet). No DB migration, no scenario-schema change (universal — no flag).
- Not in `epics.md` — design-surfaced story (same path as 6.18/6.19/6.20).

### References
- [Source: Story 6.20 `6-20-*.md` — its independent robustness items; its frontier-display idea was dropped in favor of this story]
- [Source: Story 6.10 `6-10-goal-based-dialogue.md` — why crediting must stay any-order (anti-repetition), and why strict CREDITING was abandoned]
- [Source: alignment audit 2026-06-03 — the desync is character-roam, not display]

## Smoke Test Gate (Server / Deploy Story)

- [ ] **Deployed** to the VPS (`deploy-server.yml` git_sha match).
- [ ] **Ordered pursuit (the core):** on the cop scenario, answer a *later* beat first. The cop must **credit it** (HUD ticks) **and** acknowledge it then **return to the skipped earlier beat**, not move on. _Proof:_ device + `journalctl … | grep checkpoint_advanced` (later goal flips) + the cop audibly returns to the earlier beat.
- [ ] **Anti-repetition (the 6.10 win preserved):** volunteer a later beat's info → the character does NOT re-ask it later.
- [ ] **Consigne coherence:** the on-screen step tracks the lowest unmet beat and matches what the character asks, throughout.
- [ ] **Firm but fluid / no unfair drain:** the redirect is in-character (acknowledges first) and the held beat doesn't tank patience faster than a normal off-topic turn.
- [ ] **In-order regression:** a straight in-order run flows normally and can reach `survived`.
- [ ] **Server logs clean** on the happy path.

## Dev Agent Record

### Agent Model Used
Claude Opus 4.8 (`claude-opus-4-8`), `/bmad-dev-story` under ultracode multi-agent orchestration.

### Debug Log References

### Completion Notes List

**Story 6.21 — character-enforced ordered pursuit (firm-but-fluid). Server steering-prompt change ONLY; client + crediting untouched.**

- **Task 1 (AC1, AC3):** rewrote the two shared prompt-builder helpers in `checkpoint_manager.py`.
  - `format_remaining_goals_block` header: soft *"you may pursue them in any order"* → firm *"listed in the exact order you must work through them, top to bottom: pursue the FIRST one below before any other, and move down only as each is covered. Anything already settled has dropped off this list…"*.
  - `format_suggested_focus_block`: soft *"The natural next focus is… circle back later"* → firm-but-fluid *"Right now the only objective you may pursue is: `<segment>` / Stay on it until it is genuinely addressed, and do not move on… If the other person has volunteered something that belongs to a later objective, genuinely take it in and react in character — a quick nod, a 'noted', a flicker of interest or irritation… so you never sound deaf or stuck in a loop; then, without re-raising anything already settled (the rules above keep you from that), ease the conversation back to it… firm and fully in character — in your own voice and register, never a robotic, word-for-word repeated refusal."*
  - Uses `pending_goals[0]` (lowest unmet, author order). Anti-repetition is DEFERRED to `COHERENCE_CHARTER` Rule 1, not re-implemented. Module docstring updated to describe firm pursuit (incl. *"soft pointer"* → *"FIRM pointer"*).
- **Task 2 (AC2):** `classify_multi` / `advance_goals` (crediting) left UNTOUCHED. A credited-ahead goal still drops out of `pending_goals`, so the recomposed prompt never pursues/re-asks it — proven by `test_suggested_focus_is_first_pending_in_author_order` (out-of-order `cp2` flip → `"prompt segment 2"` absent from the recomposed instruction) + `test_pending_goals_property_preserves_author_order`.
- **Task 3 (AC3):** confirmed `client/lib/features/call/views/widgets/checkpoint_snapshot.dart` `activeIndex` = first author-order not-yet-met (lowest unmet) — already correct. **NO client change.** Story 6.20's "frontier" idea is unshipped (`ready-for-dev`) → no conflict.
- **Task 4 (AC1, AC2, AC4):** updated the one pre-existing assertion pinning the old wording; added `test_ordered_pursuit_framing_in_every_system_instruction_swap` (asserts the firm ordered-pursuit framing + charter-deference + names `pending_goals[0]` at init AND after a flip). The held-beat (no-advance) invariant is already covered by `test_no_goal_matched_applies_fail_penalty` (`system_instruction == initial_prompt` on a no-flip turn).
- **Task 5 (AC5):** server gates GREEN — `ruff check` clean, `ruff format --check` clean (89 files), full `pytest` **616 passed** (615 → 616, +1 new test). Client gate not triggered (HUD untouched).

**Process (ultracode):** the firm-but-fluid wording was designed by a **4-lens design panel** (firmness / fluidity / token-economy / charter-integration) + a judge that scored each against AC1's six requirements and synthesised the winner. The implementation was then run through a **4-lens adversarial review** (AC-conformance / regression / prompt-behaviour / test-quality), every finding **skeptic-verified** → **7 findings, 0 confirmed defects**. Two real-kernel polish items the skeptic surfaced as strictly-better were applied: (1) persona-neutral redirect tone (was *"warm and human"*, wrong for the cold cop/mugger — and AC6's smoke gate IS a cop call), (2) the stale *"soft pointer"* module-docstring line.

**AC6 (device smoke gate) reserved for Walid** per Story 6.5 D6 — see the "Smoke Test Gate" section (still unchecked).

### File List
- `server/pipeline/checkpoint_manager.py` — **modified.** `format_remaining_goals_block` header + `format_suggested_focus_block` body rewritten to firm-but-fluid ordered pursuit; both function docstrings + the module docstring updated. (`classify_multi` / `advance_goals` / `pending_goals` / `compose_goal_system_instruction` UNCHANGED.)
- `server/tests/test_checkpoint_manager.py` — **modified.** Updated `test_suggested_focus_is_first_pending_in_author_order` assertions (new firm wording + AC2 credit-drop); added `test_ordered_pursuit_framing_in_every_system_instruction_swap`.
- `_bmad-output/implementation-artifacts/6-21-character-enforced-checkpoint-ordering.md` — Status + Tasks + Dev Agent Record + Change Log.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status `ready-for-dev` → `in-progress` → `review`.

- `server/pipeline/scenarios/cop-interrogation-01.yaml` — **modified (smoke-gate follow-up, call 221).** Loosened CP3 `respond_to_break_in_news` success_criteria to credit a clear yes/no said right after Mercer names the break-in (separate classifier-crediting layer; folded in).

_No client files changed (HUD already shows lowest-unmet). No new dependencies, no DB migration._

## Change Log
- 2026-06-04 — **Smoke-gate iteration (call_id=221, amended into the commit).** The 3 core behaviours PASSED on device (out-of-order credit: CP5 ticked while CP3/CP4 unmet; return-to-skipped-beat: *"Noted. Let's get back to why I called…"*; anti-repetition: 8:30 alibi never re-asked; cold persona + patience 90/90). A 3-lens adversarial analysis found ONE medium 6.21 leak — reply 4 appended later-objective probes (index6/7) while firmly pinned to an already-asked-but-not-yet-credited beat (CP3) → **hardened `format_suggested_focus_block`**: *"Raise EXACTLY ONE ask this turn — this objective only — and never tack on questions that belong to later objectives… if you have already asked this and their answer fell short, press or rephrase THIS objective rather than advancing."* Also folded a SEPARATE classifier-crediting fix (the root cause that left the cop pinned): loosened cop **CP3 `respond_to_break_in_news`** success_criteria to credit a clear yes/no said right after Mercer names the break-in (was over-strict on the anaphoric "a break-in"). Gates green: ruff + full pytest 616. Re-deployed for Walid re-test.
- 2026-06-04 — **/bmad-dev-story COMPLETE (in-progress → review).** Firm-but-fluid ordered-pursuit rewrite of `format_remaining_goals_block` + `format_suggested_focus_block` (`checkpoint_manager.py`); crediting (`classify_multi`/`advance_goals`) and the client HUD untouched (already lowest-unmet). Wording designed via a 4-lens design panel + judge; implementation passed a 4-lens adversarial review (each finding skeptic-verified → 7 findings, 0 confirmed; applied 2 strictly-better polish: persona-neutral redirect tone + stale "soft pointer" docstring fix). Tests: server 615 → 616 (+1). Gates GREEN: ruff check + ruff format clean + pytest 616. **AC6 device cop smoke gate reserved for Walid** (`review → done`, Story 6.5 D6).
- 2026-06-04 — Decisions RESOLVED + spec rewritten (Walid): ordering is UNIVERSAL strict (no flag — the app always guides through a written scenario); the only "soft" behavior is crediting-ahead to avoid the character repeating itself (6.10's real intent); the character pursues strictly in order, returning to the lowest unmet beat, firmly but fluidly; HUD stays on lowest-unmet (Story 6.20's frontier idea dropped). No open decisions — ready for `/bmad-dev-story`.
- 2026-06-03 — Initial draft (later corrected): had a per-scenario `any|strict` flag + a 6.20-frontier reconciliation; both removed 2026-06-04 after Walid clarified the app is always guided/ordered.
