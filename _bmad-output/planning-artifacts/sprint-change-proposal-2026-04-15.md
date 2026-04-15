# Sprint Change Proposal: Checkpoint-Based Scenario System

**Date:** 2026-04-15
**Author:** Scrum Master (Correct Course workflow)
**Status:** Approved
**Scope Classification:** Minor — Direct implementation by dev team
**Trigger:** Misunderstanding of original requirements discovered during Story 3.2

---

## 1. Issue Summary

### Problem Statement

During Story 3.2 (Create Launch Scenarios), it became clear that the monolithic system prompt approach does not support meaningful gameplay progression or content-based scoring. The original design assumed:

- One large system prompt sent at call start — the LLM improvises within a "narrative arc"
- `survival_pct = successful_exchanges / expected_exchanges` where "successful" = any non-empty speech
- No real-time feedback to guide the user during the call
- The ExchangeClassifier (difficulty-calibration.md §8) was planned but had no structured success criteria

### What Is Actually Needed

A **checkpoint-based progression system** where:

- Scenarios are structured as ordered checkpoints (4-12 per scenario), each with specific success criteria
- The LLM only knows the current phase (prompt segment swapping), preventing story skipping
- A stepper bar + hint text provides real-time guidance to the user
- `survival_pct = checkpoints_passed / total_checkpoints` — content-based evaluation

### Evidence

- 5 scenarios exist in monolithic format (Story 3.2 Phase 1 complete) — the "narrative arc" is a suggestion to the LLM, not an enforced mechanic
- The current formula (`any speech = success`) does not differentiate a performing user from one saying irrelevant things
- The Mugger scenario drafted in checkpoint format demonstrates richer gameplay and more meaningful scoring
- The ExchangeClassifier (AD-1) was already the right architectural hook — it only lacked structured `success_criteria`

---

## 2. Impact Analysis

### Epic Impact

| Epic | Status | Impact Level | Summary |
|------|--------|-------------|---------|
| **Epic 3** | in-progress | **High** | Story 3.1 reopened (template rewrite), Story 3.2 Phase 1 redo (5 scenarios + example) |
| Epic 4 | backlog | None | — |
| **Epic 5** | backlog | Moderate | Story 5.1 schema change (system_prompt → base_prompt + checkpoints JSON) |
| **Epic 6** | backlog | **Major** | Stories 6.1, 6.2, 6.4 modified + 2 new stories (6.6 CheckpointManager, 6.7 CheckpointStepper) |
| **Epic 7** | backlog | Low | Story 7.1 survival_pct formula change |
| Epics 1,2,4,8,9,10 | various | None | — |

**No epics added or removed.** Epic order unchanged.

### Artifact Conflicts (11 total, all approved)

| Artifact | Conflicts | IDs |
|----------|-----------|-----|
| architecture.md | 3 | A-1 (data model), A-2 (data channels), A-3 (pipeline diagram) |
| ux-design-specification.md | 5 | UX-1 (zero-text rule), UX-2 (feedback rule), UX-3 (phase 3), UX-4 (CallScreenCanvas), UX-5 (CheckpointStepper component) |
| difficulty-calibration.md | 5 | DC-1 (scoring definitions), DC-2 (§4.1 key principle), DC-3 (classifier prompt), DC-4 (config schema), DC-5 (pipeline components) |

### What Does NOT Change

- Character personality and behavioral boundaries (same content, moved to base_prompt)
- Patience meter mechanics (still decreases on failed turns, silence, etc.)
- Escalation stages (still tied to patience thresholds)
- TTS voice, Rive character assignment, content warnings
- Post-call debrief system (still uses transcript + AI scoring)
- Calibration testing tools (TranscriptLogger + score_transcript.py unchanged)
- The 5 scenario characters and their themes (Waiter, Mugger, Girlfriend, Cop, Landlord)
- Briefing text format
- Pipeline async parallel architecture (AD-1)

---

## 3. Recommended Approach

**Selected:** Option 1 — Direct Adjustment

### Rationale

1. **Zero code thrown away** — Epic 3 is a content epic (Markdown only), and Epics 4-10 are in backlog
2. **Limited rework** — rewrite 7 Markdown files (template + 5 scenarios + example) + update 4 planning docs
3. **No new external dependencies** — same stack, same services, same tools
4. **Existing content serves as base** — monolithic drafts contain character/personality content that extracts directly into `base_prompt`
5. **Minimal risk** — impacted epics (5, 6, 7) have not started, so changes are in specs not deployed code
6. **Net quality gain** — content-based scoring, visible progression, user guidance

### Alternatives Considered

- **Rollback:** Not applicable — content is Markdown, drafts are reusable, git revert adds nothing
- **MVP Review:** Not needed — MVP scope unchanged, checkpoint system improves quality without expanding scope

### Effort & Risk

