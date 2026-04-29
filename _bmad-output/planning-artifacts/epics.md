---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - prd.md
  - architecture.md
  - ux-design-specification.md
---

# surviveTheTalk2 - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for surviveTheTalk2, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

**Call Experience (FR1-FR8):**

FR1: User can initiate a voice call with an AI character from the scenario list
FR2: User can speak in English and receive real-time spoken responses from the AI character
FR3: User can see the AI character's animated emotional reactions during the call (facial expressions, gestures)
FR4: User can see the AI character's mouth movements synchronized with its speech
FR5: AI character reacts emotionally based on the quality and content of the user's speech
FR6: AI character ends the call (hangs up) when user performance drops below scenario thresholds or user behavior is inappropriate
FR7: User can end the call voluntarily at any time
FR8: System displays a phone-style "no network" screen when user attempts a call without internet connectivity

**Post-Call Debrief (FR9-FR15b):**

FR9: User can view a debrief report after each completed or failed call
FR10: Debrief identifies specific language errors the user made with correct alternatives provided
FR11: Debrief provides a survival/completion percentage for the call
FR12: Debrief highlights longest hesitation moments and their context
FR13: Debrief explains idioms or slang the user encountered but may not have understood
FR14: User can view a short situational briefing (key vocabulary, context, what to expect) before attempting a scenario for the first time
FR15: User can retry a scenario after viewing the debrief by navigating back to the scenario list (no direct retry button — intentional friction for study encouragement and cost control)
FR15b: Debrief presents failure context with encouraging framing when user completion exceeds 40% (e.g., proximity to next threshold, specific improvement since last attempt)

**Scenario Management (FR16-FR21):**

FR16: User can browse a list of all available scenarios with title and completion percentage
FR17: User can initiate a call or view the debrief/tips for each scenario from the list
FR18: User can see their best completion percentage per scenario across attempts
FR19: Scenarios are ordered in the scenario list from least to most challenging, with the first scenario calibrated for near-guaranteed user success
FR20: Free users can access 3 scenarios; paid users access all scenarios
FR21: Free users get 3 calls total (lifetime, no daily recharge); paid users get 3 calls per day

**User Onboarding & Authentication (FR22-FR27):**

FR22: User can create an account with email only
FR23: User receives their first incoming call immediately after account creation with no tutorial
FR24: User is presented with consent and privacy information before first use
FR25: User is informed that they are interacting with AI-generated characters and voices before first call
FR26: System requests microphone permission before the first call
FR27: System requests push notification permission after the first completed call — **REMOVED FROM MVP** (per Architecture decision)

**Monetization (FR28-FR31):**

FR28: User can subscribe to a weekly paid plan ($1.99/week)
FR29: Paywall is presented immediately after the user completes or fails their 3rd free scenario, on the debrief screen
FR30: User can manage their subscription status (view, cancel)
FR31: System enforces call and scenario limits based on user's free or paid tier

**Offline & Data Sync (FR32-FR34):**

FR32: User can view the scenario list offline with last-known completion percentages
FR33: User can view all past debrief reports offline
FR34: Scenario list and debrief data sync automatically when network becomes available

**Content Safety & Compliance (FR35-FR39):**

FR35: AI character stays within defined personality and behavioral boundaries during calls
FR36: AI character reacts in-persona (escalates anger, hangs up) when user inputs inappropriate or off-topic content
FR37: Debrief explains what happened when a call ends due to inappropriate user behavior
FR38: Content warnings are displayed before scenarios involving threat, confrontation, or authority pressure (e.g., mugger, cop, angry landlord)
FR39: App displays AI-generated content disclosure visible before first call (EU AI Act Article 50)

**Operator Tools (FR40-FR46) — Deferred to Post-MVP:**

FR40: Operator can create new scenarios via system prompt configuration (character personality, vocabulary challenges, escalation triggers, fail conditions, debrief templates)
FR41: Operator can test scenarios before publishing to production
FR42: Operator can adjust scenario difficulty parameters without code changes
FR43: Operator can monitor real-time operational metrics (latency, active calls, API costs)
FR44: Operator can view retention, conversion, and engagement KPIs on a dashboard
FR45: Operator receives alerts when average perceived latency exceeds 1.5s over a 5-minute window or when daily API cost exceeds 130% of the 7-day rolling average
FR46: Operator can track per-call and per-user API costs

### NonFunctional Requirements

**Performance:**

NFR1: Perceived response latency (user speech end → character speech start) <800ms target, 2,000ms hard ceiling
NFR2: STT processing time <300ms target, 500ms hard ceiling
NFR3: LLM response generation (first token) <200ms target, 400ms hard ceiling
NFR4: TTS audio generation (first audio chunk) <200ms target, 400ms hard ceiling
NFR5: Rive animation frame rate 60fps target, 30fps minimum
NFR6: App cold start to scenario list <3s target, 5s hard ceiling
NFR7: Debrief generation time <5s after call ends, 10s hard ceiling

**Security:**

NFR8: Voice data process-and-discard architecture — raw audio streamed to STT, never stored on device or server. No voice biometric derivation (BIPA compliance)
NFR9: Call transcripts stored server-side encrypted at rest (AES-256). User can request deletion (GDPR Article 17)
NFR10: Email-based passwordless authentication. Session tokens with 30-day expiry
NFR11: Zero payment data handled directly — delegated entirely to StoreKit 2 (Apple) and Google Play Billing Library
NFR12: All AI provider API keys secured server-side via API gateway, never exposed to client
NFR13: TLS 1.3 minimum for all client-server communication. WebRTC encrypted by default (DTLS-SRTP)

**Scalability:**

NFR14: MVP launch supports 60-500 concurrent subscribers, ~50-100 daily calls on single API gateway instance
NFR15: Growth phase supports 500-5,000 subscribers with horizontal API gateway scaling
NFR16: Linear cost scaling with usage — no fixed infrastructure costs that spike at thresholds. $0.05/call at any scale

**Reliability:**

NFR17: Call completion rate >95% (no mid-call drops)
NFR18: API provider failover with graceful in-persona degradation within 5s
NFR19: App crash rate <1% of sessions
NFR20: Data sync reliability — eventually consistent within 60s
NFR21: Uptime (API gateway + pipeline) 99% monthly

**Integration (Graceful Degradation):**

NFR22: Soniox v4 (STT) failure → character says "I can't hear you" → call ends in-persona
NFR23: OpenRouter / Qwen3.5 Flash (LLM) failure → character pauses → "Something's off. Call me back." → call ends
NFR24: Cartesia Sonic 3 (TTS) failure → fallback to text-only response on screen (degraded)
NFR25: LiveKit Cloud (WebRTC) failure → phone-style "call failed" screen, automatic retry once
NFR26: Apple StoreKit 2 / Google Play Billing failure → optimistic access: grant paid immediately, validate async, revoke if validation fails

### Additional Requirements

**From Architecture — Starter Template & Project Setup:**
- PoC uses `flutter create` (bare). MVP migrates to BLoC layered architecture (Very Good CLI patterns)
- Python backend uses `uv init` + `pipecat-ai` with Soniox, OpenAI, Cartesia, and LiveKit plugins
- Monorepo structure: `client/` (Flutter) + `server/` (Python/Pipecat) + `deploy/` (configs)

**From Architecture — Infrastructure:**
- Single VPS: Hetzner Cloud CX22 (2 vCPU, 4GB RAM, €3.79/month) — all server components consolidated
- Reverse proxy + HTTPS: Caddy with automatic Let's Encrypt certificates
- Process management: systemd services for Pipecat, FastAPI, and Caddy
- Deployment (PoC): SSH + git pull + systemctl restart
- Deployment (MVP): GitHub Actions → SSH deploy on push to main
- Backup: Daily SQLite cron backup + weekly Hetzner VPS snapshots

**From Architecture — Database & Data:**
- Server database: SQLite via aiosqlite — no ORM, raw SQL query functions
- Migration strategy: Numbered SQL scripts (001_init.sql, etc.) executed at server startup
- Data model: users, auth_codes, scenarios (incl. briefing_text, content_warning), call_sessions, debriefs, user_progress
- Client storage (MVP): sqflite for local cache with pull-based sync at app launch

**From Architecture — Authentication:**
- Passwordless email + JWT: 6-digit code via Resend SMTP (free tier, 100/day) → PyJWT (30-day expiry)
- Client stores JWT in flutter_secure_storage (iOS Keychain / Android Keystore)
- FastAPI middleware validates JWT signature + expiry on all protected routes

**From Architecture — API Design:**
- REST via FastAPI with Pydantic models (snake_case JSON, explicit Dart camelCase mapping)
- 8 core endpoints: auth (request-code, verify-code), scenarios (list, detail), calls (initiate, end), debriefs, user profile
- API response format: `{data, meta}` for success, `{error: {code, message}}` for errors
- Static Rive assets served by Caddy at `/static/rive/`

**From Architecture — Real-Time Pipeline:**
- LiveKit data channel messages (JSON): viseme, emotion, hang_up_warning, call_end
- Audio transport: WebRTC via LiveKit (Flutter SDK ↔ LiveKit Cloud ↔ Pipecat server)
- Streaming overlap mandatory: LLM streams to TTS before full response is generated

**From Architecture — Implementation Patterns:**
- Naming conventions: snake_case (Python, SQL, JSON, REST), camelCase (Dart vars), PascalCase (Dart classes)
- BLoC conventions (MVP): VerbNounEvent, NounStatusState, FeatureBloc
- In-persona error handling during calls — NEVER show technical error dialogs
- Standard error handling outside calls — loading spinner, contextual error message, retry button
- Logging: structured key-value via Python logging module, always include user_id/call_id context
- Pre-commit: `flutter analyze` + `flutter test` (Flutter), `ruff check` + `ruff format` + `pytest` (Python)

**From Architecture — Rive 0.14.x Integration Rules (Non-Negotiable):**
- Use RiveWidgetBuilder + FileLoader.fromAsset(), NOT RiveAnimation
- RiveNative.init() MUST be called in main() before any Rive usage
- DataBind.auto() always — DataBind.byName() causes infinite hang
- Fit.cover for full-screen immersive, Fit.layout for UI components
- Events one-way only: Rive→Flutter via addEventListener, Flutter→Rive via ViewModel properties
- Test environment: Rive native does NOT load in Flutter tests — mandatory try/catch fallback pattern

**From Architecture — Rive Hot-Update Pattern:**
- Server serves manifest.json with version per .riv file
- Flutter compares local cached version vs manifest at launch
- If different: download new .riv, replace cache. If same or offline: load from cache
- Rive loaded from bytes (File.decode) instead of asset bundle

**From Architecture — FR27 Removed:**
- Push notifications explicitly removed from MVP scope — no FCM, no APNs, no notification permission request

### UX Design Requirements

