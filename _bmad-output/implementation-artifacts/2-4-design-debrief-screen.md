# Story 2.4: Design Debrief Screen

Status: done

## Story

As a designer,
I want the debrief screen fully designed with all content sections, layout, and visual hierarchy,
so that Epic 7 (Post-Call Debrief) can be implemented with complete visual specs.

## Context

The debrief screen is the **highest-value screen in the entire product**. This is where users actually learn — specific errors flagged with corrections, hesitation analysis, idiom explanations, and clear areas to work on. The debrief is "the real value that justifies payment" (PRD). It must deliver the "Finally, the Truth" moment (UX Critical Success Moment #3): the first time someone tells the user exactly what they're doing wrong.

**Two competing design constraints:**
1. **Screenshot-worthy** — The top section (survival %, character name, scenario) must be self-contained and visually compelling as a standalone screenshot for viral sharing (like Wordle's colored grid)
2. **Study guide** — The full screen is a detailed learning resource. Users close the app after reading the debrief knowing exactly what to study before their next attempt

**Key emotional calibration:**
- No "great job!" — ever. Not even for 100% survival.
- No retry button. No CTA at the bottom. The debrief is the destination, not a trampoline.
- Honest, specific, frank — but framed for motivation, not discouragement.
- FR15b: When survival >40%, include encouraging framing (proximity to next threshold, improvement since last attempt).

**Story type:** Design specification (markdown deliverable, no code).

## Acceptance Criteria

1. **AC1: Content Sections and Layout**
   - **Given** the UX spec defines: hero survival %, attempt number, previous best, errors with corrections, hesitation moments, idiom explanations, areas to work on
   - **When** the design is complete
   - **Then** each section has layout specs, typography (using established styles), spacing, and color treatment
   - **And** survival % uses display style (64px Bold), `#E74C3C` if <100%, `#2ECC40` if 100%

2. **AC2: Error Section Visual Treatment**
   - **Given** corrections use accent color (`#00E5A0`)
   - **When** reviewing the error section design
   - **Then** "You said X" and "Correct form: Y" have distinct visual treatment that's instantly readable

3. **AC3: Screenshot-Worthy Hero Section**
   - **Given** the debrief must be screenshot-worthy for viral sharing
   - **When** reviewing the overall layout
   - **Then** the top section (survival %, character name, scenario) is self-contained and visually compelling as a standalone screenshot

4. **AC4: No Retry — Back Navigation Only**
   - **Given** no retry button — user navigates back via back arrow
   - **When** reviewing the screen
   - **Then** no call-to-action buttons exist at the bottom, and back navigation is the only exit

## Tasks / Subtasks

- [x] Task 1: Design hero section — screenshot-worthy header (AC: #1, #3)
  - [x] 1.1 Define survival percentage display (64px Bold, color-coded by score)
  - [x] 1.2 Specify character name and scenario title placement
  - [x] 1.3 Specify attempt number and previous best comparison display
  - [x] 1.4 Define the self-contained screenshot boundary (what's captured in a share screenshot)
  - [x] 1.5 Create layout specification table for hero section

- [x] Task 2: Design error section — "You said X / Correct form: Y" (AC: #1, #2)
  - [x] 2.1 Define error card layout (user phrase vs correction, distinct visual treatment)
  - [x] 2.2 Specify accent color `#00E5A0` usage for corrections
  - [x] 2.3 Define error card states (single error, multiple errors, no errors)
  - [x] 2.4 Specify spacing between error cards and maximum display count
  - [x] 2.5 Create layout specification table for error section

- [x] Task 3: Design hesitation section (AC: #1)
  - [x] 3.1 Specify longest hesitation moment display (duration + conversation context)
  - [x] 3.2 Define visual treatment for hesitation context quote
  - [x] 3.3 Create layout specification table for hesitation section

- [x] Task 4: Design idiom/slang section (AC: #1)
  - [x] 4.1 Define idiom card layout (idiom → meaning → contextual example)
  - [x] 4.2 Specify visual treatment for idiom explanation
  - [x] 4.3 Define empty state (no idioms encountered)
  - [x] 4.4 Create layout specification table for idiom section

- [x] Task 5: Design encouraging framing for >40% survival (AC: #1)
  - [x] 5.1 Define FR15b encouraging framing display (proximity to threshold, improvement since last)
  - [x] 5.2 Specify when this section appears (>40%) and where in the layout
  - [x] 5.3 Define visual treatment for progress comparison

- [x] Task 6: Design "Areas to Work On" summary and inappropriate behavior section (AC: #1)
  - [x] 6.1 Define summary section layout (2-3 key improvement areas)
  - [x] 6.2 Specify FR37 section for calls ended due to inappropriate behavior
  - [x] 6.3 Define back navigation (back arrow, no CTA buttons)

- [x] Task 7: Full screen composition and responsive layout (AC: #1, #4)
  - [x] 7.1 Define overall screen composition with all sections stacked vertically
  - [x] 7.2 Specify scrolling behavior and section ordering
  - [x] 7.3 Define responsive behavior (320-430px width range)
  - [x] 7.4 Specify back arrow position and safe area handling

- [x] Task 8: Accessibility and documentation (AC: #1, #2, #3, #4)
  - [x] 8.1 Verify WCAG 2.1 AA contrast for all elements
  - [x] 8.2 Define screen reader announcements for each section
  - [x] 8.3 Define reduced motion behavior
  - [x] 8.4 Create Mermaid flow diagram showing debrief in navigation context
  - [x] 8.5 Cross-reference design tokens with UX spec and previous stories

- [x] Task 9: Write deliverable document
  - [x] 9.1 Create `_bmad-output/planning-artifacts/debrief-screen-design.md`
  - [x] 9.2 Include all specs from Tasks 1-8
  - [x] 9.3 Include Flutter widget mapping for Epic 7 implementation
  - [x] 9.4 List open questions for Walid's review

## Dev Notes

### This is a Design Story — NOT Code

The deliverable is a **markdown design specification** document at `_bmad-output/planning-artifacts/debrief-screen-design.md`, following the same format established in Story 2.1 (`onboarding-screen-designs.md`), Story 2.2 (`incoming-call-screen-design.md`), and Story 2.3 (`call-ended-screen-design.md`). No Flutter/Python code is written.

### Design System Tokens (from UX Spec + Stories 2.1/2.2/2.3)

| Token | Hex | Usage on Debrief Screen |
|-------|-----|-------------------------|
| `background` | `#1E1F23` | Screen background |
| `text-primary` | `#F0F0F0` | Section headers, user phrases in error cards, body text |
| `text-secondary` | `#9A9AA5` | Metadata, attempt count, timestamps, explanatory text |
| `accent` | `#00E5A0` | Corrections in error cards, idiom explanations, improvement indicators |
| `destructive` | `#E74C3C` | Survival % when <100%, hang-up icon, error highlights |
| `status-completed` | `#2ECC40` | Survival % when 100% |
| `avatar-bg` | `#414143` | Card backgrounds for error/idiom/hesitation sections |

**Typography:** Inter font family exclusively. No Frijole on this screen.

| Style | Font | Size | Weight | Usage |
|-------|------|------|--------|-------|
| `display` | Inter | 64px | Bold (700) | Survival percentage — the hero number |
| `headline` | Inter | 18px | SemiBold (600) | Section titles ("Language Errors", "Hesitation Analysis", etc.) |
| `section-title` | Inter | 14px | SemiBold (600) | Sub-section headers within cards |
| `body` | Inter | 16px | Regular (400) | Error descriptions, idiom explanations, areas to work on |
| `body-emphasis` | Inter | 16px | Medium (500) | Inline emphasis, correction text |
| `caption` | Inter | 13px | Regular (400) | Attempt count, previous best, timestamps, metadata |
| `label` | Inter | 12px | Medium (500) | Tags, secondary labels |

**Spacing:**

| Property | Value |
|----------|-------|
| Base unit | 8px |
| Screen padding horizontal | 20px |
| Screen padding vertical | 30px top (below SafeArea), 40px bottom |
| Section gap | 24px (between major sections) |
| Card internal padding | 16px |
| Element gap (standard) | 16px |
| Element gap (tight) | 8px |

### Debrief Content Sections (Complete List from Requirements)

The debrief screen must include all these sections, in this order:

1. **Hero Section (screenshot-worthy)**
   - Survival percentage: 64px Bold, `#E74C3C` (<100%) or `#2ECC40` (100%)
   - Character name and scenario title
   - Attempt number for this scenario (e.g., "Attempt #3")
   - Previous best comparison if applicable (e.g., "Previous best: 67%")

2. **Encouraging Framing (conditional — FR15b)**
   - Only shown when survival >40%
   - Proximity to next threshold (e.g., "5% away from surviving the mugger")
   - Improvement since last attempt if applicable (e.g., "+12% since last attempt")

3. **Language Errors (FR10)**
   - Each error shows: "You said: [user's phrase]" and "Correct form: [correction]"
   - User phrase in `text-primary`, correction in `accent` (#00E5A0)
   - Multiple errors displayed as a list of cards
   - Count indicator (e.g., "3 errors flagged")

4. **Hesitation Analysis (FR12)**
   - Longest hesitation moment with duration (e.g., "4.2 seconds")
   - Conversation context where it occurred (what was being discussed)

5. **Idiom/Slang Explanations (FR13)**
   - Each idiom: phrase → meaning → contextual example
   - e.g., "'Pull the other one' = British idiom meaning 'I don't believe you'"
   - Section hidden if no idioms were encountered

6. **Inappropriate Behavior Explanation (FR37 — conditional)**
   - Only shown when call ended due to inappropriate user behavior
   - Explains what happened and why the character reacted that way

7. **Areas to Work On (summary)**
   - 2-3 key improvement areas as clear, actionable items
   - Clear enough to guide self-study between sessions
   - This is the last content section — no CTA button below it

**Empty/edge states:**
- First attempt: no "Previous best" line, no improvement comparison
- No errors: section shows "No errors flagged" (still visible as positive feedback)
- No idioms: section hidden entirely (don't show "No idioms encountered")
- 100% survival: same layout, green color, no congratulatory text — character's grudging respect on Call Ended screen was the reward

### Entry Transition — From Call Ended Screen

The debrief screen appears via auto-transition from the Call Ended screen (Story 2.3):
- Call Ended holds for 3-4 seconds (minimum) while debrief loads in background
- When both conditions met (timer elapsed AND debrief data received), auto-fade to debrief
- Debrief appears **fully formed** — no loading spinners, no progressive rendering
- Crossfade transition (900ms total: 600ms fade-out + 600ms fade-in with 300ms overlap) from Call Ended screen

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Phase 5: Post-Call Transition]
[Source: `_bmad-output/implementation-artifacts/2-3-design-call-ended-transition-screen.md` — Debrief Loading Strategy]

### Screenshot-Worthy Design Strategy

The hero section (survival %, character name, scenario, attempt info) must work as a **standalone screenshot** shared out of context. Design principles:

- Self-contained within roughly the first screen fold (~400px height)
- Visually compelling: large number, clear identity, minimal clutter
- Meaningful to non-users: someone seeing this screenshot on social media understands "I survived 73% of a conversation with a sarcastic mugger"
- Pattern reference: Wordle's colored grid — data that's shareable without needing the app context

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Wordle pattern analysis, lines 200-208]

### Screen Will Be Consumed By

- **Epic 7, Story 7.3:** Build Debrief Screen — **primary consumer**, implements this exact design
- **Epic 7, Story 7.1:** Build Debrief Generation Backend — data model must match the sections designed here
- **Epic 8, Story 8.2:** Build Paywall Screen — FR29 triggers paywall on debrief screen after 3rd free scenario

### What NOT to Do

- **Do NOT add a "Retry" or "Call Again" button** — per UX spec, the user navigates back to the scenario list via back arrow (intentional friction for study + cost control)
- **Do NOT add "Great job!" or any congratulatory messages** — even for 100% survival. Numbers speak for themselves.
- **Do NOT add a share button** — users screenshot and share manually (like Wordle). A share button adds UI clutter and breaks the minimalist aesthetic. This can be post-MVP.
- **Do NOT design the Call Ended transition screen** — that's Story 2.3 (already done)
- **Do NOT design the paywall integration** — that's Story 2.5. The debrief screen design is for the debrief content only.
- **Do NOT add gamification elements** — no badges, no XP, no streaks, no leaderboard. The number IS the reward.
- **Do NOT add a loading spinner or skeleton screen** — the debrief arrives fully formed (latency masked by Call Ended screen)
- **Do NOT design for landscape orientation** — portrait only per UX spec
- **Do NOT create Figma files or image mockups** — deliverable is markdown specs only (same as Stories 2.1/2.2/2.3)
- **Do NOT use fonts other than Inter** — Inter for all text on this screen
- **Do NOT add navigation to other debriefs** — each debrief is a standalone report for one call session
- **Do NOT design pre-scenario briefing here** — FR14 (pre-scenario briefing) is displayed before the call, not on the debrief screen

### Previous Story Intelligence

**Story 2.1 (Design Onboarding Flow) — Done:**
- Established the markdown design spec format: token reference table → screen layout diagram → element specs → states → transitions → accessibility → open questions
- Established layout specification table format (Element / Position / Width / Height / Padding / Notes)
- Established responsive behavior breakdown (320px / 375px / 430px)
- Established WCAG 2.1 AA contrast verification table format
- Established Flutter widget mapping table for downstream implementation
- Design decision: `text-secondary` is `#9A9AA5` (NOT `#8A8A95` — updated for WCAG AA in Story 2.1)
- Deliverable: `_bmad-output/planning-artifacts/onboarding-screen-designs.md`

**Story 2.2 (Design Incoming Call Animation) — In Review:**
- Followed Story 2.1's document structure precisely
- Introduced screen-specific color tokens (call-secondary #C6C6C8, call-accept #50D95D, call-decline #FD3833) — documented with rationale
- Included z-order specification for layered elements
- Included animation specs and vibration patterns
- Flutter widget mapping table with file locations per architecture
- Deliverable: `_bmad-output/planning-artifacts/incoming-call-screen-design.md`

**Story 2.3 (Design Call Ended Transition Screen) — In Progress:**
- Defines the screen that immediately precedes this one (Call Ended → Debrief)
- 3-4 second hold, auto-fade transition to debrief
- Debrief loads in background during Call Ended screen
- Theatrical phrase + call duration + "Call Ended" text
- Deliverable: `_bmad-output/planning-artifacts/call-ended-screen-design.md`

**Patterns to follow:**
1. Same document structure as Stories 2.1, 2.2, and 2.3
2. Same layout specification table format
3. Same responsive behavior section (320px / 375px / 430px)
4. Same WCAG 2.1 AA contrast verification table
5. Same Flutter widget mapping table with file paths
6. If introducing screen-specific tokens, document rationale (like Story 2.2 did)
7. Cross-reference all design tokens with UX spec

### Git Intelligence

**Recent commits:**
```
e96d1cd feat: design onboarding flow screens (Story 2.1)
d630a0c feat: complete Epic 1 retrospective and close PoC phase
51dc771 feat: validate PoC kill gates and document go/no-go decision
1779596 feat: create minimal Flutter app with voice call
7145643 feat: build Pipecat voice pipeline with sarcastic character
```

**Pattern:** Design stories create markdown spec files in `_bmad-output/planning-artifacts/` (deliverable) and update the story file in `_bmad-output/implementation-artifacts/`. No code files are created or modified.

**Note:** Story 2.3 is currently `in-progress` — its design doc (`call-ended-screen-design.md`) may or may not exist yet. The Call Ended screen transitions INTO this debrief screen. The entry transition spec should reference Story 2.3's exit transition once finalized.

### Architecture Compliance

**Output location:** `_bmad-output/planning-artifacts/debrief-screen-design.md`
- Planning artifact (design spec), not implementation artifact
- Consumed by Epic 7, Story 7.3 (Build Debrief Screen) during implementation
- Must use same design token names as `ux-design-specification.md` for consistency

**Flutter implementation context (for design awareness):**
- This screen will be implemented as a Flutter widget in `client/lib/features/debrief/views/`
- `DebriefBloc` in `client/lib/features/debrief/` manages state
- Data comes from `GET /debriefs/{call_id}` API endpoint
- Navigation: arrived from Call Ended auto-transition, exits via back arrow to scenario list (GoRouter)
- Scrollable content: `SingleChildScrollView` or `ListView` with themed Material widgets
- No Rive animation on this screen — pure Flutter widgets with theme tokens

**Data model context (from architecture):**
- `debriefs` table: `call_session_id`, `survival_pct`, `debrief_json` (single JSON blob storing complete LLM output)
- `user_progress` table: `user_id`, `scenario_id`, `best_score`, `attempts`
- The design must align with the data structure: errors as a list, idioms as a list, survival as a percentage, attempt count from progress table

[Source: `_bmad-output/planning-artifacts/architecture.md` — Data Model, debriefs table]
[Source: `_bmad-output/planning-artifacts/architecture.md` — API Endpoints, GET /debriefs/{call_id}]
[Source: `_bmad-output/planning-artifacts/architecture.md` — Frontend Architecture, features/debrief/]

### Navigation Context

```
Scenario List → Call Screen → Call Ended → **Debrief** → (back) → Scenario List
```

The debrief screen is a **dead end by design**. The user reads the feedback, absorbs it, then navigates back to the scenario list when ready. No forward action, no retry, no share button. The only exit is the back arrow.

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Navigation: Forward Flow]

### Debrief Data Source Example

The design should account for this data structure (from architecture):

```json
{
  "survival_pct": 73,
  "character_name": "The Mugger",
  "scenario_title": "Give me your wallet",
  "attempt_number": 3,
  "previous_best": 67,
  "errors": [
    {
      "user_said": "I am not want problem",
      "correction": "I don't want any trouble",
      "context": "After the mugger's initial threat",
      "count": 2
    },
    {
      "user_said": "I am agree",
      "correction": "I agree",
      "context": "Responding to the mugger's demand",
      "count": 3
    }
  ],
  "hesitations": [
    {
      "duration_sec": 4.2,
      "context": "After the mugger raised his voice and demanded a faster answer"
    },
    {
      "duration_sec": 3.5,
      "context": "When asked to empty pockets — unfamiliar vocabulary"
    }
  ],
  "idioms": [
    {
      "expression": "Pull the other one",
      "meaning": "I don't believe you",
      "context": "The mugger used this when you claimed to have no wallet"
    }
  ],
  "areas_to_work_on": [
    "Negative sentence structure (use don't/doesn't instead of 'not want')",
    "Responding under pressure without freezing",
    "Using complete sentences instead of single-word answers"
  ],
  "inappropriate_behavior": null,
  "encouraging_framing": {
    "proximity": "5% away from surviving the mugger",
    "improvement": "+6% since last attempt"
  }
}
```

This JSON represents the **complete client-facing response** assembled by the backend. The LLM produces `errors`, `hesitation_contexts`, `idioms`, `areas_to_work_on`, and `inappropriate_behavior`. The backend adds `survival_pct`, `character_name`, `scenario_title`, `attempt_number`, `previous_best`, hesitation `duration_sec`, and `encouraging_framing`. Full schema and field ownership defined in `debrief-content-strategy.md`.

### Project Structure Notes

- Deliverable location: `_bmad-output/planning-artifacts/debrief-screen-design.md`
- Story file location: `_bmad-output/implementation-artifacts/2-4-design-debrief-screen.md` (this file)
- No code files created or modified (design story)
- No Flutter/Python pre-commit checks needed (no code changes)

### References

- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Screen 3: Debrief Screen — PENDING DESIGN (lines 642-653)]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Phase 5: Post-Call Transition (lines 492-507)]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Critical Moment 3: "Finally, the Truth" (lines 101-102)]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — UX-DR15: Debrief screen layout]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Color System (lines 516-533)]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Typography System (lines 542-556)]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Wordle results-as-shareable-artifact pattern (lines 200-208)]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Navigation: Forward Flow, Debrief dead end]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Anti-Patterns: No "Great Job!" Trap, No Retry Loop]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Experience Principle 6: Debrief is takeaway not trampoline]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR9: View debrief after each call]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR10: Specific language errors with corrections]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR11: Survival/completion percentage]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR12: Longest hesitation moments with context]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR13: Idiom/slang explanations]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR15: No direct retry button — intentional friction]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR15b: Encouraging framing when >40%]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR37: Explanation when call ended due to inappropriate behavior]
- [Source: `_bmad-output/planning-artifacts/architecture.md` — Data Model, debriefs table]
- [Source: `_bmad-output/planning-artifacts/architecture.md` — API: GET /debriefs/{call_id}]
- [Source: `_bmad-output/planning-artifacts/architecture.md` — Frontend: features/debrief/ directory]
- [Source: `_bmad-output/planning-artifacts/architecture.md` — Naming conventions: snake_case tables, camelCase Dart]
- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 2, Story 2.4 acceptance criteria]
- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 7: Post-Call Debrief & Learning]
- [Source: `_bmad-output/planning-artifacts/epics.md` — Story 7.3: Build Debrief Screen (implementation ACs)]
- [Source: `_bmad-output/planning-artifacts/onboarding-screen-designs.md` — Design doc format reference]
- [Source: `_bmad-output/planning-artifacts/incoming-call-screen-design.md` — Design doc format reference]
- [Source: `_bmad-output/implementation-artifacts/2-1-design-onboarding-flow-screens.md` — Previous story patterns]
- [Source: `_bmad-output/implementation-artifacts/2-2-design-first-call-incoming-call-animation.md` — Previous story patterns]
- [Source: `_bmad-output/implementation-artifacts/2-3-design-call-ended-transition-screen.md` — Previous story: Call Ended transition]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

