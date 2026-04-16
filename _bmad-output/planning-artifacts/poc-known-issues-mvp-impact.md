# PoC Known Issues → MVP Design Impact Mapping

Date: 2026-04-16
Source: `_bmad-output/implementation-artifacts/poc-validation-report.md` §Known Issues for MVP
Status: Active — consult before starting any MVP code story it impacts
Retrospective context: Carried forward from Epic 1 retro (2026-03-31) and Epic 2 retro (2026-04-14). Completed during Epic 3 retro preparation (2026-04-16) before Epic 4 kickoff.

---

## Purpose

The PoC validation on 2026-03-31 surfaced 8 known issues that do not block the go/no-go decision but must be actively addressed during MVP development. This document maps each issue to the specific MVP story/stories that own its resolution, so discoveries do not happen mid-implementation.

For each issue, the table below gives:
- **Category** — product behavior, infrastructure, cost, or fit-and-finish
- **Blocks MVP?** — yes if a launch-blocking concern, no if a quality/optimization concern
- **Owner story/stories** — the MVP story or stories where this must be addressed
- **Required action** — concrete technical task
- **Severity for Epic 4** — whether Epic 4 (first code epic) is directly affected

---

## Summary Table

| # | Issue | Category | Blocks launch? | Owner story | Severity for Epic 4 |
|---|-------|----------|---------------|-------------|---------------------|
| 1 | Silence handling (no auto-response after user silence) | Product behavior | Yes | **6.4** Silence Handling and Hang-Up Mechanic | Low (not touched in Epic 4) |
| 2 | Cold start ~3-4s (worst case ~8s) | Infrastructure | Yes | **6.1** Call Initiation + new Epic 10 ops task | **Medium** — first-call UX in Story 4.5 |
| 3 | VAD stop_secs mismatch (0.3s vs recommended 0.2s) | Fit-and-finish | No | **6.1** Call Initiation | None |
| 4 | Response length (3-sentence overruns from Marcus PoC prompt) | Product behavior | No | **6.2** Call Screen (system prompt tuning) + **7.1** Debrief Generation | None — scenarios in Epic 3 enforce this |
| 5 | Barge-in sensitivity (min_words tuning per scenario) | Product behavior | No | **6.4** Silence Handling | None |
| 6 | TTS cost at scale ($0.053/call, 90% of total) | Cost / business | No (launch-acceptable) | **10.x** (Cartesia Enterprise negotiation) + Phase 3 roadmap (Chatterbox self-host) | None |
| 7 | Break-even higher than PRD estimate (~80 subs, not 60) | Business | No (doc correction) | PRD/business doc update (not a story) | None |
| 8 | Double user messages (consecutive user turns without bot response) | Product behavior | No | **6.2** Call Screen (context aggregator review) + **6.3** Emotional Reactions | None |

---

## Detailed Impact Mapping

### Issue 1 — Silence Handling

**What the PoC found:** The turn-based Pipecat pipeline requires speech to trigger a character response. When the user was silent for 24s, Marcus never spoke even though his system prompt says to mock silence.

**Owner:** Story 6.4 (Implement Silence Handling and Character Hang-Up Mechanic).

**Required action in Story 6.4:**
- Implement a silence timeout timer in the Pipecat pipeline (reset on every user frame, fires after `silence_prompt_seconds` from scenario config)
- On fire: inject a synthetic "user is silent" signal into the LLM context OR push a direct character utterance frame ("Still there?") then reset
- After `silence_hangup_seconds` of sustained silence: push `call_end` event with reason=`silence_hangup` and trigger the character's hang-up exit line

**Epic 4 impact:** None. Story 4.5 (First-Call Incoming Call Experience) does not exercise silence handling — it only covers call ringing → call start. The silence behavior is an in-call mechanic.

**Cross-reference:** `difficulty-calibration.md` §4.3 defines `silence_prompt_seconds` and `silence_hangup_seconds` per difficulty. Scenario YAMLs in Epic 3 already carry these fields (null = difficulty default).

---

### Issue 2 — Cold Start Latency (~3-4s, worst case ~8s)

**What the PoC found:** First-call cold start measured at ~3s during validation (subprocess + LiveKit connection partially cached). Story 1.3 measured ~8s worst case (full subprocess 2.3s + LiveKit handshake 4.6s + STT/TTS websocket init 0.9s).

**Owners:**
- Story 6.1 (Build Call Initiation from Scenario List with Connection Animation) — must handle cold start UX
- Epic 10 operational task — production worker pool with pre-spawned processes and pre-connected LiveKit rooms

**Required action in Story 6.1:**
- Connection animation spec must cover the worst-case ~8s gracefully (loading state, character "picking up" animation lasting ≥8s, copy like "Connecting…")
- The UX must not feel broken if the call takes 8s to establish on first use
- Document the fallback behavior if timeout exceeds 15s (likely: show NoNetworkScreen from Story 6.5)

**Required action for launch (Epic 10):**
- Implement worker pool: N pre-spawned Pipecat bot subprocesses holding warm LiveKit room pre-allocations
- On call start: assign an idle worker instead of spawning fresh
- Target: p95 connection time ≤2s in production

