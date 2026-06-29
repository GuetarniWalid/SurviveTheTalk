# Design Brief — "The Character is the Rail-Keeper" (Checkpoint ↔ HUD ↔ Conversation sync)

> **STATUS: SCOPING BRIEF — NOT A STORY.** This document is INPUT for a future
> `/bmad-create-story` session. The story itself must be created WITH the Scrum
> Master in that dedicated session (one agent per workflow), where we will dig
> much deeper. Do NOT treat the headings below as final acceptance criteria —
> they are the problem framing, the principle Walid endorsed, the worked
> examples, the tensions, and the open questions to explore together.
> Author: dev session 2026-06-26 (Gemini migration, Epic 10.6 follow-up).

---

## 1. One-line problem

The on-screen checkpoint HUD shows the user a "do this now" instruction that can
**contradict what the character is actually saying** — because the HUD is a
linear checklist anchored to the first uncredited beat, while the conversation
flows on. We need to make the **character keep the conversation on the authored
arc, in order**, so the HUD is in sync *by construction*.

## 2. The symptom (observed on-device)

Scenario **The Detective** (`cop_interrogation_01`, 20 checkpoints), call 336,
2026-06-26. The conversation itself was GOOD (no character bug):

```
[cop]  This is Detective Frank Mercer ... This call is being recorded. Do you have a minute?
[user] Yeah, sure, sir.
[cop]  Good. Can you confirm your full name for me, please? And your home address.
[user] my name is Getarny Walid, 16 Rue du Commerce.
[cop]  Walid, thank you. And the address, 16 Rue du Commerce. Is that correct?
[user] Yeah, correct.
[cop]  Thank you, Mr. Walid. There was a break-in at Halloran's Electronics ... Have you heard anything?
[user] no, nothing, sorry.
[cop]  Alright. Well, we found your fingerprints at the scene ... Were you involved?
[user] Not at all. It's not me.
```

Meanwhile the HUD kept showing the **first** checkpoint's instruction —
*"Confirm you're the person he named and acknowledge the call is being
recorded"* — the WHOLE time, even while the cop was on fingerprints (4 beats
later). The user is told to do one thing while the character is doing another →
total confusion. Walid: *"on a une consigne en même temps que la personne nous
parle et nous dit autre chose. Il y a un problème dans la conception."*

## 3. Mechanism (grounded in the logs + code)

- **Checkpoints credit out of order and some never credit.** Verdict timeline:
  `give_name_and_address` → met, `respond_to_break_in_news` → met, but
  `acknowledge_recorded_call` (beat 0) stayed `unmet` on EVERY verdict.
- **Why beat 0 stranded:** its `success_criteria` requires the USER to
  explicitly *acknowledge the recording* ("okay, understood") — something a real
  person never says, and the cop never re-asks. AND the character **fused** beat
  0 ("confirm you're the right person") with beat 1 ("give your full name") into
  one breath ("Can you confirm your full name?"), so the judge credited the name
  beat but never the acknowledge beat. Beat 0 became **unsatisfiable in practice**.
- **Why the HUD froze on it:** the server sends the client the full set of
  `goals_met_indices` + all `hints` (author order); the **Flutter HUD computes
  the active step locally** = effectively *"the first checkpoint not in
  goals_met_indices."* With `[1,2]` met and `[0]` not, it shows beat 0 forever.
  (See `checkpoint_manager.py::build_initial_envelope` / `_emit_checkpoint_advanced`,
  and the client `checkpoint_step_hud.dart`.)

**Net:** an early beat that never credits FREEZES the HUD behind the live
conversation. This is a property of the *model*, not of one bad scenario.

## 3b. CRITICAL — Prior art: Story 6.21 ALREADY decided this (NOT greenfield)

`6-21-character-enforced-checkpoint-ordering` is **done** (shipped 2026-06-04).
It is LITERALLY the rail-keeper principle, already resolved with Walid:

