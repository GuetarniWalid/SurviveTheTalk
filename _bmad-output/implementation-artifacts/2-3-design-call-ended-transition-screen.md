# Story 2.3: Design Call Ended Transition Screen

Status: done

## Story

As a designer,
I want the Call Ended transition screen fully designed (hang-up animation reference, text, duration, theatrical phrase),
so that the emotional transition between call and debrief is specified for implementation.

## Context

This is the **emotional pivot moment** of the entire product experience. The call just ended — the user either got hung up on (most common) or survived. This screen:

1. **Lets the emotional weight settle** — a 3-4 second pause after the intensity of the call
2. **Masks debrief LLM generation time** — the debrief loads in the background during this hold
3. **Maintains the phone call metaphor** — mimics a real phone's "Call Ended" screen with duration display
4. **Delivers a theatrical scenario-specific phrase** — e.g., "The mugger gave up on you" — reinforcing the adversarial entertainment positioning

The screen auto-transitions to the debrief with no user action required. When the debrief fades in, it is fully formed — no loading spinners, no progressive rendering.

**Two emotional variants exist:**
- **Hung up on (failure):** Character ended the call. Theatrical phrase is adversarial/dramatic.
- **Survived (success):** User completed the scenario. Theatrical phrase is grudgingly positive.

**Story type:** Design specification (markdown deliverable, no code).

## Acceptance Criteria

1. **AC1: Layout and Visual Design**
   - **Given** the UX spec defines a 3-4 second hold with theatrical scenario-specific phrase
   - **When** the design is complete
   - **Then** it includes layout specs for "Call Ended" text, call duration display, and theatrical phrase placement
   - **And** typography styles and colors are defined using the established design tokens

2. **AC2: Auto-Transition to Debrief**
   - **Given** this screen masks debrief LLM generation time
   - **When** reviewing the design
   - **Then** the auto-transition to debrief is defined (fade, timing) with no user action required

## Tasks / Subtasks

