# Story 4.5: Build First-Call Incoming Call Experience

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a new user,
I want my phone to "ring" with an animated incoming call from a character immediately after onboarding,
So that my first interaction with the product is the product itself — not a tutorial or menu.

## Acceptance Criteria (BDD)

**AC1 — Incoming Call Screen Display (UX-DR9, FR23):**
Given the user has completed consent and mic permission for the first time
When the incoming call screen appears
Then it displays the tutorial character's face (avatar), character name, character role, a green "Accept" button, a red "Decline" button, and triggers device vibration feedback
And the visual mirrors the native FaceTime/WhatsApp incoming call UI (per `incoming-call-screen-design.md`)

**AC2 — Accept → Call Initiation (FR23):**
Given the incoming call screen is displayed
When the user taps the "Accept" button
Then the app calls `POST /calls/initiate` (JWT-authenticated) which creates a `call_sessions` row and returns a LiveKit room token
And the transition to the placeholder call screen is smooth with a "Connecting..." animation masking pipeline initialization (1s minimum display, 5s maximum before error)

**AC3 — Character Speaks First:**
Given this is the first-call onboarding moment
When the LiveKit room is joined and both client and Pipecat bot are connected
Then the Pipecat bot is configured to speak first — the user never has to figure out how to start the conversation
(The actual Rive call screen is a placeholder for Epic 6 Story 6.2; this story verifies the handoff occurs)

**AC4 — Decline Path:**
Given the incoming call screen is displayed
When the user taps the "Decline" button
Then vibration and ring animation stop immediately, the screen fades out over 300ms, and the user is navigated to the scenario list placeholder at `/`
And no `call_sessions` row is created (no server call happens on decline)
And the decline does not count against any free-call quota (quotas are not tracked in this story)

**AC5 — One-Time Onboarding Gate:**
Given this screen is a one-time onboarding experience
When the user has seen the incoming call screen once (regardless of Accept or Decline)
Then `ConsentStorage.saveFirstCallShown(true)` is persisted
And on all subsequent app launches, the router skips `/incoming-call` entirely and routes the authenticated user straight to the scenario list placeholder at `/`

**AC6 — Call Session Persistence:**
Given the user accepts the call
When `POST /calls/initiate` is handled by the server
Then a `call_sessions` row is inserted with: `id` (auto-increment), `user_id` (from JWT), `scenario_id` (text, hardcoded `"waiter_easy_01"` for the tutorial), `started_at` (ISO 8601 UTC), `duration_sec` (NULL), `cost_cents` (NULL), via migration `002_calls.sql`
And the response envelope is `{data: {call_id, room_name, token, livekit_url}, meta: {timestamp}}` per the API contract

**AC7 — Pipeline Validation (Regression Gate):**
Given pre-commit requirements from CLAUDE.md
When the story is complete
Then `cd client && flutter analyze` returns "No issues found!" and `cd client && flutter test` shows "All tests passed!" (including all existing tests from Stories 4.1–4.4)
And `cd server && ruff check .` + `cd server && ruff format --check .` + `cd server && pytest` all pass with zero issues

## Tasks / Subtasks