- The app guides the user through a **written, ORDERED** scenario — no free-roam.
- The HUD showing the **lowest-unmet** step is **correct by design**. Story 6.20's
  "frontier / push the display forward" idea was explicitly **DROPPED** as the
  wrong direction.
- The fix lives in the **character**: `format_suggested_focus_block` /
  `format_remaining_goals_block` were made FIRM — *"address objectives in order;
  if the user volunteers a later one, credit it (anti-repetition) but bring the
  conversation BACK to the lowest unmet and do NOT advance until it is
  addressed,"* firm-but-fluid. Crediting stays any-order (`classify_multi` /
  `advance_goals` UNCHANGED). Goal: *"consigne == what the character pursues, by
  construction."*

**So the new story is NOT "design the rail-keeper" — it is: "6.21's firm ordered
pursuit is NOT HOLDING on the 20-beat detective; find out why and make it
robust."** On call 336 the character did NOT hold beat 0
(`acknowledge_recorded_call`) — it jumped to the name beat. Lines to investigate:
  (a) the `opening_line` already voiced beat 0's content (recording + "do you
      have a minute?"), so the model believed beat 0 was done and moved on;
  (b) beat 0's `success_criteria` needs the USER to acknowledge the recording —
      unsatisfiable in natural flow + never re-elicited → it can never credit;
  (c) a weaker model (gemini-2.5-flash) may obey the firm-order block less
      reliably than the model 6.21 was validated on;
  (d) **a regression THIS session may have introduced — see §8 item 7.**

## 3c. Second live evidence (call 339, OpenAI) — the judge PUNISHES good turns

Even with the character model fixed (gpt-4.1-mini), a clean checkpoint failure
recurred and exposed a deeper coupling:
- User: *"I would like to know if it is possible to order?"* — which matches the
  `greet` success_criteria ("states they want to order"). The judge returned
  `greet: unmet`, ALL beats unmet, on every turn.
- This happened on nano AND mini → **NOT the model**; it is judge strictness /
  criteria interpretation (read "is it possible to order?" as a precondition
  question, not an order-move).
- **CRITICAL COUPLING:** every non-advancing exchange costs −15 patience
  (`fail_penalty`). So the judge's false-negative PUNISHED the user
  (100→85→70→55→40 in ~50 s) → impatience ladder → "Hello? Are you still there?"
  → user hung up. The silence prompt itself respected its 6 s timer; the call
  spiralled because the JUDGE wasn't crediting good turns and the patience meter
  treats every "unmet" as "the user is failing."

**Design implications for the story:** (a) judge/criteria accuracy is in scope —
a beat MUST credit a clearly-engaged turn, and the too-strict/too-loose swing
(greet missed here vs `drink` credited early in call 337) is the same defect;
(b) the patience meter must NOT punish the user for the judge's false-negatives
— decouple it, or only penalise genuine silence/refusal, never a mis-judged good
turn. This judge↔patience fragility is the same family as the checkpoint-crediting
issues and belongs in THIS story, not a per-scenario criteria patch.

## 4. The principle Walid endorsed — "the character is the rail-keeper"

The fix is NOT "let the HUD follow the conversation wherever it goes" (that was
the dev's first lean — Walid rejected it: it would collapse the authored arc,
skip planned beats, and lose content irreversibly). The fix is the inverse:

> **The character keeps the conversation ON the authored arc — one distinct beat
> at a time, IN ORDER — and steers back (never skips) when the user jumps ahead.
> The HUD is only a reflection of that arc; it has nothing to "catch up" to.**

Three required behaviours:

1. **Advance one DISTINCT beat at a time, in order.** Never fuse two beats into
   one breath; never jump ahead.
2. **If the user volunteers something from a later beat, take it in but steer
   back.** Remember what they said; raise the in-between beats anyway; and when a
   beat's turn comes for info already volunteered, **confirm it instead of
   re-asking** (don't lose it, don't loop).