- **Effort:** Medium (Epic 3 content rework ~2-3 days, planning doc updates ~1 day)
- **Risk:** Low (no code to break, no deployed features affected)
- **Timeline impact:** Minimal — Epic 3 extends by ~2-3 days, all downstream epics unaffected

---

## 4. Detailed Change Proposals

All proposals below were reviewed and approved incrementally.

### 4.1 Story Changes (epics.md)

#### P1 — Epic 3: Stories 3.1 and 3.2

**Story 3.1 AC update:**
- `scenarios` table reference: `system_prompt` → `base_prompt, checkpoints`
- Template coverage: monolithic "system prompt format" → "checkpoint-based format (base_prompt + ordered checkpoints array with id, hint_text, prompt_segment, success_criteria)"

**Story 3.2 AC updates:**
- "each scenario has a complete system prompt" → "each scenario has a base_prompt, ordered checkpoints (each with id, hint_text, prompt_segment, success_criteria)"
- "achieves 60-80% survival" → "passes 60-80% of checkpoints"

#### P2 — Epic 5: Story 5.1

**Story 5.1 AC update:**
- Schema: `system_prompt, difficulty, is_free, briefing_text, content_warning` → `base_prompt, checkpoints (JSON), difficulty, is_free, briefing_text, content_warning`

#### P3 — Epic 6: Stories 6.1, 6.2, 6.4

**Story 6.1 AC update:**
- "loads the scenario's system prompt" → "loads the scenario's base_prompt and checkpoints, spawns Pipecat bot with base_prompt + first checkpoint's prompt_segment as initial system prompt"

**Story 6.2 AC update:**
- "zero text on screen during calls" → "zero system/technical text on screen during calls"
- "no UI text, no toasts, no banners, no indicators" → "no toasts, no banners, no error indicators, no loading spinners. The only text is the CheckpointStepper overlay (gameplay content, not system UI)"

**Story 6.4 AC update:**
- `call_end` data: add `checkpoints_passed` and `total_checkpoints` fields
- Example: `survival_pct: 42` → `survival_pct: 40, checkpoints_passed: 2, total_checkpoints: 5`

#### P4 — Epic 6: New Stories 6.6 and 6.7

**Story 6.6: Build CheckpointManager and Checkpoint-Aware ExchangeClassifier**
- CheckpointManager: Pipecat FrameProcessor tracking checkpoint index, constructing active system prompt (base_prompt + current prompt_segment), advancing on classifier confirmation, pushing data channel events
- ExchangeClassifier: evaluates user speech against current checkpoint's success_criteria, returns `{"met": true/false}`
- Fallback: classifier timeout → checkpoint NOT advanced (conservative)
- Pipeline position: `STT → Context Aggregator → [CheckpointManager + PatienceTracker] → LLM → TTS → Transport`