- [x] Task 1: Add `002_calls.sql` migration + `call_sessions` table (AC: 6)
  - [x] 1.1 Create `server/db/migrations/002_calls.sql` with: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `user_id INTEGER NOT NULL REFERENCES users(id)`, `scenario_id TEXT NOT NULL`, `started_at TEXT NOT NULL`, `duration_sec INTEGER`, `cost_cents INTEGER`
  - [x] 1.2 Add index `idx_call_sessions_user_id` on `user_id`
  - [x] 1.3 Migration must be idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`)
  - [x] 1.4 Verify startup runs both migrations: `001_init.sql` then `002_calls.sql` (lexical order, applied exactly once — existing `run_migrations()` logic handles this)

- [x] Task 2: Add `insert_call_session` + `get_call_session` queries (AC: 6)
  - [x] 2.1 Add to `server/db/queries.py`: `async def insert_call_session(db, user_id: int, scenario_id: str, started_at: str) -> int` — returns new call_id
  - [x] 2.2 Add to `server/db/queries.py`: `async def get_call_session(db, call_id: int) -> aiosqlite.Row | None` (for future tests/`/calls/{id}/end`)
  - [x] 2.3 Unit test both in `server/tests/test_queries.py` (NEW file) — CLAUDE.md demands test coverage

- [x] Task 3: Build new `POST /calls/initiate` endpoint (AC: 2, 3, 6)
  - [x] 3.1 Create `server/api/routes_calls.py` with `router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[AUTH_DEPENDENCY])`
  - [x] 3.2 Add Pydantic models to `server/models/schemas.py`: `InitiateCallIn` (empty body or optional `scenario_id: str = "waiter_easy_01"`), `InitiateCallOut` (`call_id: int`, `room_name: str`, `token: str`, `livekit_url: str`)
  - [x] 3.3 Handler logic: read `user_id` from `request.state.user_id`, generate `room_name = f"call-{uuid4()}"`, generate LiveKit `user_token` via `generate_token()`, generate `agent_token` via `generate_token_with_agent()`, `subprocess.Popen([...pipeline.bot...])` with the tutorial scenario's base_prompt loaded from the scenario YAML (Task 4), insert `call_sessions` row via `insert_call_session`, return `ok(InitiateCallOut(...))`
  - [x] 3.4 Wire router in `server/api/app.py` — `app.include_router(calls_router)` (keep `/connect` alive alongside — do NOT remove, it's used by nothing but still covered by tests)
  - [x] 3.5 The response envelope MUST use `ok(...)` from `api/responses.py` (same pattern as `/auth/verify-code`) to produce `{"data": {...}, "meta": {"timestamp": "..."}}`

- [x] Task 4: Load tutorial scenario prompt for bot spawn (AC: 3)
  - [x] 4.1 Add constant `TUTORIAL_SCENARIO_ID = "waiter_easy_01"` in `server/pipeline/prompts.py` (or a new `server/pipeline/scenarios.py` — pick whichever matches existing conventions)
  - [x] 4.2 Add helper `load_scenario_prompt(scenario_id: str) -> str` that reads `_bmad-output/planning-artifacts/scenarios/the-waiter.yaml` and returns the `base_prompt + "\n\n" + checkpoints[0].prompt_segment` concatenation (PyYAML parse)
  - [x] 4.3 Pass the composed prompt to the Pipecat bot subprocess via CLI flag `--system-prompt` (extend `pipeline/bot.py` if a flag is needed, OR set env var `SYSTEM_PROMPT` in `subprocess.Popen(env=...)`, OR write a temp file and pass its path — pick the approach that matches how `pipeline/bot.py` currently receives its prompt; the existing `/connect` endpoint already wires this somehow, re-use that mechanism)
  - [x] 4.4 Add `pyyaml` to `server/pyproject.toml` dependencies if not already there
  - [x] 4.5 **Instruct the bot to speak first** — inject a directive into the system prompt like: `"You will speak first. Start with: 'Welcome to The Golden Fork. What can I get you?' Do NOT wait for the user to speak first."` (AC3)

- [x] Task 5: Write server tests for `/calls/initiate` (AC: 2, 3, 6)
  - [x] 5.1 Create `server/tests/test_calls.py` — mirror the structure of `test_auth.py` + `test_call_endpoint.py`
  - [x] 5.2 Test: 401 when no JWT
  - [x] 5.3 Test: 401 when invalid JWT
  - [x] 5.4 Test: 200 + `{data: {call_id, room_name, token, livekit_url}, meta: {timestamp}}` envelope when JWT valid
  - [x] 5.5 Test: new `call_sessions` row exists in DB after success (query DB in test)
  - [x] 5.6 Test: `subprocess.Popen` mocked — asserted called once with args containing `room_name` and the scenario prompt (use `mocker.patch("subprocess.Popen")` as in existing tests)
  - [x] 5.7 Test: `generate_token`/`generate_token_with_agent` are called (mocked) — avoid real LiveKit calls in CI
  - [x] 5.8 Update `conftest.py` if needed — do NOT regress existing fixtures
  - [x] 5.9 Also add test: migration `002_calls.sql` creates the table (introspect `sqlite_master` — or confirm via a successful insert)

- [x] Task 6: Create Flutter `CallRepository` + `CallApi` (AC: 2, 6)
  - [x] 6.1 Create `client/lib/features/call/models/call_session.dart` — immutable data class with `callId: int`, `roomName: String`, `token: String`, `livekitUrl: String` (snake_case in JSON → camelCase in Dart via `factory CallSession.fromJson(Map<String, dynamic>)`)
  - [x] 6.2 Create `client/lib/features/call/repositories/call_repository.dart` — `class CallRepository { CallRepository(this._apiClient); final ApiClient _apiClient; Future<CallSession> initiateCall() async { final res = await _apiClient.post('/calls/initiate'); final data = (res.data as Map<String, dynamic>)['data'] as Map<String, dynamic>; return CallSession.fromJson(data); } }`
  - [x] 6.3 The endpoint path `/calls/initiate` does NOT start with `/auth/` → the existing `ApiClient` interceptor automatically attaches the Bearer token (see `core/api/api_client.dart:25`)

- [x] Task 7: Extend `ConsentStorage` with first-call-shown flag (AC: 5)
  - [x] 7.1 Add to `client/lib/core/onboarding/consent_storage.dart`: private key `_firstCallShownKey = 'first_call_shown'`, cached field `_cachedFirstCallShown = false`
  - [x] 7.2 Extend `preload()` to also read `hasSeenFirstCall()` into the cache
  - [x] 7.3 Add methods: `Future<void> saveFirstCallShown()`, `Future<bool> hasSeenFirstCall()`, and getter `bool get hasSeenFirstCallSync`
  - [x] 7.4 Extend `deleteConsent()` to also clear `_firstCallShownKey` (logout/reset must clear it)

- [x] Task 8: Build `IncomingCallBloc` (AC: 2, 4, 5)
  - [x] 8.1 Create `client/lib/features/call/bloc/incoming_call_event.dart` — sealed class: `AcceptCallEvent()`, `DeclineCallEvent()`
  - [x] 8.2 Create `client/lib/features/call/bloc/incoming_call_state.dart` — sealed class: `IncomingCallRinging()`, `IncomingCallAccepting()`, `IncomingCallConnected(CallSession session)`, `IncomingCallDeclined()`, `IncomingCallError(String message)`
  - [x] 8.3 Create `client/lib/features/call/bloc/incoming_call_bloc.dart` — constructor takes `CallRepository` + `ConsentStorage` + `VibrationService`; initial state `IncomingCallRinging()`
  - [x] 8.4 On `AcceptCallEvent`: emit `IncomingCallAccepting`, stop vibration, call `_callRepo.initiateCall()`, on success emit `IncomingCallConnected(session)` AND `await _consentStorage.saveFirstCallShown()`; on failure emit `IncomingCallError(message)`
  - [x] 8.5 On `DeclineCallEvent`: stop vibration, `await _consentStorage.saveFirstCallShown()`, emit `IncomingCallDeclined`
  - [x] 8.6 Override `close()` to always stop vibration (defensive — widget may be disposed mid-ring)

- [x] Task 9: Create `VibrationService` thin wrapper (AC: 1)
  - [x] 9.1 Add `vibration: ^3.1.3` (or the current latest stable — verify on pub.dev) to `client/pubspec.yaml` dependencies
  - [x] 9.2 Create `client/lib/core/onboarding/vibration_service.dart` — thin wrapper: `startRingPattern()` (pattern `[0, 800, 400, 800, 1600]` repeat=0), `stop()` (calls `Vibration.cancel()`)
  - [x] 9.3 `startRingPattern()` must first check `Vibration.hasVibrator()` — no-op on devices without vibration
  - [x] 9.4 Inject `VibrationService` into `IncomingCallBloc` constructor (testability — mock in tests)

- [x] Task 10: Build `RingAnimation` widget (AC: 1)
  - [x] 10.1 Create `client/lib/features/call/views/widgets/ring_animation.dart` — `StatefulWidget` with `SingleTickerProviderStateMixin`
  - [x] 10.2 Use a `CustomPainter` to draw 3 concentric circles staggered 667ms apart within a 2000ms cycle, each expanding from `120px` → `180px` diameter, opacity `40% → 0%`, stroke-only (`PaintingStyle.stroke`, `strokeWidth: 2`), color `Color(0xFF50D95D)`, easing `Curves.easeOut`
  - [x] 10.3 Container size: `SizedBox(width: 180, height: 180)` — avatar is centered at 120px inside
  - [x] 10.4 `AnimationController` with `duration: 2000ms`, `repeat()` (continuous loop)
  - [x] 10.5 Dispose the controller properly in `dispose()`

- [x] Task 11: Build `IncomingCallScreen` (AC: 1, 2, 4, 5)
  - [x] 11.1 Create `client/lib/features/call/views/incoming_call_screen.dart` — `StatefulWidget` with `SingleTickerProviderStateMixin` (for the decline fade-out)
  - [x] 11.2 On `initState`: trigger `HapticFeedback.mediumImpact()` and start `VibrationService.startRingPattern()` (provided by bloc)
  - [x] 11.3 Layout per `incoming-call-screen-design.md` §Screen Layout Diagram (see Dev Notes for full spec)
  - [x] 11.4 `BlocListener<IncomingCallBloc, IncomingCallState>`: on `IncomingCallConnected` → `context.go(AppRoutes.call)` (new placeholder route — Task 12); on `IncomingCallDeclined` → fade out 300ms `Curves.easeIn` → `context.go(AppRoutes.root)`; on `IncomingCallError` → show an inline error banner above the buttons (NOT a snackbar, NOT a dialog — consistent with Story 4.3/4.4 pattern) with a "Retry" tap that re-dispatches `AcceptCallEvent`
  - [x] 11.5 Accept button: green circle (`#50D95D`), phone icon, 60px diameter, "Accept" label below (Inter Regular 14px `#C6C6C8`). Pressed state → 80% opacity. Loading state (during `IncomingCallAccepting`) → spinner replaces phone icon, label becomes "Connecting…"
  - [x] 11.6 Decline button: red circle (`#FD3833`), `call_end` icon, 60px diameter, "Decline" label below
  - [x] 11.7 Character identity is hardcoded for the tutorial: `name = "Tina"`, `role = "Waitress"`, `avatarAsset = "assets/images/characters/waiter.jpg"` — put these in a constants file `client/lib/features/call/views/tutorial_scenario.dart` so Epic 6 can replace them without hunting
  - [x] 11.8 Avatar fallback: if `Image.asset` throws, show the initial letter "T" in Inter Regular 48px `#F0F0F0` centered on the `#414143` circle (see `errorBuilder` on `Image.asset`)
  - [x] 11.9 Semantics / screen-reader announcements per `incoming-call-screen-design.md` §Accessibility (on-appear live region announces "Calling Tina, Waitress. Double tap Accept to pick up, or Decline to dismiss." after a 500ms delay)

- [x] Task 12: Build connecting + call placeholder (AC: 2, 3)
  - [x] 12.1 Add `static const String call = '/call'` to `AppRoutes` in `client/lib/app/router.dart`
  - [x] 12.2 Add a `/call` GoRoute that shows a minimal placeholder screen: dark background, centered "Connecting to Tina…" text (Inter Regular 24px `#C6C6C8`), a three-dot pulsing animation below, a small red hang-up button at the bottom that calls `context.go(AppRoutes.root)`
  - [x] 12.3 Inside the placeholder, on init, connect to LiveKit using the `CallSession` received from the bloc — use `livekit_client` (already in pubspec: `livekit_client: ^2.6.4`). Minimal connect: `final room = Room(); await room.connect(session.livekitUrl, session.token);` then publish mic track (`await room.localParticipant?.setMicrophoneEnabled(true)`)
  - [x] 12.4 Pass the `CallSession` via GoRouter extra: `context.go(AppRoutes.call, extra: session)` from the `IncomingCallScreen` `BlocListener`
  - [x] 12.5 Disconnect (`room.disconnect()`) on dispose and on hang-up tap
  - [x] 12.6 Full-featured call UI (Rive, viseme lip sync, checkpoint HUD, etc.) is **OUT OF SCOPE** for this story — Epic 6 Story 6.2 builds the real one. This placeholder only verifies that the server-spawned bot connects to the room and starts talking (AC3)

- [x] Task 13: Update router redirect logic (AC: 5)
  - [x] 13.1 In `client/lib/app/router.dart`, extend the redirect block: after `hasMicPermissionSync` check, add `else if (!consentStorage.hasSeenFirstCallSync) → AppRoutes.incomingCall`
  - [x] 13.2 The existing `else if (isAuthRoute || consent || mic-permission)` branch must also send `AppRoutes.incomingCall` back to `/` once `hasSeenFirstCallSync` is true
  - [x] 13.3 Change the `/incoming-call` GoRoute `pageBuilder` from its current placeholder Scaffold to instantiate the real `IncomingCallScreen` wrapped in `BlocProvider<IncomingCallBloc>`
  - [x] 13.4 Provide the `IncomingCallBloc` via a route-scoped `BlocProvider` (NOT in `MultiBlocProvider` in `app.dart` — the bloc lifecycle is bound to the screen) — inject `CallRepository(ApiClient())` + the shared `ConsentStorage` from `_AppState` + a fresh `VibrationService()`