3. **Hard order constraints are respected.** Some sequences are dramatic
   necessities, not suggestions (the cop CANNOT reveal fingerprints before
   identity is confirmed).

## 5. Why the ordering is sacred (Walid's rationale — do not "solve" it away)

- The authored arc has **meaning**: identity must precede accusation.
- If the user (or character) jumps ahead, the **planned middle beats are lost**
  and there is **no way back** — e.g. a waiter beat "will you cover your
  companion's bill?" placed before the drink order would simply never happen.
- A real conversation can branch, *"mais il faut que ce soit quand même un
  sens"* — bounded divergence, always returning to the arc.

## 6. Walid's three worked examples (carry these into the story)

- **Waiter, "fish + a Coke" said at once** (skipping a planned "pay for your
  companion?" beat): the waiter should NOTE it ("fish, got it"), still RAISE the
  pay-for-companion beat in order, THEN — for the drink — **confirm** the Coke
  rather than re-ask ("and the Coke to drink, yes?"). Nothing volunteered is
  lost; nothing planned is skipped.
- **User jumps to an end-of-arc answer:** the engine must NOT credit-and-skip the
  middle; the character walks the arc; the volunteered late info is remembered
  and confirmed when its beat arrives.
- **Cop, identity before accusation:** a hard ordering constraint — never
  surface a later beat before its prerequisite is genuinely done.

## 7. The two design rules that fall out

- **Conduct rule (engine / character):** advance one distinct beat at a time, in
  order; redirect on a jump; never fuse or skip; confirm-not-re-ask for
  already-volunteered info.
- **Construction rule (scenario authoring):** no two beats may be the SAME
  conversational moment (identity ≠ name), and **no beat may require something
  the natural flow won't produce** (the "acknowledge the recording" trap). This
  is largely **mechanically detectable** → a strong candidate for a new
  fail-fast barrier alongside the existing R1/R2 lints (see §10).

## 8. Hard tensions to resolve IN the story (the deep part — dig here)

1. **Collision with the just-shipped R4/R6 engine guards.** We just added a
   "never-silent floor" + an "always-drive / already-given" branch
   (`reply_sanitizer.py`, `checkpoint_manager.py::format_suggested_focus_block`).
   "Drive forward" must now mean **"drive the NEXT beat in order, holding the
   current one,"** not "advance freely." These must be *reconciled*, not removed.
2. **Naturalness vs rail-keeping.** "We'll get to that" redirects can feel
   robotic if overdone. How firmly does the character hold the rail before it
   reads as deaf/scripted? What is "bounded divergence"?
3. **Interaction with existing crediting semantics.** `requires` (reactive beats
   gate on a trigger, Story 6.23) and `implies` (a later beat back-fills EARLIER
   beats, the call_id=266 anti-strand fix) already shape out-of-order crediting.
   Does `implies` (back-fill earlier) *conflict* with "don't skip the middle"?
   Map how rail-keeping coexists with both before changing either.
4. **What should the HUD show, exactly?** Keep one "current beat" instruction
   (now always in sync if the character holds the arc)? How do
   stranded/overtaken beats resolve — passed, missed, skipped? How are
   genuine out-of-order completions (the dots) rendered without lying?
5. **Checkpoints serve two masters.** They are BOTH the survival/scoring gate
   AND the user-facing instruction. Rail-keeping may let us keep them unified —
   or the story may decide to split "what to do now" from "what has scored."
6. **The acknowledge-the-recording beat (and its kind).** Is it a beat that
   should exist at all? Symptom vs disease: fixing one criterion is a band-aid;
   the construction rule (§7) is the cure.
7. **The 10.6 "already-given" branch may have WEAKENED 6.21's firm-hold (possible
   live regression).** This session added a branch to `format_suggested_focus_block`
   (commit 1076258): *"if they have ALREADY given what this objective needs, do
   NOT re-ask and do NOT fall silent — keep the conversation moving."* That was
   for the judge-lag dead-zone. BUT if the model wrongly believes an unmet beat
   was "already given" (e.g. beat 0's recording-ack, voiced in the opening), this
   branch tells it to MOVE ON — directly contradicting 6.21's "hold the lowest
   unmet until addressed." Reconcile: the already-given branch should likely fire
   only when the beat is genuinely **credited/met**, not merely "believed given."
   Examine whether this is the proximate cause of the call-336 strand.

## 9. Open questions for the Scrum session

- Where does rail-keeping live — purely in the prompt/steering (the focus
  block), in the crediting engine, in the HUD, or a mix?
- How does the character "remember and confirm" volunteered-early info without
  re-asking (does the context already carry it, or do we need explicit state)?
- Can the construction rule (distinct + naturally-satisfiable beats) be a hard
  lint over the full `_SCENARIO_INDEX`, like R1/R2? What is mechanically
  detectable vs what stays builder-guidance + smoke?
- Does the survival/scoring math still hold if beats are guaranteed walked in
  order? Does that change calibration?
- Scope: is this one story or an epic (engine conduct + scenario construction +
  HUD rendering are three distinct surfaces)?

## 10. Constraints / what must NOT be broken (off-limits or reconcile-don't-remove)

- **`VERDICT_WAIT_BUDGET_MS` (800 ms) and any calibrated felt timing** — off-limits
  (Walid owns these; the dev's role is the model/AI + design, not calibration).
- **The judge HTTP/classifier timeouts (4.0/4.5 s)** — just set for the 20-beat
  scenario; leave unless the story has a reason.
- **The R4/R6 engine guards** (never-silent floor + always-drive branch) —
  reconcile with rail-keeping, do NOT delete.
- **golden==prod parity** for any sanitizer/credit change; the mood-tag wire
  envelope contract with the Rive client.
- **The R1–R7 rulebook** in `server/CLAUDE.md §9` and its three-layer enforcement
  pattern — extend it, don't bypass it.

## 11. Code & decision pointers (for the dig)

- `server/pipeline/checkpoint_manager.py` — `format_suggested_focus_block`
  (~188-223, the per-turn steering + the new "already-given" branch),
  `_emit_checkpoint_advanced` (~1397) + `build_initial_envelope` (~930) (the HUD
  envelope: `goals_met_indices` + `hints`), goal flip/credit logic.
- `client/...checkpoint_step_hud.dart` — the Flutter HUD that computes the active
  step locally from `goals_met_indices` + `hints` (where "first uncredited" is shown).
- `server/pipeline/exchange_classifier.py` — the per-turn multi-goal judge (the
  `met`/`unmet` verdicts; out-of-order crediting source).
- `server/pipeline/reply_sanitizer.py` — the never-silent floor (R4 guard).
- `server/pipeline/prompts.py` — `COHERENCE_CHARTER`, `MOOD_TAG_DIRECTIVE`.
- `server/pipeline/scenarios.py` — `find_model_specific_tokens` /
  `find_scripting_violations` (the R1/R2 lint pattern to mirror for the
  construction rule), `requires`/`implies` loader validation.
- `server/pipeline/scenarios/*.yaml` — `requires` / `implies` edges; beat order.
- `server/CLAUDE.md §9` — the R1–R7 rules + "THE DURABLE LESSON".
- Related prior decisions (read before changing crediting): Story 6.23 reactive
  `requires` gating; the `implies` back-fill (call_id=266 anti-strand); difficulty
  global-only (Story 6.28).

## 12. Rough success criteria for the eventual story (to refine with the Scrum)

- The HUD instruction never contradicts the live conversation.
- No planned beat is skipped or lost, regardless of what the user volunteers or
  in what order.
- Hard ordering constraints (identity → accusation) are always respected.
- Redirects feel natural, not robotic ("we'll get to that" is not spammed).
- Validated on a Pixel 9 smoke gate on the worst case (the 20-beat detective).

---

**Reminder:** create the story WITH the Scrum in a `/bmad-create-story` session.
This brief is the springboard, not the spec.