**Epic 4 impact: MEDIUM.** Story 4.5 (First-Call Incoming Call Experience) shows a fake incoming call (not a real Pipecat call — that's Epic 6). BUT: if Story 4.5 triggers any real backend connection (e.g., "Accept call" leads to an actual LiveKit room join), the cold start latency will be visible to the user during the first-call onboarding. Confirm Story 4.5 scope: is it purely UI animation, or does it actually initiate a Pipecat call? If the latter, the onboarding UX must accommodate the cold start.

**Recommended Epic 4 follow-up:** During Story 4.5 creation, explicitly specify whether "Accept" creates a real call (requires cold-start-aware UX) or an animation-only experience (no cold start concern until Epic 6).

---

### Issue 3 — VAD stop_secs Mismatch (0.3s vs Recommended 0.2s)

**What the PoC found:** Pipecat warns that `stop_secs=0.3` differs from the recommended `0.2s`. Tuning could save ~100ms per turn. Story 3.2 later tuned the Waiter scenario to `stop_secs=0.8` and `speech_timeout=1.8` to stop interruption cascades — opposite direction.

**Owner:** Story 6.1 (Pipecat bot instantiation for MVP calls) — set the right VAD defaults.

**Required action in Story 6.1:**
- Set `stop_secs` and `speech_timeout` as scenario-overridable parameters
- Default per-difficulty: easy (slower, 0.8s stop — from Waiter tuning), medium (0.5s), hard (0.3s)
- Document that these values may need re-tuning after Story 6.6 (CheckpointManager) changes conversation dynamics

**Epic 4 impact:** None. VAD parameters live in the Pipecat bot, not in Epic 4 code.

---

### Issue 4 — Response Length (3-Sentence Overruns)

**What the PoC found:** Marcus PoC prompt occasionally generated 3 long sentences despite instruction for "1-3 short sentences." Affects latency on subsequent turns and TTS cost.

**Owners:**
- Story 6.2 (Call Screen with Rive Character Canvas) — system prompt tuning during scenario integration
- Story 7.1 (Debrief Generation Backend) — if debrief text is also constrained

**Required action in Story 6.2:**
- Scenario base_prompts (authored in Epic 3) already include "Do NOT exceed 3 sentences per character turn." Verify this instruction is preserved when CheckpointManager swaps prompt segments (Story 6.6).
- Monitor first live call during Story 6.2 validation — if Qwen still overruns, refine the instruction or add a response-length postprocessor.

**Epic 4 impact:** None. Epic 4 does not run real conversations.

---

### Issue 5 — Barge-In Sensitivity

**What the PoC found:** `min_words=3` during bot speech prevents accidental interruptions but blocks legitimate quick answers ("yes"/"no"). `min_words=1` when bot is silent allows single-word triggers.

**Owner:** Story 6.4 (Silence Handling) — owns the conversation-flow parameters.

**Required action in Story 6.4:**
- Make `min_words_during_speech` a scenario-configurable parameter (default 3 for medium/hard, 1 for easy)
- Document the trade-off in scenario authoring template: high min_words = fewer false interruptions, low min_words = more responsive

**Epic 4 impact:** None.

---

### Issue 6 — TTS Cost at Scale (90% of Per-Call Cost)

**What the PoC found:** TTS (Cartesia) is 90% of per-call cost at $0.053/call. Total $0.058/call vs $0.044-0.054 PRD target. Still under $0.08 hard ceiling.

**Owners:**
- Pre-launch ops task (Epic 10.x) — Cartesia Enterprise pricing negotiation before scaling past 186 subscribers
- Phase 3 roadmap (post-launch) — Chatterbox self-hosted TTS migration

**Required action for Epic 10:**
- Add to Epic 10 launch checklist: "Confirm Cartesia plan (Startup or Scale) and negotiate Enterprise rate if 500+ subs projected."
- Monitor TTS credits consumption post-launch — trigger Enterprise outreach at 60% plan utilization.

**Epic 4 impact:** None.

---

### Issue 7 — Break-Even Higher Than PRD Estimate (~80 Subs, Not 60)

**What the PoC found:** Real Cartesia pricing (Scale plan $299/month fixed) pushes break-even from the PRD's estimate of ~60 subscribers to ~80.

**Owner:** Business planning doc (PRD or separate financial model). Not a code story.

**Required action:** Update PRD §Financial Model to reflect real break-even of ~80 subscribers. One-line correction, non-blocking.

**Epic 4 impact:** None.

---

### Issue 8 — Double User Messages (Consecutive User Turns)

**What the PoC found:** When the user pauses mid-sentence, the pipeline sometimes sends two consecutive `user` messages to the LLM with no assistant response between them. LLM handles gracefully but it's noisy for context management and transcripts.

**Owners:**
- Story 6.2 (Call Screen) — context aggregator behavior review
- Story 6.3 (Emotional Reactions via Data Channels) — related timing

**Required action in Story 6.2:**
- Review Pipecat `context_aggregator.user()` behavior in the pipeline. Consider coalescing consecutive user frames within a small time window (e.g., 500ms).
- If coalescing is not trivial in Pipecat, accept the current behavior (LLM handles it) and document as known-limitation until a Pipecat upgrade addresses it.

**Cross-reference:** Epic 3 tech debt item **D2** (Character logger captures token-level TextFrame chunks) is a related transcript-fragmentation issue on the character side. Both point to a broader "aggregation / coalescing" gap in the production TranscriptLogger (Epic 6 Story 6.3 scope).

**Epic 4 impact:** None.

---

## Decisions to Make Before Story 4.5 Creation

**Single open question for Epic 4:**

> Does Story 4.5 (First-Call Incoming Call Experience) trigger a REAL Pipecat call on "Accept", or is it an animation-only onboarding experience with the real call starting later?

- **If REAL call:** Story 4.5 must specify cold-start-aware UX (≥8s tolerant loading animation, NoNetworkScreen fallback).
- **If ANIMATION only:** No cold-start concern in Epic 4; defer entirely to Story 6.1.

This decision should be made during Story 4.5 creation with the SM agent.

---

## Tracking

This document is the canonical map. Each owner story's Dev Notes section must reference the relevant issue(s) from this file during story creation. The retrospective workflow for Epic 4, 5, 6, 7 must verify that each issue has been addressed in its owner story before marking the epic complete.