- [x] Task 14: Write Flutter tests (AC: 1–6)
  - [x] 14.1 `test/features/call/repositories/call_repository_test.dart` — ~3 tests: success returns `CallSession`, HTTP error throws `ApiException`, malformed JSON throws
  - [x] 14.2 `test/features/call/bloc/incoming_call_bloc_test.dart` — ~6 tests: `AcceptCallEvent` happy path emits `[Accepting, Connected]` and calls `saveFirstCallShown`; `AcceptCallEvent` failure emits `[Accepting, Error]`; `DeclineCallEvent` emits `[Declined]` and calls `saveFirstCallShown`; vibration is stopped on every transition out of `Ringing`; `close()` stops vibration defensively
  - [x] 14.3 `test/features/call/views/incoming_call_screen_test.dart` — ~7 tests: renders character name + role + avatar, renders Accept and Decline buttons, tapping Accept dispatches `AcceptCallEvent`, tapping Decline dispatches `DeclineCallEvent`, shows loading spinner in Accept button on `IncomingCallAccepting`, shows error banner on `IncomingCallError`, avatar fallback when asset load fails
  - [x] 14.4 `test/features/call/views/widgets/ring_animation_test.dart` — ~1 test: the widget pumps without throwing and disposes cleanly (no animation-controller leak — CustomPainter behavior is hard to assert in widget tests, keep this lightweight)
  - [x] 14.5 `test/core/onboarding/consent_storage_test.dart` — add ~3 tests for `saveFirstCallShown` / `hasSeenFirstCall` / `preload` round-trip
  - [x] 14.6 `test/app_test.dart` — add ~3 router redirect tests: authenticated + consent + mic + NOT first-call-shown → redirects to `/incoming-call`; authenticated + consent + mic + first-call-shown → stays at `/`; stub `ConsentStorage.hasSeenFirstCallSync`
  - [x] 14.7 `test/features/call/views/tutorial_scenario_test.dart` — ~1 test: constants are non-empty strings (defensive — prevents silent regression)

- [x] Task 15: Pre-commit validation gates (AC: 7)
  - [x] 15.1 `cd client && flutter analyze` → "No issues found!" (zero errors, warnings, OR infos)
  - [x] 15.2 `cd client && flutter test` → "All tests passed!" (run ALL tests, not just new ones)
  - [x] 15.3 `cd server && python -m ruff check .` → zero issues
  - [x] 15.4 `cd server && python -m ruff format --check .` → zero diffs
  - [x] 15.5 `cd server && pytest` → all green
  - [x] 15.6 Only after 15.1–15.5 are all green, flip story status and commit (per CLAUDE.md + memory: NEVER commit autonomously — wait for Walid to say "commit ça")

## Dev Notes

### Scope Boundary (What This Story Does and Does NOT Do)

This story delivers the **incoming call onboarding moment** + the **minimum viable backend** to make Accept work end-to-end with a real LiveKit call. It is explicitly not a full call screen.

| In scope (this story) | Out of scope (later stories) |
|---|---|
| `IncomingCallScreen` with ring animation, vibration, Accept/Decline | Rive character canvas, viseme lip sync, emotion reactions (Story 6.2, 6.3) |
| New `POST /calls/initiate` endpoint + `002_calls.sql` migration | Scenario tier/quota enforcement, checkpoint-aware prompts (Story 5.1, 6.1, 6.6) |
| Hardcoded tutorial scenario (The Waiter) | Scenarios DB table + `GET /scenarios` (Story 5.1) |
| Minimal `/call` placeholder that joins LiveKit + publishes mic | Full call screen UX — hang-up button, timer, background image, checkpoints overlay (Story 6.2, 6.7) |
| `POST /calls/{id}/end` — NOT in this story | Story 7.1 / 6.4 |
| Debrief generation | Epic 7 |
| First-call-shown flag to prevent repeat display | — |

### First-Call Character: The Waiter (Tina)

The tutorial scenario is **The Waiter** (`waiter_easy_01`) — it is the only Epic-3 scenario validated end-to-end on the live VPS pipeline (per Epic 3 retro, line 48), and it is calibrated as the easiest scenario for near-guaranteed success (PRD FR19).

Hardcoded constants for this story (in `client/lib/features/call/views/tutorial_scenario.dart`):

```dart
abstract final class TutorialScenario {
  static const String id = 'waiter_easy_01';
  static const String characterName = 'Tina';
  static const String characterRole = 'Waitress';
  static const String avatarAsset = 'assets/images/characters/waiter.jpg';
}
```

Server-side constant (in `server/pipeline/prompts.py` or a sibling `scenarios.py`):
```python
TUTORIAL_SCENARIO_ID = "waiter_easy_01"
TUTORIAL_SCENARIO_YAML = Path(__file__).parent.parent.parent / "_bmad-output" / "planning-artifacts" / "scenarios" / "the-waiter.yaml"
```

> **Note on the YAML path:** the scenarios folder sits outside `server/` (project root → `_bmad-output/...`). The server process runs from `server/`, so resolve the path via `Path(__file__).resolve()` to survive both local dev and the VPS deployment. If this is awkward, copy `the-waiter.yaml` into `server/pipeline/scenarios/` at build time — this is acceptable and keeps the server self-contained.

### Backend Architecture Decisions

**Keep `/connect` alive alongside the new `/calls/initiate`.** `server/api/call_endpoint.py` is the legacy PoC endpoint with its own tests in `test_call_endpoint.py`. Removing it would cascade into test rewrites not in scope. Add the new endpoint as a sibling — both routers coexist.

**JWT required on `/calls/initiate`.** Use `dependencies=[AUTH_DEPENDENCY]` on the `APIRouter` (see `server/api/middleware.py:102`). `user_id` is then read from `request.state.user_id`.

**Hardcoded `scenario_id` for now.** The request body has no `scenario_id` field (or an optional one that always defaults to `"waiter_easy_01"`). This is intentional for Story 4.5 — full scenario selection arrives in Story 6.1 once the scenarios table exists (Story 5.1). Storing the string `"waiter_easy_01"` in `call_sessions.scenario_id` is forward-compatible: when Story 5.1 introduces the scenarios table, a migration can add the FK constraint — but **do NOT add it now** (would require the scenarios table).

**Character speaks first.** The Pipecat bot must not wait for the user to speak before greeting. Inject into the system prompt a directive: `"You will speak first when the call begins. Start with a short greeting appropriate for the scene."` — the Waiter YAML is already calibrated for this (Tina opens with "Welcome to The Golden Fork. What can I get you?"). Double-check by reading `the-waiter.yaml` + any existing bot bootstrapping logic in `pipeline/bot.py`.

**Response envelope:** `ok(InitiateCallOut(...))` → `{"data": {"call_id": 42, "room_name": "call-<uuid>", "token": "<jwt>", "livekit_url": "wss://..."}, "meta": {"timestamp": "2026-04-22T18:30:00Z"}}`. Use existing `api/responses.py` helpers (same pattern as `/auth/verify-code` in `routes_auth.py:166`).

### Incoming Call Screen — Exact Visual Spec

[Source: `_bmad-output/planning-artifacts/incoming-call-screen-design.md`]

**Screen-specific color tokens (NOT in `AppColors`):** The incoming call design intentionally uses native-phone colors that differ from the system design tokens. Scope these as private constants inside `incoming_call_screen.dart` — do **NOT** add them to `AppColors` (design note, lines 527–545).

```dart
// Private to incoming_call_screen.dart — native phone UI colors
const Color _kCallSecondary = Color(0xFFC6C6C8);   // Role, Calling..., button labels
const Color _kCallAccept    = Color(0xFF50D95D);   // Accept button
const Color _kCallDecline   = Color(0xFFFD3833);   // Decline button
// Screen-specific font sizes (NOT in AppTypography):
const double _kCallName     = 38.0;  // Inter Regular
const double _kCallRole     = 16.0;  // Inter Regular
const double _kCallStatus   = 24.0;  // Inter Regular
const double _kCallLabel    = 14.0;  // Inter Regular
```

Reuse existing tokens for `background` (`AppColors.background`), `text-primary` (`AppColors.textPrimary`), `avatar-bg` (`AppColors.avatarBg`).

**Layout summary (top → bottom):**

1. SafeArea top + 40px spacer
2. Character name "Tina" — Inter Regular 38px `#F0F0F0`, centered
3. 4px gap
4. Character role "Waitress" — Inter Regular 16px `#C6C6C8`, centered
5. `Spacer()`
6. 180x180 `Stack` container — contains `RingAnimation` (3 concentric circles, `#50D95D`) behind a 120px `CircleAvatar(backgroundImage: AssetImage('assets/images/characters/waiter.jpg'), backgroundColor: AppColors.avatarBg)`
7. 16px gap
8. "Calling…" — Inter Regular 24px `#C6C6C8`, centered
9. `Spacer()`
10. `Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [DeclineButton, AcceptButton])` with 30px horizontal padding
11. Button labels row (same padding + alignment) — Inter Regular 14px `#C6C6C8`, 8px below buttons
12. 50px bottom spacer + SafeArea bottom