- [x] Task 1: Design screen layout (AC: #1)
  - [x] 1.1 Define overall screen composition and z-order
  - [x] 1.2 Specify "Call Ended" text placement, typography, and color
  - [x] 1.3 Specify call duration display (format, typography, position)
  - [x] 1.4 Specify theatrical phrase placement and styling (scenario-specific dynamic text)
  - [x] 1.5 Define character hang-up animation reference area (Rive integration point)
  - [x] 1.6 Create complete layout specification table with all element positions
  - [x] 1.7 Define responsive behavior (320-430px width range)

- [x] Task 2: Design two emotional variants (AC: #1)
  - [x] 2.1 Specify "hung up on" variant (failure) — theatrical phrase examples, tone, color treatment
  - [x] 2.2 Specify "survived" variant (success) — theatrical phrase examples, tone, color treatment
  - [x] 2.3 Define which visual elements change between variants and which stay constant

- [x] Task 3: Define transitions and timing (AC: #2)
  - [x] 3.1 Define entry transition from call screen (how Call Ended appears after hang-up/completion)
  - [x] 3.2 Specify hold duration (3-4 seconds) and debrief loading strategy
  - [x] 3.3 Define exit transition to debrief screen (auto-fade, no user tap)
  - [x] 3.4 Specify fallback if debrief is not ready when hold timer expires
  - [x] 3.5 Document transition timing with easing curves

- [x] Task 4: Accessibility and documentation (AC: #1, #2)
  - [x] 4.1 Verify WCAG 2.1 AA contrast for all elements
  - [x] 4.2 Define screen reader announcements
  - [x] 4.3 Define reduced motion behavior
  - [x] 4.4 Create Mermaid flow diagram showing Call Ended in navigation context
  - [x] 4.5 Cross-reference design tokens with UX spec and previous stories

- [x] Task 5: Write deliverable document
  - [x] 5.1 Create `_bmad-output/planning-artifacts/call-ended-screen-design.md`
  - [x] 5.2 Include all specs from Tasks 1-4
  - [x] 5.3 Include Flutter widget mapping for Epic 6/7 implementation
  - [x] 5.4 List open questions for Walid's review

## Dev Notes

### This is a Design Story — NOT Code

The deliverable is a **markdown design specification** document at `_bmad-output/planning-artifacts/call-ended-screen-design.md`, following the same format established in Story 2.1 (`onboarding-screen-designs.md`) and Story 2.2 (`incoming-call-screen-design.md`). No Flutter/Python code is written.

### Design System Tokens (from UX Spec + Stories 2.1/2.2)

| Token | Hex | Usage on Call Ended Screen |
|-------|-----|----------------------------|
| `background` | `#1E1F23` | Screen background |
| `text-primary` | `#F0F0F0` | "Call Ended" text |
| `text-secondary` | `#9A9AA5` | Call duration display |
| `accent` | `#00E5A0` | Success variant accent (survived) |
| `destructive` | `#E74C3C` | Failure variant accent (hung up on) |
| `avatar-bg` | `#414143` | Secondary background elements |

**Typography:** Inter font family exclusively. No Frijole on this screen.

| Style | Font | Size | Weight | Usage |
|-------|------|------|--------|-------|
| `headline` | Inter | 18px | SemiBold (600) | "Call Ended" text (or larger — design decision) |
| `body` | Inter | 16px | Regular (400) | Call duration, theatrical phrase |
| `caption` | Inter | 13px | Regular (400) | Secondary labels |

**Note:** Typography sizes are starting references from the design system. The Call Ended screen may use larger sizes for emotional impact (e.g., "Call Ended" could be 24-32px). The designer should determine optimal sizes based on the phone-call-ended metaphor — real phone "Call Ended" screens use large, centered, minimal text.

### Entry Transition — From Call Screen

The Call Ended screen appears after one of two events:
1. **Character hangs up** — character delivers dramatic exit line via TTS, then Rive hang-up animation plays, then this screen appears
2. **User survives** — character grudgingly acknowledges success via TTS, then this screen appears

**From UX spec (Phase 5):**
> The "Call Ended" screen holds for 2-3 seconds — letting the emotional weight of what just happened settle. Then it fades into the debrief screen.

**Entry context:** The call screen (full-screen Rive character with blurred scenario background) transitions to this overlay. The exact entry animation needs to be designed — options include:
- Overlay fade-in on top of the call screen (phone-call metaphor)
- Full screen transition replacing the call screen
- Call screen dims/blurs and Call Ended appears as centered overlay

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Phase 5: Post-Call Transition]

### Rive Character Animation Reference

The UX spec mentions "character hang-up animation (Rive)" as part of the CallEndedOverlay component. For this design story:
- **Do NOT design the Rive animation itself** — that's Story 2.6 (Create Rive Character Puppet File)
- **DO define the space/area** where the Rive character animation will display during the Call Ended transition
- **DO specify** whether the character animation is visible on this screen or if it happens before this screen appears
- The Rive hang-up animation (from Story 2.6) shows the character's dramatic theatrical hang-up: slamming phone, storming off, etc.
- The design decision: does the Call Ended overlay show WHILE the character animation plays, or AFTER it finishes?

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — CallEndedOverlay component, lines 1045-1056]

### Debrief Loading Strategy

**Critical dual-purpose design:** This screen simultaneously:
1. Creates an emotional pause (letting the call experience settle)
2. Masks the debrief LLM generation time (server-side transcript analysis, typically <5s)

**Timing logic:**
- Minimum hold: 3 seconds (emotional pause, even if debrief is ready sooner)
- Maximum hold: ~10 seconds (debrief generation hard ceiling per NFR)
- Auto-transition: when BOTH conditions are met: (a) minimum hold elapsed AND (b) debrief data received
- Fallback if debrief exceeds 10 seconds: transition anyway with loading state on debrief screen (edge case)

**From UX spec:**
> When the debrief screen fades in, it's complete — no loading spinners, no progressive rendering.

This means the Call Ended screen MUST hold until the debrief is fully loaded. The 3-4 second hold masks most debrief generation time. If it takes longer, the screen can hold up to ~10 seconds without feeling broken (the emotional weight of the call provides context for the pause).

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Phase 5, lines 492-507]
[Source: `_bmad-output/planning-artifacts/prd.md` — NFR: Debrief generation time <5s after call ends, 10s hard ceiling]

### Theatrical Phrase Design

The theatrical phrase is the **signature element** of this screen. It must:
- Be **scenario-specific** (different for each character/scenario)
- Be **emotional variant-aware** (different for hung-up vs survived)
- Reinforce the **adversarial entertainment** positioning

**Example phrases from UX spec:**
- Mugger (hung up): "The mugger gave up on you"
- Waiter (hung up): "The waiter kicked you out"
- Girlfriend (hung up): "She hung up. Again."
- Cop (hung up): "The officer lost patience"

**Survived variants (designer to propose):**
- Mugger (survived): "The mugger walked away empty-handed"
- Waiter (survived): "You actually got your food"
- Girlfriend (survived): "She's still on the line. Barely."

**Data source:** The theatrical phrase will come from the server as part of the call-end payload (or debrief data). The design should treat it as a **dynamic text field** with a maximum character count to prevent layout overflow.

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Hang-Up Animation section, lines 476-482]