**Story 6.7: Build CheckpointStepper Overlay for Call Screen**
- Stepper bar: horizontal circles connected by lines (completed=#00E5A0+checkmark, current=outlined #F0F0F0, future=#8A8A95)
- Adaptive sizing: ≤6 checkpoints → 20x20 circles/16px gap, 7-12 checkpoints → 14x14 circles/8px gap
- Hint bubble: speech-bubble container below stepper, semi-transparent dark bg, shows current hint_text
- Animations: 300ms circle fill on advancement, 200ms hint text crossfade
- Position: overlay at top of CallScreenCanvas, above Rive character
- Accessibility: announces checkpoint progress and hint text

#### P5 — Epic 7: Story 7.1

**Story 7.1 AC updates:**
- Survival formula: explicitly `floor(checkpoints_passed / total_checkpoints × 100)`
- Debriefs table: add `checkpoints_passed`, `total_checkpoints` columns

### 4.2 Architecture Changes (architecture.md)

#### ARCH-1 — Data Model (scenarios table)

- `system_prompt` → `base_prompt` (character identity/personality/boundaries)
- Add `checkpoints` (JSON array of checkpoint objects: id, hint_text, prompt_segment, success_criteria)
- `expected_exchanges` → `total_checkpoints` (derived from len(checkpoints))
- Add authoring format note: scenarios authored as YAML in `_bmad-output/planning-artifacts/scenarios/*.yaml`, loaded into SQLite as JSON at deployment

#### ARCH-2 — Data Channel Messages

Add new message type:
```json
{"type": "checkpoint_advanced", "data": {"checkpoint_id": "refuse", "index": 1, "total": 5, "next_hint": "Ask him what he'll actually do."}}
```

Defined message types: `viseme`, `emotion`, `hang_up_warning`, `call_end`, `checkpoint_advanced` (5 total, was 4)

#### ARCH-3 — Pipeline Diagram

Add CheckpointManager, PatienceTracker, and ExchangeClassifier as visible custom processors in the Pipecat pipeline boundary diagram.

### 4.3 UX Design Changes (ux-design-specification.md)

#### UX-1 — Anti-pattern "Chatbot UI" rule

Amend from "zero text UI elements" to "zero system/technical text UI elements". The CheckpointStepper overlay functions as a game HUD, not app chrome.

#### UX-2 — Feedback rule

Amend from "Zero text-based feedback during calls" to "Zero system text during calls". Primary indicator remains the character's face; supplementary indicator is the CheckpointStepper overlay.

#### UX-3 — Phase 3 Conversational Loop

Add "Checkpoint progression" paragraph describing the checkpoint mechanic, stepper advancement, and prompt segment swapping.

#### UX-4 — CallScreenCanvas anatomy

Add CheckpointStepper overlay (Flutter widget) to the component anatomy diagram, positioned between BackdropFilter and Rive Canvas.

#### UX-5 — New Component: CheckpointStepper (#6)

6th custom component with full specification:
- Adaptive circle sizing (20x20 for ≤6 checkpoints, 14x14 for 7-12)
- Three states per circle (completed/current/future)
- Hint bubble with semi-transparent background
- Animation specs (300ms fill, 200ms crossfade)
- Max supported: 12 checkpoints (fits 320px min width)
- Accessibility: announces progress and hint text

Update component count from "Five" to "Six".

### 4.4 Difficulty Calibration Changes (difficulty-calibration.md)

#### DC-1 — Core Scoring Definitions (§3)

- New §3.1 "What Is a Checkpoint?" defining checkpoint structure
- §3.2 "What Is an Exchange?" preserved but contextualized (exchanges occur within checkpoints)
- New §3.3 "When Is a Checkpoint Passed?" with result table
- §3.4 Survival formula: `floor(checkpoints_passed / total_checkpoints × 100)`
- §3.5 Hang-up trigger: "All expected exchanges completed" → "All checkpoints passed"

#### DC-2 — §4.1 Key Principle

"Exchange Count Is Scenario-Defined" → "Checkpoint Count Is Scenario-Defined". Typical range: 4-6 for short scenarios, up to 10-12 for complex ones.

#### DC-3 — AD-1 Classifier Prompt

Add `success_criteria` to classifier input. Change return from `{"success": true/false}` to `{"met": true/false}`. Invert fallback: timeout → checkpoint NOT advanced (was: exchange defaults to successful).

#### DC-4 — §8.3 Scenario Config Schema

`system_prompt` + `expected_exchanges` → `base_prompt` + `checkpoints[]` + `total_checkpoints`

#### DC-5 — §8.4 Pipeline Components Table

Add `CheckpointManager` (Pipecat FrameProcessor). Update `ExchangeClassifier` description to reference success_criteria matching.

### 4.5 Scenario Content Files

#### TEMPLATE-1 — scenario-authoring-template.md

Full rewrite from monolithic 9-section system prompt format to checkpoint-based format (base_prompt + checkpoints array). Executed during Story 3.1 reopening.

#### STORY-1 — 3-2-create-launch-scenarios.md

Update Phase 1 description to reference checkpoint-based format and rewrite requirement for all 5 scenarios + example.

### 4.6 Sprint Status (sprint-status.yaml)

- Story 3.1: `done` → `in-progress` (reopened for checkpoint format rewrite)
- Add stories 6.6 and 6.7 to Epic 6 (backlog)
- Update `last_updated` to `2026-04-15`

---

## 5. Implementation Handoff

### Scope Classification: Minor

All changes can be implemented directly by the dev team. No backlog reorganization or architectural replanning required.

### Execution Order

| Step | Action | Who | Deliverable |
|------|--------|-----|-------------|
| 1 | Apply planning artifact updates | Dev | architecture.md, ux-design-specification.md, difficulty-calibration.md, epics.md, sprint-status.yaml updated |
| 2 | Rewrite scenario-authoring-template.md | Dev (Story 3.1) | Checkpoint-based template |
| 3 | Rewrite example-the-waiter.md | Dev (Story 3.1) | Checkpoint reference example |
| 4 | Rewrite 5 scenario files | Dev (Story 3.2) | 5 scenarios in checkpoint format |
| 5 | Calibration testing on VPS | Walid (manual) | 2 passes per scenario validated |
| 6 | Update 3-2-create-launch-scenarios.md | Dev (Story 3.2) | Story spec reflects checkpoint format |

Steps 1-3 can be done in a single session. Step 4 follows immediately. Step 5 is human testing (unchanged process).

### Success Criteria

- [ ] All planning artifacts updated with checkpoint-based specs
- [ ] scenario-authoring-template.md fully rewritten for checkpoint format
- [ ] example-the-waiter.md serves as working checkpoint reference
- [ ] 5 scenario files rewritten with base_prompt + checkpoints
- [ ] sprint-status.yaml reflects reopened Story 3.1 and new Stories 6.6/6.7
- [ ] Calibration testing passes (2 human passes per scenario, survival within target ranges)
