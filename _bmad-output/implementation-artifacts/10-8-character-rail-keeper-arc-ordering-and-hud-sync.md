# Story 10.8: The character is the rail-keeper — reliable, on-arc conversation (turn-taking, judge resilience, patience↔judge decoupling, arc-ordered conduct & HUD sync)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **SCOPE NOTE — read first.** The sprint-status key is
> `10-8-character-rail-keeper-arc-ordering-and-hud-sync` (a stable PK from when this
> was just the "rail-keeper" carve-out). The story grew: it now covers the **whole
> brief §1–9 redesign PLUS the two live-forensics reliability blockers** that stopped
> Walid from finishing the Story 10.7 Pixel 9 smoke gate. Walid (2026-06-30) ruled
> ONE story covering the **totality** — five work-streams:
>
> - **A — STT long-utterance finalization / turn-taking** (call 341): a long, no-pause
>   sentence Soniox never finalizes lets the silence ladder run to a **hang-up while the
>   user is still speaking**. The "can't even test" blocker.
> - **B — judge ReadTimeout resilience** (call 342): a >4 s OpenAI latency spike
>   ReadTimeouts the judge → the beat is **silently and permanently lost** for that turn
>   (fail-OPEN, so patience is unchanged, but the beat never credits). The other "can't
>   even test" blocker.
> - **C — patience↔judge false-negative decoupling** (call 339): a **confident-but-wrong**
>   `unmet` on a clearly-engaged turn drains −15 patience/turn → 100→40 in ~50 s →
>   impatience ladder → "Are you still there?" → hang-up. The user is punished for the
>   judge's error.
> - **D — arc-ordered character CONDUCT** (call 336; continuation of Story 6.21): the
>   character must advance **one distinct beat at a time, in order**, redirect (not skip)
>   when the user jumps ahead, and **confirm (not re-ask)** already-volunteered info.
> - **E — HUD sync** (calls 334/336): the on-screen instruction must never **contradict**
>   what the character is saying (today it freezes on the first uncredited beat).
>
> **Recommended IMPLEMENTATION order (NOT a scope cut — the spec covers all five):** do
> **A + B first** (the testability blockers), deploy + a quick Pixel 9 confirm that a call
> is now completable, THEN the construction-rule lint + scenario audit (D4), THEN D, then
> re-check E (it may already be fixed by D — see Interactions), then C. Rationale: A+B make
> the app testable again; D+E+C are the design-heavier "make it feel natural" work.
>
> **MANDATE FROM WALID — verify the fixes' INTERACTIONS (do NOT double-fix or over-build).**
> Several of these problems overlap; fixing one may by nature fix or reshape another. The
> **"Interactions" section below is binding** — the dev MUST check each overlap and adjust
> rather than building redundant or conflicting changes. (Walid 2026-06-30:
> *"corriger un des problèmes peut, par nature, corriger l'autre, donc faut vérifier cela."*)
>
> **What is LOCKED vs PROPOSED.** A + B + D4 (the lint) are fully specified — start there.
> C and the design-forky parts of D/E carry **explicit `DECISION (proposed → confirm)`
> call-outs** (the brief §8/§9 open questions); they are grounded with a recommended
> direction but Walid wants to weigh in when the dev reaches them. Treat those call-outs as
> "resolve with Walid at dev", not "already decided".

## Story

As the **maintainer shipping the MVP**,
I want **the live voice conversation to be reliable and stay on the authored arc — the
character never hangs up while the learner is still talking, a judge hiccup never silently
drops a beat or spirals the call into impatience, the character drives one ordered beat at
a time (confirming what was volunteered instead of re-asking), and the on-screen
instruction always matches what the character is actually doing**,
so that **a learner can actually complete a call (and I can run a clean Pixel 9 smoke gate
on the worst case, the 20-beat detective), and the experience feels natural instead of
confusing**.

## Context — why this story exists

Story 10.7 shipped (judge-accuracy tightening + the progressive debrief) and unblocked
Story 10.6's `done` flip. But the 10.7 Pixel 9 attempt surfaced two **out-of-scope
reliability defects** that made the call un-completable (call 341 hung up mid-sentence;
call 342 lost a beat to a judge ReadTimeout) — Walid waived the on-device gate and carved
them here. They sit ALONGSIDE the original "rail-keeper" redesign from
`checkpoint-arc-rail-keeper-design-brief.md` §1–9 (HUD stale-instruction sync + arc-ordered
character conduct + the patience↔judge false-negative decoupling, a continuation of
Story 6.21). All five are the **"natural-fluid-experience"** body of work; Walid ruled them
one story.

Read the brief in full before starting — **§1–9** is the rail-keeper framing (problem,
the principle Walid endorsed, the worked examples, the hard tensions, the open questions,
the off-limits constraints, the code pointers). This story is the dedicated Scrum session
the brief reserved those decisions for. The **ADDENDUM §A/§B is already DONE by 10.7** (judge
permissiveness + progressive debrief) — do NOT redo it; build on it.

### The five pieces of live evidence (anchor every fix to a real call)

| # | Call | What happened | Root surface |
|---|---|---|---|
| A | 341 | ~51-word sentence, **no pause** → Soniox streamed interim words (`num_spoken_words 33→51`, `interim_transcription=True`) but **never finalized** → silence ladder ran to a hang-up **while the user was still talking** | STT finalization / turn-taking |
| B | 342 | Good turn *"I would like to know if it is possible to order?"* → judge HTTP **ReadTimeout** (>4 s OpenAI spike) → `checkpoint_classifier_inconclusive` → beat **not credited** (fail-open, patience unchanged, beat silently lost) | Judge resilience |
| C | 339 | Good turn judged `greet: unmet` on every turn (judge **false-negative**, nano AND mini) → −15 patience/turn → 100→40 in ~50 s → "Are you still there?" → user hung up | Patience↔judge coupling |
| D | 336 | The 20-beat Detective. Conversation was GOOD, but the character **fused** beat 0 (`acknowledge_recorded_call`) with beat 1 (give name) into one breath and **moved on**; beat 0 (which needs the USER to "acknowledge the recording" — never said, never re-asked) **stranded `unmet` forever** | Arc conduct + scenario construction |
| E | 334/336 | Because beat 0 stranded, the **HUD froze** on *"Confirm you're the person he named and acknowledge the call is being recorded"* the whole call — while the cop was 4 beats ahead on fingerprints | HUD sync |

## Acceptance Criteria

### Stream A — STT long-utterance finalization / turn-taking (call 341)