### Screen Will Be Consumed By

- **Epic 6, Story 6.5:** Build Voluntary Call End and No-Network Screen — implements the transition from call to Call Ended
- **Epic 7, Story 7.2:** Build Call-Ended Overlay Transition — **primary consumer**, implements this exact design
- **Epic 7, Story 7.3:** Build Debrief Screen — receives the auto-transition from this screen

### What NOT to Do

- **Do NOT design the debrief screen** — that's Story 2.4 (Design Debrief Screen)
- **Do NOT design the call screen itself** — that's Story 2.6 (Rive character) and Epic 6
- **Do NOT design the Rive hang-up animation** — that's Story 2.6 (Create Rive Character Puppet File)
- **Do NOT add any interactive buttons** — this screen auto-transitions, no user action required
- **Do NOT add a "Retry" or "View Report" button** — per UX spec, the debrief appears automatically
- **Do NOT add a loading spinner or progress bar** — the emotional pause is the loading mask; visible loading indicators break the illusion
- **Do NOT design for landscape orientation** — portrait only per UX spec
- **Do NOT create Figma files or image mockups** — deliverable is markdown specs only (same as Stories 2.1/2.2)
- **Do NOT use fonts other than Inter** — Inter for all text on this screen
- **Do NOT show the "Call Ended" screen for voluntary call-end** — when the user hangs up voluntarily, the same Call Ended screen appears (the theatrical phrase changes, but the layout is identical)

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
- Introduced screen-specific color tokens (call-secondary #C6C6C8, call-accept #50D95D, call-decline #FD3833) — documented with rationale for deviating from system tokens
- Included z-order specification for layered elements
- Included animation specs (ring animation, avatar pulse, vibration pattern)
- Flutter widget mapping table with file locations per architecture
- Deliverable: `_bmad-output/planning-artifacts/incoming-call-screen-design.md`

**Patterns to follow:**
1. Same document structure as Stories 2.1 and 2.2
2. Same layout specification table format
3. Same responsive behavior section
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

**Note:** Story 2.2 is currently in `review` status — its design doc (`incoming-call-screen-design.md`) exists and was updated with Walid's Figma feedback. The Call Ended screen comes AFTER the call screen in the user flow (Call Screen → Call Ended → Debrief), so there's no direct visual handoff from Story 2.2 to this story. The handoff is from the Call Screen (Epic 6, Story 6.2-6.5) to this screen.

### Architecture Compliance

**Output location:** `_bmad-output/planning-artifacts/call-ended-screen-design.md`
- Planning artifact (design spec), not implementation artifact
- Consumed by Epic 7, Story 7.2 (Build Call-Ended Overlay Transition) during implementation
- Must use same design token names as `ux-design-specification.md` for consistency

**Flutter implementation context (for design awareness):**
- This screen will be implemented as a Flutter overlay/screen in `client/lib/features/call/views/` or `client/lib/features/call/widgets/`
- May use `AnimatedOpacity`, `FadeTransition`, or custom `AnimationController` for auto-transition
- Timer-based hold with async debrief loading check
- Rive character may be visible if the overlay approach is used (character animation continues behind the overlay)
- Navigation: after auto-transition, pushes to debrief screen (GoRouter)

**Data flow context:**
- Call ends → server sends `call_end` message via LiveKit data channel
- Server begins debrief generation (LLM transcript analysis)
- Client shows Call Ended screen, starts timer
- Client receives debrief data via API
- When timer elapsed AND debrief ready → auto-transition to debrief screen

[Source: `_bmad-output/planning-artifacts/architecture.md` — Data Flow, LiveKit Data Channel Messages]

### Navigation Context

```
Scenario List → Call Screen → **Call Ended** → Debrief → (back) → Scenario List
```

The Call Ended screen is a **non-interactive waypoint** in the forward-only navigation flow. The user cannot go back from this screen (the call is over), and they cannot skip forward (the debrief must load). The only path is the auto-transition to debrief.

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Navigation: Forward Flow]

