# Story 2.5: Design Paywall Screen

Status: done

## Story

As a designer,
I want the paywall screen designed (subscription offer, price, value proposition, accept/decline actions),
so that Epic 8 (Monetization & Subscription) can be implemented with complete visual specs.

## Acceptance Criteria

1. **Given** the UX spec defines paywall as Material BottomSheet or full screen
   **When** the design is complete
   **Then** it includes price display ($1.99/week), value proposition copy, subscribe CTA, and dismiss/decline action
   **And** visual treatment follows the established design tokens (inverted light theme permitted per BottomOverlayCard pattern)

2. **Given** the paywall triggers at moments of maximum intent (after paid scenario tap or overlay card tap)
   **When** reviewing the design
   **Then** the dismiss path returns cleanly to the scenario list with no dark patterns

## Tasks / Subtasks

- [x] Task 1: Define paywall screen format — BottomSheet vs full screen (AC: #1)
  - [x] 1.1 Evaluate BottomSheet vs full-screen tradeoffs for this use case
  - [x] 1.2 Determine final format and document rationale
- [x] Task 2: Design paywall screen layout with all content sections (AC: #1)
  - [x] 2.1 Design hero/value proposition section
  - [x] 2.2 Design price display ($1.99/week) with clear typography
  - [x] 2.3 Design subscribe CTA button
  - [x] 2.4 Design dismiss/decline action (no dark patterns)
  - [x] 2.5 Create layout specification table (Element / Position / Width / Height / Padding)
  - [x] 2.6 Create screen layout diagram (ASCII)
- [x] Task 3: Define all paywall screen states (AC: #1, #2)
  - [x] 3.1 State: Default paywall (first presentation)
  - [x] 3.2 State: Loading/processing subscription purchase
  - [x] 3.3 State: Subscription success confirmation
  - [x] 3.4 State: Subscription error/failure
  - [x] 3.5 Document dismiss behavior per entry point (paid scenario tap, overlay card tap, debrief FR29 trigger)
- [x] Task 4: Define transitions and animations (AC: #2)
  - [x] 4.1 Entry animation (slide up for BottomSheet or fade for full screen)
  - [x] 4.2 Dismiss animation (returns to previous screen cleanly)
  - [x] 4.3 Success transition (back to scenario list with updated state)
- [x] Task 5: Accessibility and responsive verification (AC: #1)
  - [x] 5.1 WCAG 2.1 AA contrast verification for all element combinations
  - [x] 5.2 Screen reader announcements for all content
  - [x] 5.3 Responsive behavior at 320px / 375px / 430px widths
  - [x] 5.4 Touch target compliance (48px minimum)
- [x] Task 6: Flutter widget mapping and file path reference (AC: #1)
  - [x] 6.1 Map each design element to Flutter/Material 3 widgets
  - [x] 6.2 Reference target file paths in MVP architecture

## Dev Notes

### Story Type
This is a **design specification story** — the deliverable is a complete markdown design document placed in `_bmad-output/planning-artifacts/paywall-screen-design.md`. No Flutter code is written. No `flutter analyze` or `flutter test` needed.

### Deliverable
A single design specification document following the format established in Stories 2.1-2.4:
- Token reference tables (colors, typography, spacing)
- Screen layout diagram (ASCII)
- Layout specification tables
- States and transitions
- Accessibility verification
- Flutter widget mapping
- Open questions (resolved during creation)

### Paywall Strategy Context (Critical — Read Before Designing)

**Invisible Tier System (UX-DR16):**
- All scenario cards look identical regardless of free/paid status
- No lock icons, no FREE/PAID badges, no visual differentiation
- User discovers paywall at moment of maximum intent (taps call on paid scenario)
- This is a deliberate conversion strategy — design the paywall to match this philosophy

**Three Paywall Trigger Points:**
1. Free user taps call icon on a paid scenario → paywall appears
2. Free user taps the BottomOverlayCard ("Unlock all scenarios" or "Subscribe to keep calling") → paywall appears
3. Free user reaches debrief after 3rd free scenario (FR29) → paywall appears on debrief screen

**Paywall Content Requirements:**
- Single price point: **$1.99/week** (auto-renewable)
- Value proposition: three benefit lines (access, habit, insight) — "3 calls/day" disclosed in legal fine print per final mockup
- Subscribe CTA: prominent, clear, single action
- Dismiss/decline: visible, no dark patterns, returns cleanly to previous context
- No trial period in MVP (weekly only, no monthly option until Phase 2)

**Clean Dismiss Principle (AC #2):**
- Dismiss from trigger point 1 → returns to scenario list (unchanged)
- Dismiss from trigger point 2 → returns to scenario list (unchanged, overlay card remains)
- Dismiss from trigger point 3 → remains on debrief screen (paywall closes, debrief stays)
- No penalty, no nag, no "are you sure?" confirmation

### Design System Tokens (Reuse Only — No New Tokens Unless Justified)

**Colors from UX Spec:**

| Token | Hex | Expected Usage on Paywall |
|-------|-----|--------------------------|
| `background` | `#1E1F23` | Screen/sheet background |
| `text-primary` | `#F0F0F0` | Heading, price, value proposition text |
| `text-secondary` | `#8A8A95` | Subtitle, legal fine print, "per week" |
| `accent` | `#00E5A0` | Subscribe CTA button background |
| `avatar-bg` | `#414143` | Card backgrounds, dividers if needed |

**Typography from UX Spec (Inter exclusively):**

| Style | Size | Weight | Expected Usage |
|-------|------|--------|----------------|
| `headline` | 18px | SemiBold (600) | Screen/sheet title |
| `body` | 16px | Regular (400) | Value proposition description |
| `body` | 16px | Regular (400) | Benefit text (per final mockup — Regular preferred over Medium for visual lightness on light surface) |
| `display` or custom | TBD | Bold (700) | Price display ($1.99/week) — size TBD, should be prominent |
| `caption` | 13px | Regular (400) | Legal text, "auto-renewable" note |
| `button-label` | 14px | SemiBold (600) | CTA button text (established in Story 2.1, NOT system `label` 12px) |

**Spacing:**

| Property | Value |
|----------|-------|
| Base unit | 8px |
| Screen padding horizontal | 20px |
| Section gap | 24px |
| Element gap | 16px (standard), 8px (tight) |

### Related Components Already Designed

**BottomOverlayCard (UX Spec — Already Fully Specified):**
- Position: Fixed bottom of scenario list
- Background: `#F0F0F0` (inverted — light card on dark bg)
- 4 states: free/calls remaining, free/0 calls permanent, paid/calls available, paid/0 calls today
- Tap → paywall screen (triggers this design)
- Do NOT redesign this component — it's already complete in the UX spec

**Scenario Card (UX Spec — Already Fully Specified):**
- All cards identical regardless of free/paid (invisible tier)
- Call icon tap on paid scenario → paywall (triggers this design)
- Do NOT redesign this component

### Architecture Alignment

**Target Flutter Implementation (for widget mapping reference):**
- Paywall presented as `BottomSheet` (Material 3) or `Dialog` — determine in Task 1
- State management: Likely `SubscriptionBloc` or similar in `features/subscription/` (Epic 8)
- StoreKit 2 (iOS) / Google Play Billing (Android) — actual integration is Epic 8
- This story designs the visual only — no purchase flow logic

**Material 3 Widgets Likely Used:**
- `BottomSheet` or `showModalBottomSheet` (if BottomSheet format chosen)
- `Scaffold` (if full screen format chosen)
- `ElevatedButton` or `FilledButton` — subscribe CTA
- `TextButton` — dismiss action
- `Text`, `Column`, `Padding` — content layout
- `CircularProgressIndicator` — loading state

### PRD Functional Requirements (Must Be Reflected in Design)

| FR | Requirement | Design Impact |
|----|-------------|---------------|
| FR28 | User can subscribe to weekly paid plan ($1.99/week) | Price display, subscribe CTA |
| FR29 | Paywall presented after 3rd free scenario on debrief screen | Third trigger point — design must work as overlay on debrief |
| FR30 | User can manage subscription (view, cancel) | Not in this screen — separate settings screen (Epic 8) |
| FR31 | System enforces call and scenario limits based on tier | Not visual — backend enforcement |

### Business Context (For Copy/Messaging Direction)

- Break-even: ~60 subscribers
- Target free-to-paid conversion: >8% (industry median 2-12%)
- Monthly churn target: <15%
- Value proposition should emphasize: all scenarios + daily calls (scarcity → abundance)
- Pricing perception: "less than a coffee" ($1.99/week ≈ $8.60/month)
- No dark patterns — product philosophy is honest, no manipulation

### Previous Story Intelligence (From Stories 2.1-2.4)

**Design Document Structure (Follow This Pattern):**
1. Design Token Reference (colors, typography, spacing tables)
2. Screen Layout section with ASCII diagram
3. Layout Specification Table (Element / Position / Width / Height / Padding / Notes)
4. Screen States (with visual differences documented)
5. Transitions & Animations (entry, exit, state changes)
6. Accessibility (WCAG contrast table, screen reader, reduced motion)
7. Responsive Behavior (320px / 375px / 430px)
8. Flutter Widget Mapping (widget → file path)
9. Open Questions (resolve during creation)

**Design Token Rules (From Review of 2.3 and 2.4):**
- Reuse existing tokens from UX spec — do NOT introduce screen-specific tokens unless absolutely necessary
- If a new token IS needed, document the rationale explicitly (like `progress-bg` in Story 2.3)
- Cross-reference all token usage with the UX Design Specification

**Story 2.3 Introduced One New Token:** `progress-bg` (#38383A) with documented rationale. This is the only screen-specific token in Epic 2 so far. Prefer existing tokens.

**Story 2.4 Patterns:**
- Card pattern: 16px padding, `#414143` background for content cards
- Section gap: 24px between major sections
- `text-secondary` (#8A8A95 in 2.4 used #9A9AA5 — verify against UX spec, UX spec says #8A8A95)
- Conditional sections: hide entirely when not applicable (like idioms in debrief)

### What NOT to Do

1. **Do NOT design the BottomOverlayCard** — it's already fully specified in the UX spec
2. **Do NOT design scenario cards** — they're already done
3. **Do NOT introduce subscription management UI** — that's Epic 8, Story 8.3
4. **Do NOT add a trial period or monthly option** — MVP is weekly only ($1.99/week)
5. **Do NOT use lock icons or tier badges anywhere** — violates the invisible tier strategy
6. **Do NOT add a "restore purchases" button in the paywall** — that goes in subscription management (8.3)
7. **Do NOT write Flutter code** — this is a design specification only
8. **Do NOT add dark patterns** — no "are you sure?" on dismiss, no countdown timers, no fake urgency
9. **Do NOT use colors outside the established token system** without documented rationale
10. **Do NOT introduce new typography styles** — use the existing Inter-based scale

### Output File

Create the design document at: `_bmad-output/planning-artifacts/paywall-screen-design.md`

Follow the exact format from Stories 2.1-2.4 (see `call-ended-screen-design.md` or `debrief-screen-design.md` for reference).

### Git Intelligence

Recent commits show a consistent pattern for Epic 2 design stories:
- Each commit creates both the story file update AND a design spec in `planning-artifacts/`
- Commit format: `feat: design [screen name] (Story 2.X)`
- Design docs created: `onboarding-screen-designs.md`, `incoming-call-screen-design.md`, `call-ended-screen-design.md`, `debrief-screen-design.md`
- Expected output: `paywall-screen-design.md`

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Epic 2, Story 2.5]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — Paywall Screen, BottomOverlayCard, Invisible Tier Strategy]
- [Source: _bmad-output/planning-artifacts/prd.md — FR28, FR29, FR30, FR31, Free/Paid Tiers]
- [Source: _bmad-output/planning-artifacts/architecture.md — Flutter project structure, Material 3 theme, BLoC patterns]
- [Source: _bmad-output/planning-artifacts/call-ended-screen-design.md — Design document format reference]
- [Source: _bmad-output/planning-artifacts/debrief-screen-design.md — Design document format reference]
- [Source: _bmad-output/implementation-artifacts/2-4-design-debrief-screen.md — Previous story learnings]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

None — clean execution, no blocking issues encountered.

### Implementation Plan

- Chose Modal Bottom Sheet format over full screen after evaluating 7 tradeoff factors
- Designed with inverted light theme (white #F0F0F0 sheet on dark app background) — follows BottomOverlayCard pattern from UX spec
- Introduced screen-specific tokens: `paywall-surface` (#F0F0F0), `paywall-text-secondary` (#4C4C4C from BottomOverlayCard), `paywall-price` (36px Bold)
- Final copy: "Speak English for real" title, 3 benefits, "Let's go" CTA, 32px primary spacing
- Defined 4 states (default, loading, success, error) + dismiss behavior per 3 entry points
- Design went through 2 revision rounds after initial creation (copy rewrite + full visual redesign to light theme)

### Completion Notes List

- Task 1: Evaluated BottomSheet vs full screen across 7 factors. Chose Modal Bottom Sheet for maximum dismissibility, context preservation, and alignment with no-dark-patterns principle.
- Task 2: Designed complete layout with ASCII diagram, all element specs. Final design: inverted light theme (#F0F0F0 surface), title + subtitle + price hero + 3 benefits + CTA + dismiss + legal. Sheet height ~552px (65% iPhone 14). Uses 32px primary spacing between sections.
- Task 3: Defined 4 states (default, loading/processing, success confirmation, error/failure) plus user-cancelled-purchase handling. Documented dismiss behavior for all 3 entry points (paid scenario, overlay card, debrief FR29).
- Task 4: Specified entry (300ms slide-up), dismiss (250ms slide-down with 3 trigger methods), and success (200ms crossfade + 1.5s hold + 250ms dismiss) transitions. Added reduced motion behavior and Mermaid navigation diagram.
- Task 5: Verified WCAG 2.1 AA contrast for light-theme combinations. Identified: green checkmarks on white (1.6:1) acceptable as decorative icons, error red darkened to #C0392B (4.7:1) for AA compliance. Defined screen reader announcements with title-first focus. Confirmed 48px touch targets. iPhone SE overflow handled via SingleChildScrollView.
- Task 6: Mapped all design elements to Flutter/Material 3 widgets (17 mappings). Referenced 7 target file paths in MVP architecture.

### File List

- `_bmad-output/planning-artifacts/paywall-screen-design.md` — NEW: Complete paywall screen design specification
- `_bmad-output/implementation-artifacts/2-5-design-paywall-screen.md` — MODIFIED: Tasks checked, status updated, Dev Agent Record filled
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — MODIFIED: Story 2-5 status updated (ready-for-dev -> in-progress -> review)

### Change Log

- 2026-04-02: Created paywall screen design specification document with all 6 tasks complete. Format: Modal Bottom Sheet. Inverted light theme (#F0F0F0 surface on dark app). Three screen-specific tokens (paywall-surface, paywall-text-secondary, paywall-price). Copy: "Speak English for real" / 3 benefits / "Let's go" CTA. Two post-creation revision rounds applied (copy rewrite + full visual redesign from dark to light theme per Figma mockup).
- 2026-04-02: Code review corrections applied — fixed `label` → `button-label` token, committed error text to #C0392B (WCAG AA), corrected contrast ratios (5.7:1, 1.6:1), clarified focus management (title-first), mandated SingleChildScrollView for iPhone SE, resolved error re-tap behavior, added 15s loading timeout, added screen reader success timing (5s), fixed Mermaid diagram entry points, specified Icon widget for checkmarks, added open questions for Epic 8.
