---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: 'complete'
completedAt: '2026-03-27'
inputDocuments:
  - prd.md
  - prd-validation-report.md
  - product-brief-surviveTheTalk2-2026-03-25.md
  - ux-design-specification.md
  - research/market-survivethetalk-research-2026-03-23.md
  - research/domain-appstore-virality-research-2026-03-24.md
  - research/technical-conversational-ai-pipeline-research-2026-03-24.md
workflowType: 'architecture'
project_name: 'surviveTheTalk2'
user_name: 'walid'
date: '2026-03-27'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**
46 FRs organized into 7 capability groups:
- **Call Experience (FR1-FR8):** Real-time voice conversation with AI character, animated emotional reactions, lip sync, character hang-up mechanic, voluntary call end, no-network handling
- **Post-Call Debrief (FR9-FR15b):** Error flagging with corrections, survival percentage, hesitation moments, idiom explanation, pre-scenario briefing, retry pathway, motivational failure messaging
- **Scenario Management (FR16-FR21):** Scenario browsing with completion tracking, graduated difficulty, free/paid tier enforcement, daily call limits
- **User Onboarding & Authentication (FR22-FR26):** Email-only registration, zero-friction first call, consent/privacy gates, AI disclosure, mic permission. FR27 (push notifications) deferred beyond MVP
- **Monetization (FR28-FR31):** Weekly subscription ($1.99/week), paywall after 3rd free scenario, subscription management, tier enforcement
- **Offline & Data Sync (FR32-FR34):** Offline scenario list, offline debriefs, automatic sync
- **Content Safety & Compliance (FR35-FR39):** Character behavioral boundaries, in-persona abuse handling, content warnings, EU AI Act disclosure
- **Operator Tools (FR40-FR46):** Scenario authoring via system prompts, testing, difficulty tuning, real-time monitoring, KPI dashboard, latency/cost alerting, per-call cost tracking

Architectural implication: The system splits naturally into a **real-time streaming domain** (call pipeline) and a **CRUD/analytics domain** (everything else). The pipeline is the high-complexity, latency-critical core. The rest is standard mobile app architecture.

**Non-Functional Requirements:**
25 NFRs across 5 categories driving architectural decisions:
- **Performance:** <800ms perceived E2E latency (STT <300ms + LLM TTFT <200ms + TTS TTFA <200ms), 60fps Rive animation, <3s cold start, <5s debrief generation
- **Security:** Process-and-discard audio (BIPA), AES-256 encryption at rest, TLS 1.3 + DTLS-SRTP, API keys server-side only, passwordless auth with 30-day session tokens
- **Scalability:** 60-500 subscribers MVP, horizontal API gateway scaling, API rate limits as bottleneck (not infrastructure), queueing for viral spikes, linear cost scaling
- **Reliability:** >95% call completion, graceful in-persona degradation per external service, <1% crash rate, eventually consistent data sync, 99% monthly uptime
- **Integration:** 6 external systems (Soniox, OpenRouter/Qwen, Cartesia, LiveKit Cloud, Apple StoreKit 2, Google Play Billing) each with defined criticality, failure mode, and graceful degradation strategy

**Scale & Complexity:**
- Primary domain: Mobile full-stack (Flutter + Python/Pipecat backend + AI API orchestration)
- Complexity level: Medium-High (real-time multi-service pipeline + synchronized animation + regulatory compliance, but intentionally minimal functional scope)
- Estimated architectural components: ~8-10 (Flutter client, Pipecat pipeline server, API gateway, LiveKit transport, AI service integrations x3, data store, operator dashboard)

### Technical Constraints & Dependencies

- **Solo developer** — architecture must minimize operational burden. All managed services, no self-hosted GPU infrastructure for MVP
- **API-dependent pipeline** — 4 external AI services (STT, LLM, TTS, WebRTC transport) in the critical call path. Any failure breaks the experience
- **Sub-800ms latency budget** — distributed across 4+ network hops. Streaming overlap mandatory (LLM streams to TTS before full response generated)
- **Rive animation synchronization** — phoneme timestamps from Cartesia mapped to 8 viseme states, transmitted via LiveKit data channels to Flutter client
- **App Store compliance** — content modifications, AI disclosure, data sharing consent (Apple 5.1.2(i)), age ratings (13+/PEGI 12)
- **Process-and-discard audio** — voice data streams to STT and is never stored. Architecture must enforce this at the pipeline level (BIPA, GDPR)
- **$0.044-0.054/call cost ceiling** — TTS is 85-90% of pipeline cost. Architecture must support provider swapping (Pipecat service abstraction) and future self-hosting (Chatterbox MIT)
- **Flutter single codebase** — iOS + Android from one codebase. LiveKit Flutter SDK for WebRTC. Rive Flutter runtime for animation

### Cross-Cutting Concerns Identified

1. **End-to-end latency management** — affects pipeline architecture, provider selection, geographic deployment, streaming overlap strategy
2. **Audio-animation synchronization** — affects pipeline data flow, transport layer (LiveKit data channels), client-side Rive state machine
3. **Graceful degradation in-persona** — affects error handling at every pipeline stage (character reacts to failures, not UI error dialogs)
4. **Cost observability** — per-call, per-user cost tracking drives energy system enforcement and profitability monitoring
5. **Offline-first for static data** — scenario list, debriefs cached locally. Calls require network. Architecture must separate online-only from offline-capable data
6. **Voice data privacy** — process-and-discard pattern enforced at pipeline level. No raw audio storage anywhere in the system
7. **Provider swappability** — Pipecat's service abstraction allows swapping STT/LLM/TTS providers without code changes. Critical for cost optimization and risk mitigation

### Phased Architecture Constraint (PoC-First)

**Critical user requirement:** No investment in secondary screens or features until the Proof of Concept validates the core technical hypothesis.

**PoC scope (Phase 0):** Single screen — call with voice. No login, no Rive animation, no scenario selection, no debrief, no UI beyond a call button. Full voice pipeline with production tech stack: Soniox v4 (STT) → Qwen3.5 Flash via OpenRouter (LLM) → Cartesia Sonic 3 (TTS), orchestrated by Pipecat, transported via LiveKit WebRTC. One hardcoded sarcastic character system prompt.

**PoC validation gates:**
- End-to-end perceived latency <2s (target <800ms)
- LLM maintains sarcastic/adversarial persona convincingly throughout conversation
- TTS voice quality natural and expressive (supports sarcastic tone)
- STT accuracy acceptable for non-native English speakers

**Kill decision:** If any gate fails → project stops or pivots. Zero wasted effort on screens, auth, payments, compliance.

**Screens pending design (deferred to post-PoC):**
- Paywall screen (subscription offer)
- Call Ended / Hang-up transition screen
- Login / Email entry screen
- CGV / GDPR consent + EU AI Act disclosure screen
- First-call incoming call animation (onboarding)
- Debrief screen (content direction defined, visual design pending)

**Architectural implication:** The system architecture must be **layered and decoupled** so that the PoC pipeline stands alone as a functional unit. All other capabilities (auth, monetization, scenario management, offline sync, operator tools, compliance screens) attach as independent modules after PoC validation — without modifying the core pipeline.

## Starter Template Evaluation

### Primary Technology Domains