UX-DR1: Implement dark theme color system in a single theme.dart file — background (#1E1F23), avatar-bg (#414143), text-primary (#F0F0F0), text-secondary (#8A8A95), accent/mint (#00E5A0), status-completed (#2ECC40), status-in-progress (#FF6B6B), destructive (#E74C3C)

UX-DR2: Implement Inter font typography system — card-title (12px Bold 700), card-tagline (12px Italic 400i), card-stats (12px Regular 400), display (64px Bold 700), headline (18px SemiBold 600), section-title (14px SemiBold 600), body (16px Regular 400), body-emphasis (16px Medium 500), caption (13px Regular 400), label (12px Medium 500)

UX-DR3: Implement spacing foundation — 8px base unit, 20px horizontal screen padding, 30px vertical padding (scenario list), 60px top safe area (call/debrief), 12px gap between scenario cards

UX-DR4: Build ScenarioCard component — Row layout: avatar circle (50x50, #414143) + text column (name Bold 12px, tagline Italic 12px, stats conditional) + action icons (report 24px + phone 24px, gap 20px). Three states: not attempted (2 lines, no report icon), in progress (3 lines, stats in #FF6B6B, report visible), completed (3 lines, stats in #2ECC40, report visible). No card background. Tap phone → call. Tap report → debrief

UX-DR5: Build BottomOverlayCard component — fixed bottom, full width, #F0F0F0 background, extends into safe area. Row: diamond icon + text column (title Bold 14px #1E1F23, subtitle Regular 11px #4C4C4C). Four states: free/calls remaining ("Unlock all scenarios"), free/0 calls permanent ("Subscribe to keep calling"), paid/calls available (hidden), paid/0 calls today ("No more calls today"). Tap → paywall (except informational state)

UX-DR6: Build CallScreenCanvas — Flutter provides scenario-specific background image with BackdropFilter gaussian blur (~15-25px, no overlay). Rive provides full-screen canvas overlay with character puppet (emotional states, lip sync) and hang-up button (64x64 circle #E74C3C, phone-down icon 28px #FFFFFF, bottom 50px). Zero text on screen during calls

UX-DR7: Build NoNetworkScreen — #1E1F23 solid background. WiFi barred icon (40x40 #E74C3C, top-right 40px). Character avatar (~100x100 circle, #414143, disappointed expression, centered). "Call failed" (SemiBold 18px #F0F0F0). "No network available" (Regular 16px #8A8A95). Hang-up button (64x64 #E74C3C, bottom 50px). Tap → returns to scenario list

UX-DR8: Build CallEndedOverlay — character hang-up animation (Rive), "Call Ended" text, call duration, theatrical scenario-specific phrase (e.g., "The mugger gave up on you"). Holds 3-4 seconds. Auto-transitions to debrief with no user action. Debrief loads in background during this screen (latency masking)

UX-DR9: Implement first-time incoming call onboarding — simulated incoming call screen (character face, name, vibration feedback, green answer button). Mirrors native FaceTime/WhatsApp incoming call UI. Seen only once after email entry + consent. User taps answer → first call begins. Character speaks first, always

UX-DR10: Implement forward-only call navigation — scenario list → connecting animation (1-2s, masks pipeline init) → call screen → call ended overlay (3-4s) → debrief → back to scenario list. No back gesture during calls. Debrief has no forward CTA — user navigates back when ready (intentional friction)

UX-DR11: Implement loading state masking — zero loading spinners. "Connecting..." phone dial animation masks LiveKit/Pipecat initialization. "Call Ended" overlay masks debrief LLM generation. Scenario list renders progressively. Background image blur makes low-res acceptable during load

UX-DR12: Implement WCAG 2.1 AA accessibility — all color combinations validated (minimum 5.2:1 contrast). All interactive elements minimum 48px touch target. Screen reader announcements per screen (scenario card reads name/tagline/status/actions, call screen announces hang-up, no-network announces state). ~~Support system "Reduce Motion" setting via MediaQuery.disableAnimations~~ — **Reduced motion deferred to post-MVP**

UX-DR13: Implement Rive character emotional reaction system — 7 states driven in real-time during call: satisfaction (correct response), smirk (minor error), frustration (significant error), impatience (long hesitation >3s), anger (very long silence >5s), confusion (off-topic/incomprehensible), disgust → hang-up (inappropriate content). Reactions happen DURING user speech, not after

UX-DR14: Implement silence handling escalation — 0-3s: normal pause, neutral expression. 3-5s: subtle impatience (frown, posture shift). 5-8s: character prompts verbally ("Hello? You still there?"). 8s+: character escalates toward hang-up ("I don't have time for this")

UX-DR15: Design and build debrief screen — scrollable vertical layout. Hero: survival percentage (64px Bold, #E74C3C if <100%, #2ECC40 if 100%). Content sections: attempt number + previous best comparison, specific errors with correct alternatives (accent #00E5A0 for corrections), longest hesitation moment with context, idiom/slang explanations, "areas to work on" summary. No retry button. No congratulatory messages. Screenshot-worthy layout for viral sharing. Back arrow to scenario list

UX-DR16: Implement invisible paywall — all scenario cards look identical regardless of free/paid. No lock icons, no FREE/PAID badges. Paywall triggers on: (a) free user taps call on paid scenario, (b) user taps BottomOverlayCard. Single price $1.99/week. Clean dismiss returns to scenario list unchanged. Material BottomSheet or full screen

UX-DR17: Implement monochrome scenario list — all icons #F0F0F0 on #1E1F23 background. No colored buttons on the list. Color enters experience only during calls (character reactions) and debriefs (error/correction highlights). Flat design — no card backgrounds, no borders, no shadows, no elevation

UX-DR18: Implement responsive layout for phones 320-430px width — flex text containers (Expanded), fixed avatar/icon/padding/font sizes. SafeArea handling: top respects notch/Dynamic Island, bottom overlay card extends into safe area. Portrait only orientation. No tablet optimization

### FR Coverage Map

FR1: Epic 1 (partial — call from button) + Epic 6 (full — call from scenario list with Rive animation)
FR2: Epic 1 — Real-time voice conversation with AI character
FR3: Epic 6 — Animated emotional reactions during call
FR4: Epic 6 — Lip sync (mouth movements synchronized with speech)
FR5: Epic 6 — Emotional reactions based on user speech quality
FR6: Epic 6 — Character hangs up when performance drops below thresholds
FR7: Epic 6 — User can end call voluntarily
FR8: Epic 6 — Phone-style "no network" screen
FR9: Epic 7 — View debrief report after call
FR10: Epic 7 — Specific language errors with correct alternatives
FR11: Epic 7 — Survival/completion percentage
FR12: Epic 7 — Longest hesitation moments highlighted
FR13: Epic 7 — Idiom/slang explanations
FR14: Epic 7 — Pre-scenario situational briefing
FR15: Epic 7 — Retry scenario after debrief
FR15b: Epic 7 — Encouraging failure framing when >40% completion
FR16: Epic 5 — Browse scenario list with title and completion %
FR17: Epic 5 — Initiate call or view debrief from list
FR18: Epic 5 — Best completion % per scenario
FR19: Epic 5 — Scenarios ordered easy to hard
FR20: Epic 5 — Free (3 scenarios) vs paid (all) access
FR21: Epic 5 — Daily call limits (free vs paid)
FR22: Epic 4 — Account creation with email only
FR23: Epic 4 — First incoming call immediately after account creation
FR24: Epic 4 — Consent and privacy information before first use
FR25: Epic 4 — AI-generated content disclosure before first call
FR26: Epic 4 — Microphone permission request before first call
FR27: REMOVED FROM MVP — No push notifications
FR28: Epic 8 — Weekly paid subscription ($1.99/week)
FR29: Epic 8 — Paywall after 3rd free scenario on debrief screen
FR30: Epic 8 — Subscription management (view, cancel)
FR31: Epic 8 — Tier enforcement (call and scenario limits)
FR32: Epic 9 — Offline scenario list
FR33: Epic 9 — Offline debrief reports
FR34: Epic 9 — Automatic data sync when network available
FR35: Epic 6 — Character stays within behavioral boundaries
FR36: Epic 6 — Character reacts in-persona to inappropriate content
FR37: Epic 7 — Debrief explains behavior-triggered call end
FR38: Epic 5 — Content warnings before threat/confrontation scenarios
FR39: Epic 4 — AI-generated content disclosure (EU AI Act Article 50)
FR40: Epic 3 (partial — scenario structure/creation) — Deferred dashboard to post-MVP
FR41: Deferred to post-MVP — Operator scenario testing tools
FR42: Epic 3 (partial — difficulty parameters) — Deferred dashboard to post-MVP
FR43: Deferred to post-MVP — Real-time operational metrics monitoring
FR44: Deferred to post-MVP — Retention/conversion/engagement KPI dashboard
FR45: Deferred to post-MVP — Latency and cost alerting
FR46: Deferred to post-MVP — Per-call and per-user API cost tracking

## Epic List

### Epic 1: Voice Pipeline Proof of Concept (Phase 0)
Validate the core technical hypothesis: a user can have a real-time voice conversation with a sarcastic AI character through a minimal mobile app. If kill gates fail, the project stops.
**FRs covered:** FR1 (partial), FR2
**NFRs addressed:** NFR1-NFR4 (latency budget), NFR22-NFR25 (pipeline integrations)
**Kill gates:** <2s perceived latency, persona quality, voice quality, STT accuracy for non-native speakers

### Epic 2: UX Design Completion & Asset Creation
Finalize all pending screen designs and create visual assets required before development can begin. Design work, not code.
**Pending screens:** Debrief screen, Call Ended transition, First-Call Incoming Call, Onboarding flow (email, GDPR consent, AI disclosure), Paywall screen
**Assets:** Rive character puppet file (7 emotional states, lip sync 8 visemes, hang-up button + animation), scenario background images, app icon/logo, splash screen
**Note:** Can be worked in parallel with Epic 1 (PoC). Non-code epic — design/creative work.

### Epic 3: Scenario Content Design & Authoring
Define the complete scenario structure (system prompt format, personality parameters, escalation triggers, fail conditions, debrief templates), establish the authoring workflow, and create the 5 launch scenarios (3 free + 2 paid). First scenario calibrated for near-guaranteed user success.
**FRs covered:** FR40 (partial — creation structure), FR42 (partial — difficulty parameters)
**Note:** Requires dedicated collaborative session. Not modeled now — to be planned. Non-code epic — content/design work.

### Epic 4: User Onboarding & Authentication
A user can create an account with email only, see required legal disclosures (GDPR, EU AI Act), grant microphone permission, and receive their first incoming call with zero-friction onboarding.
**FRs covered:** FR22, FR23, FR24, FR25, FR26, FR39
**UX-DRs:** UX-DR1 (theme), UX-DR2 (typography), UX-DR3 (spacing), UX-DR9 (incoming call onboarding), UX-DR12 (accessibility foundation)
**Architecture:** MVP project restructuring (BLoC architecture), FastAPI + SQLite + migrations, passwordless auth (Resend + PyJWT), JWT middleware

### Epic 5: Scenario Browsing & Progression
A user can browse all available scenarios, see their best completion percentage and attempt count, and choose which scenario to attempt next. Content is ordered from least to most challenging. Content warnings displayed for intense scenarios.
**FRs covered:** FR16, FR17, FR18, FR19, FR20, FR21, FR38
**UX-DRs:** UX-DR4 (ScenarioCard), UX-DR5 (BottomOverlayCard — initial state), UX-DR17 (monochrome list), UX-DR18 (responsive layout)

### Epic 6: Animated Call Experience
A user experiences a visually immersive voice call: an animated 2D character reacts emotionally in real-time to their English, synchronizes lip movements with speech, and hangs up dramatically when patience runs out. Character stays within behavioral boundaries and handles inappropriate content in-persona.
**FRs covered:** FR1 (full — from scenario list), FR3, FR4, FR5, FR6, FR7, FR8, FR35, FR36
**UX-DRs:** UX-DR6 (CallScreenCanvas), UX-DR7 (NoNetworkScreen), UX-DR10 (forward-only navigation), UX-DR11 (loading masking), UX-DR13 (emotional reactions), UX-DR14 (silence handling)
**Depends on:** Epic 2 (Rive character file), Epic 3 (scenario content)

### Epic 7: Post-Call Debrief & Learning
After each call, the user receives a brutally honest debrief: specific errors flagged with correct alternatives, hesitation analysis, idiom explanations, pre-scenario briefing for first attempts, and clear areas to work on. The debrief is the real value that justifies payment.
**FRs covered:** FR9, FR10, FR11, FR12, FR13, FR14, FR15, FR15b, FR37
**UX-DRs:** UX-DR8 (CallEndedOverlay), UX-DR15 (debrief screen)
**Depends on:** Epic 2 (debrief screen design, Call Ended transition design)

### Epic 8: Monetization & Subscription
A user can subscribe to unlock all scenarios. The system enforces free/paid tier limits seamlessly. The paywall appears at moments of maximum intent with an invisible tier design.
**FRs covered:** FR28, FR29, FR30, FR31
**UX-DRs:** UX-DR16 (invisible paywall), UX-DR5 (BottomOverlayCard — all states)
**Depends on:** Epic 2 (paywall screen design)

### Epic 9: Offline Access & Data Sync
A user can access the scenario list and all past debrief reports without network connectivity. Data syncs automatically when connection returns.
**FRs covered:** FR32, FR33, FR34

### Epic 10: App Publication & Launch Readiness
Everything needed to submit and publish the app on Apple App Store and Google Play Store, plus operational readiness for launch.
**Scope:** Privacy policy + Terms of Service (documents + hosted URL), App Store Connect configuration (privacy labels, content rating, age rating 13+), Google Play Console configuration (data safety form, content rating), store listings (descriptions, screenshots, keywords, Education category), domain/DNS setup (api.survivethetalk.com → Hetzner VPS), TestFlight + internal testing distribution, basic analytics event tracking (go/no-go gate metrics), final pre-submission checklist (8 content modifications from domain research)
**Note:** Non-code tasks + operational setup. Partially parallelizable with late-stage code epics.

---

## Epic 1: Voice Pipeline Proof of Concept (Phase 0)

Validate the core technical hypothesis: a user can have a real-time voice conversation with a sarcastic AI character through a minimal mobile app. If kill gates fail, the project stops before any further investment.

### Story 1.1: Initialize Monorepo and Deploy Server Infrastructure

As a developer,
I want the project monorepo initialized and the Hetzner VPS configured with Caddy reverse proxy,
So that I have the foundation to deploy and iterate on the voice pipeline.

**Acceptance Criteria:**

**Given** a fresh development environment
**When** I clone the repository
**Then** I find `client/` (Flutter project via `flutter create --org com.surviveTheTalk --platforms ios,android`), `server/` (Python project via `uv init` + `pipecat-ai[soniox,openai,cartesia,livekit]`), and `deploy/` directories with the monorepo structure defined in Architecture
**And** `.gitignore`, `.env.example`, and `pyproject.toml` are properly configured

**Given** a Hetzner CX22 VPS is provisioned
**When** the deploy configuration is applied
**Then** Caddy serves HTTPS on the configured domain with valid Let's Encrypt certificate
**And** systemd service files for Pipecat and Caddy are installed and enabled

**Given** environment variables are set in `.env`
**When** the server starts
**Then** all API keys (Soniox, OpenRouter, Cartesia, LiveKit) are loaded from environment variables and never hardcoded

### Story 1.2: Build Pipecat Voice Pipeline with Sarcastic Character

As a user,
I want to speak to an AI character that responds with a sarcastic, impatient personality in real-time voice,
So that the core conversational AI experience is validated end-to-end on the server.

**Acceptance Criteria:**

**Given** a Pipecat pipeline configured with Soniox v4 (STT), Qwen3.5 Flash via OpenRouter (LLM), and Cartesia Sonic 3 (TTS)
**When** audio is streamed into the pipeline via LiveKit transport
**Then** the pipeline produces voiced responses with streaming overlap (LLM streams to TTS before full response is generated)

**Given** a hardcoded sarcastic character system prompt
**When** the user speaks in English across multiple conversation turns
**Then** the character maintains its sarcastic/impatient persona consistently without breaking character

**Given** the pipeline is running on Hetzner VPS
**When** a minimal HTTP endpoint receives a call request
**Then** it creates a LiveKit room, spawns a Pipecat bot into that room, and returns the room token to the caller

**Given** voice data enters the pipeline
**When** audio is processed by STT
**Then** raw audio is never written to disk (process-and-discard pattern enforced)

### Story 1.3: Create Minimal Flutter App with Voice Call

As a user,
I want to tap a button on my phone and immediately be in a voice conversation with the AI character,
So that I can experience the core product interaction on a real mobile device.

**Acceptance Criteria:**

**Given** the Flutter app is launched
**When** the main screen loads
**Then** a single "Call" button is displayed (no other UI elements, no navigation, no login)

**Given** the user taps the Call button
**When** the app requests the room token from the server endpoint
**Then** a LiveKit connection is established and the user's microphone audio streams to the Pipecat pipeline

**Given** the pipeline generates a voiced response
**When** audio is received via LiveKit WebRTC
**Then** it plays through the device speaker in real-time

**Given** the call is active
**When** the user speaks in English
**Then** the AI character responds conversationally with perceived latency <2s (hard ceiling)

**Given** the call is active
**When** the user wants to end the conversation
**Then** they can tap an "End Call" button to disconnect cleanly

**Given** the device has no microphone permission granted
**When** the user taps the Call button
**Then** the system microphone permission dialog is shown before proceeding

### Story 1.4: Validate PoC Kill Gates

As a product owner,
I want to measure and document the four kill gates against defined thresholds,
So that I can make a clear go/no-go decision on proceeding to MVP development.

**Acceptance Criteria:**

**Given** multiple test calls with non-native English speakers (various accents)
**When** measuring end-to-end perceived latency (user speech end → character speech start)
**Then** average latency is <800ms target and no consistent pattern of >2s responses
**And** results are documented with timestamps and measurements

**Given** the sarcastic character system prompt
**When** conducting a 3+ minute multi-turn conversation
**Then** the character maintains its sarcastic/impatient persona throughout without breaking character or generating generic responses
**And** personality quality is documented with example exchanges

**Given** Cartesia Sonic 3 TTS output
**When** listening to character responses across multiple conversations
**Then** the voice sounds natural and expressive (supports sarcastic/impatient tone, not robotic or flat)
**And** voice quality assessment is documented

**Given** non-native English speakers with various accents
**When** speaking to the pipeline at intermediate English level
**Then** Soniox v4 correctly transcribes >70% of utterances without critical misinterpretation
**And** STT accuracy observations are documented

**Given** all four gates have been measured and documented
**When** reviewing results against thresholds
**Then** a clear go/no-go decision is recorded with supporting evidence for each gate

---

## Epic 2: UX Design Completion & Asset Creation

Finalize all pending screen designs and create visual assets required before MVP development can begin. This is design/creative work, not code. Can be worked in parallel with Epic 1 (PoC).

**User value:** Without these designs and assets, Epics 4-8 cannot be implemented with visual fidelity. This epic unblocks the entire MVP visual experience — the Rive character file, screen layouts, and app icon are direct inputs to user-facing features.

### Story 2.1: Design Onboarding Flow Screens

As a designer,
I want complete visual designs for the onboarding flow (email entry, GDPR consent, EU AI Act disclosure),
So that Epic 4 (Onboarding & Auth) can be implemented without design ambiguity.

**Acceptance Criteria:**

**Given** the UX spec defines zero-friction onboarding (email → consent → mic → call)
**When** designing the onboarding screens
**Then** email entry screen design is complete with layout specs, spacing, and input field styling following the dark theme (#1E1F23 bg, #F0F0F0 text, Inter font)

**Given** GDPR consent and EU AI Act Article 50 disclosure are mandatory pre-first-call gates
**When** designing the consent screen
**Then** the design integrates both legal requirements into a single minimal-friction screen with clear accept action
**And** the AI-generated content disclosure is visible and prominent per regulatory requirements

**Given** these screens precede the first incoming call
**When** the flow is designed end-to-end
**Then** the transition from consent acceptance to incoming call animation is defined with timing and visual continuity

### Story 2.2: Design First-Call Incoming Call Animation

As a designer,
I want the first-call incoming call screen fully designed (character face, name, vibration pattern, answer button),
So that the critical onboarding moment ("The Phone Rings") can be implemented faithfully.

**Acceptance Criteria:**

**Given** the UX spec defines this as a simulated incoming call mirroring FaceTime/WhatsApp
**When** the design is complete
**Then** it includes character face placement, character name display, green answer button specs (size, position, color), and background treatment

**Given** this is the make-or-break onboarding moment
**When** reviewing the design
**Then** vibration feedback pattern is specified and the visual creates an emotional spike (excitement, not generic)

**Given** this screen is seen only once (first launch after email entry)
**When** the user taps "Answer"
**Then** the transition to the call screen is defined with animation specs

### Story 2.3: Design Call Ended Transition Screen

As a designer,
I want the Call Ended transition screen fully designed (hang-up animation reference, text, duration, theatrical phrase),
So that the emotional transition between call and debrief is specified for implementation.

**Acceptance Criteria:**

**Given** the UX spec defines a 3-4 second hold with theatrical scenario-specific phrase
**When** the design is complete
**Then** it includes layout specs for "Call Ended" text, call duration display, and theatrical phrase placement
**And** typography styles and colors are defined using the established design tokens

**Given** this screen masks debrief LLM generation time
**When** reviewing the design
**Then** the auto-transition to debrief is defined (fade, timing) with no user action required

### Story 2.4: Design Debrief Screen

As a designer,
I want the debrief screen fully designed with all content sections, layout, and visual hierarchy,
So that Epic 7 (Post-Call Debrief) can be implemented with complete visual specs.

**Acceptance Criteria:**

**Given** the UX spec defines: hero survival %, attempt number, previous best, errors with corrections, hesitation moments, idiom explanations, areas to work on
**When** the design is complete
**Then** each section has layout specs, typography (using established styles), spacing, and color treatment
**And** survival % uses display style (64px Bold), #E74C3C if <100%, #2ECC40 if 100%

**Given** corrections use accent color (#00E5A0)
**When** reviewing the error section design
**Then** "You said X" and "Correct form: Y" have distinct visual treatment that's instantly readable

**Given** the debrief must be screenshot-worthy for viral sharing
**When** reviewing the overall layout
**Then** the top section (survival %, character name, scenario) is self-contained and visually compelling as a standalone screenshot

**Given** no retry button — user navigates back via back arrow
**When** reviewing the screen
**Then** no call-to-action buttons exist at the bottom, and back navigation is the only exit

### Story 2.5: Design Paywall Screen

As a designer,
I want the paywall screen designed (subscription offer, price, value proposition, accept/decline actions),
So that Epic 8 (Monetization) can be implemented with complete visual specs.

**Acceptance Criteria:**

**Given** the UX spec defines paywall as Material BottomSheet or full screen
**When** the design is complete
**Then** it includes price display ($1.99/week), value proposition copy, subscribe CTA, and dismiss/decline action
**And** visual treatment follows the dark theme with the established design tokens

**Given** the paywall triggers at moments of maximum intent (after paid scenario tap or overlay card tap)
**When** reviewing the design
**Then** the dismiss path returns cleanly to the scenario list with no dark patterns

### Story 2.6: Create Rive Character Puppet File

As a designer/animator,
I want a complete Rive character puppet file (.riv) with all emotional states, lip sync visemes, and hang-up button,
So that Epic 6 (Animated Call Experience) has the animation asset it requires.

**Acceptance Criteria:**

**Given** the UX spec defines 7 emotional states (satisfaction, smirk, frustration, impatience, anger, confusion, disgust→hang-up)
**When** the Rive file is complete
**Then** each emotional state is implemented as a distinct state machine state with transitions between them

**Given** the Architecture defines 8 grouped viseme mouth shapes driven by Cartesia phoneme timestamps
**When** lip sync inputs are configured
**Then** 8 viseme inputs are exposed via NumberInput on the state machine, controllable from Flutter via ViewModel properties

**Given** the hang-up button is built in Rive (captures click events)
**When** reviewing the call screen elements
**Then** the hang-up button (64x64 circle #E74C3C, phone-down icon 28px #FFFFFF) is integrated in the Rive canvas with click event output

**Given** Rive 0.14.x integration rules are non-negotiable
**When** building the file
**Then** all inputs use the correct types (TriggerInput/BooleanInput/NumberInput), events are one-way (Rive→Flutter), and the file is compatible with RiveWidgetBuilder + FileLoader

**Given** the character must have a dramatic hang-up animation
**When** the hang-up is triggered
**Then** a character-specific theatrical exit animation plays before the call screen transitions out

### Story 2.7: Create Visual Assets (App Icon, Splash Screen, Scenario Backgrounds)

As a designer,
I want the app icon, splash screen, and scenario background images created,
So that the app has a complete visual identity for development and store submission.

**Acceptance Criteria:**

**Given** the app targets iOS and Android
**When** the app icon is created
**Then** it follows Apple Human Interface Guidelines and Google Play icon specs (1024x1024 source, adaptive icon for Android)
**And** the icon reflects the adversarial entertainment positioning (edgy, not educational)

**Given** the app launches with a splash screen before the scenario list
**When** the splash screen is designed
**Then** it uses the dark theme background (#1E1F23) with minimal branding (logo/wordmark)

**Given** the call screen uses scenario-specific background images with gaussian blur
**When** background images are created
**Then** one background image exists per launch scenario (5 minimum), each setting the ambient mood for the scenario
**And** images work well when blurred (~15-25px gaussian) — colors and shapes remain readable as atmosphere

---

## Epic 3: Scenario Content Design & Authoring

Define the complete scenario structure (system prompt format, personality parameters, escalation triggers, fail conditions, debrief templates), establish the authoring workflow, and create the 5 launch scenarios (3 free + 2 paid). First scenario calibrated for near-guaranteed user success. Requires dedicated collaborative session — stories are high-level placeholders to be refined.

**Key References:**
- [`difficulty-calibration.md`](difficulty-calibration.md) — Defines difficulty levels (easy/medium/hard), scoring criteria, calibration targets, AI scoring prompt, and technical implementation mapping. All scenarios MUST conform to this framework.
- [`scenario-testing-process.md`](scenario-testing-process.md) — Defines the testing workflow for scenario calibration: transcript capture (TranscriptLogger), AI scoring (score_transcript.py), checklist templates, and minimum 2 test passes per scenario. Both technical tools must be built before Story 3.2.

**User value:** The scenarios ARE the product content. Without them, users have nothing to play. This epic produces the 5 conversations that users will experience at launch — the characters, their personalities, and the vocabulary challenges that drive engagement and retention.

### Story 3.1: Define Scenario Structure and Authoring Format

As a product owner,
I want a documented scenario structure defining all required fields and their format,
So that scenarios can be created consistently and loaded by the Pipecat pipeline.

**Acceptance Criteria:**

**Given** the Architecture defines a `scenarios` table (id, title, base_prompt, checkpoints, difficulty, is_free, briefing_text, content_warning, rive_character)
**When** the scenario structure is finalized
**Then** a documented template exists covering: checkpoint-based format (base_prompt for character identity/personality/boundaries + ordered checkpoints array where each checkpoint defines id, hint_text, prompt_segment, and success_criteria), briefing text format, content warning criteria, difficulty calibration parameters, and rive_character assignment (which Rive character visual variant to display — one of: mugger, waiter, girlfriend, cop, landlord)

**Given** the operator (Walid) authors scenarios manually
**When** the authoring workflow is defined
**Then** a step-by-step process exists: write system prompt → test with pipeline → calibrate difficulty → write briefing → set metadata → push to production

**Given** FR42 requires difficulty adjustment without code changes
**When** the scenario format is designed
**Then** difficulty parameters (patience threshold, silence tolerance, escalation speed) are configurable values in the system prompt or scenario metadata, not hardcoded logic

### Story 3.2: Create Launch Scenarios (3 Free + 2 Paid)

As a user,
I want 5 diverse scenarios available at launch covering different real-world situations,
So that I have enough content to experience the product and make a subscription decision.

**Acceptance Criteria:**

**Given** the PRD requires 5 scenarios at launch (3 free + 2 paid)
**When** all scenarios are created
**Then** each scenario has a base_prompt, ordered checkpoints (each with id, hint_text, prompt_segment, success_criteria), briefing text, difficulty rating, content warning (if applicable), and has been tested with the Pipecat pipeline

**Given** the first scenario must be calibrated for near-guaranteed user success (60-80% survival)
**When** the first free scenario is tested
**Then** an intermediate English speaker passes 60-80% of checkpoints on first attempt with the patience threshold tuned accordingly

**Given** scenarios are ordered from least to most challenging
**When** reviewing the 5 scenarios
**Then** difficulty progression is: easy (free #1) → medium (free #2, #3) → hard (paid #1, #2)
**And** each scenario covers a distinct real-world situation (e.g., waiter, interviewer, landlord, cop, mugger — per PRD user journeys)

**Given** the PRD requires content warnings for threat/confrontation scenarios (FR38)
**When** reviewing each scenario
**Then** scenarios involving threat, authority pressure, or confrontation have content_warning text defined

**Given** the debrief needs scenario-specific theatrical phrases (CallEndedOverlay)
**When** each scenario is authored
**Then** hang-up exit lines and completion exit lines are written per character (e.g., mugger: "Forget it. You're not even worth robbing.")

---

## Epic 4: User Onboarding & Authentication

A user can create an account with email only, see required legal disclosures (GDPR, EU AI Act), grant microphone permission, and receive their first incoming call with zero-friction onboarding. This is the first code epic for MVP — it establishes the Flutter architecture, design system, and backend foundation.

### Story 4.1: Restructure Flutter Project to MVP Architecture

As a developer,
I want the Flutter project restructured from PoC single-file to MVP feature-based BLoC architecture,
So that all subsequent MVP features can be built on a solid, organized foundation.

**Acceptance Criteria:**

**Given** the PoC used a single `main.dart`
**When** the project is restructured
**Then** it follows the Architecture-defined structure: `app/` (MaterialApp, GoRouter, theme), `features/` (auth/, call/, scenarios/, debrief/), `core/` (api/, auth/, rive/, theme/), `shared/widgets/`
**And** `RiveNative.init()` is called in `main()` before any Rive usage

**Given** dependencies are added
**When** `pubspec.yaml` is updated
**Then** `flutter_bloc`, `go_router`, `dio`, `flutter_secure_storage`, `rive`, and `livekit_client` are included
**And** `flutter analyze` passes with zero issues and `flutter test` passes

### Story 4.1b: Implement Design System (Theme, Typography, Spacing)

As a developer,
I want the complete Material Design 3 dark theme with all color tokens, typography styles, and spacing constants,
So that every screen uses a consistent visual foundation matching the UX specification.

**Acceptance Criteria:**

**Given** UX-DR1 defines the color system
**When** the theme is implemented in a single `theme.dart` file
**Then** all 8 color tokens are defined: background (#1E1F23), avatar-bg (#414143), text-primary (#F0F0F0), text-secondary (#8A8A95), accent (#00E5A0), status-completed (#2ECC40), status-in-progress (#FF6B6B), destructive (#E74C3C)

**Given** UX-DR2 defines the typography system
**When** the theme is implemented
**Then** Inter font is configured with all 10 text styles (card-title, card-tagline, card-stats, display, headline, section-title, body, body-emphasis, caption, label) at their specified sizes and weights

**Given** UX-DR3 defines the spacing foundation
**When** the theme is implemented
**Then** 8px base unit, 20px horizontal screen padding, and screen-specific vertical paddings are defined as reusable constants

**Given** UX-DR12 requires WCAG 2.1 AA accessibility
**When** reviewing the theme
**Then** all color combinations meet minimum contrast ratios (validated in UX spec) and dynamic font sizing is supported

**Given** `flutter analyze` and `flutter test` are pre-commit requirements
**When** the design system is complete
**Then** both pass with zero issues

### Story 4.2: Build FastAPI Server with Passwordless Auth System

As a user,
I want to create an account using only my email and receive a verification code to sign in,
So that I can access the app with zero-friction authentication.

**Acceptance Criteria:**

**Given** the Architecture defines FastAPI + SQLite + passwordless auth
**When** the server is deployed
**Then** FastAPI runs on the Hetzner VPS behind Caddy reverse proxy with SQLite database initialized via migration script `001_init.sql` (users, auth_codes tables)

**Given** a user submits their email to `POST /auth/request-code`
**When** the endpoint processes the request
**Then** a 6-digit code is generated, stored in `auth_codes` with 15-minute expiry, and sent to the email via Resend SMTP
**And** the response returns success without revealing whether the email already exists

**Given** a user submits a valid code to `POST /auth/verify-code`
**When** the code matches and has not expired
**Then** a JWT token is returned with 30-day expiry, the user record is created if new, and the auth code is marked as used

**Given** a user submits an invalid or expired code
**When** verification is attempted
**Then** a clear error response is returned (`AUTH_CODE_EXPIRED` or `AUTH_CODE_INVALID`) following the API error format

**Given** the JWT middleware is configured
**When** a request with a valid JWT hits a protected endpoint
**Then** the user is authenticated and their user_id is available to the route handler

**Given** the API response format is defined in Architecture
**When** any endpoint responds
**Then** it follows the `{data, meta}` / `{error: {code, message}}` wrapper format with snake_case fields

**Given** pre-commit checks are required
**When** code is committed
**Then** `ruff check .` and `ruff format .` pass with zero issues

### Story 4.3: Build Email Authentication Flow in Flutter

As a user,
I want to enter my email and verification code on my phone to sign in,
So that I can access the app quickly without remembering a password.

**Acceptance Criteria:**

**Given** the user opens the app without a valid JWT stored
**When** the app launches
**Then** GoRouter redirects to the email entry screen

**Given** the email entry screen is displayed
**When** the user enters a valid email and taps submit
**Then** `POST /auth/request-code` is called via Dio and the user is navigated to the code verification screen

**Given** the code verification screen is displayed
**When** the user enters the 6-digit code and submits
**Then** `POST /auth/verify-code` is called, the returned JWT is stored in `flutter_secure_storage`, and the user is navigated to the consent screen

**Given** authentication fails (invalid code, expired, network error)
**When** an error occurs
**Then** a contextual error message is displayed on the screen (no popup dialogs) with a retry option

**Given** the user has a valid JWT stored from a previous session
**When** the app launches
**Then** GoRouter skips the auth flow and navigates directly to the scenario list

**Given** the AuthBloc manages authentication state
**When** events and states are defined
**Then** they follow BLoC conventions: `SubmitEmailEvent`, `SubmitCodeEvent` (events), `AuthInitial`, `AuthLoading`, `AuthAuthenticated`, `AuthError` (states)

**Given** `flutter analyze` and `flutter test` are pre-commit requirements
**When** the story is complete
**Then** both pass with zero issues

### Story 4.4: Build Consent, AI Disclosure, and Microphone Permission Flow

As a user,
I want to see privacy/consent information and grant microphone access before my first call,
So that I understand how my data is used and the app can access my microphone for voice calls.

**Acceptance Criteria:**

**Given** the user has just authenticated for the first time
**When** navigated to the consent screen
**Then** GDPR consent information and EU AI Act Article 50 AI-generated content disclosure are displayed in a single screen (FR24, FR25, FR39)
**And** the user must explicitly accept to proceed (blocking gate — Material Dialog pattern)

**Given** the user accepts consent
**When** the consent is recorded
**Then** the consent acceptance is stored locally and the user is navigated to the microphone permission step

**Given** microphone permission has not been granted
**When** the permission flow is triggered
**Then** the system microphone permission dialog is displayed (FR26)

**Given** the user denies microphone permission
**When** they attempt to proceed
**Then** an in-persona message is displayed: character taps screen impatiently — "I can't hear you. Check your mic." with a button to re-request permission via app settings

**Given** the user grants microphone permission
**When** permission is confirmed
**Then** the user is navigated to the first-call incoming call animation

**Given** the user returns to the app on subsequent launches
**When** consent has already been given and mic permission exists
**Then** these screens are skipped entirely (straight to scenario list)

### Story 4.5: Build First-Call Incoming Call Experience

As a new user,
I want my phone to "ring" with an animated incoming call from a character immediately after onboarding,
So that my first interaction with the product is the product itself — not a tutorial or menu.

**Acceptance Criteria:**

**Given** the user has completed consent and mic permission for the first time
**When** the incoming call screen appears
**Then** it displays the character's face, character name, a green "Answer" button, and triggers device vibration feedback (UX-DR9)
**And** the visual mirrors native FaceTime/WhatsApp incoming call UI

**Given** the incoming call screen is displayed
**When** the user taps the "Answer" button
**Then** the app initiates a call to the first scenario (easiest, calibrated for near-guaranteed success) via the call pipeline (FR23)
**And** the transition to the call screen is smooth with the "Connecting..." animation masking pipeline initialization

**Given** this is the first-call onboarding moment
**When** the call connects
**Then** the character speaks first, setting the scenario — the user never has to figure out how to start

**Given** this screen is a one-time onboarding experience
**When** the user opens the app on subsequent launches
**Then** the incoming call screen is never shown again — the user goes directly to the scenario list

**Given** the call is initiated
**When** the server processes the request
**Then** `POST /calls/initiate` creates a `call_sessions` row (requires `002_calls.sql` migration) and returns a LiveKit room token

---

## Epic 5: Scenario Browsing & Progression

A user can browse all available scenarios, see their best completion percentage and attempt count, and choose which scenario to attempt next. Content is ordered from least to most challenging. Content warnings displayed for intense scenarios. Includes subscription status display and daily call limit enforcement.

### Story 5.1: Build Scenarios API and Database

As a user,
I want the server to provide my scenario list with my progression data,
So that the app can display my available scenarios and track my progress.

**Acceptance Criteria:**

**Given** the Architecture defines a `scenarios` table
**When** migration `001_init.sql` is extended (or already includes scenarios)
**Then** the `scenarios` table exists with columns: id, title, base_prompt, checkpoints (JSON), difficulty, is_free, briefing_text, content_warning
**And** the `user_progress` table exists with columns: user_id, scenario_id, best_score, attempts

**Given** a user requests `GET /scenarios` with a valid JWT
**When** the endpoint processes the request
**Then** it returns all scenarios ordered by difficulty (ascending) with the user's best_score and attempts per scenario
**And** the response indicates which scenarios are free vs paid

**Given** a user requests `GET /scenarios/{id}` with a valid JWT
**When** the endpoint processes the request
**Then** it returns scenario details including briefing_text and content_warning (if applicable)

**Given** FR20 defines free users access 3 scenarios and paid users access all
**When** the scenario list is returned
**Then** the `is_free` flag is included per scenario for client-side tier enforcement

**Given** the API response format
**When** scenarios are returned
**Then** they follow the `{data: [...], meta: {count, timestamp}}` format with snake_case fields

### Story 5.2: Build Scenario List Screen with ScenarioCard Component

As a user,
I want to browse a scrollable list of scenarios showing each character's name, tagline, and my completion stats,
So that I can choose which scenario to attempt and see my progress at a glance.

**Acceptance Criteria:**

**Given** the ScenariosBloc loads data from `GET /scenarios`
**When** the scenario list screen renders
**Then** it displays a scrollable vertical list of ScenarioCard components on the dark background (#1E1F23) with no header and no nav bar (UX-DR17)

**Given** UX-DR4 defines the ScenarioCard layout
**When** each card is rendered
**Then** it displays: avatar circle (50x50, #414143), text column (name Bold 12px, tagline Italic 12px), and action icons (report 24px + phone 24px, 20px gap) in a horizontal row
**And** cards have no background, no borders, no shadows (flat design) with 12px gap between cards

**Given** a scenario has not been attempted
**When** the card is displayed
**Then** only 2 lines show (name + tagline), no stats line, and the report icon is hidden

**Given** a scenario is in progress (best_score < 100%)
**When** the card is displayed
**Then** a third line shows "Best: {score}% · {attempts} attempts" in #FF6B6B and the report icon is visible (FR18)

**Given** a scenario is completed (best_score = 100%)
**When** the card is displayed
**Then** the stats line shows in #2ECC40 and the report icon is visible

**Given** FR19 requires scenarios ordered easy to hard
**When** the list renders
**Then** scenarios appear in ascending difficulty order with the first scenario calibrated for near-guaranteed success

**Given** UX-DR18 requires responsive layout for 320-430px
**When** displayed on any supported phone width
**Then** the text column flexes (Expanded), avatar/icons/padding remain fixed sizes, and SafeArea is respected at top

**Given** screen reader accessibility (UX-DR12)
**When** VoiceOver/TalkBack is active
**Then** each card announces: character name, tagline, status, and available actions

### Story 5.3: Build BottomOverlayCard and Daily Call Limit Enforcement

As a user,
I want to see my subscription status and remaining calls at the bottom of the scenario list,
So that I understand what content is available to me and when I need to subscribe.

**Acceptance Criteria:**

**Given** UX-DR5 defines the BottomOverlayCard
**When** a free user with calls remaining views the scenario list
**Then** a persistent card appears fixed at the bottom (#F0F0F0 bg, extends into safe area) showing: diamond icon + "Unlock all scenarios" (Bold 14px #1E1F23) + "If you can survive us, real humans don't stand a chance" (Regular 11px #4C4C4C)

**Given** a free user has 0 calls remaining (permanent — no daily recharge)
**When** the scenario list is displayed
**Then** the overlay card changes to "Subscribe to keep calling" with the same subtitle

**Given** a paid user has calls remaining
**When** the scenario list is displayed
**Then** the overlay card is hidden (clean list)

**Given** a paid user has exhausted their daily call limit
**When** the scenario list is displayed
**Then** the overlay card shows "No more calls today" + "Come back tomorrow"

**Given** FR21 defines daily call limits
**When** the user attempts to initiate a call
**Then** the system checks remaining calls: free users get 3 total (lifetime, no daily recharge), paid users get 3/day
**And** if no calls remain, the call is blocked and the overlay card state reflects this

**Given** the overlay card is actionable (free user states)
**When** the user taps it
**Then** it navigates to the paywall screen (Epic 8 — navigates to placeholder until implemented)

### Story 5.4: Build Content Warning Display for Intense Scenarios

As a user,
I want to see a content warning before attempting scenarios involving threat, confrontation, or authority pressure,
So that I can make an informed choice about whether to proceed.

**Acceptance Criteria:**

**Given** FR38 requires content warnings for intense scenarios
**When** a user taps the call icon on a scenario with a non-null `content_warning` field
**Then** a Material Dialog displays the content warning text before proceeding

**Given** the content warning is displayed
**When** the user confirms they want to proceed
**Then** the call initiation continues normally

**Given** the content warning is displayed
**When** the user cancels
**Then** they return to the scenario list with no action taken

**Given** a scenario has no content warning (null field)
**When** the user taps the call icon
**Then** the call initiates directly with no warning dialog

---

## Epic 6: Animated Call Experience

A user experiences a visually immersive voice call: an animated 2D character reacts emotionally in real-time to their English, synchronizes lip movements with speech, progresses through checkpoint-based challenges with on-screen hints, and hangs up dramatically when patience runs out. Character stays within behavioral boundaries and handles inappropriate content in-persona. Depends on Epic 2 (Rive character file) and Epic 3 (scenario content in checkpoint format).

**Key Reference:** [`difficulty-calibration.md`](difficulty-calibration.md) §8 — Defines `PatienceTracker` (patience state, silence timers, escalation, hang-up), `ExchangeClassifier` (async parallel LLM evaluating user speech against checkpoint success_criteria), `CheckpointManager` (checkpoint progression, prompt segment swapping, client event pushing), and `TranscriptLogger` (timestamped transcript capture) pipeline components required by this epic.

### Story 6.1: Build Call Initiation from Scenario List with Connection Animation

As a user,
I want to tap the phone icon on a scenario card and see a phone-dialing animation while the call connects,
So that the transition to the call feels instant and natural, like dialing a real phone.

**Architectural decision (must read before implementation):** [ADR 003 — Call-Session Lifecycle](adr/003-call-session-lifecycle.md). Story 6.1 implements **raw LiveKit** (no `flutter_callkit_incoming` / no CallKit / no ConnectionService wrapper). Three back-press strategy tiers are mandatory: (1) push the call screen via `Navigator.of(context, rootNavigator: true).push(...)` — NOT via `context.go('/call')` — to detach from `_GoRouterRefreshStream` which is the suspected root cause of the Story 5.2 back-press failures; (2) enable LiveKit's `AndroidAudioServiceConfiguration` foreground service (manifest `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_MICROPHONE` permissions); (3) `UIBackgroundModes: [audio]` in `Info.plist`. The Smoke Test in §"Smoke test for Story 6.1" of ADR 003 is a Definition-of-Done gate. UX-DR10 ("forward-only navigation") is reinterpreted as documented in the ADR if Tier-1 empirically fails.

**Acceptance Criteria:**

**Given** the user taps the phone icon on a scenario card
**When** the call initiation begins
**Then** `POST /calls/initiate {scenario_id}` is called with the user's JWT, the server verifies tier/daily limits, creates a `call_sessions` row, loads the scenario's base_prompt and checkpoints, spawns a Pipecat bot in a LiveKit room with base_prompt + first checkpoint's prompt_segment as initial system prompt, and returns a LiveKit room token (FR1 full)

**Given** the server returns the LiveKit token
**When** the Flutter client connects
**Then** a "Connecting..." phone dial animation plays (1-2 seconds) masking the LiveKit + Pipecat initialization (UX-DR11)

**Given** the LiveKit connection is established
**When** both client and Pipecat bot are in the room
**Then** the connecting animation transitions smoothly to the call screen
**And** the character speaks first, setting the scenario context

**Given** forward-only navigation is required (UX-DR10)
**When** the user is on the call screen
**Then** back gesture and system navigation are disabled — the only exit is the hang-up button

### Story 6.2: Build Call Screen with Rive Character Canvas

As a user,
I want to see an animated character on a visually immersive full-screen call,
So that the experience feels like talking to a real person, not using an app.

**Acceptance Criteria:**

**Given** UX-DR6 defines the CallScreenCanvas architecture
**When** the call screen renders
**Then** Flutter loads a scenario-specific background image and applies BackdropFilter gaussian blur (~15-25px, no overlay)
**And** a full-screen Rive canvas renders on top with the character puppet

**Given** the Rive character file from Epic 2 is available (with 5 character variants via `character` EnumInput)
**When** the character loads
**Then** it is loaded via the Rive hot-update pattern: check manifest.json → download if newer → cache locally → load from bytes (File.decode)
**And** the character displays in Rive `Fit.cover` for full-screen immersive rendering
**And** the `character` EnumInput is set to the scenario's `rive_character` value before the conversation begins (e.g., 'girlfriend' for The Furious Girlfriend scenario)

**Given** Rive 0.14.x integration rules are non-negotiable
**When** the Rive canvas initializes
**Then** `RiveWidgetBuilder` + `FileLoader` are used (not `RiveAnimation`), `DataBind.auto()` is used, and all ViewModel property references are null-safe (`?.value`)

**Given** the hang-up button is built in Rive
**When** the call screen is active
**Then** the hang-up button (64x64 circle #E74C3C) is visible at the bottom of the Rive canvas and captures click events via Rive→Flutter event listener

**Given** zero system/technical text on screen during calls (UX spec rule)
**When** the call is active
**Then** no toasts, no banners, no error indicators, no loading spinners are visible. The only text on screen is the CheckpointStepper overlay (stepper bar + hint text) which is gameplay content, not system UI. Visible elements: character, hang-up button, and CheckpointStepper overlay.

### Story 6.3: Implement Emotional Reactions and Lip Sync via Data Channels

As a user,
I want the character's face to react in real-time to what I say and its lips to move when it speaks,
So that the character feels alive and genuinely responsive to my performance.

**Acceptance Criteria:**

**Given** the Architecture defines LiveKit data channel messages with type discrimination
**When** the Pipecat pipeline sends `{"type": "emotion", "data": {"emotion": "frustrated", "intensity": 0.8}}`
**Then** the Flutter client receives the message and updates the Rive state machine to the corresponding emotional state via ViewModel properties (NumberInput/BooleanInput)

**Given** UX-DR13 defines 7 emotional states
**When** emotion messages are received
**Then** the character transitions between: satisfaction (correct response), smirk (minor error), frustration (significant error), impatience (hesitation >3s), anger (silence >5s), confusion (off-topic), disgust→hang-up (inappropriate content)
**And** reactions happen DURING the user's speech, not after (real-time driven by pipeline analysis)

**Given** the Architecture defines 8 grouped viseme mouth shapes from Cartesia phoneme timestamps
**When** the pipeline sends `{"type": "viseme", "data": {"viseme_id": 3, "timestamp_ms": 1450}}`
**Then** the Flutter client updates the Rive lip sync NumberInput to the corresponding viseme state, creating synchronized mouth movements during character speech (FR4)

**Given** FR35 requires the character to stay within behavioral boundaries
**When** the pipeline generates emotional reactions
**Then** reactions are driven by the system prompt's defined personality — the character is sarcastic TO the situation, never insulting TO the person

**Given** the Rive events are one-way (Rive→Flutter for events, Flutter→Rive for property updates)
**When** updating emotional states and visemes
**Then** Flutter sets ViewModel properties (`.number()`, `.boolean()`) and never attempts bidirectional event communication

### Story 6.4: Implement Silence Handling and Character Hang-Up Mechanic

As a user,
I want the character to grow visibly impatient with my silences and eventually hang up if I perform poorly,
So that the call feels like a real high-stakes conversation with consequences.

**Acceptance Criteria:**

**Given** UX-DR14 defines silence escalation stages
**When** the user is silent for 0-3 seconds
**Then** the character waits with neutral expression (normal conversational pause)

**Given** silence exceeds 3 seconds
**When** the 3-5 second threshold is reached
**Then** the character shows subtle impatience (frown, posture shift via emotion data channel)

**Given** silence exceeds 5 seconds
**When** the 5-8 second threshold is reached
**Then** the character prompts verbally: "Hello? You still there?" / "I'm waiting..." (pipeline generates contextual verbal prompt)

**Given** silence exceeds 8 seconds
**When** the 8+ second threshold is reached
**Then** the character escalates: "Okay, I don't have time for this" — approaching hang-up

**Given** FR6 defines the character hangs up when performance drops below thresholds
**When** the internal patience meter (managed by pipeline) reaches zero
**Then** the pipeline sends `{"type": "hang_up_warning", "data": {"seconds_remaining": 5}}` followed by `{"type": "call_end", "data": {"reason": "character_hung_up", "survival_pct": 40, "checkpoints_passed": 2, "total_checkpoints": 5}}`
**And** the character delivers a dramatic exit line in-character before the call ends

**Given** FR36 requires in-persona reaction to inappropriate content
**When** the user inputs abusive or off-topic content
**Then** the character reacts with disgust expression → escalates anger → hangs up in-persona ("I'm done with this. *click*")
**And** the pipeline sends a `call_end` message with reason `"inappropriate_content"`

### Story 6.5: Build Voluntary Call End and No-Network Screen

As a user,
I want to be able to end the call myself, and see a phone-style "no network" screen if I have no connectivity,
So that I always have a graceful exit and the app behaves like a real phone even in error states.

**Acceptance Criteria:**

**Given** FR7 allows the user to end the call voluntarily
**When** the user taps the Rive hang-up button
**Then** the Rive click event is captured via `addEventListener`, the LiveKit connection is closed, and `POST /calls/{id}/end` is called to finalize the call session
**And** the app transitions to the Call Ended overlay (Epic 7)

**Given** FR8 requires a phone-style no-network screen
**When** the user taps the call icon without internet connectivity
**Then** the NoNetworkScreen is displayed (UX-DR7): #1E1F23 background, WiFi barred icon (40x40 #E74C3C, top-right), character avatar (~100x100 circle, disappointed expression), "Call failed" (SemiBold 18px #F0F0F0), "No network available" (Regular 16px #8A8A95), hang-up button at bottom

**Given** the NoNetworkScreen is displayed
**When** the user taps the hang-up button
**Then** they return to the scenario list
**And** no call attempt is consumed (daily limit not decremented)

**Given** network drops during an active call
**When** the LiveKit connection is lost
**Then** the call cuts immediately and transitions to the Call Ended screen with whatever data is available
**And** the character's in-persona degradation line is not played (connection already lost)

**Given** NFR18 defines graceful in-persona degradation for API failures during calls
**When** STT, LLM, or TTS fails mid-call
**Then** the pipeline sends appropriate character lines ("I can't hear you anymore", "My mind went blank") via the existing audio channel before sending a `call_end` message
**And** no technical error dialogs or UI error messages are ever shown during an active call

**Given** the call ends (any reason)
**When** `POST /calls/{id}/end` is called
**Then** the server calculates cost_cents, updates the call_sessions row with duration and cost, and triggers debrief generation

### Story 6.6: Build CheckpointManager and Checkpoint-Aware ExchangeClassifier

As a user,
I want the AI to progress through scenario phases based on what I actually say,
So that the conversation has structured goals and my performance is evaluated on content, not just whether I spoke.

**Acceptance Criteria:**

**Given** a scenario defines an ordered list of checkpoints (base_prompt + checkpoints[])
**When** the call starts
**Then** the CheckpointManager initializes with checkpoint index 0 and constructs the active system prompt as base_prompt + checkpoints[0].prompt_segment

**Given** the ExchangeClassifier evaluates each user turn in async parallel (AD-1)
**When** a TranscriptionFrame arrives from STT
**Then** the classifier receives the user text, last character line, and current checkpoint's success_criteria, and returns {"met": true/false}
**And** the classifier runs in parallel with the main LLM — zero impact on conversation latency

**Given** the classifier returns {"met": true}
**When** the CheckpointManager receives the result
**Then** it advances the checkpoint index, constructs a new system prompt (base_prompt + checkpoints[next].prompt_segment), injects it into the LLM context for the next turn, and sends a checkpoint_advanced event via LiveKit data channel: {"type": "checkpoint_advanced", "data": {"checkpoint_id": "refuse", "index": 1, "total": 5, "next_hint": "Ask him what he'll actually do."}}

**Given** the classifier returns {"met": false}
**When** the CheckpointManager receives the result
**Then** no checkpoint advancement occurs, the PatienceTracker applies its normal failed exchange penalty, and the current prompt_segment remains active

**Given** all checkpoints are passed (index reaches total_checkpoints)
**When** the last checkpoint is validated
**Then** the character delivers its completion exit line and the pipeline sends a call_end event with reason "completed" and survival_pct 100

**Given** the classifier fails or times out (>2s)
**When** the fallback triggers
**Then** the checkpoint is NOT advanced (conservative — no free progression) and the exchange is treated as a normal failed exchange by the PatienceTracker

**Given** difficulty-calibration.md §8 defines the pipeline architecture
**When** the CheckpointManager is implemented
**Then** it is a Pipecat FrameProcessor inserted alongside the PatienceTracker in the pipeline: STT → Context Aggregator → [CheckpointManager + PatienceTracker] → LLM → TTS → Transport

### Story 6.7: Build CheckpointStepper Overlay for Call Screen

As a user,
I want to see my progress through scenario checkpoints and a hint about what to do next during the call,
So that I understand what's expected of me and feel a sense of progression.

**Acceptance Criteria:**

**Given** the call screen is active and a scenario has checkpoints
**When** the CheckpointStepper renders
**Then** a horizontal stepper bar appears at the top of the call screen showing one circle per checkpoint connected by lines: completed checkpoints show a green (#00E5A0) circle with white checkmark, the current checkpoint shows an outlined circle, future checkpoints show grey (#8A8A95) circles
**And** circle sizing is adaptive: ≤6 checkpoints use 20x20 circles with 16px gap, 7-12 checkpoints use 14x14 circles with 8px gap (max 12 supported)

**Given** the current checkpoint has a hint_text
**When** the stepper renders
**Then** a speech-bubble style container appears below the stepper bar displaying the current checkpoint's hint_text in body text style (#F0F0F0 on semi-transparent dark background at 80% opacity, rounded 12px, max-width 280px)

**Given** a checkpoint_advanced event is received via LiveKit data channel
**When** the Flutter client processes the event
**Then** the stepper animates: the current circle transitions to green with checkmark (300ms ease-out), the next circle becomes outlined (active), and the hint text updates to the new checkpoint's hint_text with a smooth crossfade (200ms)

**Given** the stepper is a gameplay overlay, not system UI
**When** the call screen renders
**Then** the CheckpointStepper is positioned as an overlay at the top of the CallScreenCanvas, above the Rive character, and does not interfere with the hang-up button at the bottom

**Given** accessibility requirements (UX-DR12)
**When** VoiceOver/TalkBack is active
**Then** the stepper announces checkpoint progress ("Checkpoint 2 of 5 completed") and the hint text is readable by screen readers

### Story 6.8: Post-CheckpointManager Scenario Calibration (Carry-Forward from Epic 3)

As an operator,
I want the 4 remaining launch scenarios (Mugger, Girlfriend, Cop, Landlord) calibrated end-to-end using the CheckpointManager from Story 6.6,
So that all 5 launch scenarios have validated survival % ranges and final tts_voice_id selections before Epic 10 launch.

**Context:** Epic 3 Story 3.2 shipped 5 scenario YAMLs, but only The Waiter was validated end-to-end on the live VPS pipeline. The remaining 4 scenarios have complete YAML structure but their `calibration.pass_a` / `calibration.pass_b` blocks are placeholders and `tts_voice_id` is `null`. Meaningful survival % measurement requires the CheckpointManager built in Story 6.6 to track checkpoint progression — without it, the LLM improvises and survival % is just utterance count. This story closes the loop on Epic 3's deferred acceptance criteria.

**Acceptance Criteria:**

**Given** the CheckpointManager (Story 6.6) is functional and deployed on the VPS
**When** each of the 4 uncalibrated scenarios (Mugger, Girlfriend, Cop, Landlord) is loaded via `server/pipeline/prompts.py`
**Then** CheckpointManager advances through checkpoints based on ExchangeClassifier verdicts and emits `checkpoint_advanced` data channel events as specified in Story 6.6

**Given** per-scenario calibration is executed by the operator (Walid)
**When** each scenario is tested in 2 passes (Pass A = Good B1 learner, Pass B = Struggling B1 learner)
**Then** transcript + `score_transcript.py` results are captured and the scenario YAML's `calibration.pass_a` and `calibration.pass_b` blocks are populated with actual survival %, checkpoint progression, and PASS/FAIL verdict against target ranges (Mugger/Girlfriend medium: 35-55%, Cop/Landlord hard: 15-35%)

**Given** each character requires a distinct Cartesia voice matching their personality
**When** voice selection is performed
**Then** `tts_voice_id` is set in each of the 4 scenario YAMLs to a Cartesia voice ID audition-validated to match character age, tone, energy (Mugger: gruff male; Girlfriend: emotional female; Cop: authoritative male; Landlord: stern male or female)

**Given** calibration may reveal scenarios out of target range
**When** a scenario falls outside its survival % band by more than ±10%
**Then** nullable difficulty overrides (patience_start, fail_penalty, silence_penalty, etc.) are tuned and the scenario is retested until in range, with all changes documented in the scenario YAML

**Given** all 5 scenarios must be launch-ready
**When** Story 6.8 completes
**Then** all 5 scenario YAMLs have non-null `tts_voice_id`, populated calibration blocks with PASS verdicts, and are ready for database ingestion in Epic 5 (or re-confirmed if Epic 5 already completed)

---

## Epic 7: Post-Call Debrief & Learning

After each call, the user receives a brutally honest debrief: specific errors flagged with correct alternatives, hesitation analysis, idiom explanations, pre-scenario briefing for first attempts, and clear areas to work on. The debrief is the real value that justifies payment. Depends on Epic 2 (debrief screen design, Call Ended transition design).

**Key Reference:** [`difficulty-calibration.md`](difficulty-calibration.md) §5 — Defines the AI scoring system prompt, input/output JSON schemas, and evaluation boundaries for the `PostCallScorer` component built in this epic.

### Story 7.1: Build Debrief Generation Backend

As a user,
I want the server to analyze my call transcript and generate a detailed debrief report,
So that I receive specific, actionable feedback on my English performance.

**Acceptance Criteria:**

**Given** the call has ended and `POST /calls/{id}/end` has been called
**When** the server processes the call transcript
**Then** the LLM (Qwen3.5 Flash via OpenRouter) analyzes the full conversation transcript and generates a structured debrief

**Given** the debrief analysis is performed
**When** the LLM processes the transcript
**Then** it produces: survival/completion percentage calculated as floor(checkpoints_passed / total_checkpoints × 100) (FR11), a list of specific language errors with correct alternatives (FR10), longest hesitation moments with context (FR12), idioms/slang the user encountered with explanations (FR13), and a failure context with encouraging framing if completion >40% (FR15b)

**Given** the debrief is generated
**When** the result is stored
**Then** a row is created in the `debriefs` table (requires `003_debriefs.sql` migration) with call_session_id, survival_pct (backend-calculated from checkpoints_passed / total_checkpoints), checkpoints_passed, total_checkpoints, and debrief_json (complete LLM output merged with backend-measured hesitation durations and encouraging_framing). Schema defined in `debrief-content-strategy.md`
**And** the `user_progress` table is updated with the new best_score (if higher) and incremented attempts count

**Given** FR37 requires explanation when a call ends due to inappropriate behavior
**When** the call ended with reason `"inappropriate_content"`
**Then** the debrief includes a section explaining what happened and why the character reacted that way

**Given** debrief generation must be fast (NFR7: <5s target, <10s hard ceiling)
**When** the LLM analysis runs
**Then** the generation completes within the time budget, masked by the Call Ended overlay (3-4 seconds)

**Given** `GET /debriefs/{call_id}` is requested with a valid JWT
**When** the debrief exists
**Then** it returns the complete debrief data following the `{data, meta}` response format

### Story 7.2: Build Call Ended Overlay Transition

As a user,
I want to see a dramatic "Call Ended" screen for a few seconds after the call before the debrief appears,
So that the emotional weight of what just happened settles before I receive detailed feedback.

**Acceptance Criteria:**

**Given** UX-DR8 defines the CallEndedOverlay
**When** the call ends (character hung up or user ended)
**Then** an overlay screen displays: "Call Ended" text, call duration, and a theatrical scenario-specific phrase (e.g., "The mugger gave up on you" or "The waiter is still hungry")

**Given** the overlay serves as latency masking
**When** the overlay is displayed
**Then** the debrief is fetched from `GET /debriefs/{call_id}` in the background during the 3-4 second hold

**Given** the overlay has a fixed display duration
**When** 3-4 seconds have elapsed
**Then** the screen auto-transitions to the debrief screen with a fade — no user action required

**Given** the debrief is not yet available when the overlay timer expires
**When** the transition occurs
**Then** a minimal loading indicator is shown briefly until the debrief data is ready (exception to zero-spinner rule — outside active call)

**Given** the character survived the full scenario (rare completion)
**When** the Call Ended overlay displays
**Then** the theatrical phrase reflects grudging respect, not frustration (e.g., "Huh. You actually knew what you wanted.")

### Story 7.3: Build Debrief Screen

As a user,
I want to read a detailed, brutally honest debrief showing my specific errors, hesitation moments, and areas to improve,
So that I know exactly what to work on before my next attempt.

**Acceptance Criteria:**

**Given** UX-DR15 defines the debrief screen layout
**When** the debrief screen renders
**Then** it displays a scrollable vertical layout with: hero survival percentage (64px Bold, #E74C3C if <100%, #2ECC40 if 100%), attempt number, previous best comparison (if applicable)

**Given** FR10 requires specific error flagging
**When** errors are displayed
**Then** each error shows "You said: [user's phrase]" and "Correct form: [correction]" with corrections highlighted in accent color (#00E5A0)

**Given** FR12 requires hesitation analysis
**When** the hesitation section renders
**Then** the longest hesitation moment is displayed with its duration and the conversation context where it occurred

**Given** FR13 requires idiom/slang explanations
**When** idioms were encountered during the call
**Then** each idiom is listed with its meaning and contextual example (e.g., "'Pull the other one' = British idiom meaning 'I don't believe you'")

**Given** FR15b requires encouraging failure framing when >40%
**When** the user achieved >40% survival
**Then** the debrief includes proximity to next threshold and specific improvement since last attempt (if applicable)

**Given** the debrief ends with areas to work on
**When** the user scrolls to the bottom
**Then** a summary section lists 2-3 key areas for improvement — clear enough to guide self-study between sessions

**Given** no retry button and no congratulatory messages (UX principles)
**When** the debrief is complete
**Then** no CTA buttons exist — the user navigates back to the scenario list via back arrow when ready
**And** no "great job" or praise messages appear regardless of score

**Given** the debrief should be screenshot-worthy
**When** viewing the top section
**Then** survival %, character name, and scenario title form a self-contained, visually compelling block suitable for sharing

### Story 7.4: Build Pre-Scenario Briefing Display

As a user,
I want to see a short situational briefing before attempting a scenario for the first time,
So that I know what to expect and can prepare key vocabulary.

**Acceptance Criteria:**

**Given** FR14 requires a pre-scenario briefing for first attempts
**When** the user taps the call icon on a scenario they have never attempted
**Then** a briefing screen or dialog displays the scenario's `briefing_text`: key vocabulary, context overview, and what to expect

**Given** the briefing is displayed
**When** the user confirms they're ready
**Then** the call initiation proceeds normally (connecting animation → call screen)

**Given** the user has already attempted the scenario at least once
**When** they tap the call icon
**Then** the briefing is skipped — the call initiates directly (or shows content warning if applicable)

**Given** the briefing text is authored per scenario (Epic 3)
**When** the briefing is displayed
**Then** it uses the established typography styles (body for content, section-title for headers) on the dark theme background

---

## Epic 8: Monetization & Subscription

A user can subscribe to unlock all scenarios. The system enforces free/paid tier limits seamlessly. The paywall appears at moments of maximum intent with an invisible tier design. Depends on Epic 2 (paywall screen design).

### Story 8.1: Integrate StoreKit 2 and Google Play Billing

As a user,
I want to purchase a weekly subscription through the native app store payment system,
So that I can unlock all scenarios with a seamless, trusted payment experience.

**Acceptance Criteria:**

**Given** FR28 defines a $1.99/week auto-renewable subscription
**When** the in-app purchase integration is configured
**Then** StoreKit 2 (iOS) and Google Play Billing Library (Android) are integrated with a single weekly subscription product

**Given** the user initiates a purchase
**When** the native payment flow completes successfully
**Then** the server validates the receipt/purchase token asynchronously
**And** the user's tier is updated to `paid` in the `users` table immediately (optimistic access per Architecture — NFR26)

**Given** receipt validation fails asynchronously
**When** the server cannot verify the purchase
**Then** the user's tier is reverted to `free` on the next API call
**And** no data is lost — the user keeps access to debriefs from paid-tier calls

**Given** NFR11 defines zero payment data handled directly
**When** the purchase is processed
**Then** all payment data is handled entirely by StoreKit 2 / Google Play Billing — no credit card numbers, no payment tokens stored on our server

**Given** pre-commit checks are required
**When** the integration is complete
**Then** `flutter analyze` and `flutter test` pass with zero issues

### Story 8.2: Build Paywall Screen with Invisible Tier Design

As a user,
I want to see a clear subscription offer when I try to access paid content,
So that I can make an informed decision to subscribe at the moment I'm most interested.

**Acceptance Criteria:**

**Given** UX-DR16 defines invisible tiers — all scenario cards look identical
**When** a free user taps the call icon on a paid scenario
**Then** the paywall screen is displayed instead of initiating a call

**Given** the BottomOverlayCard is tapped (free user states)
**When** the user taps the overlay card
**Then** the paywall screen is displayed

**Given** FR29 defines paywall timing after 3rd free scenario
**When** a free user completes or fails their 3rd free scenario
**Then** the paywall is presented on the debrief screen at the emotional peak

**Given** the paywall screen is displayed (Epic 2 design)
**When** the user views the offer
**Then** it shows the price ($1.99/week), value proposition (all scenarios, more daily calls), and a clear subscribe CTA
**And** the visual follows the dark theme with established design tokens

**Given** the user dismisses the paywall
**When** they tap dismiss or system back
**Then** they return to the scenario list unchanged — no dark patterns, no repeated prompts

**Given** screen reader accessibility
**When** VoiceOver/TalkBack is active
**Then** the paywall announces price, value proposition, and available actions

### Story 8.3: Build Subscription Management and Full Tier Enforcement

As a user,
I want to view my subscription status and have the system correctly enforce my access level,
So that I get exactly what I'm paying for and can manage my subscription easily.

**Acceptance Criteria:**

**Given** FR30 requires subscription management
**When** a paid user wants to manage their subscription
**Then** the app provides access to the native subscription management screen (StoreKit 2 / Google Play — platform-managed, not custom UI)

**Given** FR31 requires tier enforcement based on free/paid status
**When** a free user attempts to call a paid scenario
**Then** the paywall is shown instead

**Given** FR31 requires daily call limit enforcement
**When** a user has exhausted their daily calls
**Then** call icons on all scenarios are non-functional and the BottomOverlayCard reflects the appropriate state (UX-DR5)

**Given** the BottomOverlayCard has 4 states (UX-DR5)
**When** the user's status changes
**Then** the overlay card updates correctly: free/calls remaining → "Unlock all scenarios", free/0 calls → "Subscribe to keep calling", paid/calls available → hidden, paid/0 calls today → "No more calls today"

**Given** `GET /user/profile` returns subscription status
**When** the app requests the user profile
**Then** it includes tier (free/paid), calls remaining today, and subscription expiry date
**And** the server enforces limits on `POST /calls/initiate` — returning HTTP 403 with error code `CALL_LIMIT_REACHED` or `TIER_RESTRICTED` if limits are exceeded

**Given** a user's subscription expires or is cancelled
**When** the tier reverts to free
**Then** the user retains access to all past debriefs but loses access to paid scenarios and the daily call limit changes to the free tier

---

## Epic 9: Offline Access & Data Sync

A user can access the scenario list and all past debrief reports without network connectivity. Data syncs automatically when connection returns. Local-first architecture with pull-based sync at app launch.

### Story 9.1: Build Local Cache with sqflite for Scenarios and Debriefs

As a user,
I want my scenario list and past debrief reports stored on my device,
So that I can browse scenarios and review my feedback even without internet.

**Acceptance Criteria:**

**Given** FR32 requires offline scenario list with last-known completion %
**When** the app fetches scenarios from `GET /scenarios`
**Then** the full scenario list with user progression data is cached locally in sqflite
**And** when the app is opened offline, the scenario list renders from the local cache with last-known data

**Given** FR33 requires offline debrief access
**When** a debrief is received from `GET /debriefs/{call_id}`
**Then** it is stored locally in sqflite
**And** all past debrief reports are accessible offline by tapping the report icon on a scenario card

**Given** the Architecture defines local-first with pull-based sync
**When** the app renders the scenario list
**Then** it loads from local cache first (instant render), then refreshes from API in the background if network is available

**Given** the local database mirrors the server data model
**When** sqflite tables are created
**Then** local tables exist for scenarios (id, title, difficulty, is_free, briefing_text, content_warning), user_progress (scenario_id, best_score, attempts), and debriefs (call_session_id, survival_pct, debrief_json). Schema for debrief_json defined in `debrief-content-strategy.md`

### Story 9.2: Build Automatic Data Sync on Network Availability

As a user,
I want my data to sync automatically when I get an internet connection,
So that I always see up-to-date scenarios and my progress is preserved across devices.

**Acceptance Criteria:**

**Given** FR34 requires automatic sync when network becomes available
**When** the app launches with network connectivity
**Then** it pulls the latest scenario list and user progression from the API and updates the local sqflite cache

**Given** new scenarios have been added on the server (weekly content drops post-MVP)
**When** the sync runs
**Then** new scenarios appear in the local cache and are displayed in the scenario list

**Given** the user completed a call on this device
**When** progression data was already sent to the server during the call flow
**Then** the local cache is updated simultaneously — no separate sync needed for data originating from this device

**Given** NFR20 defines eventually consistent data within 60s
**When** the app has network access
**Then** all local data is consistent with server data within 60 seconds of app launch

**Given** sync runs in the background
**When** the user is browsing the scenario list
**Then** the sync does not cause UI jank or visible loading — the list updates smoothly if new data arrives

---

## Epic 10: App Publication & Launch Readiness

Everything needed to ship: legal pages, domain/DNS/server provisioning, App Store and Play Store configuration, beta testing with analytics, and a final launch checklist ensuring the MVP is truly complete and submittable.

**User value:** Without this epic, users cannot discover or download the app. Store listings, legal pages, and beta testing are the gate between "product built" and "product available." No publication = no users.

### Story 10.1: Create Privacy Policy, Terms of Service, and Legal Compliance Pages

As a user,
I want to read clear privacy and terms pages that explain how my data is handled,
So that I can trust the app and the stores accept the submission.

**Acceptance Criteria:**

**Given** App Store and Play Store require a privacy policy URL
**When** the app is submitted
**Then** a publicly accessible privacy policy page exists at a stable URL, covering: data collected (email, voice — process-and-discard per BIPA/GDPR), data retention (no audio stored, transcripts for debrief only), third-party services (LiveKit, Cartesia, Soniox, OpenRouter), user rights (deletion, export)

**Given** FR39 requires consent and disclosure for AI interaction
**When** the privacy policy is written
**Then** it explicitly states the user is interacting with AI characters, not real humans, and that voice is processed in real-time but never stored

**Given** App Store requires Terms of Service for subscription apps
**When** the ToS is created
**Then** it covers: subscription terms ($1.99/week auto-renewable), cancellation policy (managed via platform), content disclaimer (scenarios involve simulated confrontation), age restriction (13+ per content intensity)

**Given** GDPR and BIPA compliance are required (NFR10)
**When** legal pages are reviewed
**Then** they comply with process-and-discard audio architecture — no biometric data retention

### Story 10.2: Provision Domain, DNS, SSL, and Server Infrastructure

As a developer,
I want the production server fully provisioned with a domain, SSL, and reverse proxy,
So that the backend is accessible, secure, and ready for app store review.

**Acceptance Criteria:**

**Given** the Architecture specifies a single Hetzner CX22 VPS (€3.79/mo)
**When** the server is provisioned
**Then** the VPS runs Ubuntu 24.04 with systemd services (pipecat.service, fastapi.service, caddy.service), hosting FastAPI + SQLite (aiosqlite) + Pipecat pipeline

**Given** the app needs a stable backend URL
**When** DNS is configured
**Then** a domain points to the VPS with A/AAAA records and Caddy reverse proxy handles automatic Let's Encrypt SSL certificates

**Given** the Architecture defines Caddy as the reverse proxy
**When** Caddy is configured
**Then** it routes: `/api/*` → FastAPI (port 8000), LiveKit traffic passes through on standard WebRTC ports, and all HTTP traffic is redirected to HTTPS

**Given** LiveKit Cloud is used for WebRTC (Architecture decision)
**When** LiveKit is configured
**Then** a LiveKit Cloud project is created with API key/secret stored in server environment variables

**Given** external service accounts are needed
**When** the server environment is set up
**Then** API keys are configured for: Soniox (STT), OpenRouter (LLM — Qwen3.5 Flash), Cartesia (TTS), Resend (email), and LiveKit Cloud

### Story 10.3: Configure App Store and Play Store Listings

As a developer,
I want both store listings fully configured with all required assets,
So that the app can be submitted for review without delays.

**Acceptance Criteria:**

**Given** the App Store requires specific metadata
**When** the listing is configured
**Then** it includes: app name ("Survive the Talk"), subtitle, description, keywords, category (Education), age rating (12+ or equivalent), screenshots (6.7" and 5.5" iPhone), and privacy policy URL

**Given** the Play Store requires specific metadata
**When** the listing is configured
**Then** it includes: app title, short/full description, category, content rating questionnaire completed, feature graphic (1024x500), screenshots, and privacy policy URL

**Given** subscription products must be configured in both stores
**When** in-app purchases are set up
**Then** a single weekly auto-renewable subscription ($1.99/week) is configured in App Store Connect and Google Play Console with matching product IDs

**Given** the app uses AI voice processing
**When** store metadata is completed
**Then** the microphone usage description clearly states: "Used for real-time English conversation practice with AI characters"

**Given** Epic 2 produces the app icon
**When** the icon is ready
**Then** it is exported at all required sizes: 1024x1024 (App Store), 512x512 (Play Store), and platform-specific adaptive icon formats

### Story 10.4: Set Up Beta Testing Pipeline and Analytics

As a developer,
I want to run a closed beta with real users and track key metrics,
So that I can validate the experience and catch issues before public launch.

**Acceptance Criteria:**

**Given** NFR23 requires analytics for call completion, retry, and subscription conversion
**When** analytics is integrated
**Then** the app tracks: call initiated, call completed (with survival %), call abandoned (voluntary hang-up), debrief viewed, paywall shown, subscription purchased, daily active users

**Given** beta testing needs real user feedback
**When** TestFlight (iOS) and internal testing track (Android) are configured
**Then** the app can be distributed to up to 25 beta testers with a feedback mechanism (in-app or external form)

**Given** crash reporting is essential for launch readiness
**When** crash reporting is integrated
**Then** Firebase Crashlytics (or equivalent) captures crashes with stack traces, and the crash-free rate target is >99.5%

**Given** the PoC pipeline validated in Epic 1 must work end-to-end in production
**When** beta testing begins
**Then** testers complete full call flows (initiate → conversation → hang-up → debrief) on both iOS and Android physical devices

### Story 10.5: Execute Final Launch Checklist and Store Submission

As a developer,
I want a comprehensive pre-launch checklist verified before submission,
So that the app passes store review on the first attempt with no blockers.

**Acceptance Criteria:**

**Given** the MVP must be complete
**When** the launch checklist is executed
**Then** all items are verified: all 10 epics completed, all acceptance criteria met, `flutter analyze` zero warnings, `flutter test` all passing

**Given** store review requires a functional app
**When** the app is submitted
**Then** a demo account or test credentials are provided to reviewers (email code-based auth — provide a test email that auto-validates)

**Given** NFR performance targets must be met
**When** the checklist validates performance
**Then** confirmed: perceived latency <800ms (NFR1), STT <300ms (NFR2), LLM TTFT <200ms (NFR3), TTS TTFA <200ms (NFR4), cold start <3s (NFR6), debrief generation <5s (NFR7)

**Given** security requirements must be met
**When** the checklist validates security
**Then** confirmed: HTTPS everywhere (NFR13), JWT auth on all endpoints (NFR10), API keys server-side only (NFR12), audio process-and-discard verified (NFR8), payment handled by platform (NFR11)

**Given** the app is ready for submission
**When** all checklist items pass
**Then** the app is submitted to App Store Connect and Google Play Console for review, with all metadata, screenshots, privacy policy, and subscription products in place
