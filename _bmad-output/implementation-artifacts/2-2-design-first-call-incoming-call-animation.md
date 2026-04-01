# Story 2.2: Design First-Call Incoming Call Animation

Status: done

## Story

As a designer,
I want the first-call incoming call screen fully designed (character face, name, vibration pattern, answer button),
so that the critical onboarding moment ("The Phone Rings") can be implemented faithfully.

## Context

This is the **make-or-break onboarding moment**. After Story 2.1's friction-minimized consent flow (email → consent → mic permission), the user's screen fades to black and then the incoming call animation appears. This is the user's FIRST real interaction with the product — not a tutorial, not a menu, but the product itself.

The incoming call screen simulates a native FaceTime/WhatsApp incoming call. It is seen **only once** (first launch after email entry). Every subsequent call is user-initiated from the scenario list.

**Emotional design goal:** Create a visceral, real-feeling "phone ringing" moment that triggers an emotional spike (excitement, not generic). If this moment feels flat or app-like, the entire phone call illusion fails.

**Story type:** Design specification (markdown deliverable, no code).

## Acceptance Criteria

1. **AC1: Visual Components Specified**
   - Character face/avatar placement, size, and visual treatment defined
   - Character name display specs (typography, positioning)
   - Green "Answer" button specs (size, position, color, label, icon)
   - Background treatment defined (dark, mimicking native incoming call)
   - Overall layout simulates FaceTime/WhatsApp incoming call aesthetic

2. **AC2: Emotional & Interaction Design**
   - Vibration feedback pattern specified (pulsed incoming call pattern)
   - Ringing animation specs defined (visual pulse/glow or ring indicator)
   - The visual creates emotional spike — visceral, real-feeling, not generic
   - Answer button interaction states defined (default, pressed, loading)

3. **AC3: Transitions Specified**
   - Entry transition: picks up from Story 2.1's Transition 3 (fade from black, 500ms fade-in, haptic medium impact)
   - Exit transition: user taps "Answer" → transition to call screen (Story 2.6/Epic 6) defined
   - Timing and visual continuity between consent flow → incoming call → call screen specified end-to-end

## Tasks / Subtasks