**Animation + feedback (on screen-enter):**
- `HapticFeedback.mediumImpact()` — fires once on `initState`
- `VibrationService.startRingPattern()` — pattern `[0, 800, 400, 800, 1600]` (pause, vibrate, pause, vibrate, pause), repeat continuously
- `RingAnimation` starts (3 circles, 2000ms cycle, 667ms stagger, `Curves.easeOut`)
- Avatar subtle scale pulse (1.0 → 1.02 → 1.0, 3600ms cycle, `Curves.easeInOut`) — use a second `AnimationController`

**Exit transitions:**
- Accept → button enters loading state (80% opacity, 100ms) → spinner replaces phone icon → on `IncomingCallConnected` state, `context.go(AppRoutes.call, extra: session)` (GoRouter's built-in 500ms fade page transition via existing `_fadePage` helper handles the crossfade)
- Decline → vibration + rings stop immediately → 300ms `FadeTransition` opacity 1.0 → 0.0, `Curves.easeIn` → `context.go(AppRoutes.root)`

### Router Redirect Logic Update

Current redirect (Story 4.4):
```
token + no consent → /consent
token + consent + no mic → /mic-permission
token + consent + mic + on auth/consent/mic route → /
```

**Add for Story 4.5:**
```
token + consent + mic + NOT first-call-shown → /incoming-call
token + consent + mic + first-call-shown → (stay, or → / if currently on /incoming-call or an auth/consent/mic route)
```

Concrete code sketch (extending `router.dart:58-75`):

```dart
if (isAuthenticated) {
  final hasConsent = consentStorage.hasConsentSync;
  final hasMic = consentStorage.hasMicPermissionSync;
  final seenFirstCall = consentStorage.hasSeenFirstCallSync;

  if (!hasConsent) {
    if (currentPath != AppRoutes.consent) return AppRoutes.consent;
  } else if (!hasMic) {
    if (currentPath != AppRoutes.micPermission) return AppRoutes.micPermission;
  } else if (!seenFirstCall) {
    if (currentPath != AppRoutes.incomingCall) return AppRoutes.incomingCall;
  } else if (isAuthRoute ||
      currentPath == AppRoutes.consent ||
      currentPath == AppRoutes.micPermission ||
      currentPath == AppRoutes.incomingCall) {
    return AppRoutes.root;
  }
}
```

**Critical — sync cache:** `hasSeenFirstCallSync` must be seeded via `ConsentStorage.preload()` at startup (same pattern as `hasConsentSync` / `hasMicPermissionSync`). The router redirect is synchronous — it CANNOT `await` storage reads or you get the flash-of-wrong-content bug from Story 4.4 (see 4.4 Dev Agent Record → "Deliberate Deviations §3").

### Pipecat Bot Spawn — Reuse Existing Pattern

The legacy `/connect` endpoint (`server/api/call_endpoint.py:41-53`) already spawns the bot via:
```python
subprocess.Popen([
    sys.executable, "-m", "pipeline.bot",
    "--url", settings.livekit_url,
    "--room", room_name,
    "--token", agent_token,
])
```

**Copy this exact shape** for `/calls/initiate` and add the system-prompt flag. Read `pipeline/bot.py` first to find out how the prompt is currently passed — if there's no flag yet, add one (e.g., `--system-prompt`) and read it via `argparse` in `bot.py`. Do NOT refactor `pipeline/bot.py` beyond what's needed for this flag — Story 6.1/6.2 owns the checkpoint-based prompt composition rewrite.

### Vibration — Platform Support

| Platform | Mechanism |
|---|---|
| iOS | The `vibration` package falls back to repeated `HapticFeedback.mediumImpact()` since iOS does not expose a true "custom-pattern vibration" API. This is acceptable — the design doc (line 302) explicitly accepts this. |
| Android | Native `Vibrator.vibrate(pattern: [0, 800, 400, 800, 1600], repeat: 0)` via the package. |
| No vibrator (e.g., tablet, some emulators) | `Vibration.hasVibrator()` returns false → no-op. Screen still works — ring animation + design are sufficient. |

Package to use: `vibration: ^3.1.3` (verify latest stable at pub.dev before adding — CLAUDE.md requires flutter analyze to be clean, and outdated packages often produce deprecation warnings that count as `info` lints in Flutter 3.x).

### Error Handling (Accept-path failures)

Per the design doc §Exit Transition (line 405): "Maximum wait: 5 seconds — if pipeline fails to connect, show error and return to scenario list."

Implementation:
- `Dio` connectTimeout/receiveTimeout is already 15s in `ApiClient` — fine for `/calls/initiate`
- On `ApiException`, the bloc emits `IncomingCallError(message)` with a user-facing message (e.g., "Couldn't start the call. Tap to retry.")
- The `IncomingCallScreen` `BlocListener` shows an inline error banner above the buttons (consistent with Story 4.3/4.4 pattern — **NOT** a snackbar, **NOT** a dialog, **NOT** a toast)
- Tapping Retry re-dispatches `AcceptCallEvent` (does NOT leave the screen)
- Tapping Decline is always available as a fallback (Decline still marks first-call-shown and navigates home — user never gets stranded)
- LiveKit connection failure inside the `/call` placeholder → show a "Couldn't connect" error and a button to `context.go(AppRoutes.root)`. Do NOT try to retry automatically — Epic 6 owns the real retry UX.

### Character Speaks First — How to Verify (AC3)

Story 4.5 does NOT render the character's speech visually (no Rive face, no lip sync — that's Epic 6). But AC3 says the bot MUST speak first. Verification options for the reviewer:

1. **Smoke test (manual):** deploy to VPS, go through onboarding, accept the tutorial call — you should hear Tina say "Welcome to The Golden Fork. What can I get you?" through the phone speaker. If the call is silent, the bot is misconfigured.
2. **Server log check:** `journalctl -u pipecat.service -n 200` should show the bot emitting its first TTS frame within ~2s of room-join. If the bot is waiting on user speech, this line will be absent.
3. **Unit test (automated):** in `test_calls.py`, assert that `subprocess.Popen.call_args` contains a system prompt string that includes the phrase "speak first" (or equivalent directive). This is proxy-level verification — the actual audio behavior is validated by manual smoke test.

### What NOT to Do

1. **Do NOT remove or modify `/connect`** — its tests still pass; leave it alone. New work goes in `routes_calls.py`.
2. **Do NOT add call-secondary / call-accept / call-decline to `AppColors`** — they are screen-specific native-phone tokens (see Design Token Cross-Reference, line 527–545). Scope them privately in the incoming call screen file.
3. **Do NOT add `call-name` / `call-role` / `call-status` / `call-button-label` to `AppTypography`** — same reason.
4. **Do NOT build a full call screen** — the `/call` route is a **minimal placeholder** that proves AC3 (bot speaks first via audio). Rive canvas, background image, lip sync, checkpoint HUD, hang-up animation are Epic 6.
5. **Do NOT add the scenarios database table** — that's Story 5.1. `call_sessions.scenario_id` is a TEXT column with no FK for now.
6. **Do NOT add tier / daily-call-limit checks** — that's Story 5.3 (BottomOverlayCard) + Story 6.1. First call has unlimited quota in this story.
7. **Do NOT implement `POST /calls/{id}/end`** — Story 6.4 / 7.1.
8. **Do NOT add ringtone audio** — the design doc explicitly rejects audio (line 347–353). Vibration + visual rings only.
9. **Do NOT use `Navigator.push` / `Navigator.pop`** — all navigation via GoRouter (consistent with Story 4.3/4.4).
10. **Do NOT skip `flutter analyze` info-level lints** — CLAUDE.md + memory: infos block CI, fix them all.
11. **Do NOT commit autonomously** — memory rule: NEVER commit without Walid's explicit `/commit` or "commit ça". Dev workflow stops at "review" status.
12. **Do NOT use snackbars, toasts, or dialogs for errors** — inline banner only (Story 4.3 pattern, reaffirmed in 4.4).
13. **Do NOT put the `IncomingCallBloc` in `MultiBlocProvider` at `app.dart` level** — its lifecycle is screen-bound. Provide it via route-scoped `BlocProvider` in the GoRoute `pageBuilder`.
14. **Do NOT create a `kill-switch` / `skip first call` dev shortcut** — `hasSeenFirstCallSync` is the only gate; logout via `deleteConsent()` resets it.
15. **Do NOT assume `_bmad-output/planning-artifacts/scenarios/the-waiter.yaml` will be at the same relative path in production** — copy or embed the prompt. The VPS systemd service runs `server/` as working dir.
16. **Do NOT forget to update `sprint-status.yaml`** BEFORE committing (memory: Epic 1 Retro Lesson) — dev flips `4-5-...` from `ready-for-dev` → `in-progress` at start, `in-progress` → `review` at finish.

