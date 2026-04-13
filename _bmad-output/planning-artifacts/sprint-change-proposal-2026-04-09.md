# Sprint Change Proposal — Character Variants in Rive File

**Date:** 2026-04-09
**Triggered by:** Story 2.6 (Create Rive Character Puppet File) — in-progress
**Proposed by:** Walid (product owner)
**Scope:** Minor — Direct Adjustment
**Mode:** Batch

---

## 1. Issue Summary

During implementation of Story 2.6 (Rive character puppet), an inconsistency was identified in the current design. All documents (PRD, UX spec, architecture) specify "single puppet reused across all scenarios — new scenarios = new system prompts, not new art."

However, the 5 launch scenarios feature characters of distinctly different genders and appearances:

| Scenario | Character Archetype |
|----------|-------------------|
| The Mugger | Male, menacing |
| The Sarcastic Waiter | Variable |
| The Furious Girlfriend | Female |
| The Cop | Variable |
| The Angry Landlord | Male, older |

A single visual character with a feminine voice for "The Girlfriend" and a masculine voice for "The Cop" creates an obvious visual/audio mismatch that breaks immersion — the core product promise.

**Evidence:** The PRD defines 5 scenarios at launch with distinct character archetypes. Cartesia TTS voice is configured per scenario (masculine/feminine). The Rive file currently being designed has no mechanism to vary the character's appearance per scenario.

**Discovery context:** Identified during Story 2.6 implementation planning, before the .riv file was created — optimal timing for course correction.

---

## 2. Impact Analysis

### Epic Impact

| Epic | Impact | Details |
|------|--------|---------|
| Epic 2 (in-progress) | **Direct** | Story 2.6 must add `character` EnumInput to the .riv file with 5 variants |
| Epic 3 (backlog) | Minor | Story 3.1 scenario structure must include `rive_character` field |
| Epic 6 (backlog) | Minor | Story 6.2 must set character input when loading call screen |
| All others | None | No impact |

### Artifact Conflicts

| Artifact | Conflict | Resolution |
|----------|----------|------------|
| PRD | Capability #2 says "single puppet, not new art" | Update to mention character skins within single file |
| UX Spec | Line 283 says "single Rive puppet file" | Update to mention multiple character skins |
| Architecture | Scenarios table missing `rive_character` column | Add column |
| Architecture | No mention of character variant input | Add Rive Character Variants note |
| Rive Creation Guide | No `character` input defined | Add input + new section + validation updates |
| Story 2.6 | No AC for character variants | Add AC #8 + Task 1b |
| Epics | Stories 3.1, 6.2 unaware of character variants | Add notes to acceptance criteria |

### Technical Impact

- **Rive file:** Single file, but with 5 visual variants sharing the same state machine. File size may increase (stay under 2MB ceiling). The `character` EnumInput is the same pattern already used for `emotion` and `visemeId`.
- **Server:** `scenarios` table gains a `rive_character` column (string, enum value name).
- **Flutter:** Call screen sets `character` EnumInput before conversation starts — trivial addition to existing Rive integration.
- **No pipeline changes** — Pipecat is unaware of visual variants.

---

## 3. Recommended Approach

**Selected path:** Direct Adjustment

**Rationale:**
- Story 2.6 is `in-progress` and the .riv file is not yet created — this is the perfect moment to integrate the change
- The mechanism (EnumInput) is identical to the existing pattern for emotions and visemes — no new architectural pattern
- All document edits are minor text changes (1-2 lines each)
- Zero timeline impact — this change was going to be needed regardless; catching it now avoids rework later
- Effort: **Low**. Risk: **Low**

**Alternatives evaluated:**
- Rollback: Not viable — no completed work to revert
- MVP Review: Not viable — the change improves the MVP, doesn't reduce it

---

## 4. Detailed Change Proposals

### 4.1 PRD — Capability #2

**Before:** "Single Rive puppet file reused across all scenarios — new scenarios = new system prompts, not new art"
**After:** "Single Rive puppet file with 5 character skins (mugger, waiter, girlfriend, cop, landlord) switchable via EnumInput — new scenarios = new system prompts + character variant selection, not new .riv files"

### 4.2 UX Spec — Design Inspiration Strategy

**Before:** "single Rive puppet file with maximum expressiveness through minimal geometry"
**After:** "single Rive puppet file with 5 character skins (switchable via EnumInput) and maximum expressiveness through minimal geometry"