- [x] Task 1: Design screen layout (AC: #1)
  - [x] 1.1 Define overall screen composition and z-order
  - [x] 1.2 Specify character avatar/face placement, size, and visual treatment
  - [x] 1.3 Specify character name display (typography, position, content)
  - [x] 1.4 Specify caller subtitle/context line (e.g., "Incoming call...")
  - [x] 1.5 Create layout specification table with all element positions
  - [x] 1.6 Define responsive behavior (320-430px width)

- [x] Task 2: Design Answer button (AC: #1, #2)
  - [x] 2.1 Specify button size, shape, color, icon, label
  - [x] 2.2 Define button states (default, pressed, loading/connecting)
  - [x] 2.3 Specify button position (bottom center, padding)
  - [x] 2.4 Define Decline button specs (red, left of answer — optional per native call pattern)

- [x] Task 3: Define animation and feedback (AC: #2)
  - [x] 3.1 Specify vibration pattern (pulse timing, duration, repeat)
  - [x] 3.2 Specify ringing visual indicator (pulse/glow around avatar, ring animation)
  - [x] 3.3 Define animation loop timing (ring cycle duration)
  - [x] 3.4 Specify any audio cue consideration (ringtone or silent — design decision)

- [x] Task 4: Define transitions (AC: #3)
  - [x] 4.1 Document entry transition (from Story 2.1 Transition 3 handoff)
  - [x] 4.2 Specify exit transition: Answer tap → call screen
  - [x] 4.3 Specify exit transition: Decline tap behavior (if decline button included)
  - [x] 4.4 Define transition timing and easing curves

- [x] Task 5: Accessibility and documentation (AC: #1, #2, #3)
  - [x] 5.1 Verify WCAG 2.1 AA contrast for all elements
  - [x] 5.2 Define screen reader announcements
  - [x] 5.3 Create Mermaid flow diagram showing incoming call in context
  - [x] 5.4 Cross-reference design tokens with UX spec

- [x] Task 6: Write deliverable document
  - [x] 6.1 Create `_bmad-output/planning-artifacts/incoming-call-screen-design.md`
  - [x] 6.2 Include all specs from Tasks 1-5
  - [x] 6.3 Include Flutter widget mapping for Epic 4/Epic 6 implementation
  - [x] 6.4 List open questions for Walid's review

## Dev Notes

### This is a Design Story — NOT Code

The deliverable is a **markdown design specification** document at `_bmad-output/planning-artifacts/incoming-call-screen-design.md`, following the same format established in Story 2.1 (`onboarding-screen-designs.md`). No Flutter/Python code is written.

### Design System Tokens (from UX Spec + Story 2.1)

| Token | Hex | Usage |
|-------|-----|-------|
| `background` | `#1E1F23` | Screen background |
| `text-primary` | `#F0F0F0` | Character name |
| `avatar-bg` | `#414143` | Character avatar background circle |

**Typography:** Inter font family (all styles). NO Frijole on this screen — Frijole is email entry screen only.

#### Screen-Specific Token Overrides (per Walid's Figma review, 2026-04-01)

This screen intentionally deviates from system-wide tokens to achieve a native phone call aesthetic. The following screen-specific tokens were approved via Figma review:

| Token | Hex | Replaces | Rationale |
|-------|-----|----------|-----------|
| `call-secondary` | `#C6C6C8` | `text-secondary` (#9A9AA5) | Lighter gray for native call aesthetic, better contrast (9.8:1 vs 5.1:1) |
| `call-accept` | `#50D95D` | `accent` (#00E5A0) | Native iOS/Android phone call green |
| `call-decline` | `#FD3833` | `destructive` (#E74C3C) | Native iOS/Android phone call red |

| Style | Font | Size | Weight | Usage |
|-------|------|------|--------|-------|
| `call-name` | Inter | 38px | Regular (400) | Character name (screen-specific, larger than system headline) |
| `call-role` | Inter | 16px | Regular (400) | Character role below name |
| `call-status` | Inter | 24px | Regular (400) | "Calling..." status text |
| `call-button-label` | Inter | 14px | Regular (400) | Button labels ("Accept", "Decline") |

**Button size override:** 60x60px circles (vs system 55px rectangular buttons). Circular shape matches native phone call UI.
**Button row padding override:** 30px horizontal (vs system 20px). Wider padding for balanced button spacing on the call screen.

### Entry Transition — Handoff from Story 2.1

Story 2.1 defines Transition 3 (Mic Granted → Incoming Call):
- **Trigger:** User grants microphone permission
- **Sequence:**
  1. Permission granted → system dialog dismisses
  2. Consent screen fades to `#1E1F23` (300ms, `Curves.easeIn`)
  3. **THIS SCREEN** fades in (500ms, `Curves.easeOut`)
  4. Medium impact haptic feedback on transition start
  5. Device vibration begins (incoming call pulse pattern)
- **Total transition:** 800ms
- **Visual continuity:** Fade-through-black creates clear scene break (leaving "setup" phase, entering "experience" phase)

[Source: `_bmad-output/planning-artifacts/onboarding-screen-designs.md` — Transition 3]

### Exit Transition — Answer Tap

When user taps Answer:
- Transition to the Call Screen (connection animation, then Rive character appears)
- Per UX spec: "The screen transitions to a full-screen call connection view — brief 'connecting...' animation (1-2 seconds maximum) that mimics a real phone dialing."
- This masks pipeline initialization (LiveKit connection, Pipecat session setup)
- The character speaks first, ALWAYS

[Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Phase 1: Call Initiation]

### Native Incoming Call Reference Pattern

Simulate the look and feel of iOS/Android native incoming call screens:
- **iOS FaceTime:** Large circular avatar centered, caller name below, Accept (green circle) and Decline (red circle) at bottom
- **WhatsApp call:** Avatar top-center, name + "WhatsApp Audio..." label, green/red circle buttons bottom
- **Key elements:** Dark background, centered character identity, prominent accept/decline buttons, pulsing ring animation around avatar, vibration pattern

### Screen Will Be Consumed By

- **Epic 4, Story 4.5:** Build First-Call Incoming Call Experience (Flutter implementation of this design)
- **Epic 6:** Call screen transitions reference the exit transition from this screen

### What NOT to Do

- **Do NOT design the Call Screen itself** — that's Story 2.6 (Rive character puppet) and Epic 6 (animated call experience)
- **Do NOT specify Rive animation details** — the incoming call screen uses standard Flutter widgets (no Rive on this screen; Rive starts on the call screen after Answer)
- **Do NOT create Figma files or image mockups** — deliverable is markdown specs only (same as Story 2.1)
- **Do NOT include any text-based feedback or tutorial text** — the incoming call IS the onboarding, no instructions needed
- **Do NOT add a "call duration" timer** — this is an incoming call, not an active call
- **Do NOT design for landscape orientation** — portrait only per UX spec

### Previous Story Intelligence (Story 2.1)

**Patterns to follow from Story 2.1:**
- Same design document structure: token reference table → screen layout diagram → element specs → states → transitions → accessibility → open questions
- Same layout specification table format (Element / Position / Width / Height / Padding / Notes)
- Same responsive behavior breakdown (320px / 375px / 430px)
- Same WCAG 2.1 AA contrast verification table format
- Same Flutter widget mapping table for downstream implementation

**Story 2.1 design decisions that apply here:**
- `text-secondary` is `#9A9AA5` (NOT `#8A8A95` — updated for WCAG AA in Story 2.1)
- Buttons are 55px height with 12px border radius
- Screen padding horizontal: 20px
- Touch target minimum: 44px

**Story 2.1 transition handoff coordinates:**
- This screen picks up at the END of Story 2.1's flow
- Visual context: user just accepted consent + granted mic permission
- Emotional context: user is past legal gates, expecting the product experience
- The fade-through-black transition creates a deliberate scene break

[Source: `_bmad-output/implementation-artifacts/2-1-design-onboarding-flow-screens.md`]

### Git Intelligence

**Last commit (HEAD):** `e96d1cd feat: design onboarding flow screens (Story 2.1)`
- Created `_bmad-output/planning-artifacts/onboarding-screen-designs.md` (719 lines)
- Created `_bmad-output/implementation-artifacts/2-1-design-onboarding-flow-screens.md` (304 lines)
- Updated sprint-status.yaml

**Pattern established:** Design stories produce markdown spec files in `_bmad-output/planning-artifacts/` with the design document, and the story file in `_bmad-output/implementation-artifacts/`. Follow this exact pattern.

### Project Structure Notes

- Deliverable location: `_bmad-output/planning-artifacts/incoming-call-screen-design.md`
- Story file location: `_bmad-output/implementation-artifacts/2-2-design-first-call-incoming-call-animation.md` (this file)
- No code files created or modified (design story)
- No Flutter/Python pre-commit checks needed (no code changes)

### References

- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Critical Moment 1: "The Phone Rings"]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Phase 1: Call Initiation, first-call special case]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Screen 2: Call Screen layout]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Navigation: Forward Flow (No Escape)]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — Action Hierarchy During Calls]
- [Source: `_bmad-output/planning-artifacts/onboarding-screen-designs.md` — Transition 3: Mic Granted → Incoming Call]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR23: first incoming call after account creation]
- [Source: `_bmad-output/planning-artifacts/prd.md` — NFR: 60fps animation frame rate target]
- [Source: `_bmad-output/planning-artifacts/architecture.md` — Design System / Theming section]
- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 2, Story 2.2 acceptance criteria]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

No debug issues encountered. Design story — no code compilation or test execution.

### Completion Notes List

- Created comprehensive incoming call screen design spec (incoming-call-screen-design.md)
- Updated design to match Walid's final Figma screenshot — significant layout changes from initial draft
- Layout: name (38px) + role at top → avatar centered → "Calling..." (24px) below avatar → buttons at bottom
- Screen-specific color tokens: secondary text #C6C6C8, accept #50D95D, decline #FD3833 (native phone colors)
- Buttons: 60x60px circles, Row with spaceBetween, 30px horizontal padding
- Labels: "Accept"/"Decline" in Inter Regular 14px #C6C6C8
- New element: character role line (e.g., "Girlfriend") — Inter Regular 16px #C6C6C8
- Vibration pattern: 800ms-400ms-800ms-1600ms pulse cycle mimicking phone ring
- Ring animation: 3 concentric expanding circles (#50D95D) with staggered 667ms timing
- Subtle avatar scale pulse (1.0→1.02) synced to vibration cycle
- Design decision: No ringtone audio (vibration + visual sufficient; audio can be added post-MVP)
- Design decision: Decline button included for native call realism; decline navigates to scenario list
- Entry transition picks up from Story 2.1 Transition 3 (800ms total: 300ms fade-out + 500ms fade-in)
- Exit transition (Accept): button loading state → connecting animation → call screen (masks pipeline init)
- Exit transition (Decline): 300ms fade-out → scenario list with tutorial scenario as regular card
- WCAG 2.1 AA verified — all text passes; noted icon-on-button contrast follows native phone UI pattern
- Design tokens cross-referenced: system tokens preserved, screen-specific tokens documented with rationale
- Flutter widget mapping table and file locations provided for Epic 4/6 implementation
- Document follows same structure as Story 2.1 design output
- 4 open questions flagged for Walid's review

### File List

- `_bmad-output/planning-artifacts/incoming-call-screen-design.md` (NEW — design deliverable)
- `_bmad-output/implementation-artifacts/2-2-design-first-call-incoming-call-animation.md` (MODIFIED — this story file)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (MODIFIED — status updates)

### Change Log

- 2026-04-01: Created incoming call screen design specification covering all 6 tasks (layout, button design, animation/feedback, transitions, accessibility, deliverable document). All acceptance criteria satisfied.
- 2026-04-01: Updated design document to match Walid's final Figma screenshot — revised layout (name/role top, avatar center, calling below, buttons bottom), screen-specific color tokens (#C6C6C8, #50D95D, #FD3833), button sizing (60px), typography (38px name, 24px calling, 14px labels), and button row layout (spaceBetween, 30px padding).