Two distinct technology domains identified from project requirements:
1. **Flutter mobile client** (Dart) — iOS + Android cross-platform app
2. **Python/Pipecat backend** — Voice AI pipeline server

### Starter Options Considered

**Flutter Client:**

| Option | Verdict | Rationale |
|--------|---------|-----------|
| `flutter create` (bare) | **Selected for PoC** | Minimal overhead for single-screen PoC. Maximum flexibility |
| Very Good CLI (BLoC + layered) | Deferred to MVP | Excellent architecture but over-engineered for PoC validation |
| Surf Flutter Template | Rejected | Similar to VGV, less community adoption |

**Python Backend:**

| Option | Verdict | Rationale |
|--------|---------|-----------|
| `uv init` + pipecat-ai | **Selected** | Official recommended setup. Lightweight, no unnecessary structure |
| Pipecat examples | Reference only | Used as pattern reference, not as project template |

### Selected Starters

#### Flutter Client: `flutter create` (PoC) → Very Good CLI (MVP)

**PoC Initialization:**

```bash
flutter create --org com.surviveTheTalk --platforms ios,android survive_the_talk
cd survive_the_talk
flutter pub add livekit_client
flutter pub add rive
```

**MVP Migration (post-PoC validation):**
Restructure to BLoC layered architecture using Very Good CLI patterns or manual migration. Add Material Design 3 dark theme, routing, state management.

**Rationale:** PoC requires one screen with one button. No architecture needed. MVP requires proper state management (BLoC), routing, offline support, and multiple screens — architecture investment justified only after PoC validates the core hypothesis.

#### Python Backend: `uv init` + Pipecat

**Initialization:**

```bash
uv init survive-the-talk-server
cd survive-the-talk-server
uv add "pipecat-ai[soniox,openai,cartesia,livekit]"
```

**Rationale:** Pipecat is a framework, not an app scaffold. The recommended setup is `uv init` with Pipecat as a dependency. Pipecat examples provide reference patterns for LiveKit transport, STT/LLM/TTS service integration, and barge-in handling.

### Architectural Decisions Provided by Starters

**Flutter `flutter create`:**
- Language: Dart (latest stable)
- Build system: Gradle (Android) + Xcode (iOS)
- No state management opinion (added later)
- No routing opinion (added later)
- No testing framework beyond basic widget tests
- Material Design available but not configured

**Python `uv init` + Pipecat:**
- Language: Python 3.12 (recommended)
- Package management: uv (fast, Rust-based)
- Pipecat frame-based pipeline architecture
- Service abstraction for STT/LLM/TTS providers (swap without code changes)
- LiveKit transport integration
- No web framework (not needed — Pipecat handles transport)

### Key Versions (Verified March 2026)

| Technology | Version | Source |
|-----------|---------|--------|
| Flutter | 3.41.x stable | flutter.dev |
| Pipecat | Latest (March 24, 2026 release) | PyPI |
| LiveKit Flutter SDK | 2.6.0 | pub.dev |
| Rive Flutter | 0.14.x | pub.dev |
| Python | 3.12 (recommended) | Pipecat docs |

**Note:** PoC project initialization is the first implementation story. MVP restructuring is a separate story triggered only by successful PoC validation.

### Production-Proven Rive 0.14.x Integration Rules

Critical lessons learned from a previous production project. These rules are **non-negotiable** for any Rive integration in this project.

**Rive 0.14.x Breaking API Changes:**
- All 0.13.x examples and documentation are INVALID. Use `RiveWidgetBuilder` + `FileLoader.fromAsset()`, not `RiveAnimation`
- `RiveNative.init()` MUST be called in `main()` before any Rive usage — without it, silent crash or hang
- State machine inputs: `TriggerInput` / `BooleanInput` / `NumberInput` (not SMI* classes)

**Mandatory Patterns:**
- `DataBind.auto()` always — `DataBind.byName()` causes infinite hang with zero error output
- `Fit.cover` for full-screen immersive (call screen) — `Fit.contain` causes black bars
- `Fit.layout` for UI components in SizedBox
- Events are **one-way only**: Rive→Flutter via `addEventListener`. Flutter→Rive via ViewModel properties (`.number()`, `.boolean()`, `.enumerator()`). Never attempt bidirectional events
- All ViewModel property references are **null-safe** (`?.value`) — missing inputs return null silently
- `dispose()` must always call `removeEventListener` + `fileLoader.dispose()`

**Test Environment:**
- Rive native does NOT load in Flutter tests. Mandatory try/catch fallback pattern with `ArgumentError` / `FlutterError`
- Never mock `RiveWidgetBuilder` — test the fallback widget only

**Pre-Commit (Non-Negotiable):**
- `flutter analyze` THEN `flutter test` — both must pass before every commit
- `flutter analyze` fails on infos too, not just errors/warnings

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
1. Voice pipeline stack: Soniox v4 (STT) → Qwen3.5 Flash via OpenRouter (LLM) → Cartesia Sonic 3 (TTS) → Pipecat (orchestration) → LiveKit (WebRTC transport)
2. Single VPS architecture: Hetzner Cloud CX22 — all server components consolidated on one instance
3. Database: SQLite on VPS — no external database service
4. Authentication: Self-coded passwordless email + JWT — no Firebase, no third-party auth
5. Rive asset delivery: Served from VPS as static files (hot-updatable without App Store resubmission)

**Important Decisions (Shape Architecture):**
6. API gateway: FastAPI on the same VPS
7. API design: REST (no GraphQL)
8. State management: BLoC (MVP only, not PoC)
9. Offline-first for static data (MVP only)
10. CI/CD: GitHub Actions → SSH deploy

**Deferred Decisions (Post-PoC):**
- Routing strategy (GoRouter) — PoC has one screen
- Offline sync mechanism — PoC requires network
- Subscription billing integration (StoreKit 2 / Google Play Billing) — post-PoC
- Operator dashboard technology — post-MVP

### Data Architecture

**Server-Side Database: SQLite on VPS**
- **Choice:** SQLite via `aiosqlite` (async Python driver)
- **Rationale:** 500 users max MVP. Zero config, zero separate process, zero maintenance. Backup = `sqlite3 .backup` in a cron job
- **Migration strategy:** Numbered SQL scripts (`001_init.sql`, `002_add_debriefs.sql`) executed at server startup. No ORM — raw SQL for full control and transparency
- **No caching layer:** SQLite at this scale is effectively in-memory. No Redis, no Memcached