### 4.3 Architecture — Scenarios Table

**Before:** `scenarios` columns: id, title, system_prompt, difficulty, is_free, briefing_text, content_warning
**After:** Added `rive_character` column — EnumInput value selecting character visual variant (e.g., 'mugger', 'girlfriend')

### 4.4 Architecture — Rive Character Variants Note

**Added:** Note after Rive Hot-Update Pattern documenting the character EnumInput and how Flutter uses it.

### 4.5 Rive Creation Guide — Complete Updates

- Added `character` EnumInput (5 values: mugger, waiter, girlfriend, cop, landlord) to inputs table
- Added new section: Character Variants (design direction per variant)
- Updated Input/Output Contract table
- Updated Validation Checklist
- Updated Quick Reference Card

### 4.6 Story 2.6 — AC + Tasks + Contract

- Added AC #8: Character Variants (5 visual variants sharing same rig)
- Added Task 1b: Build character variant system
- Modified "What NOT to Do" #2 to clarify single file with variants
- Updated Input/Output Contract to match current Rive guide + character input

### 4.7 Epics — Stories 3.1 and 6.2

- Story 3.1: Added `rive_character` to scenario structure fields and acceptance criteria
- Story 6.2: Added character EnumInput setting to acceptance criteria

---

## 5. Implementation Handoff

**Scope classification:** Minor — Direct implementation within current story

**Handoff:** Story 2.6 continues as-is with expanded scope (AC #8 + Task 1b). No backlog reorganization needed. No new stories required.

**Success criteria:**
- All 7 documents updated with approved changes
- Story 2.6 .riv deliverable includes 5 character variants with functional emotions and visemes per variant
- File size remains < 2MB

### Character Variant Enum Values (Locked)

| Enum Value | Character | Used By Scenario |
|------------|-----------|-----------------|
| `mugger` | The Mugger | Mugging scenario |
| `waiter` | The Sarcastic Waiter | Restaurant scenario |
| `girlfriend` | The Furious Girlfriend | Relationship scenario |
| `cop` | The Cop | Police scenario |
| `landlord` | The Angry Landlord | Housing scenario |

### Extensibility

Future scenarios can either reuse existing variants (e.g., a "job interviewer" scenario could use the `waiter` variant) or add new enum values to the `character` input without breaking changes — EnumInputs in Rive are additive.

---

## 6. Addendum — Remove Reduced Motion from MVP

**Date:** 2026-04-09 (same session)
**Triggered by:** Walid's request during character variant correction
**Scope:** Minor — Scope reduction (simplification)

### Issue

All design documents contained detailed reduced motion specifications (alternative animations, `MediaQuery.disableAnimations` checks, static fallbacks). This level of detail is unnecessary for the MVP and adds implementation complexity for a feature that can be added post-MVP as a purely additive change.

### Decision

**Remove ALL reduced motion handling from MVP scope.** Full animations only at launch. Reduced motion support can be added later without breaking changes (additive `reduced_motion` BooleanInput in Rive, `MediaQuery.disableAnimations` check in Flutter).

### Files Modified

| File | Change |
|------|--------|
| `ux-design-specification.md` | Simplified Reduced Motion section (line 744) + detailed table (line 1292) + testing row (line 1315) → "Deferred to post-MVP" |
| `rive-character-creation-guide.md` | Simplified Section 9, removed `reduced_motion` from quick reference card, removed conditional blend duration/transition references |
| `2-6-create-rive-character-puppet-file.md` | AC #6 marked as REMOVED FROM MVP, I/O Contract table updated |
| `debrief-screen-design.md` | Subtask 8.3 replaced with "Deferred to post-MVP" |
| `call-ended-screen-design.md` | Subtask 4.3 replaced with "Deferred to post-MVP" + widget table line struck through |
| `incoming-call-screen-design.md` | Reduced motion paragraph replaced with "Deferred to post-MVP" |
| `paywall-screen-design.md` | Reduced Motion Behavior section replaced + widget table line struck through |
| `epics.md` | UX-DR12 reduced motion clause struck through |

### Not Modified (Intentional)

- Completed story files (2-3, 2-4, 2-5) — historical records, left as-is
- Section headers that say "Reduced Motion" — kept with "Deferred" note for traceability

---

**Approved by:** Walid (2026-04-09)
**Applied:** All document edits executed in this session