### Post-Action Feedback Reference

| Event | Feedback | Duration |
|-------|----------|----------|
| Call ended (hung up) | "Call Ended" overlay + theatrical phrase | 3-4 seconds, auto-transition |
| Call ended (survived) | Same overlay, different tone | 3-4 seconds, auto-transition |

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Post-Action Feedback Pattern]

### Project Structure Notes

- Deliverable location: `_bmad-output/planning-artifacts/call-ended-screen-design.md`
- Story file location: `_bmad-output/implementation-artifacts/2-3-design-call-ended-transition-screen.md` (this file)
- No code files created or modified (design story)
- No Flutter/Python pre-commit checks needed (no code changes)

### References

- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Phase 5: Post-Call Transition (3-5 seconds)]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Hang-Up Animation section]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — CallEndedOverlay component]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Post-Action Feedback Pattern]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Forward Navigation Flow]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Loading & Transition Patterns]
- [Source: `_bmad-output/planning-artifacts/prd.md` — NFR: Debrief generation time <5s, 10s ceiling]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR9: User can view debrief after each call]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR11: Debrief provides survival/completion percentage]
- [Source: `_bmad-output/planning-artifacts/architecture.md` — LiveKit Data Channel Messages (call_end type)]
- [Source: `_bmad-output/planning-artifacts/architecture.md` — Data Flow (call lifecycle steps)]
- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 2, Story 2.3 acceptance criteria]
- [Source: `_bmad-output/planning-artifacts/incoming-call-screen-design.md` — Design doc format reference]
- [Source: `_bmad-output/planning-artifacts/onboarding-screen-designs.md` — Design doc format reference]
- [Source: `_bmad-output/implementation-artifacts/2-1-design-onboarding-flow-screens.md` — Previous story patterns]
- [Source: `_bmad-output/implementation-artifacts/2-2-design-first-call-incoming-call-animation.md` — Previous story patterns]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

None — design story, no code debugging required.

### Completion Notes List

- Designed Call Ended screen reusing incoming call layout (Story 2.2): character name, role, avatar
- Added call duration at 38px (same prominence as character name)
- Added achievement percentage (24px, variant-colored) and progress bar (8px, #38383A track)
- Theatrical phrase in Inter Italic 24px with 42px horizontal padding
- "Call Ended" label at 20px Regular below avatar — understated status label
- Four emotional variants: failure (character hung up), failure (user hung up), success (survived), neutral (network loss)
- New screen-specific token: `progress-bg` #38383A for progress bar track
- Reused `call-secondary` #C6C6C8 from Story 2.2 for character role
- Entry transition: 500ms fade-out + 500ms fade-in (1000ms total), accounts for blurred call screen background
- Exit transition: 600ms crossfade with 300ms overlap to debrief (900ms total)
- Hold duration: 3s minimum (5s with screen reader), 10s maximum — canonical values
- All color combinations pass WCAG 2.1 AA contrast
- All 5 open questions resolved during code review
- Added: back navigation blocking, screen reader semantic labels, 0% and 0:00 edge cases, vertical overflow verification
- Typography deviations from story spec documented as intentional (duration 38px, phrase 24px Italic, label Regular)

### Change Log

- 2026-04-01: Created call-ended-screen-design.md with full design specification (Tasks 1-5)
- 2026-04-01: Updated design to match Walid's final Figma — added character identity (name/role/avatar from incoming call), achievement percentage, progress bar, changed typography and layout
- 2026-04-01: Code review completed (3 layers: Blind Hunter, Edge Case Hunter, Acceptance Auditor). Applied all findings:
  - Resolved 5 intent gaps (IG-1 through IG-5): percentage on both screens, Rive before screen, voluntary hang-up = failure, network loss = neutral, survival_pct field
  - Fixed 7 bad spec items (BS-1 through BS-7): documented token/typography deviations as intentional, standardized hold duration 3-10s, qualified fallback exception
  - Applied 10 patches (P-1 through P-10): edge cases, accessibility, back gesture, responsive overflow verification
  - Resolved all 5 open questions — no unresolved items remain
  - Added voluntary hang-up variant, network loss variant, variant selection logic table

### File List

- `_bmad-output/planning-artifacts/call-ended-screen-design.md` (NEW) — Complete design specification
- `_bmad-output/implementation-artifacts/2-3-design-call-ended-transition-screen.md` (MODIFIED) — Story file updated
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (MODIFIED) — Status updated
