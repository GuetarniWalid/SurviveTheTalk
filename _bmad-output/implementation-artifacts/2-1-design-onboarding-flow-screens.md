# Story 2.1: Design Onboarding Flow Screens

Status: done

## Story

As a designer,
I want complete visual designs for the onboarding flow (email entry, GDPR consent, EU AI Act disclosure),
so that Epic 4 (Onboarding & Auth) can be implemented without design ambiguity.

## Nature of This Story

This is a **design specification story**, not a code implementation story. The deliverable is a set of detailed screen design documents in markdown format with exact layout specs, spacing, typography, color values, and interaction specifications. These specs directly unblock Epic 4, Story 4.3 (email auth flow) and Story 4.4 (consent/disclosure/mic permission flow).

**Output format:** Markdown design specs with precise measurements — the same format used throughout the UX design specification. No external design tools required. Each screen gets a complete layout specification table with pixel measurements, color tokens, typography styles, and interaction behaviors.

## Acceptance Criteria

### AC1: Email Entry Screen Design

**Given** the UX spec defines zero-friction onboarding (email → consent → mic → call)
**When** designing the email entry screen
**Then** the design is complete with:
- Full layout specification table (position, size, spacing for every element)
- Input field styling: background, border, text color, placeholder text, focus state
- Submit button: size, color, label, disabled/enabled states
- Dark theme compliance: #1E1F23 bg, #F0F0F0 text, Inter font
- SafeArea handling for notch/Dynamic Island
- Keyboard behavior: screen adjusts when keyboard opens
- Error state: invalid email visual feedback
- Responsive layout for 320-430px width range

### AC2: Consent & AI Disclosure Screen Design

**Given** GDPR consent and EU AI Act Article 50 disclosure are mandatory pre-first-call gates
**When** designing the consent screen
**Then** the design integrates both legal requirements into a single minimal-friction screen with:
- GDPR consent text: plain language, specific purpose statement, link to privacy policy
- EU AI Act Article 50 disclosure: prominent AI-generated content notice (voice + text are AI-generated)
- Single "Got it. Bring it on." action button (no pre-ticked checkboxes)
- Consent must be freely given — no dark patterns, clear decline path
- Typography hierarchy: disclosure headline visible, legal text readable (min body 16px)
- WCAG 2.1 AA contrast ratios maintained
- Layout specification table with all measurements

### AC3: Flow Transition Design

**Given** these screens precede the first incoming call (email → consent → mic permission → incoming call)
**When** the flow is designed end-to-end
**Then** transitions between screens are defined:
- Email → Consent: transition type, duration, direction
- Consent → System mic permission dialog: timing (immediate after accept tap)
- Mic permission granted → Incoming call animation: transition type, duration
- Mic permission denied → Error state: in-persona character message ("I can't hear you. Check your mic.")
- Visual continuity maintained across all transitions (same dark bg, no jarring changes)

## Tasks / Subtasks