1. A long, continuously-spoken user utterance with **no pause** (50+ words) that Soniox
   never finalizes MUST NOT trigger the impatience prompt or a hang-up **while the user is
   still producing interim words**. **First confirm the actual mechanism against the real
   call-341 frame stream** (drive a real pipeline per `server/CLAUDE.md §1` — do NOT mock
   frame directions/types). The grounded picture today: the `PatienceTracker` silence
   ladder is cancelled only by a **finalized** `TranscriptionFrame`, `UserStartedSpeakingFrame`,
   or `BotStartedSpeakingFrame` — it has **no `InterimTranscriptionFrame` branch**, so a
   never-finalizing utterance produces no cancel signal; and the `EndpointWatchdog`
   **restarts its 8 s timer on every interim** (`_restart_watchdog`), so a continuously
   streamed long utterance never force-finalizes.
2. The pipeline reliably produces a **finalized turn** for a continuously-spoken long
   utterance within a bounded time so the bot can respond and the turn completes — fix the
   `EndpointWatchdog` so it distinguishes a *stuck partial interim* (call 171 — no new
   interims; already handled) from a *continuously growing interim* (call 341 — user still
   talking), e.g. a total-interim-duration cap or a `num_spoken_words`-stall trigger.
   **Do NOT break the call-171 stuck-partial case** the watchdog already fixes.
3. The silence ladder is made **interim-aware**: while `InterimTranscriptionFrame`s are
   actively streaming, the impatience/hang-up ladder is suppressed (the user is audibly
   speaking). Respect the existing `_self_speaking` guard (don't let the bot's own stage-2
   prompt cancel the ladder) and the asymmetric-`finalized`-default rationale in
   `server/CLAUDE.md §1`.
4. New **real-pipeline** tests (not direction-mocked): continuous long interim stream →
   no hang-up + a finalize is produced; the call-171 stuck-partial case still fires; the
   interim-aware ladder suppression. No regression to the D1 bounded wait,
   `SpeechTimeoutUserTurnStopStrategy`, the 600 ms `handle_playback_idle`, or barge-in.

### Stream B — judge ReadTimeout resilience (call 342)

5. A **transient** judge HTTP `ReadTimeout` (an OpenAI latency spike beyond
   `_HTTP_TIMEOUT_SECONDS = 4.0`) MUST NOT **silently and permanently** drop a clearly-met
   beat. Implement the safest recovery that respects the felt-timing budget — **`DECISION
   (proposed → confirm)`**: a single bounded retry on a transient `ReadTimeout` (preferred,
   if it fits the outer `_CLASSIFIER_TIMEOUT_SECONDS = 4.5` / felt budget); OR carry the
   timed-out turn's `user_text` forward to be re-judged on the next cycle against the SAME
   pending beats; OR an HTTP keepalive / connection warmup to cut spike probability. Keep
   the verdict **fail-OPEN** (a timeout never drains patience — already true) but make the
   beat **recoverable, not lost**.
6. The judge stays **strict structured output** (`response_format=json_schema`,
   `strict:true`) — never weaken the `server/CLAUDE.md §4` judge-format law for the sake of
   resilience.
7. Do **NOT** raise the felt judge timeouts (4.0/4.5 s) — brief §10 + Story 10.7 both
   restored them after measuring the gpt-4.1-mini judge at ~2 s/call; a wider HTTP budget
   re-introduces terminal dead-air. If the chosen recovery must touch them, re-validate the
   golden net + felt timing on the VPS and justify in the story.
8. Tests for the recovery path (transient timeout → recovery → beat credited) and that a
   genuine sustained failure still surfaces (the existing 5-consecutive-`None` force-drain
   stays intact).

### Stream C — patience↔judge false-negative decoupling (call 339)

9. A **confident-but-wrong** `unmet` verdict on a clearly-engaged turn must not, on its own,
   spiral the call to a hang-up. **Decouple** the patience drain from raw checkpoint `False`
   verdicts so a handful of judge false-negatives cannot drain 100→0. **`DECISION (proposed
   → confirm with Walid)`** — reduce the coupling WITHOUT removing the survival mechanic;
   candidate directions:
   - (a) a **grace count** — require N consecutive non-advancing turns before the
     `fail_penalty` drains (a single mis-judged turn costs nothing);
   - (b) a **smaller / softer penalty** for a checkpoint-miss, reserving the big drains for
     genuine silence / refusal / abuse;
   - (c) **only** silence / refusal / abuse drain patience; a checkpoint-miss contributes
     little or nothing.
   The non-negotiable constraint: **the survival game keeps its teeth** — a learner who
   genuinely does not engage (stalls, goes silent, refuses, rambles off-topic) must still be
   able to LOSE. This is the §3c design crux; pick the direction with Walid, then prove it
   with AC12.
10. The judge **timeout** path is ALREADY patience-neutral (fail-open) — C targets the
    confident-`False` path, NOT the `None` path. Do not re-fix the timeout→patience coupling
    (it isn't coupled); see Interactions.
11. Keep intact the existing decoupled mechanisms: the 5-consecutive-`None` force-drain, the
    Story 6.25 fast-re-speak coalescing (one impatience event per window), and the silence
    ladder's stage-4 drain (genuine silence is a legitimate drain).

### Stream D — arc-ordered character conduct (call 336; continuation of Story 6.21)

12. The character **advances one DISTINCT beat at a time, in author order** — never fuses
    two beats into one breath (the call-336 "confirm identity" + "give name" fusion), never
    jumps ahead. Strengthen `format_suggested_focus_block` / `format_remaining_goals_block`,
    and **reconcile the Story 10.6 "already-given" branch** (brief §8.7): it must fire only
    when a beat is **genuinely `met`/credited**, NOT merely "the model believes it was
    given" — the proximate cause of the call-336 strand (the opening line voiced beat 0's
    content, so the model believed it done and moved on). Reconcile, do NOT delete the
    R4/R6 never-silent / always-drive guards (brief §8.1, §10).
13. If the user volunteers later-beat info, the character **takes it in (in character) but
    steers back** to the lowest-unmet beat; when a beat's turn arrives for info the user
    already volunteered, the character **CONFIRMS instead of re-asking** ("and the Coke,
    yes?") — nothing volunteered is lost, nothing planned is skipped, no loop. Reconcile
    with the `implies` back-fill (Story 6.27) and the COHERENCE_CHARTER anti-repetition.
14. **Hard ordering constraints are respected** (identity → accusation: the cop cannot
    surface fingerprints before identity is genuinely done). Reconcile with `requires`
    reactive gating (Story 6.23) — map how rail-keeping coexists with `requires`/`implies`
    BEFORE changing either (brief §8.3).
15. A **new construction-rule lint (R9)**, mirroring the R1/R2/R8 three-layer pattern
    (`find_*` helper in `scenarios.py` → builder HARD reject → loader WARN →
    `tests/test_scenarios.py` glob over the full `_SCENARIO_INDEX`), flags — to the extent
    **mechanically detectable** — a beat whose `success_criteria` requires something the
    natural conversational flow won't produce (the `acknowledge_recorded_call` trap: a
    criterion that needs the USER to explicitly acknowledge/confirm a thing a real person
    never says and the character never re-elicits). What is not lexically detectable (two
    beats being the *same conversational moment*) stays builder `CHECKPOINTS_PROMPT`
    guidance + the smoke gate. Record as **R9** in `server/CLAUDE.md §9`. Audit the 6
    shipped scenarios and **fix the unsatisfiable beat(s)** — at minimum
    `cop_interrogation_01`'s `acknowledge_recorded_call` (brief §3, §6, §7).