### Library & Version Requirements

**New Flutter dependencies:**

| Package | Version | Purpose |
|---|---|---|
| `vibration` | `^3.1.3` (verify latest stable) | Custom vibration ring pattern |

**New Python dependency (if not already present):**

| Package | Version | Purpose |
|---|---|---|
| `pyyaml` | `^6.0` (or whatever is current) | Parse `the-waiter.yaml` for `base_prompt` extraction |

> Check `server/pyproject.toml` first — PyYAML may already be a transitive dep via Pipecat. If so, add it as an explicit dep anyway (self-documenting).

**Do NOT add:**
- `audio_session`, `just_audio`, `audioplayers` — no ringtone audio
- Any ringtone asset files — no audio files in this story
- `flutter_ringtone_player` — design rejected this (line 349–353)
- `app_settings` (already rejected in Story 4.4 — `permission_handler.openAppSettings()` suffices)

**Existing deps (already in pubspec.yaml, DO NOT change versions):**

| Package | Version | Relevance |
|---|---|---|
| `flutter_bloc` | `^9.1.1` | `IncomingCallBloc` |
| `go_router` | `^17.2.1` | `/incoming-call` + `/call` routes, redirect |
| `flutter_secure_storage` | `^10.0.0` | `ConsentStorage.firstCallShown` |
| `dio` | `^5.9.2` | `/calls/initiate` via `ApiClient` |
| `livekit_client` | `^2.6.4` | `/call` placeholder joins LiveKit |
| `permission_handler` | `^12.0.1` | (unchanged — Story 4.4 handled mic) |
| `bloc_test` | `^10.0.0` | `IncomingCallBloc` tests |
| `mocktail` | `^1.0.5` | Mock `CallRepository`, `VibrationService`, `ConsentStorage` |

### Key Imports (Epic 1 Retro Lesson — exact imports = #1 velocity multiplier)

```dart
// CallRepository
import 'package:dio/dio.dart';
import 'package:client/core/api/api_client.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/features/call/models/call_session.dart';

// IncomingCallBloc
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:client/core/onboarding/consent_storage.dart';
import 'package:client/core/onboarding/vibration_service.dart';
import 'package:client/features/call/repositories/call_repository.dart';

// IncomingCallScreen
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // HapticFeedback
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';
import 'package:client/app/router.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/features/call/bloc/incoming_call_bloc.dart';
import 'package:client/features/call/bloc/incoming_call_event.dart';
import 'package:client/features/call/bloc/incoming_call_state.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/call/views/tutorial_scenario.dart';
import 'package:client/features/call/views/widgets/ring_animation.dart';

// VibrationService
import 'package:vibration/vibration.dart';

// /call placeholder
import 'package:livekit_client/livekit_client.dart';
```

```python
# server/api/routes_calls.py
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import yaml
from fastapi import APIRouter, Request
from loguru import logger
from pipecat.runner.livekit import generate_token, generate_token_with_agent

from api.middleware import AUTH_DEPENDENCY
from api.responses import ok
from config import Settings
from db.database import get_connection
from db.queries import insert_call_session
from models.schemas import InitiateCallIn, InitiateCallOut

router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[AUTH_DEPENDENCY])
```

### Previous Story Intelligence