**Data Model:**

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `users` | email, jwt_hash, created_at, tier (free/paid) | ~500 rows max MVP |
| `auth_codes` | email, code, expires_at, used | Temporary, cleaned by cron |
| `scenarios` | id, title, base_prompt, checkpoints (JSON), difficulty, is_free, briefing_text, content_warning, rive_character, language_focus, patience_start, fail_penalty, silence_penalty, recovery_bonus, silence_prompt_seconds, silence_hangup_seconds, escalation_thresholds, tts_voice_id | Operator-managed content. **Checkpoint-based format:** `base_prompt` = character identity, personality rules, behavioral boundaries (constant across all checkpoints). `checkpoints` = JSON array of ordered checkpoint objects, each with `{id, hint_text, prompt_segment, success_criteria}`. Pipeline constructs active system prompt as `base_prompt + checkpoints[current].prompt_segment`. **Authoring format:** scenarios authored as YAML files in `_bmad-output/planning-artifacts/scenarios/*.yaml`, loaded into SQLite as JSON at deployment. briefing_text = pre-call vocabulary/context (FR14). content_warning = nullable, shown before threat/confrontation scenarios (FR38). rive_character = Rive EnumInput value selecting character visual variant (e.g., 'mugger', 'girlfriend', 'cop') — each scenario maps to one of the 5 character skins in the .riv file. Difficulty calibration fields nullable — defaults from difficulty preset. See [`difficulty-calibration.md`](difficulty-calibration.md) §8.3 for full schema |
| `call_sessions` | user_id, scenario_id, started_at, duration, cost_cents | Per-call cost tracking |
| `debriefs` | call_session_id, survival_pct, debrief_json | LLM-generated post-call. `debrief_json` stores the complete LLM output (errors, hesitation_contexts, idioms, areas_to_work_on, inappropriate_behavior) plus backend-merged fields (hesitation durations, encouraging_framing). See `debrief-content-strategy.md` for full schema. |
| `user_progress` | user_id, scenario_id, best_score, attempts | Progression tracking |

**Client-Side Storage (MVP, not PoC):**
- `sqflite` for local cache (scenarios, debriefs, progression)
- Sync pattern: pull from API at launch → store locally → display from cache
- Calls are online-only (no offline calls possible)

### Authentication & Security

**Authentication: Passwordless Email + JWT (Self-Coded)**
- **Flow:** User enters email → server generates 6-digit code (15 min expiry) → sends via Resend SMTP → user enters code → server verifies → issues JWT (30-day expiry)
- **Server stack:** PyJWT for token generation/verification, `aiosqlite` for code storage
- **Client storage:** `flutter_secure_storage` (iOS Keychain / Android Keystore)
- **FastAPI middleware:** Every protected route validates JWT signature + expiry
- **Why not Firebase Auth:** Adds Google Cloud dependency, Firebase SDK weight in Flutter, breaks single-service consolidation principle. Passwordless email is ~100-150 lines of Python

**Email Service: Resend (Free Tier)**
- 100 emails/day — sufficient for 500 users (auth codes are infrequent)
- Only external service added beyond AI APIs and transport
- Fallback option: Brevo (300 emails/day free)

**API Key Security:**
- All AI provider keys (Soniox, OpenRouter, Cartesia, LiveKit) stored server-side only
- Environment variables loaded at server startup, never exposed to client
- Client authenticates to own API via JWT, server proxies to AI services