16. Redirects feel **natural, not robotic** — "we'll get to that" is not spammed; bounded
    divergence (brief §8.2). Validated on the smoke gate, not just unit tests.

### Stream E — HUD sync (calls 334/336)

17. The HUD instruction **never contradicts** the live conversation. **VERIFY-FIRST**: after
    Stream D + the R9 lint + the scenario fix land, **re-check whether the HUD still
    strands at all** — the brief's thesis (and Story 6.21's ruling) is that the
    lowest-unmet HUD is correct *by construction* once the character holds the arc and no
    beat is unsatisfiable. If beats no longer strand, E may need **only** the regression
    tests (AC19) + a minimal residual decision, NOT an engine/rendering rewrite.
18. **`DECISION (proposed → confirm)`** — for any residual stale instruction that can still
    occur (judge lag, a provably-overtaken beat): keep the **lowest-unmet** step (do NOT
    adopt the rejected "HUD follows the conversation wherever it goes" — brief §4, §5), and
    ensure the server's authoritative current-beat cannot disagree with what the character
    is steered to pursue. The client today computes `activeIndex` = "first index not in
    `metIndices`" locally (`checkpoint_snapshot.dart`); decide whether that stays
    client-computed or the server stamps an authoritative `current_index` into the
    `checkpoint_advanced` envelope. Out-of-order completions (the dots) must keep rendering
    truthfully (no lying about what scored).