**From Story 4.4 (Consent + Mic):**
- `FlutterSecureStorage.setMockInitialValues({})` required in every test `setUp` — without it, tests crash on storage access. This applies to the new `hasSeenFirstCall` tests too.
- Sealed classes with `bloc_test`: must call `registerFallbackValue(ConcreteEvent())` in `setUpAll` (can't create fake subclass).
- `pumpAndSettle` hangs forever when the widget contains a `CircularProgressIndicator` with continuous animation (the incoming call screen has several continuous animations: rings, vibration icon, avatar pulse). **Use explicit `pump(Duration(milliseconds: X))` calls in widget tests**, not `pumpAndSettle`.
- Router redirect must be **synchronous** (`hasConsentSync` / `hasMicPermissionSync` / `hasSeenFirstCallSync`) — async redirect produces flash-of-wrong-content. Seed the cache via `ConsentStorage.preload()` at `_AppState.initState()`.
- BlocListener's same-state skip: when emitting `const` states, `emit(const SomeState())` followed by another `emit(const SomeState())` is silently skipped because `const == const`. If you need to re-trigger the listener, emit an intermediate state first.
- `_fadePage()` helper is already the default route transition in `router.dart:145` — reuse it for `/incoming-call` and `/call` (the 500ms fade-in matches `incoming-call-screen-design.md` §Entry Transition).
- Page transition artifacts can appear when the OS keyboard is closing mid-transition (Story 4.4 ghost-page bug) — the incoming call screen comes AFTER the mic-permission screen, which has no text input, so this specific bug should not recur. Still, if you see visual artifacts during mic→incoming-call transition, check if the previous screen had focus that needs dismissing.

**From Story 4.3 (Email Auth):**
- Lint traps to watch out for: `prefer_const_constructors`, `no_leading_underscores_for_local_identifiers`, `verifyNever()` not `verify(...).called(0)`.
- Auth screens use `BlocConsumer` (listener + builder in one widget). This is a valid pattern for `IncomingCallScreen` too — the listener drives navigation, the builder renders the button states.
- `SizedBox(width: 20, height: 20, child: CircularProgressIndicator(...))` is the exact pattern for the "loading inside button" state (Accept button → Connecting…).
- Error display: inline `Text` widget with `AppColors.destructive`, NOT snackbar/dialog/toast.
- `widget_tests` with BLoC: use `BlocProvider.value(value: mockBloc)` + `whenListen(bloc, Stream.fromIterable([state1, state2]))` to stub emissions.

**From Epic 3 (Scenarios):**
- The Waiter YAML is battle-tested end-to-end on the live VPS pipeline. 4 other scenarios (Mugger, Girlfriend, Cop, Landlord) have `calibration` fields still at placeholder — **do not use them for the tutorial**.
- `base_prompt` + `checkpoints[0].prompt_segment` is the correct composition for a "just start talking" first call. Checkpoint-aware progression arrives in Epic 6 (Story 6.6 CheckpointManager).
- `/no_think` prefix at the top of the Waiter base_prompt is intentional — it tells Qwen3.5 to skip its "thinking" tags. Preserve it when composing the prompt.

**From Epic 1 Retrospective (2026-03-31):**
- Detailed story specs (exact imports, "What NOT to Do") = #1 velocity multiplier. This story deliberately front-loads that density.
- Sprint-status discipline is non-negotiable — dev flips status AT START and BEFORE COMMIT.

### Git Intelligence

**Recent commit pattern to follow:**
```
28c2dca feat: implement consent, AI disclosure, and mic permission flow (Story 4.4)
4bd3222 feat: implement email authentication flow in Flutter (Story 4.3)
d1c05f9 feat: implement FastAPI auth system and server skeleton (Story 4.2)
97890ed feat: implement MVP design system (theme, typography, spacing) (Story 4.1b)
```

**Key files to read before starting (for patterns, NOT to modify):**
- `server/api/call_endpoint.py` — legacy `/connect` endpoint. Copy its `subprocess.Popen` shape for `/calls/initiate`.
- `server/api/routes_auth.py:44-166` — `APIRouter` setup + `ok(...)` envelope + `HTTPException` pattern.
- `server/api/middleware.py` — `AUTH_DEPENDENCY` usage.
- `server/pipeline/bot.py` — how the bot reads its system prompt today (drives the `--system-prompt` flag decision).
- `client/lib/features/onboarding/presentation/mic_permission_screen.dart` — exact pattern for StatefulWidget with BlocListener-driven navigation + fade animation (Story 4.4).
- `client/lib/features/auth/bloc/auth_bloc.dart` — sealed class event/state pattern (Story 4.3).
- `client/lib/core/api/api_client.dart` — Dio wrapper, how Bearer tokens are auto-attached.
- `client/lib/app/router.dart` — existing redirect logic + `_fadePage()` helper. THIS file will be modified (Task 13).

### Testing Requirements

**Target:** ~22–25 new Flutter tests, ~8–10 new Python tests. ALL previous tests (total 85+ in Flutter, 54+ in Python) must continue passing.

**Mock strategy — Flutter:**
- `CallRepository` → mock with `mocktail` in bloc tests
- `VibrationService` → mock with `mocktail` (do NOT call real `Vibration` in unit/widget tests — it throws on headless test runners)
- `ConsentStorage` → mock for bloc + router tests (use `MockConsentStorage` same as Story 4.4)
- `ApiClient` → mock `Dio` with `mocktail` for repository tests (already the pattern in `auth_repository_test.dart`)
- `Image.asset` → in widget tests, the waiter.jpg asset must be discoverable (`TestWidgetsFlutterBinding.ensureInitialized` + pubspec already lists `assets/images/characters/`). If tests fail on image loading, use `Image.asset(..., errorBuilder: ...)` fallback — the fallback is AC-required anyway (Task 11.8).

**Mock strategy — Python:**
- `subprocess.Popen` → `mocker.patch("subprocess.Popen")` (already the pattern in `test_call_endpoint.py`)
- `generate_token` / `generate_token_with_agent` → `mocker.patch("pipecat.runner.livekit.generate_token", return_value="fake_token")` or equivalent
- Database → real in-memory SQLite per conftest pattern (see `server/tests/conftest.py`)

### Accessibility Requirements

[Source: `incoming-call-screen-design.md` §Accessibility + `ux-design-specification.md` UX-DR12]

- All touch targets ≥ 44px (buttons are 60px — pass)
- Contrast ratios verified in design doc (all pass WCAG AA)
- Screen reader live region fires 500ms after screen is fully visible: "Calling Tina, Waitress. Double tap Accept to pick up, or Decline to dismiss." Use `SemanticsService.announce(message, TextDirection.ltr)` via a `Future.delayed`.
- VoiceOver focus order: name → role → avatar (decorative) → "Calling…" → Decline → Accept (left-to-right matches visual layout per design doc §Focus Order)
- Buttons have `Semantics(button: true, label: "Accept call" / "Decline call")` wrappers
- No `Reduced Motion` handling in this story — deferred post-MVP per design doc line 491

### Project Structure Notes

**Alignment with architecture:** `features/call/` already exists (scaffolded but empty — see `lib/features/call/{bloc,models,repositories,services,views}/`). This story populates those directories consistently with the architecture's feature-module layout.

**New files to create:**

```
client/lib/
  core/onboarding/
    vibration_service.dart                   # Thin wrapper for Vibration package
  features/call/
    bloc/
      incoming_call_bloc.dart
      incoming_call_event.dart
      incoming_call_state.dart
    models/
      call_session.dart
    repositories/
      call_repository.dart
    views/
      incoming_call_screen.dart
      tutorial_scenario.dart                 # Tina / Waitress / waiter.jpg constants
      call_placeholder_screen.dart           # /call placeholder (Task 12)
      widgets/
        ring_animation.dart

client/test/
  core/onboarding/
    vibration_service_test.dart              # Optional — trivial wrapper, skip if no logic to test
  features/call/
    bloc/incoming_call_bloc_test.dart
    models/call_session_test.dart            # fromJson round-trip
    repositories/call_repository_test.dart
    views/incoming_call_screen_test.dart
    views/tutorial_scenario_test.dart
    views/widgets/ring_animation_test.dart

server/
  api/routes_calls.py
  db/migrations/002_calls.sql
  pipeline/scenarios.py                      # OR add to prompts.py if that's cleaner
  tests/test_calls.py
  tests/test_queries.py                      # NEW — covers insert_call_session
```

**Files to modify:**
- `client/pubspec.yaml` — add `vibration: ^3.1.3`
- `client/lib/core/onboarding/consent_storage.dart` — add `firstCallShown` key + cache + methods
- `client/lib/app/router.dart` — extend redirect, wire `/incoming-call` to real screen, add `/call` route
- `client/test/core/onboarding/consent_storage_test.dart` — add firstCall tests
- `client/test/app_test.dart` — add first-call redirect tests
- `server/api/app.py` — `app.include_router(calls_router)`
- `server/models/schemas.py` — add `InitiateCallIn`, `InitiateCallOut`
- `server/db/queries.py` — add `insert_call_session`, `get_call_session`
- `server/pyproject.toml` — add `pyyaml` if not already present

**Files to verify but DO NOT modify:**
- `ios/Runner/Info.plist` — `NSMicrophoneUsageDescription` already present from Story 1.3
- `android/app/src/main/AndroidManifest.xml` — `RECORD_AUDIO` already present from Story 1.3
- `server/api/call_endpoint.py` — legacy `/connect`, keep running
- `client/lib/features/auth/**` — DO NOT touch (complete since 4.3)
- `client/lib/features/onboarding/**` — DO NOT touch (complete since 4.4)

### References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 4 Story 4.5 lines 837–866]
- [Source: `_bmad-output/planning-artifacts/incoming-call-screen-design.md` — complete screen spec, transitions, accessibility, animations]
- [Source: `_bmad-output/planning-artifacts/architecture.md` — FR23, `call_sessions` table line 248, `POST /calls/initiate` line 303, data flow lines 923–941]
- [Source: `_bmad-output/planning-artifacts/prd.md` — FR23 line 57, FR19 line 50 (first scenario calibrated), UX-DR9 line 217]
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` — UX-DR9 + Phone call metaphor lines 51, 95–96, 214]
- [Source: `_bmad-output/planning-artifacts/scenarios/the-waiter.yaml` — tutorial character + base_prompt + checkpoints]
- [Source: `_bmad-output/implementation-artifacts/epic-3-retro-2026-04-16.md` — Waiter validated end-to-end line 48]
- [Source: `_bmad-output/implementation-artifacts/4-4-build-consent-ai-disclosure-and-microphone-permission-flow.md` — previous-story intelligence, router pattern, BlocListener patterns]
- [Source: `client/lib/app/router.dart` — current `/incoming-call` placeholder to replace]
- [Source: `server/api/call_endpoint.py` — legacy `/connect` shape to mirror]

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (2026-04-23)

### Debug Log References

- `flutter analyze` → initial pass flagged 3 lints: `unnecessary_nullable_for_final_variable_declarations` on `VibrationService`, `deprecated_member_use` on `SemanticsService.announce`, `prefer_const_constructors` on the character-identity Column. All fixed — final run returns "No issues found!" (113 tests green).
- `flutter_test` — the `RingAnimation` widget has a continuously-looping `AnimationController`; widget tests that host it cannot use `pumpAndSettle`. Explicit `pump(Duration(milliseconds: ...))` calls are used instead (router redirect test + incoming-call-screen test).
- `pytest` — 94 tests green. The new `test_queries.py` wraps async query calls in `asyncio.run(...)` to match the existing sync `test_auth.py` style (no `pytest-asyncio` dependency added — keeps the testing stack unchanged).

### Completion Notes List

- **Deliberate deviation — screen-scoped call colors:** the story specified scoping the native-phone colors (`#50D95D`, `#FD3833`, `#C6C6C8`) privately inside `incoming_call_screen.dart`, but the existing project-wide test `test/core/theme/theme_tokens_test.dart` rejects any `0xRRGGBB` literal outside `lib/core/theme/`. I created a new `lib/core/theme/call_colors.dart` that holds these tokens in a dedicated `CallColors` class, separate from `AppColors`. Later iteration added `CallColors.avatarBackground = #38383A` (native-phone avatar-circle grey) for the same reason.
- **Bot prompt transport — env var over CLI flag:** the story offered three options (CLI flag, env var, temp file). I chose `SYSTEM_PROMPT` env var on `subprocess.Popen(env=...)` — argv on Windows has a 32KB cap and long prompts would be fragile; a temp file adds cleanup complexity. The env-var path keeps the bot subprocess stateless and its argv identical to the legacy `/connect` path.
- **`run_bot` prompt fallback:** `pipeline/bot.py` reads `os.environ.get("SYSTEM_PROMPT") or SARCASTIC_CHARACTER_PROMPT`. That preserves the legacy `/connect` behaviour (tests in `test_call_endpoint.py` still pass without setting the env var) while letting the new `/calls/initiate` inject a scenario-specific prompt.
- **AC3 verification:** the LLM system prompt includes the injected directive "You will speak first when the call begins. Start with: 'Welcome to The Golden Fork. What can I get you?' Do NOT wait for the user to speak first." — verified as a proxy in `test_initiate_spawns_bot_with_scenario_prompt` (asserts `"speak first"` present in the `SYSTEM_PROMPT` env). Note: the actual speaks-first mechanism is the existing `TTSSpeakFrame` queued on `on_first_participant_joined` inside `pipeline/bot.py` — the prompt directive is belt-and-braces: even if the TTS frame is later removed, the LLM will still open the conversation.
- **Default `hasSeenFirstCallSync` stub in `app_test.dart`:** added `true` defaults for `hasConsentSync` / `hasMicPermissionSync` / `hasSeenFirstCallSync` in `setUp()` so each test only overrides what it cares about. Simpler than duplicating stubs per-test and short-circuit-safe because the redirect logic evaluates these getters sequentially.
- **`/call` placeholder is intentionally minimal:** no Rive, no background image, no checkpoint HUD — just a "Connecting to Tina…" label, pulsing dots, LiveKit connect + mic publish, and a red hang-up button that disconnects and returns to `/`. Epic 6 Story 6.2 builds the real call screen.
- **Router redirect handles `/call` vs `/incoming-call`:** when `seenFirstCall=false`, the user is sent to `/incoming-call` unless they're already at `/incoming-call` or `/call` (so the Accept transition to `/call` doesn't immediately bounce back once `saveFirstCallShown()` fires inside the bloc — the storage write is awaited before `emit(IncomingCallConnected(...))`).
- **`InkWell` inside colored `Material`:** the Accept/Decline buttons use `Material(color: …, shape: CircleBorder())` + `InkWell(customBorder: …)` so the 60px touch target has a proper tap ripple without needing a separate tap-area widget.