**Transport Security:**
- TLS 1.3 via Caddy (automatic Let's Encrypt certificates)
- WebRTC encrypted by default (DTLS-SRTP via LiveKit)

**Voice Data Privacy (BIPA/GDPR):**
- Process-and-discard enforced at Pipecat pipeline level — audio streams to STT, never written to disk
- Transcripts stored encrypted in SQLite for debrief generation
- User can request transcript deletion (GDPR Article 17)

**Rate Limiting:**
- Caddy level: global rate limiting (DDoS protection)
- FastAPI middleware: per-user rate limiting (prevent abuse)

### API & Communication Patterns

**API Design: REST via FastAPI**
- **Rationale:** Simple, well-supported by Flutter (`dio` package), sufficient for ~10 endpoints. GraphQL is overkill for this scope
- **Serialization:** Pydantic models for request/response validation

**Core Endpoints (MVP):**

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/auth/request-code` | No | Send 6-digit code to email |
| POST | `/auth/verify-code` | No | Verify code, return JWT |
| GET | `/scenarios` | JWT | List scenarios with user progression |
| GET | `/scenarios/{id}` | JWT | Scenario detail + system prompt metadata |
| POST | `/calls/initiate` | JWT | Start call, return LiveKit room token |
| POST | `/calls/{id}/end` | JWT | End call, trigger debrief generation |
| GET | `/debriefs/{call_id}` | JWT | Retrieve generated debrief. Response assembles: backend-calculated fields (survival_pct, character_name, scenario_title, attempt_number, previous_best, encouraging_framing) + LLM-generated content (errors, hesitation_contexts, idioms, areas_to_work_on, inappropriate_behavior) + backend-measured hesitation durations. Full response schema in `debrief-content-strategy.md` |
| GET | `/user/profile` | JWT | User tier, stats, progression |

**Static Assets (Caddy-served):**

| Path | Content | Caching |
|------|---------|---------|
| `/static/rive/manifest.json` | Rive file version metadata | Short TTL (5 min) |
| `/static/rive/{filename}.riv` | Rive animation files | Immutable (versioned filename) |

**Error Handling:**
- Standard JSON format: `{"error": "ERROR_CODE", "message": "Human readable", "detail": {}}`
- During active calls: errors handled in-persona by character (no UI error dialogs). Character says contextually appropriate lines ("I can't hear you anymore", "Something's wrong with my phone")
- HTTP status codes: 400 (client error), 401 (auth), 403 (tier/limit), 429 (rate limit), 500 (server)

**Real-Time Communication (During Calls):**
- Audio transport: WebRTC via LiveKit (Flutter SDK ↔ LiveKit Cloud ↔ Pipecat server)
- Viseme data: LiveKit data channels (Pipecat → Flutter) for lip sync animation
- No custom WebSocket — LiveKit handles all real-time transport

### Frontend Architecture

**PoC: Zero Architecture**
- Single `main.dart` with a "Call" button
- Direct LiveKit connection
- No state management, no routing, no architecture layers

**MVP (Post-PoC Validation):**

| Decision | Choice | Rationale |
|----------|--------|-----------|
| State management | **BLoC** (`flutter_bloc`) | Clear UI/logic separation, testable, Flutter standard |
| Routing | **GoRouter** | Declarative, deep linking support, auth guards |
| HTTP client | **dio** | Interceptors for JWT injection, retry logic, logging |
| Local DB | **sqflite** | SQLite on device, mirrors server data for offline |
| Secure storage | **flutter_secure_storage** | JWT in Keychain (iOS) / Keystore (Android) |
| Rive loading | **Network + local cache** | Download from VPS, cache on device, check manifest for updates |

**MVP Project Structure:**
```
lib/
  app/                → MaterialApp, theme config, GoRouter setup
  features/
    call/             → CallBloc, CallScreen, LiveKit integration
    scenarios/        → ScenariosBloc, ScenarioListScreen
    debrief/          → DebriefBloc, DebriefScreen
    auth/             → AuthBloc, LoginScreen (email + code entry)
  core/
    api/              → Dio client, JWT interceptor, error handling
    auth/             → JWT storage, auth state, route guards
    rive/             → RiveLoader (network fetch + local cache + manifest check)
    theme/            → Material Design 3 dark theme, typography, colors
```

**Rive Hot-Update Pattern:**
- Server serves `/static/rive/manifest.json` with version number per file
- Flutter on launch: compare local cached version vs manifest
- If different: download new `.riv` file, replace local cache
- If same or offline: load from local cache
- Rive loaded from bytes (`File.decode`) instead of asset bundle (`FileLoader.fromAsset`)
- Enables instant animation iteration without App Store resubmission

**Rive Character Variants:**
- The Rive character file exposes a `character` EnumInput that selects the visual variant (mugger, waiter, girlfriend, cop, landlord)
- Each scenario defines a `rive_character` value in the database — Flutter sets the Rive input when the call screen loads, before the conversation begins
- All 5 variants share the same state machine (emotions, visemes, hang-up button) — only the visual appearance changes
- Future scenarios can reuse existing variants or add new ones (EnumInput is additive, no breaking changes)

### Infrastructure & Deployment

**Hosting: Hetzner Cloud CX22 — Single VPS, Everything Consolidated**

| Component | Technology | Location |
|-----------|------------|----------|
| Voice pipeline | Pipecat (Python process) | Hetzner CX22 |
| API gateway | FastAPI (Python process) | Hetzner CX22 |
| Database | SQLite (file on disk) | Hetzner CX22 |
| Reverse proxy + HTTPS | Caddy (auto Let's Encrypt) | Hetzner CX22 |
| Rive assets | Static files served by Caddy | Hetzner CX22 |
| **Total infrastructure cost** | | **€3.79/month** |

**VPS Specifications (CX22):**
- 2 shared vCPU, 4 GB RAM, 40 GB NVMe, 20 TB bandwidth
- EU data center (Falkenstein/Nuremberg) — GDPR compliant
- Managed via `hcloud` CLI + SSH
- Upgrade path: CX32 (4 vCPU, 8 GB RAM, €6.80/mo) if needed at scale

**Alternatives evaluated and rejected:**
- Hostinger: CLI available (`hapi`) but worse value (1 vCPU/4GB at $6.49/mo with 24-month commitment vs Hetzner 2 vCPU/4GB at €3.79/mo no commitment)
- DigitalOcean: $6/mo for 1GB RAM — significantly more expensive for less
- Fly.io: Pay-as-you-go but opaque pricing, less control

**Process Management:**
- `systemd` services: `pipecat.service`, `fastapi.service`, `caddy.service`
- Auto-restart on crash, log to journald

**Deployment Strategy:**
- **PoC:** SSH + `git pull` + `systemctl restart` (manual, fast iteration)
- **MVP:** GitHub Actions → SSH deploy on push to `main` (automated)

**Monitoring (Solo Dev Appropriate):**
- Structured logging: Python `logging` module → stdout (captured by journald)
- Caddy access logs for HTTP traffic analysis
- Health endpoint: `GET /health` — checks SQLite connectivity + API provider reachability
- Cost alerting: log estimated cost per call, alert if cost/call exceeds threshold
- No heavy monitoring stack (no Grafana, no Prometheus) — overkill for 500 users

**Backup Strategy:**
- Daily cron: `sqlite3 db.sqlite ".backup /backups/db_$(date +%Y%m%d).sqlite"`
- 7-day retention (delete older backups)
- Weekly Hetzner VPS snapshot (€0.01/GB/month) for full disaster recovery

**Scaling Path (Post-MVP):**
- 500→5,000 users: Upgrade to CX32, optimize SQLite queries, add connection pooling
- 5,000+ users: Consider PostgreSQL migration, separate API and pipeline processes to different VPS instances, Hetzner Load Balancer (€8.76/mo)

### Decision Impact Analysis

**Implementation Sequence:**
1. **PoC:** Pipecat + LiveKit on Hetzner VPS → bare Flutter app with call button → validate latency/quality
2. **Post-PoC:** Add FastAPI + SQLite + passwordless auth on same VPS
3. **MVP Build:** Restructure Flutter to BLoC + GoRouter + offline cache + Rive hot-loading
4. **Growth:** Upgrade VPS, add automated CI/CD, enhanced monitoring

**Cross-Component Dependencies:**
- Call initiation requires LiveKit token generation (FastAPI endpoint) → depends on auth (JWT)
- Debrief generation depends on call transcript → depends on call pipeline completion
- Rive hot-update depends on manifest.json served by Caddy → same VPS, zero latency
- Offline cache (Flutter sqflite) syncs with server SQLite via REST API
- Cost tracking (call_sessions table) feeds operator dashboard metrics

**External Service Dependencies (Unavoidable):**

| Service | Purpose | Failure Impact | Degradation Strategy |
|---------|---------|---------------|---------------------|
| LiveKit Cloud | WebRTC transport | Call impossible | Show "no connection" in-persona |
| Soniox v4 | Speech-to-text | Can't hear user | Character: "I can't hear you" → end call |
| OpenRouter (Qwen3.5) | LLM responses | No AI dialogue | Character: "My mind went blank" → end call |
| Cartesia Sonic 3 | Text-to-speech | No voice output | Fallback to text display (degraded) |
| Resend | Auth emails | Can't sign up/in | Show "try again later" + local JWT still valid for 30 days |
| Apple StoreKit 2 | iOS payments | Can't subscribe | Free tier still works, retry payment later |
| Google Play Billing | Android payments | Can't subscribe | Free tier still works, retry payment later |

## Implementation Patterns & Consistency Rules

### Critical Conflict Points

Two languages (Python + Dart) communicating via JSON API. The primary conflict zone is the **interface between them** — naming, formats, and conventions must be locked down so AI agents never make inconsistent choices.

### Naming Patterns

**Cross-Language Convention — The Golden Rule:**

| Context | Convention | Example |
|---------|-----------|---------|
| JSON API fields | `snake_case` | `{"user_id": 1, "best_score": 85}` |
| Python (all) | `snake_case` (PEP 8) | `user_id`, `get_scenarios()`, `call_session.py` |
| Dart variables/functions | `camelCase` | `userId`, `getScenarios()` |
| Dart classes | `PascalCase` | `CallBloc`, `ScenarioModel` |
| Dart files | `snake_case.dart` | `call_bloc.dart`, `scenario_model.dart` |
| SQLite tables | `snake_case`, plural | `users`, `call_sessions`, `debriefs` |
| SQLite columns | `snake_case` | `user_id`, `created_at`, `best_score` |
| REST endpoints | `snake_case`, plural | `/scenarios`, `/calls`, `/debriefs` |
| Environment variables | `UPPER_SNAKE_CASE` | `OPENROUTER_API_KEY`, `LIVEKIT_URL` |

**JSON mapping:** Python sends `snake_case` natively via Pydantic. Dart models map to `camelCase` in their `fromJson`/`toJson` factory constructors.

```dart
// Dart model — explicit mapping
class UserProgress {
  final int userId;
  final int bestScore;

  factory UserProgress.fromJson(Map<String, dynamic> json) => UserProgress(
    userId: json['user_id'] as int,
    bestScore: json['best_score'] as int,
  );
}
```

```python
# Python model — native snake_case
class UserProgress(BaseModel):
    user_id: int
    best_score: int
```

### BLoC Naming Conventions (MVP)

**Events:** `VerbNounEvent`
```dart
class LoadScenariosEvent extends ScenariosEvent {}
class InitiateCallEvent extends CallEvent {}
class SubmitAuthCodeEvent extends AuthEvent {}
class RetryCallEvent extends CallEvent {}
```

**States:** `NounStatusState`
```dart
class ScenariosInitial extends ScenariosState {}
class ScenariosLoading extends ScenariosState {}
class ScenariosLoaded extends ScenariosState { final List<Scenario> scenarios; }
class ScenariosError extends ScenariosState { final String message; }
```

**Blocs:** `FeatureBloc`
```dart
class ScenariosBloc extends Bloc<ScenariosEvent, ScenariosState> {}
class CallBloc extends Bloc<CallEvent, CallState> {}
class AuthBloc extends Bloc<AuthEvent, AuthState> {}
class DebriefBloc extends Bloc<DebriefEvent, DebriefState> {}
```

### API Response Format

**Success response:**
```json
{
  "data": { "user_id": 1, "email": "user@example.com", "tier": "free" },
  "meta": { "timestamp": "2026-03-27T14:30:00Z" }
}
```

**List response:**
```json
{
  "data": [
    { "id": 1, "title": "The Sarcastic Barista", "difficulty": 1 },
    { "id": 2, "title": "The Angry Landlord", "difficulty": 3 }
  ],
  "meta": { "timestamp": "2026-03-27T14:30:00Z", "count": 2 }
}
```

**Error response:**
```json
{
  "error": {
    "code": "AUTH_CODE_EXPIRED",
    "message": "The verification code has expired. Please request a new one."
  }
}
```

**Data format rules:**
- Dates: ISO 8601 UTC always (`2026-03-27T14:30:00Z`)
- Null fields: omitted from JSON (not `"field": null`), unless absence has specific meaning
- Booleans: `true`/`false` (never `1`/`0`)
- IDs: integers (SQLite ROWID)
- Monetary values: integer cents (`cost_cents: 5` = $0.05)
- Percentages: integer 0-100 (`survival_pct: 73`)

### Structure Patterns

**Python Server Structure:**
```
server/
  main.py                → Entry point (FastAPI app + Pipecat startup)
  pipeline/
    bot.py               → Pipecat pipeline definition
    prompts.py           → System prompts for characters
    handlers.py          → Pipeline event handlers (viseme, hang-up, errors)
  api/
    routes_auth.py       → /auth/* endpoints
    routes_scenarios.py  → /scenarios/* endpoints
    routes_calls.py      → /calls/* endpoints
    routes_debriefs.py   → /debriefs/* endpoints
    middleware.py        → JWT validation, rate limiting
  db/
    database.py          → SQLite connection, init, migration runner
    migrations/          → 001_init.sql, 002_add_debriefs.sql, ...
    queries.py           → Raw SQL query functions (no ORM)
  models/
    schemas.py           → Pydantic request/response models
  config.py              → Environment variables loading via pydantic-settings
```

**Flutter MVP Structure (defined in Step 4):**
```
lib/
  app/                   → MaterialApp, theme, GoRouter setup
  features/
    call/                → CallBloc, CallScreen, LiveKit integration
    scenarios/           → ScenariosBloc, ScenarioListScreen
    debrief/             → DebriefBloc, DebriefScreen
    auth/                → AuthBloc, LoginScreen
  core/
    api/                 → Dio client, JWT interceptor, error handling
    auth/                → JWT storage, auth state, route guards
    rive/                → RiveLoader (network fetch + local cache + manifest check)
    theme/               → Material Design 3 dark theme, typography, colors
```

**Test Structure:**
- Python: `tests/` at server root, mirroring `server/` structure (`tests/api/`, `tests/pipeline/`, `tests/db/`)
- Flutter: `test/` at project root, mirroring `lib/` structure (`test/features/call/`, `test/core/api/`)
- No co-location — tests are always in separate directories
- Test file naming: `test_<module>.py` (Python), `<module>_test.dart` (Flutter)

### Communication Patterns

**LiveKit Data Channel Messages (Pipecat → Flutter):**

All messages are JSON with a mandatory `type` field for discrimination:

```json
{"type": "viseme", "data": {"viseme_id": 3, "timestamp_ms": 1450}}
{"type": "emotion", "data": {"emotion": "annoyed", "intensity": 0.8}}
{"type": "hang_up_warning", "data": {"seconds_remaining": 5}}
{"type": "call_end", "data": {"reason": "character_hung_up", "survival_pct": 40, "checkpoints_passed": 2, "total_checkpoints": 5}}
{"type": "checkpoint_advanced", "data": {"checkpoint_id": "refuse", "index": 1, "total": 5, "next_hint": "Ask him what he'll actually do."}}
```

Defined message types: `viseme`, `emotion`, `hang_up_warning`, `call_end`, `checkpoint_advanced`

**BLoC Communication Pattern (MVP):**
- UI dispatches Events to BLoC
- BLoC emits States
- UI reacts to States via `BlocBuilder` / `BlocListener`
- Cross-feature communication: via shared repository classes, never direct BLoC-to-BLoC

### Process Patterns

**Error Handling — Two Modes:**

**During active call (in-persona, CRITICAL):**
- NEVER show technical error dialogs, snackbars, or UI error messages
- Character reacts naturally to failures:
  - STT failure → "I can't hear you anymore... *click*" → end call
  - LLM failure → "My mind just went blank... I gotta go" → end call
  - TTS failure → fallback to text subtitle on screen (last resort)
  - Network lost → "You're breaking up..." → end call screen
- All degradation is in-character, maintaining immersion

**Outside calls (standard Flutter):**
- Loading: centered `CircularProgressIndicator` (Material Design 3)
- Error: contextual message within the screen (no popup dialogs)
- Retry: explicit button, no invisible automatic retries
- Empty state: descriptive message + action suggestion

**Loading State Convention (BLoC):**
- Every feature BLoC has 4 base states: `Initial`, `Loading`, `Loaded`, `Error`
- `Loading` state carries no data (show spinner)
- `Loaded` state carries the data
- `Error` state carries error message string
- No nested loading states — keep flat

### Logging Patterns

**Python server logging:**
```python
import logging
logger = logging.getLogger(__name__)

# Always include context IDs when available
logger.info("call_initiated", extra={"user_id": 1, "scenario_id": 5})
logger.warning("stt_slow_response", extra={"user_id": 1, "latency_ms": 450})
logger.error("tts_timeout", extra={"user_id": 1, "call_id": 42, "duration_ms": 3500})
```

- Levels: `DEBUG` (dev only), `INFO` (business events), `WARNING` (degraded performance), `ERROR` (failures requiring attention)
- Always include `user_id` and `scenario_id`/`call_id` when available
- NEVER log sensitive data: email addresses, JWT tokens, audio data, API keys
- Log format: structured key-value for parseability

### Enforcement Guidelines

**All AI Agents MUST:**
1. Run `flutter analyze` (zero issues) AND `flutter test` (all pass) before every Flutter commit
2. Run `ruff check .` AND `ruff format .` AND `pytest` before every Python commit
3. Use `snake_case` in ALL JSON API fields — no exceptions
4. Follow the BLoC naming convention exactly: `VerbNounEvent`, `NounStatusState`, `FeatureBloc`
5. Never show technical errors during active calls — always degrade in-persona
6. Use the exact API response format (`data`/`meta`/`error` wrapper)
7. Follow the Rive 0.14.x integration rules from Step 3 — no exceptions

**Convention Reference (When in Doubt):**
- Python → PEP 8
- Dart → Effective Dart Style Guide (`dart.dev/guides/language/effective-dart/style`)
- SQL → lowercase `snake_case`
- REST → plural nouns, `snake_case` paths
- JSON → `snake_case` fields

## Project Structure & Boundaries

### Complete Monorepo Directory Structure

```
surviveTheTalk2/
├── .gitignore
├── .github/
│   └── workflows/
│       ├── flutter-ci.yml              # flutter analyze + flutter test
│       └── server-deploy.yml           # ruff + pytest + SSH deploy (MVP)
│
├── client/                             # Flutter app (iOS + Android)
│   ├── pubspec.yaml
│   ├── analysis_options.yaml
│   ├── lib/
│   │   └── main.dart                   # PoC: single file, one screen
│   ├── test/
│   │   └── widget_test.dart
│   ├── android/
│   ├── ios/
│   └── assets/
│       └── rive/
│           └── fallback_character.riv  # Bundled fallback if network fails on first launch
│
├── server/                             # Python backend (Pipecat + FastAPI)
│   ├── pyproject.toml                  # uv project config + dependencies
│   ├── .python-version                 # 3.12
│   ├── main.py                         # Entry point (FastAPI + Pipecat startup)
│   ├── config.py                       # Env vars via pydantic-settings
│   ├── pipeline/
│   │   ├── bot.py                      # Pipecat pipeline definition
│   │   ├── prompts.py                  # Character system prompts
│   │   └── handlers.py                 # Viseme, hang-up, error handlers
│   ├── api/
│   │   ├── routes_auth.py              # POST /auth/*
│   │   ├── routes_scenarios.py         # GET /scenarios/*
│   │   ├── routes_calls.py             # POST /calls/*
│   │   ├── routes_debriefs.py          # GET /debriefs/*
│   │   ├── routes_health.py            # GET /health
│   │   └── middleware.py               # JWT validation, rate limiting
│   ├── db/
│   │   ├── database.py                 # SQLite connection + migration runner
│   │   ├── queries.py                  # Raw SQL query functions
│   │   └── migrations/
│   │       ├── 001_init.sql            # users, scenarios (incl. briefing_text, content_warning), auth_codes
│   │       ├── 002_calls.sql           # call_sessions
│   │       └── 003_debriefs.sql        # debriefs, user_progress
│   ├── models/
│   │   └── schemas.py                  # Pydantic request/response models
│   ├── static/
│   │   └── rive/
│   │       ├── manifest.json           # Version metadata for hot-update
│   │       └── character_v1.riv        # Hot-updatable Rive file
│   └── tests/
│       ├── test_auth.py
│       ├── test_pipeline.py
│       ├── test_calls.py
│       └── test_queries.py
│
└── deploy/
    ├── Caddyfile                       # Reverse proxy + HTTPS + static files
    ├── pipecat.service                 # systemd unit for Pipecat process
    ├── fastapi.service                 # systemd unit for FastAPI process
    ├── backup.sh                       # SQLite daily backup cron script
    └── .env.example                    # Template for env vars (no secrets)
```

### Flutter MVP Client Structure (Post-PoC)

PoC is a single `lib/main.dart`. MVP restructures to feature-based BLoC architecture:

```
client/lib/
├── main.dart                            # App entry, RiveNative.init()
├── app/
│   ├── app.dart                         # MaterialApp wrapper
│   ├── router.dart                      # GoRouter config + auth guards
│   └── theme.dart                       # MD3 dark theme setup
│
├── features/
│   ├── auth/
│   │   ├── bloc/
│   │   │   ├── auth_bloc.dart
│   │   │   ├── auth_event.dart
│   │   │   └── auth_state.dart
│   │   ├── models/
│   │   │   └── user.dart
│   │   ├── repositories/
│   │   │   └── auth_repository.dart
│   │   └── views/
│   │       ├── login_screen.dart        # Email entry
│   │       └── code_screen.dart         # 6-digit code verification
│   │
│   ├── call/
│   │   ├── bloc/
│   │   │   ├── call_bloc.dart
│   │   │   ├── call_event.dart
│   │   │   └── call_state.dart
│   │   ├── models/
│   │   │   └── call_session.dart
│   │   ├── repositories/
│   │   │   └── call_repository.dart
│   │   ├── services/
│   │   │   ├── livekit_service.dart     # LiveKit room management
│   │   │   └── viseme_handler.dart      # Data channel → Rive viseme input
│   │   └── views/
│   │       ├── call_screen.dart         # Main call UI + Rive character
│   │       └── call_ended_screen.dart   # Hang-up transition
│   │
│   ├── scenarios/
│   │   ├── bloc/
│   │   │   ├── scenarios_bloc.dart
│   │   │   ├── scenarios_event.dart
│   │   │   └── scenarios_state.dart
│   │   ├── models/
│   │   │   └── scenario.dart
│   │   ├── repositories/
│   │   │   └── scenarios_repository.dart
│   │   └── views/
│   │       └── scenario_list_screen.dart
│   │
│   └── debrief/
│       ├── bloc/
│       │   ├── debrief_bloc.dart
│       │   ├── debrief_event.dart
│       │   └── debrief_state.dart
│       ├── models/
│       │   └── debrief.dart
│       ├── repositories/
│       │   └── debrief_repository.dart
│       └── views/
│           └── debrief_screen.dart
│
├── core/
│   ├── api/
│   │   ├── api_client.dart              # Dio instance + JWT interceptor
│   │   └── api_exceptions.dart          # Typed API errors
│   ├── auth/
│   │   └── token_storage.dart           # flutter_secure_storage wrapper
│   ├── rive/
│   │   ├── rive_loader.dart             # Download + cache + manifest check
│   │   └── rive_manifest.dart           # Manifest model
│   └── theme/
│       ├── app_colors.dart              # MD3 dark color system
│       ├── app_typography.dart          # Inter font, size scale
│       └── app_theme.dart               # ThemeData builder
│
└── shared/
    └── widgets/
        ├── loading_indicator.dart       # Standard loading spinner
        └── error_display.dart           # Standard error message widget
```

### Architectural Boundaries

**Boundary 1 — Client ↔ Server (REST API over HTTPS)**
```
Flutter (Dio + JWT) ──HTTPS──► Caddy ──► FastAPI
                                         ├── routes_auth.py      (public)
                                         ├── routes_scenarios.py  (JWT required)
                                         ├── routes_calls.py      (JWT required)
                                         └── routes_debriefs.py   (JWT required)
```
- Client NEVER calls AI services directly — all API keys are server-side only
- Client sends JWT in `Authorization: Bearer <token>` header
- Caddy terminates TLS, FastAPI receives plain HTTP on localhost

**Boundary 2 — Client ↔ LiveKit (WebRTC)**
```
Flutter (livekit_client) ──WebRTC──► LiveKit Cloud ◄── Pipecat (server)
                         ◄──data channel──┘
```
- Flutter connects to LiveKit room with a token generated by FastAPI (`POST /calls/initiate`)
- Audio flows bidirectionally via WebRTC
- Viseme/emotion data flows Pipecat → Flutter via LiveKit data channels
- Client NEVER connects directly to Pipecat process

**Boundary 3 — Pipecat ↔ AI Services (Streaming APIs)**
```
Pipecat pipeline (server/pipeline/bot.py)
  ├──► Soniox v4          (STT: audio stream → text)
  ├──► CheckpointManager  (checkpoint progression, prompt segment swapping)
  ├──► PatienceTracker     (patience state, silence timers, escalation)
  ├──► ExchangeClassifier  (async parallel: user speech vs checkpoint success_criteria)
  ├──► OpenRouter          (LLM: text → response text, streaming)
  ├──► Cartesia Sonic 3    (TTS: text → audio stream + phoneme timestamps)
  └──► LiveKit Cloud       (transport: audio + data channels to client)
```
- Pipecat is the ONLY component touching AI APIs
- Service abstraction via Pipecat plugins — swap providers without touching other code
- All streaming, no batch — audio flows continuously through the pipeline

**Boundary 4 — FastAPI ↔ SQLite (Data Access)**
```
FastAPI routes ──► db/queries.py ──► SQLite file
```
- ALL database access goes through `db/queries.py` — no raw SQL in route handlers
- `db/database.py` handles connection management and migration execution
- Routes use Pydantic models, queries return dicts, schemas map between them

**Boundary 5 — Caddy ↔ Static Assets (Rive Hot-Update)**
```
Flutter ──HTTPS──► Caddy ──► /static/rive/manifest.json
                             /static/rive/character_v1.riv
```
- Caddy serves static files directly — no FastAPI involvement
- Rive files versioned by filename (immutable, cacheable forever)
- Manifest.json has short TTL (5 min) for version checking

### FR Categories → Structure Mapping

| FR Category | Server Location | Client Location |
|-------------|----------------|-----------------|
| **Call Experience (FR1-FR8)** | `pipeline/bot.py`, `pipeline/handlers.py` | `features/call/` |
| **Post-Call Debrief (FR9-FR15b)** | `api/routes_debriefs.py`, LLM analysis in pipeline | `features/debrief/` |
| **Scenario Management (FR16-FR21)** | `api/routes_scenarios.py`, `db/queries.py` | `features/scenarios/` |
| **Auth & Onboarding (FR22-FR26)** | `api/routes_auth.py`, `api/middleware.py` | `features/auth/` |
| **Monetization (FR28-FR31)** | `api/middleware.py` (tier enforcement) | StoreKit 2 / Play Billing (native) |
| **Offline & Sync (FR32-FR34)** | `api/routes_scenarios.py` (data source) | `core/api/`, sqflite local cache |
| **Content Safety (FR35-FR39)** | `pipeline/prompts.py` (behavioral boundaries) | `features/call/views/` (content warnings) |
| **Operator Tools (FR40-FR46)** | `db/queries.py` (KPIs), `config.py` | Deferred (post-MVP dashboard) |

### Cross-Cutting Concerns Mapping

| Concern | Server Files | Client Files |
|---------|-------------|-------------|
| **JWT Auth** | `api/middleware.py`, `api/routes_auth.py` | `core/auth/token_storage.dart`, `core/api/api_client.dart` (interceptor) |
| **Cost Tracking** | `pipeline/handlers.py` (calculate), `db/queries.py` (store) | N/A (server-only) |
| **Rive Hot-Update** | `static/rive/manifest.json` + `.riv` files | `core/rive/rive_loader.dart` |
| **In-Persona Errors** | `pipeline/handlers.py` (character error responses) | `features/call/bloc/call_bloc.dart` (state transitions) |
| **Structured Logging** | `main.py` (config), all modules via `logging.getLogger(__name__)` | `debugPrint` for dev only |

### Data Flow — Complete Call Lifecycle

```
 1. Flutter: user taps "Call" button on scenario
 2. Flutter → FastAPI: POST /calls/initiate {scenario_id}
 3. FastAPI: verify JWT → check user tier/daily limits → create call_session row → generate LiveKit token
 4. FastAPI → Flutter: {livekit_token, room_name, call_id}
 5. Flutter: connect to LiveKit room with token
 6. Pipecat: joins same LiveKit room server-side, loads scenario base_prompt + first checkpoint's prompt_segment
 7. CALL LOOP:
    a. User speaks → audio → LiveKit WebRTC → Pipecat
    b. Pipecat → Soniox STT → transcribed text
    c. Pipecat → OpenRouter LLM (Qwen3.5 Flash) → response text (streaming)
    d. Pipecat → Cartesia TTS → audio stream + phoneme timestamps (streaming)
    e. Pipecat → LiveKit → Flutter: audio playback + viseme data channel
    f. Flutter: plays audio + drives Rive lip sync from viseme data
 8. Call ends: user hangs up OR character hangs up (survival mechanic)
 9. Flutter → FastAPI: POST /calls/{id}/end
10. FastAPI: calculate cost → update call_session → generate debrief via LLM transcript analysis
11. Flutter → FastAPI: GET /debriefs/{call_id}
12. Flutter: display debrief screen (survival %, errors, idioms)
```

### Deploy Configuration

**Caddyfile:**
```
api.survivethetalk.com {
    handle /static/* {
        root * /opt/survive-the-talk/server
        file_server
    }
    handle {
        reverse_proxy localhost:8000
    }
}
```

**.env.example:**
```
# AI Services
SONIOX_API_KEY=
OPENROUTER_API_KEY=
CARTESIA_API_KEY=

# LiveKit
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

# Auth
RESEND_API_KEY=
JWT_SECRET=

# Database
DATABASE_PATH=/opt/survive-the-talk/data/db.sqlite
```

## Architecture Validation Results

### Coherence Validation — PASS

**Decision Compatibility:**
All technology choices work together without conflicts. Flutter 3.41.x + LiveKit Flutter SDK 2.6.0 + Rive 0.14.x are compatible. Python 3.12 + Pipecat (latest) + FastAPI + aiosqlite are compatible. Caddy as reverse proxy in front of FastAPI is standard. No contradictory decisions found.

**Pattern Consistency:**
- snake_case JSON ↔ camelCase Dart with explicit `fromJson` mapping — consistent
- BLoC naming conventions (VerbNounEvent, NounStatusState) align with feature-based structure
- REST API wrapper format (`data`/`error`) consistent between Pydantic models and Dart models
- In-persona error handling defined on both sides (pipeline handlers + call BLoC)

**Structure Alignment:**
- Every FR category maps to specific server + client directories
- 5 architectural boundaries clearly defined with data flow direction
- PoC is a clean subset of MVP structure (just `main.dart` + `pipeline/bot.py`)
- Deploy config (Caddyfile, systemd, .env) specified and aligned with VPS architecture

### Requirements Coverage Validation — PASS

**Functional Requirements (45 of 46 in scope):**

| FR Category | FRs | Coverage | Notes |
|-------------|-----|----------|-------|
| Call Experience | FR1-FR8 | Full | Pipeline + LiveKit + Rive animation |
| Post-Call Debrief | FR9-FR15b | Full | LLM transcript analysis + debrief table. `briefing_text` added to scenarios (FR14) |
| Scenario Management | FR16-FR21 | Full | Scenarios table + tier enforcement middleware |
| Auth & Onboarding | FR22-FR26 | Full | Passwordless email + JWT. FR27 (push notifications) removed from MVP scope |
| Monetization | FR28-FR31 | Full | StoreKit 2 / Play Billing (deferred to post-PoC implementation) |
| Offline & Sync | FR32-FR34 | Full | sqflite local cache + pull-based sync |
| Content Safety | FR35-FR39 | Full | `content_warning` field added to scenarios (FR38). EU AI Act disclosure screen (FR39) deferred to post-PoC |
| Operator Tools | FR40-FR46 | Deferred | Post-MVP. Cost tracking (FR46) supported by `call_sessions.cost_cents` from MVP |

**FR27 — Explicitly Removed from MVP:** Push notifications are out of scope for the MVP. No FCM, no APNs, no notification permission request. This simplifies the architecture by eliminating a Firebase dependency.

**Non-Functional Requirements Coverage:**

| NFR Category | Status | Implementation |
|-------------|--------|---------------|
| Performance (<800ms latency) | Covered | Streaming overlap in Pipecat, provider selection optimized for TTFT/TTFA |
| Performance (60fps Rive) | Covered | Rive 0.14.x C++ renderer (`Factory.rive`), `Fit.cover` for full screen |
| Performance (<3s cold start) | Covered | Standard Flutter app, cached data loads first |
| Performance (<5s debrief) | Covered | LLM analysis triggered at call end |
| Security (process-and-discard) | Covered | Enforced at Pipecat pipeline level — audio never written to disk |
| Security (encryption at rest) | Covered | VPS disk-level encryption (Hetzner supports LUKS). SQLite data encrypted at rest via OS layer. SQLCipher deferred unless regulatory audit requires it |
| Security (TLS 1.3) | Covered | Caddy auto-TLS with Let's Encrypt |
| Security (DTLS-SRTP) | Covered | LiveKit WebRTC default encryption |
| Security (API keys server-side) | Covered | All keys in .env on VPS, never in client code |
| Security (passwordless 30-day) | Covered | PyJWT with 30-day expiry, code verification via email |
| Scalability (60-500 users) | Covered | Single Hetzner CX22 VPS, upgrade path to CX32 documented |
| Reliability (>95% call completion) | Covered | Graceful in-persona degradation per external service |
| Reliability (<1% crash rate) | Covered | Standard Flutter quality practices, pre-commit checks |
| Reliability (eventual consistency) | Covered | Pull-based sync at app launch |
| Reliability (99% monthly uptime) | Covered | systemd auto-restart, Hetzner SLA |

### Implementation Readiness Validation — PASS

**Decision Completeness:**
- All 10 critical + important decisions documented with technology names and versions
- Deferred decisions explicitly listed with rationale
- No ambiguous "TBD" items in critical path

**Structure Completeness:**
- Complete monorepo directory tree with all files
- Flutter MVP structure with full feature-based layout
- Server structure with all modules
- Deploy configuration files specified

**Pattern Completeness:**
- Naming conventions cover all layers (Python, Dart, SQL, JSON, REST, env vars)
- BLoC event/state naming convention with concrete examples
- API response format with success/list/error examples
- Error handling split: in-persona (during calls) vs standard (outside calls)
- LiveKit data channel message format with type discrimination
- Logging pattern with mandatory context fields

### Gaps Addressed

| Gap | Severity | Resolution |
|-----|----------|------------|
| FR14 — pre-scenario briefing storage | Minor | Added `briefing_text` column to `scenarios` table |
| FR38 — content warning field | Minor | Added `content_warning` nullable column to `scenarios` table |
| Checkpoint-based scenarios | Major | Replaced monolithic `system_prompt` with `base_prompt` + `checkpoints` (JSON array). Scenarios authored as YAML files, loaded into DB as structured JSON. Pipeline swaps prompt segments per checkpoint via `CheckpointManager` (Epic 6) |
| FR27 — push notifications | N/A | Removed from MVP scope entirely per user decision |
| AES-256 encryption at rest | Clarification | VPS disk-level encryption (LUKS). SQLCipher deferred unless regulatory audit |

### Architecture Completeness Checklist

**Requirements Analysis**
- [x] Project context thoroughly analyzed (46 FRs, 25 NFRs, 7 cross-cutting concerns)
- [x] Scale and complexity assessed (Medium-High, 60-500 users MVP)
- [x] Technical constraints identified (8 constraints including solo dev, latency budget, cost ceiling)
- [x] Cross-cutting concerns mapped (7 concerns with architectural implications)
- [x] PoC-first constraint established as governing principle

**Architectural Decisions**
- [x] Critical decisions documented with versions (pipeline stack, VPS, DB, auth, Rive delivery)
- [x] Technology stack fully specified (Flutter 3.41.x, Python 3.12, Pipecat, FastAPI, SQLite, Caddy)
- [x] Integration patterns defined (5 boundaries with data flow)
- [x] Performance considerations addressed (streaming overlap, provider latency budgets)
- [x] Security architecture defined (process-and-discard, JWT, TLS, disk encryption)

**Implementation Patterns**
- [x] Naming conventions established (snake_case JSON, BLoC conventions, file naming)
- [x] Structure patterns defined (feature-based Flutter, module-based Python)
- [x] Communication patterns specified (REST, LiveKit data channels, BLoC events/states)
- [x] Process patterns documented (in-persona errors, loading states, logging)
- [x] Enforcement guidelines with pre-commit checks

**Project Structure**
- [x] Complete directory structure defined (monorepo with client/ + server/ + deploy/)
- [x] Component boundaries established (5 boundaries documented)
- [x] Integration points mapped (call lifecycle 12-step flow)
- [x] Requirements to structure mapping complete (FR categories → directories)
- [x] Deploy configuration specified (Caddyfile, systemd, .env)

### Architecture Readiness Assessment

**Overall Status: READY FOR IMPLEMENTATION**

**Confidence Level:** HIGH

**Key Strengths:**
- PoC-first architecture ensures zero wasted effort if voice pipeline doesn't validate
- Single VPS consolidation minimizes operational burden for solo developer
- Pipecat service abstraction enables provider swapping without code changes
- Production-proven Rive 0.14.x rules prevent known integration pitfalls
- Clear boundaries and data flow make each component independently implementable
- Cost: €3.79/month infrastructure + pay-per-use AI APIs only

**Areas for Future Enhancement (Post-MVP):**
- Push notifications (removed from MVP, may return in growth phase)
- Operator dashboard (FR40-FR46 deferred to post-MVP)
- SQLCipher encryption (if regulatory audit requires database-level encryption)
- PostgreSQL migration (if user base exceeds SQLite comfort zone, 5,000+ users)
- CI/CD pipeline hardening (GitHub Actions → automated deploy)

### Implementation Handoff

**AI Agent Guidelines:**
- Follow all architectural decisions exactly as documented
- Use implementation patterns consistently across all components
- Respect project structure and boundaries
- Refer to this document for all architectural questions
- Follow Rive 0.14.x integration rules — no exceptions
- Run pre-commit checks (flutter analyze + flutter test / ruff + pytest) before every commit

**First Implementation Priority:**
PoC (Phase 0) — Initialize monorepo, set up Pipecat pipeline on Hetzner VPS, create minimal Flutter app with call button + LiveKit connection. Validate the 4 gates: latency, persona quality, voice quality, STT accuracy.