- [x] Task 1: Design email entry screen (AC: #1)
  - [x] 1.1 Define screen layout grid (SafeArea, vertical centering, horizontal padding 20px)
  - [x] 1.2 Specify app logo/wordmark placement (if any — keep minimal per UX spec)
  - [x] 1.3 Specify email input field (dimensions, colors, states: empty/focused/filled/error)
  - [x] 1.4 Specify submit button (dimensions, color, label, states: disabled/enabled/loading)
  - [x] 1.5 Specify helper text and error message styling
  - [x] 1.6 Define keyboard interaction behavior (scroll/resize)
  - [x] 1.7 Create complete layout specification table

- [x] Task 2: Design consent & AI disclosure screen (AC: #2)
  - [x] 2.1 Define content hierarchy: headline → AI disclosure → GDPR consent → privacy policy link → action button
  - [x] 2.2 Specify AI disclosure block (text, icon/badge, background treatment to make it prominent)
  - [x] 2.3 Specify GDPR consent text block (plain language, specific purpose)
  - [x] 2.4 Specify privacy policy link styling
  - [x] 2.5 Specify "Got it. Bring it on." button (same styling as submit button — consistency)
  - [x] 2.6 Specify decline/back path (system back gesture returns to email screen)
  - [x] 2.7 Create complete layout specification table

- [x] Task 3: Define screen transitions (AC: #3)
  - [x] 3.1 Define email → consent transition (type, duration, easing)
  - [x] 3.2 Define consent accept → mic permission request timing
  - [x] 3.3 Define mic granted → incoming call animation transition
  - [x] 3.4 Define mic denied → error state design and recovery flow
  - [x] 3.5 Document complete flow diagram with all branch paths

- [x] Task 4: Create consolidated design document
  - [x] 4.1 Compile all specs into a single design document: `_bmad-output/planning-artifacts/onboarding-screen-designs.md`
  - [x] 4.2 Include a flow diagram (mermaid or text) showing the complete onboarding sequence
  - [x] 4.3 Cross-reference all design tokens used (from UX spec)
  - [x] 4.4 Note any open questions or decisions for Walid's review

## Dev Notes

### Design System Tokens (from UX Spec — UX-DR1, UX-DR2, UX-DR3)

**Colors:**
| Token | Hex | Usage in Onboarding |
|-------|-----|---------------------|
| `background` | `#1E1F23` | Screen background |
| `text-primary` | `#F0F0F0` | All body text, input text, button labels |
| `text-secondary` | `#9A9AA5` | Placeholder text, helper text, legal fine print |
| `accent` | `#00E5A0` | Submit/Accept button background, links |
| `destructive` | `#E74C3C` | Error states (invalid email) |
| `avatar-bg` | `#414143` | Input field background, card backgrounds |

**Typography (Inter font family + Frijole for app title):**
| Style | Font | Size | Weight | Usage in Onboarding |
|-------|------|------|--------|---------------------|
| `app-title` | Frijole | 48px | Regular (400) | App title "Survive / The Talk" |
| `tagline` | Inter | 20px | Italic (400) | Tagline on email entry |
| `headline` | 18px | Inter | SemiBold (600) | Screen titles, AI disclosure headline |
| `body` | Inter | 16px | Regular (400) | Consent text, disclosure text, helper text |
| `body-emphasis` | Inter | 16px | Medium (500) | Key disclosure phrases |
| `button-label` | Inter | 14px | SemiBold (600) | Button labels |
| `input-label` | Inter | 12px | SemiBold (600) | Input field labels |
| `label` | Inter | 12px | Medium (500) | Secondary labels |
| `caption` | Inter | 13px | Regular (400) | Privacy policy link, fine print |

**Spacing:**
| Property | Value |
|----------|-------|
| Base unit | 8px |
| Screen padding horizontal | 20px |
| Screen padding vertical | 30px (top SafeArea + 30px) |
| Element gap (standard) | 16px |
| Element gap (tight) | 8px |
| Button height | 55px (custom — both screens consistent) |
| Input field height | 56px (Material Design 3 standard) |

### Regulatory Requirements

**GDPR Consent (FR24):**
- Consent must be freely given, specific, informed, unambiguous
- No pre-ticked checkboxes — explicit opt-in required
- Plain language at 8th-grade reading level
- Must state specific purpose: "We process your email to create your account and send login codes"
- Must link to full privacy policy
- Must be as easy to withdraw as to grant (future settings screen)
- Timestamped consent log (backend implementation — Story 4.2)

**EU AI Act Article 50 (FR25, FR39) — Effective August 2, 2026:**
- Must disclose that user is interacting with an AI system
- Must label AI-generated audio (TTS voice) and text (LLM responses) as artificially generated
- Disclosure must be "clear and distinguishable" — not buried in fine print
- Recommended: combine visible disclosure with technical metadata
- Example text: "You will speak with AI-generated characters. Their voices and responses are created by artificial intelligence, not real people."

**Microphone Permission (FR26):**
- System-level permission dialog — cannot be customized
- Request timing: after consent acceptance, before first call
- Denial handling: in-persona error message from character (per UX spec)

### Screen Flow (Complete Onboarding Sequence)

```
App Opens
  │
  ├─ [Returning user with valid session] → Scenario List
  │
  └─ [New user / no session]
       │
       ▼
  ┌─────────────────────┐
  │  Email Entry Screen  │  ← Task 1
  │  (enter email)       │
  └──────────┬──────────┘
             │ Submit
             ▼
  ┌─────────────────────────────────┐
  │  Consent & AI Disclosure Screen  │  ← Task 2
  │  (GDPR + EU AI Act Article 50)  │
  └──────────┬──────────────────────┘
             │ "Got it. Bring it on."
             ▼
  ┌─────────────────────┐
  │  System Mic Dialog   │  (iOS/Android native)
  └──────┬───────┬──────┘
         │       │
    Granted    Denied
         │       │
         ▼       ▼
  ┌──────────┐  ┌─────────────────────┐
  │ Incoming │  │ "I can't hear you"  │
  │ Call     │  │ + re-request prompt  │
  │ (2.2)   │  └─────────────────────┘
  └──────────┘
```

### Architecture Compliance

**Output location:** `_bmad-output/planning-artifacts/onboarding-screen-designs.md`
- This is a planning artifact (design spec), not an implementation artifact
- Will be consumed by Epic 4 stories (4.3 and 4.4) during implementation
- Must use the same design token names as `ux-design-specification.md` for consistency

**Flutter implementation context (for design awareness):**
- These screens will be built as Flutter widgets in `client/lib/features/auth/views/`
- Material Design 3 components: `TextField` (email input), `ElevatedButton` (submit/accept), `Text` widgets
- GoRouter navigation between screens
- Theme defined in `client/lib/core/theme/` (app_colors.dart, app_typography.dart, app_theme.dart)
- Dark theme: `ThemeData` with `brightness: Brightness.dark`

### What NOT to Do

- **DO NOT** create a multi-step tutorial or feature tour — the call IS the onboarding (zero-instruction principle)
- **DO NOT** add welcome screens, splash explanations, or "how it works" panels
- **DO NOT** design for landscape orientation — portrait only
- **DO NOT** use any colors outside the established design token palette
- **DO NOT** add social login buttons (Google, Apple) — email-only for MVP (FR22)
- **DO NOT** add a "Terms of Service" checkbox separate from the consent screen — keep it one consolidated screen
- **DO NOT** design push notification permission request here — that happens after the first completed call (FR27)
- **DO NOT** over-design — these are minimal friction gates, not feature-rich screens
- **DO NOT** create actual image/mockup files — the deliverable is detailed markdown specs with measurements
- **DO NOT** add the microphone permission screen design — that's a system dialog, not custom UI
- **DO NOT** use fonts other than Inter and Frijole — Inter for all UI text, Frijole for app title only (approved during code review)

### Cross-Story Context

**Predecessor:** No previous design story in Epic 2. This is the first.

**Immediate successor:** Story 2.2 (Design First-Call Incoming Call Animation)
- The last screen in this story's flow (consent accept → mic granted) transitions directly into the incoming call animation designed in Story 2.2
- Visual continuity is critical: same dark background, same character face appearing
- Coordinate transition timing so Story 2.2 can pick up exactly where this story ends

**Downstream consumers:**
- Epic 4, Story 4.3 (Build Email Authentication Flow in Flutter) — will implement the email entry screen
- Epic 4, Story 4.4 (Build Consent, AI Disclosure, and Microphone Permission Flow) — will implement the consent screen
- Both stories depend on exact pixel specifications from this design

### Previous Story Intelligence (from Epic 1 Retrospective)

**Key learnings applied to this story:**
1. **Detailed specs = velocity multiplier.** Epic 1 proved that exact measurements, "What NOT to Do" lists, and explicit references eliminate rework. Apply the same rigor to design specs.
2. **Sprint-status discipline.** Dev MUST update sprint-status.yaml at every transition (backlog → in-progress → review). This was the #1 process gap in Epic 1.
3. **Design review process needed.** Epic 1 retro Action Item #2 calls for a design review process for Epic 2 — the story output should be reviewable against UX spec and design tokens.

### Git Intelligence

**Recent commits (6 total):**
- All Epic 1 stories completed successfully
- File pattern: story files in `_bmad-output/implementation-artifacts/`
- Code in `client/lib/` and `server/`
- Current Flutter app: single `main.dart` with CallScreen (PoC state)
- Dark theme already in use: `#1E1F23` bg, `#F0F0F0` text (validated in PoC)

### Design References

| Reference | Source | Section |
|-----------|--------|---------|
| Zero-friction onboarding philosophy | UX spec | Lines 81-86, 929 |
| First-time user journey flow | UX spec | Lines 791-818 (Journey 1: Karim) |
| Color system tokens | UX spec | Lines 516-533 |
| Typography system | UX spec | Lines 542-556 |
| Spacing & layout foundation | UX spec | Lines 560-613 |
| Contrast ratios (WCAG 2.1 AA) | UX spec | Lines 712-720 |
| Onboarding FRs (FR22-FR27) | PRD | Functional Requirements section |
| Auth screen file locations | Architecture | `client/lib/features/auth/views/` |
| Theme file locations | Architecture | `client/lib/core/theme/` |
| Material Design 3 choice | Architecture | Design framework section |
| Epic 1 retro: design review process | Retro doc | Action Item #2 |

### Project Structure Notes

- Design output goes in `_bmad-output/planning-artifacts/` (planning artifact, not implementation)
- Implementation will later go in `client/lib/features/auth/views/` (Epic 4)
- Theme tokens will be defined in `client/lib/core/theme/app_colors.dart` and `app_typography.dart` (Epic 4, Story 4.1)
- No conflicts with existing code — PoC has a single `main.dart` that will be restructured in Story 4.1

## File List

- `_bmad-output/planning-artifacts/onboarding-screen-designs.md` (NEW) — Consolidated onboarding design specification
- `_bmad-output/implementation-artifacts/2-1-design-onboarding-flow-screens.md` (MODIFIED) — Story file updated with task completion
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (MODIFIED) — Status updated to review

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

No debug issues encountered. Design spec story — no code compilation or test execution required.

### Completion Notes List

- ✅ Task 1: Designed email entry screen with full layout spec including SafeArea grid, vertical centering, input field with 4 states (empty/focused/filled/error), submit button with 3 states (disabled/enabled/loading), helper/error text, keyboard interaction behavior (autofocus, scroll adjustment), and responsive layout for 320-430px.
- ✅ Task 2: Designed consent & AI disclosure screen with content hierarchy (title → AI disclosure block → GDPR consent → privacy policy link → button). AI disclosure uses accent left border + card background for EU AI Act "clear and distinguishable" compliance. GDPR consent text in plain language at 8th-grade level. Single "Got it. Bring it on." button, no checkboxes. Decline via system back gesture.
- ✅ Task 3: Defined all 4 transitions: email→consent (slide right, 300ms, easeInOut), consent→mic (immediate system dialog), mic granted→incoming call (fade through black, 800ms total, haptic), mic denied→error bottom sheet (in-persona "I can't hear you" message with Open Settings + Skip for now options).
- ✅ Task 4: Compiled all specs into single `onboarding-screen-designs.md`. Includes mermaid flow diagram, design token cross-reference table, accessibility compliance section (WCAG 2.1 AA), Flutter widget mapping for Epic 4, and 4 open questions for Walid's review.
- All acceptance criteria (AC1, AC2, AC3) are fully satisfied by the design document.

### Implementation Plan

This is a design specification story. The implementation approach was:
1. Read UX spec design tokens (colors, typography, spacing) as the foundation
2. Design each screen per AC requirements with exact pixel measurements
3. Define all state variations (input states, button states, error states)
4. Specify transitions with type, duration, easing, and visual continuity
5. Compile into a single reviewable document with cross-references and open questions
6. Validate WCAG 2.1 AA contrast ratios for all color combinations used

### Change Log

- 2026-03-31: Created onboarding-screen-designs.md with complete specs for email entry screen, consent & AI disclosure screen, screen transitions, and flow diagram. All 4 tasks and 22 subtasks completed.