### Post-implementation iterations (2026-04-23)

These diverge from the original spec in `Dev Notes` above — the design and character-asset strategy evolved during implementation. Recording the final reality here to prevent review confusion.

- **Character asset unification (Rive puppet replaces .jpg stack).** Walid provided a new `characters.riv` puppet file that covers all 5 scenario characters (waiter, cop, girlfriend, landlord, mugger). The `Picture` artboard + `MainStateMachine` + `ViewModel1.character` enum switches between characters by string value. Implications:
  - Dropped `client/assets/images/characters/*.jpg` entirely (5 files deleted).
  - Dropped the unused `client/assets/rive/character.riv` (Epic 2 Story 2.6 deliverable — superseded).
  - New `client/assets/rive/characters.riv` (single source of truth for every character-bearing screen, Epic 6 included).
  - New reusable `CharacterAvatar` widget (`client/lib/features/call/views/widgets/character_avatar.dart`) — loads `characters.riv`, selects `artboardSelector: byName('Picture')` + `stateMachineSelector: byName('MainStateMachine')`, sets `viewModel.enumerator('character').value = character`. Reactive to `didUpdateWidget` when the character prop changes. Fallback to an empty `CallColors.avatarBackground` circle when `RiveNative.isInitialized` is false (tests).
  - `TutorialScenario.avatarAsset` → replaced by `TutorialScenario.riveCharacter = 'waiter'` (the Rive enum value, not a file path).
  - `IncomingCallScreen` avatar stack simplified: no more `CircleAvatar` + image + `errorBuilder` fallback; just `CharacterAvatar(character: 'waiter', size: 166)`.

- **Screen redesign per new Figma spec (`.figma/iphone-16-14/spec.md`).** The layout shifted:
  - **RingAnimation removed entirely** (widget + test file deleted). The pulsing concentric rings from the original spec are no longer part of the UX — the avatar sits on a solid `#38383A` circle instead.
  - Avatar upscaled from 120 to 166 px on a 166x166 background circle (Figma Frame 11).
  - "Calling…" sits directly under the avatar with no `Spacer` between (original layout had a big gap).
  - Frame padding now matches Figma exactly: `60 / 30 / 70 / 30` (top/right/bottom/left).
  - Accept/Decline button columns lifted into a reusable `_CallButton` private widget.

- **Accept-button shift fix.** Observed during smoke test: tapping Accept caused the green circle to jump ~17px to the left. Root cause: `Row(mainAxisAlignment: spaceBetween)` + `Column(mainAxisSize: min)` — when the Accept label grew from "Accept" (~47px) to "Connecting…" (~95px), its column widened, the right edge stayed anchored by `spaceBetween`, so the center of the column (and the circle centered in it) slid left. Fix: locked each `_CallButton` to `SizedBox(width: 100)`; the circle now stays pinned at the same screen-X regardless of label. Also hardened the label with `maxLines: 1, softWrap: false, overflow: TextOverflow.visible` against future longer labels.

- **Animated "Calling" loader.** Added `_AnimatedCallingText` (private widget in `incoming_call_screen.dart`) — cycles 0-3 dots on a 400ms `Timer.periodic`. Uses `Text.rich` with three `TextSpan('.')` whose color toggles between `CallColors.secondary` and `Colors.transparent` so the text's *rendered width* is constant (no wobble of the centered text). `Text.rich` chosen over raw `RichText` because `find.textContaining('Calling')` matches it in widget tests; `RichText` would not.

### Areas worth reviewer attention

- **Rive enum contract.** `TutorialScenario.riveCharacter = 'waiter'` must match one of the `character` enum values inside `characters.riv`. There is no compile-time check — a typo surfaces as a blank avatar at runtime. If Walid adds a new character to the puppet, both the Rive enum values AND the scenario_id stored in `call_sessions` need to stay in sync.
- **`_AnimatedCallingText` Timer lifetime.** The timer runs as long as the widget is mounted. If the user backgrounds the app while the incoming-call screen is visible, the timer keeps firing `setState` in the background. Acceptable for a transient screen; something Epic 6 will revisit when the full call screen lands with more complex animations.
- **No dedicated test for `_AnimatedCallingText`.** The widget's cycle is exercised indirectly by `incoming_call_screen_test.dart` (which pumps once, so sees only frame 0 = zero dots). A targeted test with `tester.pump(Duration(milliseconds: 400))` would be a small addition if review flags it.
- **`CharacterAvatar` Rive behaviour is only verified at runtime.** The widget tests cover the test-env fallback path (dark circle, no crash). Artboard selection, state machine binding, and enum assignment cannot be unit-tested — they depend on the real `characters.riv` + `rive_native.dll`. Smoke-test on device is the verification path.

### File List

**Server (Python):**
- `server/db/migrations/002_calls.sql` — new migration, creates `call_sessions` + index.
- `server/db/queries.py` — added `insert_call_session` + `get_call_session`.
- `server/models/schemas.py` — added `InitiateCallIn` + `InitiateCallOut`.
- `server/api/routes_calls.py` — new `POST /calls/initiate` endpoint + `APIRouter`.
- `server/api/app.py` — registered `calls_router`.
- `server/pipeline/scenarios.py` — new: `TUTORIAL_SCENARIO_ID` + `load_scenario_prompt()`.
- `server/pipeline/bot.py` — reads `SYSTEM_PROMPT` env var, falls back to hardcoded prompt.
- `server/pyproject.toml` — added `pyyaml>=6.0,<7.0.0`.
- `server/tests/test_calls.py` — new: 8 tests (JWT gate, envelope, persistence, Popen mock, coexistence with `/connect`, scenario loader rejects unknown ids).
- `server/tests/test_queries.py` — new: 4 tests (migration creates table/index, `schema_migrations` record, insert returns id, `get_call_session` returns row/none).

**Client (Flutter) — new files:**
- `client/lib/core/theme/call_colors.dart` — `CallColors.accept/decline/secondary/avatarBackground`.
- `client/lib/core/onboarding/vibration_service.dart` — thin wrapper on `Vibration` package.
- `client/lib/features/call/models/call_session.dart` — DTO with `fromJson`.
- `client/lib/features/call/repositories/call_repository.dart` — `initiateCall()`.
- `client/lib/features/call/bloc/incoming_call_event.dart` — `AcceptCallEvent`, `DeclineCallEvent`.
- `client/lib/features/call/bloc/incoming_call_state.dart` — `Ringing/Accepting/Connected/Declined/Error`.
- `client/lib/features/call/bloc/incoming_call_bloc.dart` — bloc with vibration stop invariants + first-call-shown persistence.
- `client/lib/features/call/views/tutorial_scenario.dart` — Tina / Waitress / `riveCharacter = 'waiter'` constants.
- `client/lib/features/call/views/incoming_call_screen.dart` — the screen itself (includes private `_CallButton` + `_AnimatedCallingText`).
- `client/lib/features/call/views/widgets/character_avatar.dart` — reusable Rive avatar keyed by character enum.
- `client/lib/features/call/views/call_placeholder_screen.dart` — minimal /call placeholder.