No debug issues encountered. Design story — no code compilation or test execution required.

### Completion Notes List

- Created comprehensive debrief screen design specification at `_bmad-output/planning-artifacts/debrief-screen-design.md`
- Hero section designed as screenshot-worthy standalone element (~280px height) with 64px Bold survival %, character/scenario identity, and attempt info
- Error section uses "You said" / "Correct form" cards with distinct visual treatment: white (#F0F0F0) for user phrases, accent green (#00E5A0) for corrections on #414143 card backgrounds
- Hesitation section updated to 1-3 cards (only gaps > 3s), with count indicator and backend/LLM data split
- Idiom section follows same card pattern — hidden entirely when no idioms encountered
- Encouraging framing (FR15b) conditional section for >40% survival: proximity text in accent green + improvement comparison
- Inappropriate behavior (FR37) conditional section with red left border accent stripe
- Areas to Work On: numbered list (1-3 items) in single card — last content section, no CTA below
- Back arrow only exit — no retry, no share, no CTA buttons (per UX spec principle: debrief is destination, not trampoline)
- All design tokens cross-referenced with UX spec — NO screen-specific tokens introduced
- WCAG 2.1 AA contrast verified for all element combinations
- Screen reader announcements defined for every section
- Reduced motion behavior specified (entry crossfade → instant cut)
- Mermaid flow diagram showing debrief in full navigation context
- Flutter widget mapping table with file paths per architecture
- All open questions resolved (originally 5, reduced to 3 during content strategy, all 3 resolved during review)
- Followed exact document structure from Stories 2.1, 2.2, 2.3
- Content Strategy Decisions section added: 10 resolved questions with UX Designer justifications
- LLM JSON schema defined (json_schema strict mode): errors[], hesitation_contexts[], idioms[], areas_to_work_on[], inappropriate_behavior
- Backend vs LLM data ownership documented: survival_pct, attempt info, hesitation durations = backend; corrections, context, areas = LLM
- Tone specification for LLM prompt: clinical-frank, app voice not character voice
- Error cards updated: max 5 errors (deduplicated), count badge (×N) when count >= 2
- No strengths field (Q1), no summary field (Q2) — confirmed by UX Designer as intentional omissions

### Implementation Plan

Design story — deliverable is a markdown specification document. No code implementation.

### File List

- `_bmad-output/planning-artifacts/debrief-screen-design.md` (NEW) — Complete debrief screen design specification
- `_bmad-output/implementation-artifacts/2-4-design-debrief-screen.md` (MODIFIED) — Story file: tasks checked, Dev Agent Record updated
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (MODIFIED) — Story status: ready-for-dev → in-progress → review

### Change Log

- 2026-04-01: Story 2.4 implementation complete — created debrief screen design specification with all 7 content sections, accessibility specs, Flutter widget mapping, and 5 open questions for review
- 2026-04-01: Content Strategy update — resolved 10 content questions with UX Designer, added LLM JSON schema, backend/LLM data split, tone spec, error deduplication (max 5), hesitation multi-card (1-3), count badges. Open questions reduced to 3.
- 2026-04-01: Review complete — resolved 7 intent gaps (hesitation empty state, merge logic, encouraging_framing API contract, areas_to_work_on fallback, floor() rounding, idiom cap at 3, coexistence rules), applied 9 patches (transition duration, back arrow, DB reference, FR37 maxLines, screen reader, Mermaid, typo, contrast ratio, reduced motion). All open questions resolved.