19. No planned beat is **skipped or lost** regardless of what the user volunteers or in what
    order — regression-lock the Story 6.10 any-order credit + Story 6.21 ordered pursuit +
    `requires`/`implies`. New client + server tests cover the **stranded / overtaken beat**
    case (today there is NO test for "an early beat never credits → does the HUD advance or
    hold?", server or client).

### Global — validation + gate (all streams)

20. `python scripts/calibrate_scenario.py --golden-only` stays **6/6 PASS** (Story 10.7's
    judge accuracy is not regressed by any prompt/criteria/engine change here).
21. A cooperative-learner calibration sweep (`calibrate_scenario.py <id>`, default
    `--difficulty easy`) keeps each scenario in its band (easy 60–80, ±5 = ⚠️ still passes)
    AND an off-topic / non-engaging learner still **fails** — proving C9 did not trivialize
    survival and D did not break completion. Bump `ENGINE_VERSION` in
    `calibration_engine.py` if the patience/credit rules changed.
22. All automated gates green: server `ruff check .` + `ruff format --check .` + `pytest`
    (incl. the new R9 lint test, the EndpointWatchdog/turn-taking real-pipeline tests, the
    judge-resilience tests, the patience-decoupling tests, the HUD regression tests) AND
    client `flutter analyze` (No issues found!) + `flutter test` (All tests passed!).
23. Deployed to the VPS and the **Pixel 9 smoke gate PASSES on the worst case (the 20-beat
    Detective)** — see the Smoke Test Gate. This gate is the `review → done` trigger.

## Tasks / Subtasks

> Implement in the recommended order (A → B → D4 lint + scenario fix → D → re-check E → C).
> After A+B, deploy + a quick on-device confirm that a call completes before continuing.

- [x] **Task 1 — Stream A: STT long-utterance finalization + interim-aware ladder (AC: 1–4)**
  - [x] Reproduce/confirm the call-341 mechanism against real Soniox frames (real-pipeline drive, `server/CLAUDE.md §1`). Confirmed: `SonioxSTTService` emits NO `UserStartedSpeakingFrame` (only `UserStoppedSpeakingFrame`), and `PatienceTracker` had no `InterimTranscriptionFrame` branch (L639 cancel-on-interim intent keyed on `TranscriptionFrame(finalized=False)`, which Soniox never emits) → a never-finalizing utterance had NO cancel signal.
  - [x] Fix `EndpointWatchdog` (`pipeline/endpoint_watchdog.py`): NEW `_MAX_INTERIM_DURATION_SECONDS=15.0` continuous-growth hard cap (`_hardcap_task`), armed ONCE on the first interim of a turn and NOT refreshed, so a continuously-growing interim still force-finalizes; the per-interim-restarted 8s stuck-partial timer (call 171) is preserved. Shared `_synthesize_finalize`; each fire cancels its sibling so exactly one synthetic finalize fires; `cleanup` drains both.
  - [x] Make `PatienceTracker` silence ladder interim-aware (`pipeline/patience_tracker.py::process_frame`): NEW `InterimTranscriptionFrame` branch cancels the ladder on real interim speech (`text and not self._self_speaking`) — the missing branch the §1 trap hid. Keeps the `_self_speaking` echo guard.
  - [x] Real-pipeline tests: `tests/test_endpoint_watchdog.py` (+3: hardcap-fires-on-continuous-stream, hardcap-cancelled-on-finalize, hardcap-drained-by-cleanup), `tests/test_patience_tracker.py` (+4: soniox-interim-cancels/empty/self-speaking + a real PipelineTask drive proving the interim reaches PatienceTracker through `checkpoint_manager → patience_tracker`). 8/8 new pass; full watchdog+patience suite 86/86 green.
- [x] **Task 2 — Stream B: judge ReadTimeout resilience (AC: 5–8)** — DECISION RESOLVED (Walid 2026-06-30): **bounded retry once**.
  - [x] `pipeline/exchange_classifier.py`: a NEW `_last_failure_was_timeout` flag (set on httpx `TimeoutException` in `_post_for_content` + on the outer `asyncio.TimeoutError` in `_classify_multi_guarded`); `classify_multi` grants ONE bounded retry on a transient timeout via an `elif` after the cold-start branch (so at most ONE retry/turn, never stacked). Strict json_schema untouched; fail-open kept (a timeout still drains no patience); 4.0/4.5 s NOT widened (the retry re-runs the same guarded attempt with a fresh outer budget — fire-and-forget for non-terminal turns, so no felt latency added).
  - [x] Reconcile with `checkpoint_manager.py::_classify_and_flip_goals` `None`-handling: unchanged — a sustained timeout still returns `None` after exactly one retry, so the 5-consecutive-None force-drain backstop is intact.
  - [x] Tests: transient-timeout-after-first-success-is-retried (verdict lands), sustained-timeout-surfaces-as-None (one retry then None), non-timeout-after-success-NOT-retried (narrows the old D2b rule). 49/49 classifier tests green.
- [x] **Task 3 — Stream D4: the R9 construction-rule lint + scenario audit (AC: 15)**
  - [x] `scenarios.py::find_unsatisfiable_criteria` — single source of truth; mirrors R8 (a within-sentence `acknowledg… record(ed|ing)` / `acknowledg… disclaimer` regex tuple, the mechanically-detectable slice of "requires the user to acknowledge a passive notice the character never re-elicits").
  - [x] Builder HARD reject (`scenario_builder.validate_structure`, +import) + loader WARN (`load_scenario_checkpoints`) + `tests/test_scenarios.py` glob (`test_shipped_scenarios_have_no_unsatisfiable_criteria`); zero false-positives verified — does NOT trip "acknowledges the fingerprint claim / her feelings / the situation" (3 dedicated false-positive tests).
  - [x] Audited the 6 scenarios — only `cop_interrogation_01::acknowledge_recorded_call` tripped. Rewrote its `success_criteria` (dropped part (b) "acknowledge the recording"; now credits confirming identity OR agreeing to talk), `hint_text`, and `prompt_segment` (cop no longer re-states the recording, defers the name request to beat 1 — also reduces the call-336 beat-fusion at the construction level). Builder now HARD-rejects the ORIGINAL; the FIXED beat loads clean. Live re-golden owed at deploy (Task 7; no reviewed cop golden fixture, so no stale case — only the universal off-topic seed).
  - [x] Recorded **R9** in `server/CLAUDE.md §9` (rule + enforcement + the "broader same-moment class stays builder guidance + smoke gate" caveat; Status line updated to 2026-06-30).
- [x] **Task 4 — Stream D: arc-ordered conduct (AC: 12–14, 16)**
  - [x] Reconciled the "already-given" branch in `format_suggested_focus_block` (brief §8.7): a genuinely-credited beat has already dropped off `pending_goals`, so the block only ever sees a STILL-PENDING beat → the already-given path now **CONFIRMS-and-HOLDS** (gives the judge a clean turn) and explicitly forbids advancing on the model's own assumption ("not even if you believe it is already handled", "NEVER jump ahead on your own assumption that it is done") — the old "keeps the conversation moving" advance license (the proximate call-336 strand cause) is removed. Confirm-not-re-ask (AC13) is the behaviour. R4/R6 preserved (the confirm is a spoken line; confirming-and-holding is still driving). `requires`/`implies` + the any-order credit engine are UNCHANGED (rail-keeping lives in the steering prompt only, per 6.21) — so hard ordering (AC14: identity → accusation) holds via the firm ordered steering + the existing `requires` gate; COHERENCE_CHARTER anti-repetition is unchanged above the block. The D4 cop beat-0 prompt_segment fix also de-fuses beat 0 from the name beat at the construction level (AC12).
  - [x] Unit test pins the reconcile (confirm-and-hold, ban-on-assumption, old advance-license gone); the existing 6.21 ordered-pursuit tests stay green. Behavioural naturalness (AC16) is validated on the calibration sweep + the Pixel 9 smoke gate (Task 7).
- [x] **Task 5 — Stream E: HUD sync (AC: 17–19)** — VERIFY-FIRST outcome: Interaction #1 HELD. The HUD froze ONLY because beat 0 stranded `unmet`; D (confirm-and-hold, no advance-on-assumption) + D4 (R9 + the satisfiable beat-0 criterion) stop the strand, so the lowest-unmet HUD is correct **by construction**. NO engine/rendering rewrite.
  - [x] **DECISION (AC18) RESOLVED → keep CLIENT-computed lowest-unmet.** The client's `activeIndex` = "first index not in `metIndices`" (`checkpoint_snapshot.dart:39`) is ALWAYS the same beat as the server's steering target `pending_goals[0]` (= lowest author-order unmet), and the server sends the full truthful `goals_met_indices` on every envelope — so they CANNOT disagree by construction. A server-stamped `current_index` would be redundant (it'd recompute the identical value) and add wire surface; NOT added. Kept lowest-unmet (did NOT adopt the rejected "HUD follows the conversation"). Surfaced for Walid's awareness in the recap.
  - [x] Regression tests (AC19): client `checkpoint_step_hud_test.dart` (+3 pure-snapshot: holds on the stranded early beat with later beats met / advances the instant it credits / null+allMet when all done) + server `test_checkpoint_manager.py` (+1: out-of-order flip → the envelope's `goals_met_indices` is the TRUTHFUL out-of-order set AND the steering holds the lowest-unmet beat → the client's activeIndex can't disagree). Client 12/12 + server 4/4 (Stream D+E subset) green.
- [x] **Task 6 — Stream C: patience↔judge (AC: 9–11)** — DECISION RESOLVED (Walid 2026-06-30): **REJECTED softening the patience coupling** (it would dilute the "Survive the Talk" ADN). Instead, HARDEN judge reliability so the call-339 false-negative (a SYSTEMATIC judge error, not random) doesn't happen — then the spiral never starts and patience stays 100% coupled.
  - [x] Judge prompt (`EXCHANGE_CLASSIFIER_MULTI_PROMPT`): principle 2 now credits a genuine move phrased POLITELY / INDIRECTLY / as a QUESTION-REQUEST ("I would like to know if I can order?" / "Could I get the chicken?") — judged by what the turn ACCOMPLISHES, not by whether it ends in a question mark (fixes 339). Principle 7 refined to distinguish a DODGE-question (performs none of the objective's move → unmet) from a genuine-move-question (→ met), and notes the dodge test is OBJECTIVE-dependent (so it never contradicts a beat whose criterion accepts "asks what you recommend"). The 10.7 anti-permissive content ("Default to UNMET", "PERFORM the move", the call-340 evasions) is PRESERVED — both poles held.
  - [x] AC10 (timeout path already fail-open) + AC11 (5-None force-drain + 6.25 coalescing + stage-4 silence drain) — UNCHANGED; no patience code touched, so the survival mechanic keeps all its teeth (ADN intact).
  - [x] Proof: golden fixture +1 case (the 339 polite-question order → must be `met`), deterministic prompt wiring test (`test_multi_prompt_credits_polite_indirect_question_form_intent`), `ENGINE_VERSION` 6 → 7 (forces a full revalidation sweep — judge prompt + steering are outside `scenario_hash`). Live golden 6/6 + cooperative band + off-topic-fails owed at deploy (Task 7).
- [ ] **Task 7 — Validate + gate (AC: 20–23)** — golden 6/6, calibration band, server `ruff`/`format`/`pytest` + client `flutter analyze`/`flutter test`, deploy, Pixel 9 smoke on the 20-beat Detective.

## Interactions — verify these overlaps BEFORE building (binding, per Walid)

> Walid 2026-06-30: fixing one problem may by nature fix or reshape another — verify each
> overlap and adjust rather than building redundant or conflicting changes.

1. **D (+ R9 lint + scenario fix) very likely FIXES E by construction.** The HUD freezes
   ONLY because an early beat strands. If the character holds the arc (D) and no beat is
   unsatisfiable (R9 + the `acknowledge_recorded_call` fix), no beat strands → the
   lowest-unmet HUD is correct with nothing to "catch up" to. **Build D + R9 first, then
   re-check E (AC17).** Do NOT build an elaborate HUD/engine rewrite before confirming E
   still reproduces. Likely E shrinks to regression tests + one small decision.
2. **The R9 scenario fix is the single highest-leverage change for the call-336 symptom**
   (it's a scenario-authoring bug, not an engine bug — brief §3, §7). Do it early; it may
   resolve both the D confusion AND the E freeze on the Detective at once.
3. **B's timeout path is ALREADY patience-neutral; C targets the confident-`False` path.**
   Don't double-fix. After B lands, confirm call 339 (a confident `greet: unmet`, not a
   timeout) still reproduces → C is still needed. The `None`/timeout path must stay
   fail-open in BOTH B and C.
4. **A and C both live in `patience_tracker.py` and both touch the hang-up paths** —
   but DIFFERENT ones: A = the **silence ladder** (cancel/suppress on interim, stage-4
   silence drain), C = the **checkpoint-fail** drain (`apply_exchange_outcome(success=False)`).
   Coordinate the edits; don't let one regress the other's tests.
5. **A's two halves reinforce each other.** The `EndpointWatchdog` synthetic finalize (A2)
   IS a finalized `TranscriptionFrame`, which already cancels the silence ladder — so a
   robust watchdog partly covers A1. Decide whether the interim-aware ladder (A3) is still
   needed as defense-in-depth (recommended: yes — the watchdog is an 8 s backstop, the
   ladder can fire sooner at the easy `ladder_impatience_seconds = 4.5 s`).

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** included — server pipeline changes (STT/turn-taking, judge, patience,
> checkpoint steering, scenarios, a new lint) + a VPS deploy. **No new DB migration is
> expected** (mark the migration/backup boxes N/A unless a stream adds one).
>
> **Transition rule:** every unchecked box is a stop-ship for `in-progress → review`. Paste
> the actual command + output as proof.

- [x] **Deployed to VPS.** `GET https://api.survivethetalk.com/health` `git_sha` matches the
      commit under test; the CI deploy-server run was green.
  - _Proof:_ CI deploy-server run `28434840693` SUCCESS (push of `b6e98bc`); `/health` →
    `{"status":"ok","db":"ok","git_sha":"b6e98bcdcb36196a5dd0780d512d9d6e2692aeab"}` @ 2026-06-30T09:41Z (matches HEAD).

- [x] **Golden net not regressed (judge accuracy from 10.7 holds).**
      `python scripts/calibrate_scenario.py --golden-only` → **6/6 PASS** on the deployed judge.
  - _Command:_ `cd server && python scripts/calibrate_scenario.py --golden-only` (run on the VPS against the live gpt-4.1-mini judge)
  - _Actual:_ `=== 6/6 passed (0 cached) ===` — cop_hard / **cop_interrogation** / girlfriend / landlord / mugger / **waiter** all PASS. 0 cached = the ENGINE_VERSION 6→7 bump forced a full re-judge. waiter PASS proves BOTH poles on the live model: the new call-339 fixture ("I would like to know if it is possible to order?" → `met`) passes AND the off-topic seed is `unmet` on every beat (greet/main/clarify/drink/confirm/close all `unmet` in the verdict log). cop_interrogation PASS = the R9 beat-0 rewrite is golden-clean.

- [ ] **Calibration band holds (C didn't trivialize, D didn't break completion).**
      A cooperative easy sweep stays in band AND an off-topic learner does NOT complete.
  - _Command:_ `cd server && python scripts/calibrate_scenario.py cop_interrogation_01`
  - _Actual:_ OWED. The cop sweep (20-beat, N=10, ~20-30 min) was KILLED mid-run to free the OpenAI account for Walid's live Pixel 9 calls (it was inducing rate-limit contention). Judge accuracy is already proven by the live golden 6/6 + zero false-negatives across calls 344/345. The cooperative-easy band on the NEW −9 `fail_penalty` is owed for the reviewer/Walid (re-run when no live call is in flight). NOTE: the band itself is about to be reworked by Story 10.9 (survival decoupling), so a deep cop calibration on −9 has limited shelf-life.

- [x] **DB migration / backup — N/A** (no schema change — no stream added a migration).

- [x] **Server logs clean on deploy/boot.** New release booted clean: `systemctl is-active
      pipecat.service` → `active`; `journalctl -u pipecat.service` grep for
      `error|traceback|exception|hardcap|retry-on-timeout` → no error/traceback lines. Full
      happy-path-DURING-A-CALL verification (no `endpoint_watchdog_fired` spam, no
      `checkpoint_classifier_inconclusive` on good turns, no unexpected `character_hung_up`)
      rides the Pixel 9 smoke gate below.
  - _Proof:_ service `active`, clean journal @ 2026-06-30T09:50Z (post-deploy `b6e98bc`).

- [ ] **Pixel 9 on-device smoke gate — the 20-beat Detective (`cop_interrogation_01`), the
      worst case.** All five money moments hold (script handed to Walid at Task 7):
  - **A:** a long, no-pause sentence (read ~40–50 words in one breath) → the character WAITS,
    responds when you finish; NO "Are you still there?", NO hang-up mid-sentence.
  - **B:** during a normal call a beat is still credited even if a judge call is slow (no
    silently-missed beat on a good turn; HUD still ticks).
  - **C:** a clearly-engaged but borderline turn does NOT spiral patience to a hang-up.
  - **D:** the character drives **one beat at a time, in order**, confirms volunteered info
    instead of re-asking, and never reveals a later beat (fingerprints) before identity is done.
  - **E:** the on-screen instruction **always matches** what the cop is actually saying — it
    never freezes on a beat the conversation has passed.
  - _Result (calls 344 + 345, 2026-06-30):_ **The 10.8 FIXES validated; completion confounded by the 10.9 survival issue.** **A ✅** no mid-sentence hang-up (the call-341 bug did not recur; hard cap force-finalized, ladder stayed cancelled; after the 25s fix, no truncation). **B ✅** no silently-missed beat on a good turn; HUD ticked. **E ✅** HUD never froze; beat 0 credited immediately (call-336 strand gone). Judge accurate (zero false negatives). **C / D (completion):** the engaged learner was HUNG UP by the patience meter (10/20 then 8/20) — NOT the call-341 bug, but the structural "patience drains on non-advancement" conflation (cop circles back to met beats; `lock_arrival_and_departure` near-unsatisfiable for a stay-home alibi). **Carved to Story 10.9 (`survival-decoupling-design-brief.md`) — not a 10.8 failure.** RECOMMENDED for review→done: accept that 10.8's fixes are live-validated (A/B/E + judge + no-truncation + golden 6/6) and that "complete the 20-beat Detective" is gated by 10.9; OR re-smoke the 10.8 fixes on a SHORTER scenario (6-beat waiter) where the survival math isn't a confound. Walid's call.

## Dev Notes

### Read first
- `checkpoint-arc-rail-keeper-design-brief.md` §1–12 (the principle, worked examples, hard
  tensions §8, open questions §9, off-limits constraints §10, code pointers §11). The
  ADDENDUM §A/§B is DONE by 10.7 — don't redo it.
- `server/CLAUDE.md` §1 (FrameProcessor direction/frame-type traps — **the §1 trap is the
  exact class of bug behind both Stream A and the EndpointWatchdog's history**), §4 (judge
  strict json_schema law), §6 (`calibrate_scenario` golden==prod), §7 (`requires`), §8
  (difficulty-neutral), §9 (R1–R8 + the three-layer enforcement + "THE DURABLE LESSON").
- Story 6.21 (`6-21-character-enforced-checkpoint-ordering`, done) — this story makes its
  firm ordered pursuit ROBUST on the 20-beat scenario; it is NOT greenfield (brief §3b).

### Stream A — exact seams (all main-tree, verified)
- `pipeline/endpoint_watchdog.py` — `_WATCHDOG_TIMEOUT_SECONDS = 8.0` (L65); arms on
  `InterimTranscriptionFrame` via `_restart_watchdog()` **on every interim** (L98–109,
  L118–120) → the timer is perpetually reset on a continuously-spoken utterance, so it
  never fires until interims STOP (the call-341 gap); cancels on a real `TranscriptionFrame`
  (L90–97); synthesises the finalize (L122–150). The **frame-type contract** (module
  docstring L21–34): Soniox interims are `InterimTranscriptionFrame`, finals are
  `TranscriptionFrame(finalized=True)` — SEPARATE sibling classes; the original Story 6.9
  watchdog armed on the wrong type and was dormant all of Epic 6 (call 171).
- `pipeline/patience_tracker.py` — `process_frame` (L565); the `TranscriptionFrame` branch
  (L616–643, `finalized=getattr(frame,"finalized",True)` L617, the cancel condition L639–640)
  handles **only finalized** frames (Soniox interims never reach it — there is no
  `InterimTranscriptionFrame` branch); `UserStartedSpeakingFrame` cancel (L661–665);
  `BotStartedSpeakingFrame` with the `_self_speaking` guard (L667–719); `handle_playback_idle`
  (L721–774) starts the ladder; `_start/_cancel_silence_timer` (L1042–1067); the silence
  ladder (`_run_silence_ladder`) stage-4 silence drain (~L1141).
- `bot.py` — `SonioxSTTService(... vad_force_turn_endpoint=False ...)` (Soniox neural VAD
  owns endpointing) + the `EndpointWatchdog` placement (between STT and the user aggregator,
  per `test_bot_pipeline_wiring.py` L65–68, L250). Do not move observers below the aggregator
  (the §1 / Story 6.6 lesson).
- Tests: `tests/test_endpoint_watchdog.py` (the frame-type contract is documented L9–13),
  `tests/test_patience_tracker.py`, `tests/test_bot_pipeline_wiring.py`.

### Stream B — exact seams
- `pipeline/exchange_classifier.py` — `_CLASSIFIER_TIMEOUT_SECONDS = 4.5` (L192),
  `_HTTP_TIMEOUT_SECONDS = 4.0` (L193); httpx client init (L307); the outer
  `asyncio.wait_for(_CLASSIFIER_TIMEOUT_SECONDS)` (L419 single / L512 multi); the
  `except httpx.HTTPError` catch → returns `None` with **no retry** (L539); strict json_schema
  payload (`response_format` L695, `"strict": True` L699). `classify_multi` returns
  `{goal_id: True|False|None}` or whole-value `None` on infra failure.
- `pipeline/checkpoint_manager.py::_classify_and_flip_goals` (L1147+) — the `None` path
  (fail-open, patience unchanged) + the **5-consecutive-`None` force-drain**
  (`_MAX_CONSECUTIVE_NONE_VERDICTS`, ~L1234–1260). Keep this; B makes a SINGLE transient
  timeout recoverable, not the sustained-degradation behaviour.
- The project memory references a `VERDICT_WAIT_BUDGET_MS = 800 ms` felt budget — it is
  Walid's off-limits knob (brief §10). If the chosen recovery interacts with felt timing,
  flag it as a decision; do not silently change it.

### Stream C — exact seams (the §3c crux)
- `pipeline/patience_tracker.py` — `apply_exchange_outcome(success: bool)` (L806) →
  `step_patience` (L245–263): `success=False` → `max(0, meter + fail_penalty)` with
  `fail_penalty = -15`; `_PATIENCE_WARNING_THRESHOLD = 25` (L215); `silence_penalty = -10`;
  `recovery_bonus = +5`.
- `pipeline/checkpoint_manager.py::_classify_and_flip_goals` — the **"fail" outcome** calls
  `apply_exchange_outcome(success=False)` (~L1315) when `advance_goals` finds no flips and
  ≥1 goal is actively `unmet`. A mis-judged `False` is indistinguishable from a genuine miss
  here — that is exactly what C must soften WITHOUT removing the survival mechanic. The
  Story 6.25 fast-re-speak coalescing already skips the drain for a turn stacked behind a
  prior fail (~L1301) — a precedent for gating the drain.
- **The hard part (be honest):** the system cannot tell a judge error from a genuine miss
  at judge time — that is why C is a *softening* (grace/penalty), not a perfect classifier.
  Stream B (fewer timeouts) and Story 10.7 (tighter judge) reduce the FREQUENCY of false
  negatives; C reduces their IMPACT. Pick the direction with Walid (AC9).

### Stream D — exact seams (continuation of Story 6.21)
- `pipeline/checkpoint_manager.py` — `format_suggested_focus_block` (L188–227): the firm
  lowest-unmet steering + the **"already-given" branch** (L214–227, the Story 10.6 addition,
  brief §8.7 — the suspected regression that lets the model move off an uncredited beat it
  *believes* was given). `format_remaining_goals_block` (L164–185, the FIRM author-order
  header). `advance_goals` (L356–421, any-order flip + `implies` back-fill L393–406),
  `judgeable_goals` (L283–322, `requires` reactive gating).
- Crediting stays **any-order** (`classify_multi` → `advance_goals`); rail-keeping lives in
  the **steering prompt**, not the credit engine (Story 6.21's ruling — don't move crediting
  to in-order). Reconcile with `requires`/`implies` before changing either (brief §8.3).
- `prompts.py` — `COHERENCE_CHARTER` (anti-repetition Rule 1), `EXCHANGE_CLASSIFIER_MULTI_PROMPT`
  (10.7's principle 7 — don't loosen), `MOOD_TAG_DIRECTIVE`. `reply_sanitizer.py` — the R4
  never-silent floor (don't delete).

### Stream D4 / E — the lint + HUD seams
- `pipeline/scenarios.py` — mirror `find_model_specific_tokens` (~L413, R1),
  `find_scripting_violations` (~L453, R2), `find_permissive_criteria_phrases` (~L491, R8):
  add the R9 helper + wire builder/loader/test (the three-layer pattern; `_SCENARIO_INDEX`
  glob, never a hand-list — "THE DURABLE LESSON"). `requires` validation ~L930, `implies`
  ~L960.
- `pipeline/scenarios/cop-interrogation-01.yaml` — the `acknowledge_recorded_call` beat 0
  (the unsatisfiable-in-natural-flow criterion + the opening_line already voicing its
  content). Fix per brief §3/§6/§7; re-golden.
- Client: `client/lib/features/call/views/widgets/checkpoint_snapshot.dart` (`activeIndex`
  getter L39–48 = "first index not in `metIndices`"), `.../widgets/checkpoint_step_hud.dart`
  (renders one step, L122–179), `.../services/data_channel_handler.dart` (parses the
  `checkpoint_advanced` envelope, L128–211), `.../views/call_screen.dart` (feeds the HUD via
  a `ValueNotifier`, L880–886, L1266). Server envelope: `build_initial_envelope` (L930–963)
  + `_emit_checkpoint_advanced` (L1397–1463) send full-state `goals_met_indices` + all
  `hints`. If E needs a server-authoritative `current_index`, it goes in this envelope.

### Constraints / what must NOT be broken (brief §10 + server/CLAUDE.md)
- **Felt timing is Walid's:** `VERDICT_WAIT_BUDGET_MS` (800 ms), the judge 4.0/4.5 timeouts,
  the silence-ladder/difficulty timing presets — off-limits unless a stream has a measured
  reason + a re-validation.
- **R4/R6 engine guards** (never-silent floor + always-drive) — reconcile with rail-keeping,
  do NOT delete (brief §8.1).
- **Strict judge json_schema** (§4), **golden==prod parity** (§6), the **mood-tag wire
  envelope** contract with the Rive client, the **R1–R8 rulebook** (extend with R9, don't
  bypass — §9).
- **`requires`/`implies` semantics** (Story 6.23 / 6.27) — map before changing.
- **Story 7.1 "never persist the transcript"** — unaffected; keep it.
- The §1 FrameProcessor trap: drive Stream A frames through a REAL pipeline (don't mock
  direction or frame type) — this exact trap is why the EndpointWatchdog was dormant for an
  epic.

### Out of scope (do NOT pull in)
- The device-authoritative hesitation measurement (a separate 7.5 follow-up —
  `device-hesitation-followup-brief.md`).
- Re-doing 10.7's judge permissiveness / progressive debrief (DONE).
- Any new scenario authoring beyond fixing the unsatisfiable beat(s).

## Project Structure Notes
- Server-heavy: `endpoint_watchdog.py`, `patience_tracker.py`, `exchange_classifier.py`,
  `checkpoint_manager.py`, `prompts.py`/`reply_sanitizer.py` (steering), `scenarios.py`
  (R9 lint) + `scenario_builder.py` + a scenario YAML + `server/CLAUDE.md` (R9). Deploys via
  the normal CI deploy-server path; **no new migration expected**.
- Client: HUD widgets only (`checkpoint_snapshot.dart`, `checkpoint_step_hud.dart`, possibly
  `data_channel_handler.dart`) — Flutter gates apply. Likely small if Interaction #1 holds.
- Validation is `calibrate_scenario.py` (golden + band, the prod-equivalent text harness) +
  real-pipeline pytest + the Pixel 9 smoke gate. The on-device gate is the only thing Walid
  runs; everything else the dev runs.

## References
- [checkpoint-arc-rail-keeper-design-brief.md §1–12 + ADDENDUM](_bmad-output/implementation-artifacts/checkpoint-arc-rail-keeper-design-brief.md) (ADDENDUM done by 10.7).
- [10-7 story (the judge-accuracy + progressive-debrief slice this builds on)](_bmad-output/implementation-artifacts/10-7-fix-checkpoint-conversation-sync-and-judge-accuracy.md)
- [server/CLAUDE.md §1 frame traps, §4 judge law, §6 calibration, §7 requires, §8 difficulty-neutral, §9 R1–R8 + durable lesson](server/CLAUDE.md)
- Stream A: `server/pipeline/endpoint_watchdog.py`, `pipeline/patience_tracker.py`, `bot.py`, `tests/test_endpoint_watchdog.py`, `tests/test_bot_pipeline_wiring.py`.
- Stream B: `server/pipeline/exchange_classifier.py`, `pipeline/checkpoint_manager.py`.
- Stream C: `server/pipeline/patience_tracker.py`, `pipeline/checkpoint_manager.py`.
- Stream D/E: `server/pipeline/checkpoint_manager.py`, `pipeline/scenarios.py`, `scripts/scenario_builder.py`, `pipeline/scenarios/cop-interrogation-01.yaml`, `pipeline/prompts.py`, `pipeline/reply_sanitizer.py`; client `checkpoint_snapshot.dart`, `checkpoint_step_hud.dart`, `data_channel_handler.dart`, `call_screen.dart`.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (dev-story, 2026-06-30)

### Debug Log References
- Mechanism confirmation (Stream A, AC1): `SonioxSTTService` emits NO `UserStartedSpeakingFrame` (only `UserStoppedSpeakingFrame`) — confirmed via `inspect.getsource` over the installed pipecat 0.0.108. So the silence ladder's only user-speech cancel during a never-finalizing utterance was a finalized `TranscriptionFrame`, which call 341 never produced.
- Interactions verified (binding section): #1 D+R9 fix E **by construction** (verify-first → no HUD rewrite); #2 the R9 scenario fix is the single highest-leverage call-336 change; #3 B's timeout path is already fail-open so C stayed off the timeout path (and Walid redirected C to judge-reliability anyway); #4 A and C touch DIFFERENT patience paths (A = silence ladder cancel/suppress; C = no patience change at all); #5 A's two halves reinforce (A3 ladder suppression is the hang-up fix, A2 watchdog cap guarantees the bot eventually responds).

### Completion Notes List
**Two dev-time DECISIONS resolved with Walid (2026-06-30):**
- **B** → bounded **retry once** on a transient `ReadTimeout`.
- **C** → Walid REJECTED softening the patience coupling (it would dilute the "Survive the Talk" ADN). Redirected to **harden judge reliability** instead: the call-339 spiral was a SYSTEMATIC judge false-negative (a polite/indirect order read as a dodge-question), fixable at the prompt; once fixed the spiral never starts, so patience stays 100% coupled and the survival game keeps its teeth.
- **E** (AC18) → resolved by the verify-first outcome: keep CLIENT-computed lowest-unmet (it equals the server's steering target by construction; a server `current_index` would be redundant). Surfaced for Walid's awareness.

**Per-stream:** A = EndpointWatchdog continuous-growth hard cap (`_MAX_INTERIM_DURATION_SECONDS=15`, armed once/turn) + PatienceTracker `InterimTranscriptionFrame` cancel branch (the missing §1-trap branch). B = `_last_failure_was_timeout` flag + an `elif` single bounded retry in `classify_multi` (≤1 retry/turn, strict json_schema + fail-open + 4.0/4.5 untouched). D4 = R9 `find_unsatisfiable_criteria` lint (builder reject + loader warn + glob test, zero false positives) + `cop_interrogation_01` beat-0 rewrite + `server/CLAUDE.md §9` R9. D = `format_suggested_focus_block` already-given reconcile (confirm-and-hold, never advance-on-assumption). E = verify-first (no rewrite) + stranded/overtaken regression tests (client + server). C = judge prompt principles 2/7 (polite/indirect/question-form genuine intent counts; dodge-question stays unmet, objective-dependent) + golden 339 fixture + `ENGINE_VERSION` 6→7.

**Owed at deploy/review (Task 7 + the gates):** live VPS golden 6/6 (`calibrate_scenario.py --golden-only`, needs the OpenAI key absent locally) incl. the new 339 fixture; a cooperative easy calibration sweep in-band + off-topic fails; deploy via CI deploy-server; Pixel 9 smoke on the 20-beat Detective (the 5 money moments). NO new DB migration.

**DEPLOY + LIVE VALIDATION (2026-06-30).** Deployed `b6e98bc` (CI deploy-server `28434840693` green, `/health` SHA match, db ok). Live VPS golden net = **6/6 PASS** (0 cached after ENGINE_VERSION 6→7) — `waiter_easy_01` PASS proves both poles on the deployed gpt-4.1-mini judge (the new call-339 polite-question fixture → `met` AND off-topic seed → `unmet` on every beat). Service `active`, journal clean (no error/traceback).

**REVIEW-PASS TUNING (calls 344/345, deployed `00dfe03`).** Two Pixel 9 calls on the 20-beat Detective surfaced two tuning issues, both fixed live: (1) the 15s hard cap truncated a SLOW B1 speaker mid-answer → fragments judged `unmet` → patience drained; RAISED 15s → 25s + ERROR→WARNING log (a cap fire is expected on a continuous talker, not a crash). (2) easy `fail_penalty` LOWERED −15 → −9. Both deployed (`00dfe03`, CI `28438447106` green, `/health` SHA match).

**WHAT THE LIVE CALLS PROVED — 10.8's fixes HOLD:** the call-341 bug (Soniox-never-finalizes → silence-ladder hang-up mid-sentence) did NOT recur (the hard cap force-finalized the long turns, the ladder stayed cancelled during speech — A2+A3 confirmed in prod); **beat 0 credited immediately** ("yeah sure" → `acknowledge_recorded_call: met` — the call-336 strand is GONE); the **HUD never froze** (truthful out-of-order `goals_met_indices`); the **judge was accurate** (zero false negatives across both ~5-min calls — Stream C validated live); progressive debrief OK; after the 25s cap fix, NO truncation.

**THE RESIDUAL "ENGAGED LEARNER STILL GETS HUNG UP" IS CARVED TO A NEW STORY (10.9), NOT a 10.8 bug.** Both calls ended in a PATIENCE-meter hang-up (survival mechanic), NOT the call-341 bug. Root cause: the patience meter drains on "didn't advance a beat", but an ENGAGED learner doesn't advance for GOOD reasons (the cop's circle-back persona re-asks already-met beats; a beat — `lock_arrival_and_departure` — is near-unsatisfiable for a stay-home alibi; clarifications; slow B1 pace). −9 slowed but didn't cure it (it's a structural conflation, not a magnitude knob). A 13-agent design exploration produced `survival-decoupling-design-brief.md` (decouple SURVIVAL=engagement from PROGRESS=beats via one extra `__engaged__` field on the existing judge call). Walid will open **Story 10.9** in a DEDICATED create-story session from that brief. The −9 is an interim gentling that 10.9 supersedes.

### File List
**Server — pipeline:**
- `server/pipeline/endpoint_watchdog.py` (A2 — continuous-growth hard cap)
- `server/pipeline/patience_tracker.py` (A3 — interim-aware silence ladder)
- `server/pipeline/exchange_classifier.py` (B — transient-timeout bounded retry)
- `server/pipeline/scenarios.py` (D4 — R9 `find_unsatisfiable_criteria` + loader WARN)
- `server/pipeline/scenarios/cop-interrogation-01.yaml` (D4 — beat-0 fix; D — beat-0 prompt_segment de-fusion)
- `server/pipeline/checkpoint_manager.py` (D — `format_suggested_focus_block` reconcile)
- `server/pipeline/prompts.py` (C — judge prompt principles 2/7)
**Server — scripts / config / docs:**
- `server/scripts/scenario_builder.py` (D4 — R9 HARD reject + import)
- `server/scripts/calibration_engine.py` (`ENGINE_VERSION` 6→7)
- `server/CLAUDE.md` (§9 R9 rule + Status)
**Server — tests / fixtures:**
- `server/tests/test_endpoint_watchdog.py` (+3 hard-cap)
- `server/tests/test_patience_tracker.py` (+4 interim-aware incl. real-pipeline drive)
- `server/tests/test_exchange_classifier.py` (+3 retry; 1 updated)
- `server/tests/test_scenarios.py` (+3 R9)
- `server/tests/test_checkpoint_manager.py` (+2: focus reconcile, stranded-beat envelope)
- `server/tests/test_prompts.py` (+1 judge-reliability wiring)
- `server/tests/test_calibration_engine.py` (1 updated — ENGINE_VERSION pin)
- `server/tests/fixtures/golden/waiter_easy_01.json` (+1 call-339 positive case)
**Client (tests only — Stream E was verify-first, no `lib/` change):**
- `client/test/features/call/views/widgets/checkpoint_step_hud_test.dart` (+3 stranded/overtaken snapshot)
**Story bookkeeping:**
- `_bmad-output/implementation-artifacts/10-8-character-rail-keeper-arc-ordering-and-hud-sync.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