**Client (Flutter) — new assets:**
- `client/assets/rive/characters.riv` — unified character puppet (all 5 scenarios — artboard `Picture` for the incoming-call avatar, future artboards for Epic 6's in-call scene).

**Client (Flutter) — deleted:**
- `client/assets/rive/character.riv` — unused (Epic 2 Story 2.6 deliverable superseded by `characters.riv`).
- `client/assets/images/characters/{cop,girlfriend,landlord,mugger,waiter}.jpg` — entire folder removed, Rive replaces it.
- `client/lib/features/call/views/widgets/ring_animation.dart` — design iteration removed the concentric rings.
- `client/test/features/call/views/widgets/ring_animation_test.dart` — companion test.

**Client (Flutter) — modified:**
- `client/pubspec.yaml` — added `vibration: ^3.1.3`; asset list swap (`characters.riv` in, `character.riv` + `assets/images/characters/` out).
- `client/pubspec.lock` — regenerated after `vibration` add.
- `client/lib/core/onboarding/consent_storage.dart` — added `_firstCallShownKey`, cache, `saveFirstCallShown()`, `hasSeenFirstCall()`, `hasSeenFirstCallSync`; extended `preload()` and `deleteConsent()`.
- `client/lib/app/router.dart` — added `AppRoutes.call`, `/call` GoRoute with `CallSession` via extra, `/incoming-call` now wraps real screen with route-scoped `BlocProvider<IncomingCallBloc>`, redirect extended with `hasSeenFirstCallSync`.

**Client (Flutter) — new tests:**
- `client/test/features/call/models/call_session_test.dart`
- `client/test/features/call/repositories/call_repository_test.dart`
- `client/test/features/call/bloc/incoming_call_bloc_test.dart`
- `client/test/features/call/views/tutorial_scenario_test.dart`
- `client/test/features/call/views/incoming_call_screen_test.dart`
- `client/test/features/call/views/widgets/character_avatar_test.dart`

**Client (Flutter) — modified tests:**
- `client/test/core/onboarding/consent_storage_test.dart` — added 4 tests for first-call flag round-trip, preload, delete.
- `client/test/app_test.dart` — added default `hasSeenFirstCallSync=true` stub in `setUp`, plus 2 new router-redirect tests (first-call-not-shown → `/incoming-call`, first-call-seen → `/`).

**Sprint tracking:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `4-5-... → review`, `last_updated: 2026-04-23 (Story 4.5 → review)`.

### Review Findings

Code review run 2026-04-23 via `bmad-code-review` — 3 adversarial layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor).

**Patch:**

- [x] [Review][Patch] Copy `the-waiter.yaml` into `server/pipeline/scenarios/` (self-contained deploy) and point `_TUTORIAL_SCENARIO_YAML` at the bundled copy — decision resolved to option (a) by walid 2026-04-23 [`server/pipeline/scenarios.py:25-28`]
- [x] [Review][Patch] Wrap `/calls/initiate` body in try/except — return proper envelope on `subprocess.Popen` OSError / token generation / YAML parse failures [`server/api/routes_calls.py:34-101`]
- [x] [Review][Patch] Reorder `/calls/initiate` side-effects — Popen must be the LAST side-effect (tokens → DB insert → Popen), rollback DB row if spawn raises [`server/api/routes_calls.py:46-92`]
- [x] [Review][Patch] Block double-submit on Accept — guard at handler entry: `if (state is IncomingCallAccepting || state is IncomingCallConnected) return;` [`client/lib/features/call/bloc/incoming_call_bloc.dart:34-72`]
- [x] [Review][Patch] Guard emit after bloc close — `if (emit.isDone) return;` before every emit in `_onAccept` / `_onDecline` [`client/lib/features/call/bloc/incoming_call_bloc.dart:34-86`]
- [x] [Review][Patch] Isolate `saveFirstCallShown()` failure — `_tryPersistFirstCallShown()` helper swallows storage errors (`debugPrint`) so a secure-storage failure never cancels a successful call [`client/lib/features/call/bloc/incoming_call_bloc.dart:88-94`]
- [x] [Review][Patch] Cache the composed prompt at module import — `_PROMPT_CACHE` dict + lazy single-load per process; eliminates per-request blocking YAML I/O [`server/pipeline/scenarios.py:38-70`]
- [x] [Review][Patch] Drop the retry banner altogether — on `IncomingCallError`, fade 300ms + navigate to `/` (mirrors Decline); `saveFirstCallShown` is now also persisted in the catch paths so a server outage does not trap the user in an infinite re-ring loop. Design decision by walid 2026-04-23: error UX = bounce to scenario list [`client/lib/features/call/views/incoming_call_screen.dart` + `bloc/incoming_call_bloc.dart`]
- [x] [Review][Patch] `unawaited(_room?.disconnect())` in `dispose()` [`client/lib/features/call/views/call_placeholder_screen.dart:71`]
- [x] [Review][Patch] Stale `RingAnimation` comment updated to reference `_AnimatedCallingText` Timer + Rive [`client/test/app_test.dart:199-201`]

**Deferred (pre-existing / out of scope / architectural):**

- [x] [Review][Defer] Bot subprocess never reaped — architectural: Epic 6.4 / 7.1 own call-end cleanup via `POST /calls/{id}/end` [`server/api/routes_calls.py:63-76`]
- [x] [Review][Defer] `CallPlaceholderScreen` has no LiveKit timeout / reconnect / disconnect-event handler — spec explicitly scopes real call UX to Epic 6.2 [`client/lib/features/call/views/call_placeholder_screen.dart:34-60`]
- [x] [Review][Defer] Mic permission revoked between onboarding and `/call` not user-guided — Epic 6.2 owns the real mic-error UX [`client/lib/features/call/views/call_placeholder_screen.dart:44-58`]
- [x] [Review][Defer] No rate-limit / per-user in-flight guard on `/calls/initiate` — post-MVP infrastructure concern [`server/api/routes_calls.py:33-101`]
- [x] [Review][Defer] Migration `002_calls.sql` has no explicit `ON DELETE` policy on `user_id` FK — defaults to `NO ACTION` (user-delete blocked by existing rows); intentional but undocumented [`server/db/migrations/002_calls.sql`]

**Dismissed as noise (count: 12):** `generate_token_with_agent` unused (false, it IS used), `SYSTEM_PROMPT` env leak (scoped to Popen call), `_CallButton` opacity bug (logic is correct), `IncomingCallBloc.close()` not awaiting (it IS awaited), router whitelist brittle (whitelist is currently correct), `Vibration.hasVibrator()` nullable (v3.x returns non-nullable `bool`), button-row padding 40 vs 30 (Figma iteration doesn't pin this), avatar-pulse missing (replaced by Rive puppet which owns its own idle animation), Decline fade layering (behavior is correct), haptic-once-on-first-frame (spec-compliant), `_buildErrorBanner` auto-reset (BlocBuilder rebuilds on state change), `_AnimatedCallingText` Timer leak (properly cancelled in `dispose()`).

## Change Log

- 2026-04-23 (initial): Story 4.5 implemented end-to-end — server endpoint, client screens/bloc/repository, router integration, full test coverage. Server deployed to VPS (167.235.63.129), migration `002_calls` applied, smoke tests green. Status flipped `ready-for-dev → in-progress → review`.
- 2026-04-23 (iteration 1 — Rive + Figma redesign): Replaced static .jpg character images with a single `characters.riv` puppet (artboard `Picture`, state machine `MainStateMachine`, enum `character` on `ViewModel1`). Introduced reusable `CharacterAvatar` widget. Removed `RingAnimation` entirely. Redesigned `IncomingCallScreen` layout per new Figma spec (166px avatar on #38383A circle, no ring, "Calling…" directly under avatar, padding 60/30/70/30). Extracted reusable `_CallButton`. Client-side only — no server redeploy.
- 2026-04-23 (iteration 2 — polish): Fixed ~17px left-shift of the Accept circle when its label grew from "Accept" to "Connecting…" (locked `_CallButton` to `SizedBox(width: 100)`, hardened label with `maxLines: 1, softWrap: false`). Added `_AnimatedCallingText` loader — three dots cycling on a 400ms timer via `Text.rich`, with transparent-dot trick to keep total text width constant (no centered-text wobble).
- Final validation: 114/114 Flutter tests + 94/94 Python tests, `flutter analyze` / `ruff check` / `ruff format --check` all clean.
- 2026-04-23 (code review corrections): 10 patches applied via `bmad-code-review`. Server: try/except envelope around `/calls/initiate`, side-effects reordered (Popen is now LAST with DB rollback on spawn failure), `the-waiter.yaml` bundled into `server/pipeline/scenarios/` for self-contained deploys, composed prompt cached at first load. Client: bloc guards against double-submit + emits-after-close, isolates `saveFirstCallShown` failures, persists the first-call gate on error paths too (AC5 spirit — prevents infinite re-ring loop on server outage). UX change (walid decision): error path now bounces to `/` like Decline instead of showing a retry banner — banner widget deleted, `IncomingCallError` state handled in `BlocListener` like `IncomingCallDeclined`. Minor: `unawaited(_room?.disconnect())`, stale RingAnimation comment refreshed. Final validation: flutter analyze clean, 114/114 Flutter + 94/94 Python tests green.
