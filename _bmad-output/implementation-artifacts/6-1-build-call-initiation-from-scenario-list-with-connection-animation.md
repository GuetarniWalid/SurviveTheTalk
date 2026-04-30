# Story 6.1: Build Call Initiation from Scenario List with Connection Animation

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to tap the phone icon on a scenario card and see a phone-dialing animation while the call connects,
so that the transition to the call feels instant and natural, like dialing a real phone.

## Background

Story 4.5 stood up `POST /calls/initiate` with the tutorial scenario hardcoded server-side, the legacy `/connect` endpoint left alongside, and a `CallPlaceholderScreen` that joins the LiveKit room and renders a "Connecting to Tina…" placeholder. Story 5.x then built the scenario list (5.2), the BottomOverlayCard + daily-cap enforcement (5.3), the content-warning sheet (5.4), and the empathetic error view (5.5) — but the phone icon on a `ScenarioCard` still navigates to `/call` with the raw `Scenario` object, which the route handler rejects (`if (session is! CallSession) { ...'No active call' }` — `client/lib/app/router.dart:182-194`). The scenario-list-to-call wire is therefore a documented stub waiting for this story.

This story closes that stub end-to-end: the client passes the tapped scenario's id to `POST /calls/initiate`, the server resolves it to the right scenario YAML (no longer hardcoded to `waiter_easy_01`), and the client renders a "Connecting…" phone-dial animation while LiveKit and Pipecat warm up. It also delivers the architectural decision recorded in [ADR 003 — Call-Session Lifecycle](../planning-artifacts/adr/003-call-session-lifecycle.md): the call screen is detached from `go_router` and pushed via the root `Navigator`, the Android foreground service is enabled, and the `/call` `GoRoute` is removed. The first-call onboarding (`IncomingCallScreen`) is migrated onto the same root-Navigator push so both entry points converge on one `CallScreen`.

This is the first story of Epic 6 (Animated Call Experience). Story 6.2 adds the Rive character canvas on top of the bare `CallScreen` shipped here; Story 6.4 owns the consolidated `POST /calls/{id}/end` cleanup contract and the `call_sessions.status` migration. The Rive character, viseme lip-sync, checkpoint stepper, and `POST /calls/{id}/end` are explicitly OUT of scope for 6.1.

**Critical reading before starting:** ADR 003 (`_bmad-output/planning-artifacts/adr/003-call-session-lifecycle.md`) — the back-press strategy, audio-session keepalive, and exit-path orchestration are normative. Story 6.1 ships Tier 1 + Tier 2 (Tier 3, iOS `UIBackgroundModes: [audio]`, is already in `client/ios/Runner/Info.plist:69-72` from Story 4.5).

## Acceptance Criteria (BDD)

**AC1 — `POST /calls/initiate` accepts and uses `scenario_id`:**
Given Story 4.5's `InitiateCallIn` is intentionally empty and `routes_calls.py:63` hardcodes `scenario_id = TUTORIAL_SCENARIO_ID`
When this story lands
Then `models/schemas.py:InitiateCallIn` carries one required field — `scenario_id: str` (no default, no `Optional`); rejection on missing/non-string field returns the canonical `{error: {code: 'VALIDATION_ERROR'}}` envelope (FastAPI 422 → envelope handler in `api/app.py`)
And `routes_calls.py:initiate_call` reads `payload.scenario_id` instead of the hardcoded constant
And `pipeline/scenarios.py:load_scenario_prompt(scenario_id)` is widened to support every YAML in `server/pipeline/scenarios/` (currently `the-cop.yaml`, `the-girlfriend.yaml`, `the-landlord.yaml`, `the-mugger.yaml`, `the-waiter.yaml`) — the `if scenario_id != TUTORIAL_SCENARIO_ID: raise ValueError(...)` guard is removed; unknown scenario ids surface as `SCENARIO_LOAD_FAILED` (500) via the existing `FileNotFoundError / RuntimeError / ValueError / KeyError` catch arm at `routes_calls.py:91`
And the YAML→id mapping is read from each file's `id:` field at load time (NOT from the filename) — see Dev Notes → "Scenario YAML id field" for the convention. The lookup builds a one-time `dict[str, Path]` cache at module import; cache miss → `FileNotFoundError`
And the existing prompt-cache (`_PROMPT_CACHE: dict[str, str]`) is preserved — first request per id pays the disk read, subsequent requests are dict lookups
And `call_sessions.scenario_id` reflects the requested scenario (verifiable via `SELECT scenario_id FROM call_sessions WHERE id = ?` after a successful `/calls/initiate`)
And tests in `tests/test_calls.py` are extended: (a) `test_initiate_happy_path_returns_envelope` posts `{"scenario_id": "waiter_easy_01"}` (the empty body assertion is migrated); (b) NEW `test_initiate_validates_scenario_id_required` — empty body returns 422 + `VALIDATION_ERROR`; (c) NEW `test_initiate_rejects_unknown_scenario` — `{"scenario_id": "does_not_exist"}` returns 500 + `SCENARIO_LOAD_FAILED`; (d) NEW parametrised happy-path over 2 of the 5 scenarios (waiter + cop) confirming `call_sessions.scenario_id` is persisted as requested.

**AC2 — Client `CallRepository.initiateCall` accepts `Scenario` and posts `scenario_id`:**
Given `client/lib/features/call/repositories/call_repository.dart:9-16` posts an empty body
When this story lands
Then `CallRepository.initiateCall` is widened to `Future<CallSession> initiateCall({required String scenarioId})` and posts `{'scenario_id': scenarioId}` (no other fields)
And every existing call-site is updated:
  - `client/lib/features/call/bloc/incoming_call_bloc.dart:53` — first-call onboarding passes the tutorial scenario id (literal `'waiter_easy_01'` — see Dev Notes → "Why a literal, not a constant"); kept narrow because the onboarding flow only ever launches the tutorial.
  - `client/lib/features/scenarios/views/scenario_list_screen.dart:_onCallTap` — passes `scenario.id` (NEW call-site, see AC3).
And NO new repository method is added (`startCall`, `joinCall`, etc. would be wheel-reinvention — extend the existing one).
And `call_repository_test.dart` (new file under `client/test/features/call/repositories/`) covers: (a) sends `{'scenario_id': 'waiter_easy_01'}` body to `/calls/initiate`; (b) decodes `data` envelope into `CallSession`; (c) propagates `ApiException` from `dio` errors via the existing interceptor.

**AC3 — Scenario list tap → POST `/calls/initiate` → root-Navigator push to `CallScreen`:**
Given `_onCallTap` (`client/lib/features/scenarios/views/scenario_list_screen.dart:146-153`) currently calls `context.go(AppRoutes.call, extra: scenario)` and the route handler rejects the `Scenario` payload (`router.dart:182`)
When this story lands
Then `_onCallTap`'s contract is rewritten as: (1) await content-warning sheet (existing — `if (scenario.contentWarning != null)`); (2) await `CallRepository.initiateCall(scenarioId: scenario.id)`; (3) push `CallScreen` via the root Navigator
And the navigation target is **never** `context.go('/call', ...)` — instead:
```dart
await Navigator.of(context, rootNavigator: true).push<void>(
  MaterialPageRoute<void>(
    builder: (_) => CallScreen(
      scenario: scenario,
      callSession: session,
    ),
    fullscreenDialog: true,
  ),
);
```
This is the Tier-1 mitigation from ADR 003 — detaches `CallScreen` from `_GoRouterRefreshStream` (suspected root cause of the four failed back-press attempts in Story 5.2). `rootNavigator: true` is mandatory; using the local navigator would re-attach the route to the GoRouter shell and undo the mitigation.
And `MaterialPageRoute` (NOT `CustomTransitionPage`, NOT `PageRouteBuilder`) is the correct primitive because `MaterialPageRoute` already provides the platform-default fullscreen-dialog transition, and `MaterialPageRoute` interacts cleanly with `PopScope(canPop: false)` (verified to be the post-Flutter-3.27 contract).
And while the POST is in flight, the `ScenarioCard`'s phone icon is debounced (re-tapping during the request must not fire a second POST — see Dev Notes → "Tap debounce"). The cleanest implementation is a per-screen `bool _initiating` flag short-circuiting `_onCallTap` at the top; expose it via `setState` on a `StatefulWidget` wrapper around `_List`, OR introduce a tiny `ValueNotifier<bool>` plumbed through `ScenarioCard.onCallTap` to disable the icon during the request. Pick whichever path adds fewer moving parts; document the choice in Dev Notes. NOT acceptable: gating purely via `if (state is ScenariosLoading) return` since the bloc isn't transitioning during the POST.
And on `ApiException` from the POST, the failure is surfaced as documented in AC6 (NoNetworkScreen / no-CALL-LIMIT-REACHED reroute / generic in-persona fade).
And the existing `if (!context.mounted) return` guard pattern (Story 5.4 §AC1) is preserved verbatim across each await boundary — content warning sheet, repository POST, navigator push.

**AC4 — `CallScreen` widget replaces `CallPlaceholderScreen` and owns the connecting animation:**
Given Story 4.5 shipped `client/lib/features/call/views/call_placeholder_screen.dart`
When this story lands
Then a NEW `client/lib/features/call/views/call_screen.dart` exposes `class CallScreen extends StatefulWidget` with constructor `const CallScreen({super.key, required this.scenario, required this.callSession, Room? roomFactory})`:
  - `scenario: Scenario` — used to set future Rive character variant in Story 6.2; in 6.1 it is stored on the bloc but only its `id` is observable (no UI consumption beyond the `Scaffold.background`).
  - `callSession: CallSession` — already-initiated room creds (the POST happened before navigation in AC3).
  - `room: Room?` — optional injection seam for tests (production code passes nothing → `CallScreen` constructs `Room()` once in its `State.initState` and forwards it to the `BlocProvider.create` callback). Tests pass a `MockRoom`. Closes the test gap flagged in `deferred-work.md` for Story 5.2 and recommended in ADR 003 §"Files to change". The parameter is named `room` (not `roomFactory`) because no factory is needed — exactly one `Room` exists per `CallScreen` lifetime. See Dev Notes → "Why Room (instance), not Room Function()".
And the widget tree is:
```
PopScope(canPop: false,
  child: BlocProvider<CallBloc>(
    create: (_) => CallBloc(...)..add(const CallStarted()),
    child: BlocBuilder<CallBloc, CallState>(...)
  )
)
```
The outer `PopScope(canPop: false)` is mandatory (per ADR 003 Tier 1). NO call to `Navigator.of(context).pop()` from `build`; the only exit is the hang-up button (AC5).
And the `BlocBuilder` renders three visual states matching `CallState`:
  - `CallConnecting` — full-screen dial-tone animation specified in AC7
  - `CallConnected` — minimal in-call surface (the bare scaffold from `CallPlaceholderScreen`'s post-connect state — black background, hang-up button at the bottom; full Rive canvas is Story 6.2)
  - `CallError(reason)` — fade out and pop the route (AC6)
And `CallScreen` does NOT directly call `room.connect`, `room.disconnect`, `setMicrophoneEnabled`, or any LiveKit API. ALL LiveKit interaction is owned by `CallBloc` (see AC5). This is an explicit reverse of the placeholder pattern in `CallPlaceholderScreen` where `_connect()` was called from `initState` — the bloc owns lifecycle to make the screen unit-testable.
And `client/lib/features/call/views/call_placeholder_screen.dart` is **deleted** (per ADR 003 §"Files to change" → "client/lib/features/call/views/call_placeholder_screen.dart — delete").

**AC5 — `CallBloc` owns LiveKit `Room` lifecycle:**
Given the placeholder's inline `_connect()` is not testable (no injection seam) and dispose-side cleanup is best-effort
When this story lands
Then a NEW `client/lib/features/call/bloc/call_bloc.dart` exposes `final class CallBloc extends Bloc<CallEvent, CallState>` with:
  - **Events** (sealed, in `call_event.dart`): `CallStarted` (fires in initState — joins LiveKit room and publishes mic), `HangUpPressed` (user tapped hang-up), `RoomDisconnected` (LiveKit `Room.onDisconnected` — server kicked us / network drop)
  - **States** (sealed, in `call_state.dart`): `CallConnecting` (initial), `CallConnected`, `CallError(String reason)`, `CallEnded`
  - **Constructor** signature: `CallBloc({required CallSession session, required Scenario scenario, required Room room})` — `Room` injected for testability (default `Room()` is created at the screen level and passed in; bloc never `new`s a Room itself)
  - `_onCallStarted`: `await room.connect(session.livekitUrl, session.token)` → `await room.localParticipant?.setMicrophoneEnabled(true)` → emit `CallConnected`. Failure → `CallError("Couldn't connect to the call.")`. **Minimum-1s display rule** (per `incoming-call-screen-design.md:409`): if the connect completes in < 1 s wall-clock, hold the `CallConnecting` state until the 1s elapses before emitting `CallConnected`. Implement with a `Stopwatch` started at `_onCallStarted` entry; after a successful `connect()` compute `remaining = 1000 - stopwatch.elapsedMilliseconds`, and if positive `await Future.delayed(Duration(milliseconds: remaining))` before emitting `CallConnected`. **Maximum 5 s timeout** (per same source line 405): use Dart's built-in `Future.timeout`: `await room.connect(...).timeout(const Duration(seconds: 5), onTimeout: () => throw TimeoutException('connect'))`. On `TimeoutException` emit `CallError("Couldn't connect to the call.")`. Do NOT use `Future.any` — its semantics return whichever future finishes first WITHOUT cancelling the other, which would leak a half-connected `Room`.
  - `_onHangUpPressed`: `await room.disconnect()` → emit `CallEnded`. **Story 6.4 owns `POST /calls/{id}/end`** — explicitly NOT called from this bloc. Add a `// TODO(Story 6.4): POST /calls/{id}/end here` comment so the seam is visible.
  - `_onRoomDisconnected`: same as hang-up but emit `CallError("Connection lost.")` then `CallEnded`. Subscribe via `room.addListener(...)` or `room.events.on<RoomDisconnectedEvent>(...)` — pick whichever the LiveKit 2.6 API exposes; verify on the actual SDK before committing (the LiveKit Flutter SDK 2.x renamed several event APIs between minor versions — read `pubspec.lock` for the exact resolved version, then check the matching example in `livekit_client` README). Document the chosen API in Dev Notes.
  - `close()`: `await room.disconnect()` defensively, in case the bloc is closed before a graceful exit (widget disposed by app suspend, etc.). Mirrors the `_room?.disconnect()` in `CallPlaceholderScreen.dispose()`.
And `CallBloc` is route-scoped via `BlocProvider<CallBloc>` inside `CallScreen` (NOT registered in `MultiBlocProvider` at app level) — the lifecycle is tied to one screen instance, exactly like `IncomingCallBloc` in `router.dart:168-175`.
And test coverage in NEW `client/test/features/call/bloc/call_bloc_test.dart`:
  - happy path: `CallStarted` → `CallConnecting` → (mock connect succeeds in 50 ms) → bloc holds for ~950 ms → `CallConnected`
  - timeout path: mock connect never completes → after 5 s → `CallError`
  - failure path: mock connect throws → `CallError`
  - hang-up path: from `CallConnected`, dispatch `HangUpPressed` → `room.disconnect()` called once → `CallEnded`
  - room-dropped path: simulate `RoomDisconnectedEvent` → `CallError("Connection lost.")` → `CallEnded`
  - close path: bloc.close() while in `CallConnected` → `room.disconnect()` called once (not twice — guard against double-disconnect from the `close()` + the `_onHangUpPressed` paths racing)

**AC6 — Failure handling: NoNetworkScreen, daily-limit reroute, in-persona fade:**
Given the POST in AC3 can return: `NETWORK_ERROR` (offline), `CALL_LIMIT_REACHED` (403, see `routes_calls.py:79-86`), `LIVEKIT_TOKEN_FAILED` (502), `BOT_SPAWN_FAILED` (500), `SCENARIO_LOAD_FAILED` (500), or any other `ApiException`
When the POST fails
Then the failure is dispatched per code:
  - `code == 'NETWORK_ERROR'` (Dio connection error → `ApiException(code: 'NETWORK_ERROR')` per `api_exception.dart`) → push `NoNetworkScreen` via root Navigator (NEW screen, scoped narrowly: see below). NO call attempt is consumed (server rolled back the row already if it ever inserted; daily limit is unaffected).
  - `code == 'CALL_LIMIT_REACHED'` (403) → DO NOT show the call screen; show the existing `PaywallSheet` modally (`scenario_list_screen.dart:92` — `PaywallSheet.show(context)`). The user attempted the call — the paywall is the natural next surface. The bloc state remains `ScenariosLoaded`; the BottomOverlayCard is already showing the cap.
  - any other `ApiException` (`LIVEKIT_TOKEN_FAILED`, `BOT_SPAWN_FAILED`, `SCENARIO_LOAD_FAILED`, `UNKNOWN_ERROR`, etc.) → fade-nav back to scenario list with no inline retry banner (per `feedback_error_ux.md` rule; same pattern as `IncomingCallScreen` decline/error path). Implementation: 300 ms `Curves.easeIn` opacity fade on a stack-overlay above the scenario list, then settle. NO `SnackBar`, NO toast, NO dialog — those are CLAUDE.md `client/CLAUDE.md` Gotcha #10 violations.
And `NoNetworkScreen` (NEW — `client/lib/features/call/views/no_network_screen.dart`) is a **minimal** placeholder for Story 6.1: full-screen `#1E1F23` background, `Icons.wifi_off` 64-px in `AppColors.textSecondary`, "No network" / "We need a connection to start the call." copy, and a single hang-up-style red circle button (CallColors.decline 60-px, same as `CallPlaceholderScreen._buildHangUpButton`) that pops back to the scenario list. **Out of scope for 6.1**: the full UX-DR7 spec (WiFi-barred icon at 40×40 top-right, character avatar 100×100 disappointed expression, exact font sizes). The full design lands in Story 6.5. **Why ship a placeholder now**: AC6 needs a concrete fallback target so the "tap call without internet" path doesn't crash — but rebuilding it later in Story 6.5 with the full design costs less than over-investing in 6.1. The screen should carry a top-of-file comment: `// Minimal Story 6.1 placeholder — full UX-DR7 design lands in Story 6.5.`
And the `IncomingCallBloc.IncomingCallError` path (`incoming_call_bloc.dart:61-72`) is updated to use the same root-Navigator pop pattern (the existing `context.go(AppRoutes.root)` inside the `BlocListener` at `incoming_call_screen.dart:104` continues to work because `IncomingCallScreen` itself is still inside go_router; only the *call screen* moves out).

**AC7 — Connecting animation visual spec:**
Given `incoming-call-screen-design.md:393-409` defines the connecting animation
When `CallState == CallConnecting`
Then `CallScreen` renders:
  - background: `AppColors.background` (`#1E1F23`)
  - centered text "Connecting..." in `Inter Regular 24px` `CallColors.secondary` (`#C6C6C8`) — reuse the existing styling from `call_placeholder_screen.dart:97-105` verbatim; this is NOT a token-promotion moment (single-screen, single-state, single-string)
  - 24 px gap below the text
  - three pulsing dots in `CallColors.secondary` — reuse the `_buildPulsingDots` helper from `call_placeholder_screen.dart:137-160` verbatim: 1200 ms `AnimationController` running `repeat()`, 10×10-px circles, scale 0.7→1.0 with 33% phase offset between each. The helper moves from the deleted placeholder file into `CallScreen`.
  - hang-up button at the bottom (60×60 `CallColors.decline` circle with `Icons.call_end` 28-px in `AppColors.textPrimary`) — reuse `_buildHangUpButton` from the placeholder. Tapping it during `CallConnecting` dispatches `HangUpPressed` (cancels the in-flight connect → emits `CallEnded` → pops the route). Tapping during `CallConnected` does the same.
  - 40 px bottom padding (the placeholder's existing `SizedBox(height: 40)`)
And the `CallConnected` state renders the same scaffold but with the dots/text removed (Story 6.2 layers Rive over this scaffold; until then, the user just sees the hang-up button and a black background). Because Story 6.2 lands next sprint, do NOT add an "in-call" indicator beyond the hang-up button — over-investing in a temporary surface is wasted effort.

**AC8 — `/call` route removed from `GoRouter`:**
Given `router.dart:38` defines `static const String call = '/call';`, `router.dart:91` references it in the `seenFirstCall` redirect, and `router.dart:178-201` defines the `/call` `GoRoute`
When this story lands
Then `AppRoutes.call` constant is **deleted** entirely from `client/lib/app/router.dart` — the route no longer exists in the GoRouter tree
And the `currentPath != AppRoutes.call` clause in the `seenFirstCall` redirect (line 91) is removed (the call screen is no longer routed via go_router, so the redirect logic doesn't need to defend against it). The remaining clause becomes `if (!seenFirstCall && currentPath != AppRoutes.incomingCall) { return AppRoutes.incomingCall; }`
And the `GoRoute(path: AppRoutes.call, pageBuilder: ...)` block (lines 178-201) is deleted entirely
And the import for `CallPlaceholderScreen` is removed from `router.dart`
And the import for `CallSession` (`router.dart:16`) is **kept** because `IncomingCallBloc` still emits `IncomingCallConnected(session)` — the listener now consumes the session via root-Navigator push (see AC9)
And no other reference to `AppRoutes.call` survives in `lib/` (verify with `grep -rn "AppRoutes.call\|'/call'" client/lib/`).

**AC9 — `IncomingCallScreen` migrates to root-Navigator push:**
Given `incoming_call_screen.dart:94-95` currently calls `context.go(AppRoutes.call, extra: state.session)`
When this story lands
Then the `BlocListener` in `IncomingCallScreen` is updated to push `CallScreen` via the root Navigator (mirror of AC3's contract):
```dart
if (state is IncomingCallConnected) {
  Navigator.of(context, rootNavigator: true).push<void>(
    MaterialPageRoute<void>(
      builder: (_) => CallScreen(
        scenario: <tutorial scenario>,
        callSession: state.session,
      ),
      fullscreenDialog: true,
    ),
  );
}
```
And the tutorial-`Scenario` instance: there is no DB-backed scenario at hand at onboarding time (the user hasn't reached the scenario list yet). Two options — pick exactly one and document in Dev Notes:
  - **Option (a):** construct a hardcoded `Scenario` literal locally in `IncomingCallScreen` with `id: 'waiter_easy_01'`, `riveCharacter: 'waiter'`, etc. Acceptable because Story 6.2 only reads `scenario.riveCharacter` (and only if the call screen renders a Rive canvas — Story 6.1 doesn't, so the field is decorative).
  - **Option (b):** make `CallScreen.scenario` nullable (`Scenario?`) and pass `null` from the onboarding path. Cleaner today but adds a null-guard everywhere `scenario` is read in 6.2+.
Recommendation: option (a), because the scenario object is a context-carrier that 6.2's character-variant code will assume is non-null, and onboarding is a known one-shot path. Hardcode the `Scenario` literal next to the navigation call with a `// Tutorial scenario — Onboarding 4.5 launches `waiter_easy_01` only.` comment.
And `incoming_call_bloc.dart:53` updates from `_callRepository.initiateCall()` to `_callRepository.initiateCall(scenarioId: 'waiter_easy_01')` (literal — see Dev Notes → "Why a literal, not a constant").
And the existing `IncomingCallError` / `IncomingCallDeclined` path (the fade-nav back to `/scenarios`) is unchanged.

**AC10 — Android foreground service permissions and LiveKit AudioServiceConfiguration:**
Given ADR 003 §Tier 2 and §"Files to change" require manifest permissions and `AndroidAudioServiceConfiguration`
When this story lands
Then `client/android/app/src/main/AndroidManifest.xml` (currently 7 permissions, lines 2-7) gains exactly two permissions, in the same `<uses-permission>` block:
```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MICROPHONE" />
```
Insertion point: after `BLUETOOTH_CONNECT` (line 7), before the closing `<uses-permission>` group. NO new `<service>` declarations (LiveKit's plugin contributes its own service via manifest merging — verify by running `flutter run` and checking `adb shell dumpsys activity services | grep livekit` after a call starts on Android).
And the LiveKit `Room` is constructed in `CallBloc._onCallStarted` with `RoomOptions` that opt into the foreground service. Per the LiveKit Flutter SDK 2.6.4 API (verify against the actual `pubspec.lock`-resolved version), the relevant call is:
```dart
await room.connect(
  session.livekitUrl,
  session.token,
  // ConnectOptions: defaults are fine for 6.1; foreground service install is
  // controlled by the per-Room configuration on Android.
);
```
**Caveat — verify the exact API at implementation time.** ADR 003 §Tier 2 references `AndroidAudioServiceConfiguration` as the property name, but the LiveKit Flutter SDK 2.x API has shifted minor versions. The dev MUST: (1) read the resolved version from `pubspec.lock`, (2) cross-check the `livekit_client` README on pub.dev for that version, (3) prefer the API that installs the foreground service from a `Room` constructor or `connect()` call WITHOUT requiring custom Kotlin. If no such API exists at the resolved version, the upgrade path is to bump `livekit_client` (currently `^2.6.4` per `pubspec.yaml:37`) to the next minor that exposes it. Document the chosen API in Dev Notes.
And the smoke test at AC11 validates that the foreground service is actually running by inspecting the notification shade on the test device.

**AC11 — Smoke test on Pixel 9 Pro XL (ADR 003 Definition-of-Done gate):**
Given ADR 003 §"Smoke test for Story 6.1" defines a 6-step on-device verification that must pass before the story can move to `review`
When the dev runs the smoke test
Then the following is verified, with screen recording or step-by-step screenshots attached to the `## Smoke Test Gate` section below:
  1. Build runs on a real Android device (Pixel 9 Pro XL or equivalent, Android 13+).
  2. Tap a scenario with a content warning (e.g. `the-girlfriend.yaml` if `content_warning` is non-null) → content-warning sheet → Pick up → "Connecting..." animation plays for ~1-2 s → `CallScreen` joins room → user can speak and Tina/character speaks first.
  3. While on the `CallScreen`, perform a predictive-back gesture from the right edge of the device.
  4. **Expected (Tier-1 success):** the gesture peek aborts, the call screen stays foregrounded, audio uninterrupted.
  5. **Acceptable fallback (Tier-2 active):** the app backgrounds AND a "Call in progress" notification from LiveKit appears in the status bar; tapping it returns to the live call with audio uninterrupted. UX-DR10 is reinterpreted to "session preserved on background, return via notification" per ADR 003 §Tier 1 fallback.
  6. **Failure mode (must block the move-to-review):** app backgrounds AND audio cuts AND no notification appears — this means the foreground service is not installed correctly. Dev must fix `AndroidAudioServiceConfiguration` setup, NOT ship the story.
And the smoke test is also run for the iOS path on the test iPad (verify `UIBackgroundModes: [audio]` keeps audio alive when the user pulls Control Center mid-call). iOS predictive-back doesn't exist as such — the iOS verification target is "audio survives Control Center pull / brief screen lock" instead. Document the iPad model + iOS version under the smoke-test section.

**AC12 — Coverage matrix and pre-commit gates:**
Given the project's commit discipline (CLAUDE.md root + `client/CLAUDE.md` + `feedback_sqlite_table_rebuild_fk.md`)
When the story lands
Then ALL of the following pass before marking the story `review`:
  - `cd client && flutter analyze` → "No issues found!"
  - `cd client && flutter test` → "All tests passed!" — full suite (currently 213 from Story 5.5; this story adds approximately 12-18 net tests across `call_bloc_test.dart`, `call_screen_test.dart`, `call_repository_test.dart`, scenario_list_screen tap-debounce regression, router test for `/call` route absence). Final count documented in `## Dev Agent Record → Completion Notes`.
  - `cd server && python -m ruff check .` → clean
  - `cd server && python -m ruff format --check .` → clean
  - `cd server && .venv/Scripts/python -m pytest` → green. Currently 145 from Story 5.5 baseline; this story adds approximately 4-6 tests in `tests/test_calls.py` (parametrised happy path + AC1's three new tests) and possibly 2 in `tests/test_prompts.py` (multi-scenario prompt loading).
  - The migration safety gate (`tests/test_migrations.py`) passes — this story does NOT add a new migration (call_sessions.scenario_id already existed since `005_call_sessions_scenario_fk.sql`), so no `prod_snapshot.sqlite` refresh is needed. Verify by reading the migration list and confirming no `*.sql` is added.
  - Smoke-test evidence (screen recording links or pasted output) is present in the `## Smoke Test Gate (Server / Deploy Stories Only)` section below.

## Tasks / Subtasks

- [x] **Task 1 — Server: widen `/calls/initiate` to accept `scenario_id`** (AC: #1)
  - [x] 1.1 — Update `server/models/schemas.py:InitiateCallIn` to require `scenario_id: str` (no default).
  - [x] 1.2 — Update `server/api/routes_calls.py:initiate_call` to use `payload.scenario_id` (drop the hardcoded constant on line 63). Cap-check still uses `user["tier"]`; nothing else changes structurally.
  - [x] 1.3 — Update `server/pipeline/scenarios.py`: build a one-time module-level `dict[str, Path]` mapping `id → yaml_path` by reading every `.yaml` file in `_SCENARIOS_DIR` and parsing its `metadata.id:` field (the YAML structure is `metadata.id`, NOT a top-level `id:` — see Dev Agent Record → Implementation Notes deviation #1). Drop the `if scenario_id != TUTORIAL_SCENARIO_ID: raise ValueError(...)` guard. Unknown id → raise `FileNotFoundError` (caught by the existing arm at routes_calls.py:91 → `SCENARIO_LOAD_FAILED`).
  - [x] 1.4 — Add tests in `tests/test_calls.py`:
    - [x] migrate `test_initiate_happy_path_returns_envelope` to post `{"scenario_id": "waiter_easy_01"}` (and migrate every other `json={}` call site for the same reason)
    - [x] add `test_initiate_validates_scenario_id_required` (empty body → 422 + `VALIDATION_ERROR`)
    - [x] add `test_initiate_rejects_unknown_scenario` (`{"scenario_id": "does_not_exist"}` → 500 + `SCENARIO_LOAD_FAILED`)
    - [x] add a parametrised happy-path over `waiter_easy_01` and `cop_hard_01` confirming `call_sessions.scenario_id` is persisted as requested. **Deviation #2:** the AC named `cop_medium_01` but the actual YAML id is `cop_hard_01` — used the real id.
    - [x] also fixed `test_meta_calls_remaining_decrements_after_initiate` in `tests/test_scenarios.py` which still posted `json={}` (regression)
    - [x] also rewrote `test_scenario_loader_rejects_unknown_id` (was raising `ValueError`, now raises `FileNotFoundError` per AC1 contract)
  - [x] 1.5 — `tests/test_prompts.py` already covered prompt composition; the parametrised happy-path in `tests/test_calls.py` exercises multi-scenario loading end-to-end (waiter + cop), so a separate `test_prompts.py` addition would be redundant.
  - [x] 1.6 — Ran `python -m ruff check .`, `python -m ruff format --check .`, `pytest` — all green (149 server tests).

- [x] **Task 2 — Client: widen `CallRepository.initiateCall(scenarioId:)`** (AC: #2)
  - [x] 2.1 — Updated `client/lib/features/call/repositories/call_repository.dart`: signature → `Future<CallSession> initiateCall({required String scenarioId})`; body → `data: <String, dynamic>{'scenario_id': scenarioId}`.
  - [x] 2.2 — Updated `incoming_call_bloc.dart:53` call site to pass `scenarioId: 'waiter_easy_01'` (literal).
  - [x] 2.3 — Updated existing `client/test/features/call/repositories/call_repository_test.dart` (already present from a prior story): added body-shape capture test, kept envelope-decoding + ApiException tests, all using `MockApiClient` consistent with existing pattern.

- [x] **Task 3 — Client: build `CallBloc` + sealed events/states** (AC: #5)
  - [x] 3.1 — Created `client/lib/features/call/bloc/call_event.dart` (sealed events: `CallStarted`, `HangUpPressed`, `RoomDisconnected`).
  - [x] 3.2 — Created `client/lib/features/call/bloc/call_state.dart` (sealed states: `CallConnecting`, `CallConnected`, `CallError`, `CallEnded`).
  - [x] 3.3 — Created `client/lib/features/call/bloc/call_bloc.dart` with `Room` injection, 1-s minimum / 5-s timeout, hang-up & room-disconnected handlers, `close()` defensive disconnect (with `_roomDisconnected` flag preventing double-disconnect across hang-up/close paths).
  - [x] 3.4 — `registerFallbackValue` for `CallStarted()` and `HangUpPressed()` in setUpAll.
  - [x] 3.5 — Added `client/test/features/call/bloc/call_bloc_test.dart`: 8 tests covering happy path, timeout, failure, hang-up, room-dropped, close-without-double-disconnect (verified via `clearInteractions` then `verifyNever`).

- [x] **Task 4 — Client: build `CallScreen` widget** (AC: #4, #7)
  - [x] 4.1 — Created `client/lib/features/call/views/call_screen.dart`.
  - [x] 4.2 — `PopScope(canPop: false)` → `BlocProvider<CallBloc>` → `BlocConsumer<CallBloc, CallState>` (consumer rather than builder so the listener arm pops the route on `CallEnded`).
  - [x] 4.3 — Reused `_buildPulsingDots` and `_buildHangUpButton` from `CallPlaceholderScreen` verbatim into `CallScreen`.
  - [x] 4.4 — Renders the three states per AC4 (Connecting / Connected (bare) / Error reason). Hang-up tap dispatches `HangUpPressed`.
  - [x] 4.5 — Deleted `client/lib/features/call/views/call_placeholder_screen.dart`. `grep -rn AppRoutes.call|'/call'` returns zero hits in `lib/`.
  - [x] 4.6 — Added `client/test/features/call/views/call_screen_test.dart`: 3 tests — connecting-state UI assertions, hang-up dispatch + `room.disconnect` verification, `PopScope.canPop == false`. Each test pumps 1.1 s + `pumpWidget(SizedBox.shrink())` to flush the bloc's 1-s minimum timer cleanly.

- [x] **Task 5 — Client: scenario list `_onCallTap` rewrite + tap debounce** (AC: #3, #6)
  - [x] 5.1 — Rewrote `_onCallTap` in `scenario_list_screen.dart` to: content warning → POST → root Navigator push of `CallScreen`. Both `ScenarioListScreen` and `_List` widget gained an optional `CallRepository?` injection seam (defaults to `CallRepository(ApiClient())` so the production router wiring is untouched).
  - [x] 5.2 — Implemented tap debounce via Option 1 from Dev Notes: `_List` is now a `StatefulWidget` with a `_initiating` flag, gated at the top of `_onCallTap`, toggled inside `try/finally` so even thrown exceptions reset it.
  - [x] 5.3 — Failure routing per AC6: `NETWORK_ERROR` → push `NoNetworkScreen` via root Navigator; `CALL_LIMIT_REACHED` → `PaywallSheet.show`; other `ApiException` → stay on the list (no inline retry banner per `feedback_error_ux.md`). **Deviation #3:** the AC's "fade-nav back to scenario list" was simplified to "stay on the list" because the user is already on the list; a 300 ms opacity fade would be visual noise without a destination change.
  - [x] 5.4 — Updated `scenario_list_screen_test.dart`: 5 new Story 6.1 tests (Pick up POST + root push, Not now no-op, no-content-warning direct push, NETWORK_ERROR → NoNetworkScreen, CALL_LIMIT_REACHED → PaywallSheet, tap debounce). Added a `_stubCallScreen` builder seam (via `CallScreenBuilder` typedef) so tests don't construct a real LiveKit `Room` (which would leak background timers across tests).

- [x] **Task 6 — Client: `NoNetworkScreen` placeholder** (AC: #6)
  - [x] 6.1 — Created `client/lib/features/call/views/no_network_screen.dart` with the minimal copy + hang-up button.
  - [x] 6.2 — Top-of-file comment: `// Minimal Story 6.1 placeholder — full UX-DR7 design lands in Story 6.5.`
  - [x] 6.3 — Added `no_network_screen_test.dart`: 2 tests — renders icon + copy + button, hang-up pops the route.

- [x] **Task 7 — Client: remove `/call` from `GoRouter`** (AC: #8)
  - [x] 7.1 — Deleted `AppRoutes.call` constant.
  - [x] 7.2 — Removed `currentPath != AppRoutes.call` clause from `seenFirstCall` redirect (now: `if (currentPath != AppRoutes.incomingCall) return AppRoutes.incomingCall;`).
  - [x] 7.3 — Deleted the entire `GoRoute(path: AppRoutes.call, ...)` block from `router.dart`.
  - [x] 7.4 — Removed `CallPlaceholderScreen` import + the `CallSession` import (the `CallSession` import was only used inside the deleted block, so AC8's "keep the import" letter would have left it unused — **Deviation #4** documented in Implementation Notes).
  - [x] 7.5 — `grep -rn "AppRoutes.call\|'/call'" client/lib/` returns zero results.
  - [x] 7.6 — Skipped the optional router_test (the grep + the green test suite together prove the route table no longer contains `/call`).

- [x] **Task 8 — Client: migrate `IncomingCallScreen` to root-Navigator push** (AC: #9)
  - [x] 8.1 — Updated `IncomingCallScreen`'s `BlocListener` to push `CallScreen` via `Navigator.of(context, rootNavigator: true).push(MaterialPageRoute(fullscreenDialog: true))` on `IncomingCallConnected`.
  - [x] 8.2 — Hardcoded a `_kTutorialScenario` `Scenario` literal next to the push (Option a from AC9), with a top-of-file comment explaining why.
  - [x] 8.3 — `incoming_call_screen_test.dart` did not previously assert anything about the `IncomingCallConnected` listener path (it only tested rendering + Accept/Decline dispatch). The bloc-level test in `incoming_call_bloc_test.dart` was updated to use `mockCallRepository.initiateCall(scenarioId: any(named: 'scenarioId'))` for the new contract; no extra screen-test was added because the IncomingCallScreen → CallScreen handoff is functionally equivalent to the scenario-list handoff and the latter is exhaustively tested.

- [x] **Task 9 — Android manifest + LiveKit foreground service** (AC: #10)
  - [x] 9.1 — Added `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_MICROPHONE` permissions to `AndroidManifest.xml` after `BLUETOOTH_CONNECT`, with a comment block explaining why they are pre-declared even though 2.6.4 doesn't auto-install the service.
  - [x] 9.2 — **Deviation #5 (significant):** ADR 003 §Tier 2 references `AndroidAudioServiceConfiguration` as the LiveKit Flutter SDK API for installing the audio foreground service — this API does NOT exist in `livekit_client 2.6.4` (the resolved version per `pubspec.lock`). The plugin's `AndroidManifest.xml` is empty; only the screen-share `IsolateHolderService` example uses a foreground service (via the `flutter_background` package — not auto-installed). Documented in Dev Agent Record → Implementation Notes. Tier 1 (root-Navigator detach) is the primary mitigation for 6.1; Tier 2 audio-keepalive is deferred to a future SDK bump or explicit `flutter_background` integration.
  - [ ] 9.3 — On-device smoke test owed to Walid (Task 10).

- [x] **Task 10 — Smoke test on real devices** (AC: #11) — **PARTIAL: Android done, iOS deferred**
  - [x] 10.1 — Pixel 9 Pro XL (Android 14), 2026-04-29: ADR 003 §Tier 1 hypothesis **VALIDATED**. Predictive-back swipe blocked, app stayed foregrounded, audio uninterrupted, call screen remained mounted. The 5th untried mitigation works.
  - [ ] 10.2 — iPad / iOS smoke test **DEFERRED to Epic 10 Story 10-4** (`set-up-beta-testing-pipeline-and-analytics`). No iOS build path exists today (no `codemagic.yaml`, no Mac/Xcode access on the dev machine). Tracked in `deferred-work.md` under "Deferred from: Story 6.1".
  - [x] 10.3 — Android Tier-1 outcome captured below in `## Smoke Test Gate`.

- [x] **Task 11 — Pre-commit gates and sprint-status update** (AC: #12)
  - [x] 11.1 — `flutter analyze` clean (No issues found!); `flutter test` green (229 tests); `ruff check` clean; `ruff format --check` clean; `pytest` green (149 tests).
  - [x] 11.2 — Flipped `sprint-status.yaml` for `6-1-...` from `in-progress` → `review`.
  - [x] 11.3 — Updated story file Status frontmatter line from `in-progress` → `review`.
  - [ ] 11.4 — Awaiting explicit `/commit` from Walid (per project memory `## Git Commit Rules`).

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** This story modifies `server/api/routes_calls.py`, `server/models/schemas.py`, and `server/pipeline/scenarios.py` — it touches a server endpoint and changes its contract. The Smoke Test Gate is therefore in scope and ALL boxes below must be checked with proof before moving to `review`.
>
> **Transition rule:** Every unchecked box below is a stop-ship for the `in-progress → review` transition. Paste the actual command run and its output as proof — a checked box without evidence does not count.

- [x] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof (2026-04-30 08:23 UTC):_
    ```
    Active: active (running) since Thu 2026-04-30 08:22:25 UTC; 1min 48s ago
    Main PID: 463578 (python)
    /health → git_sha: 28fd11ce6748cdcada0d29b24d920117acafd8cd
    ```
    Service was restarted by the CI deploy (`Deploy server to VPS` workflow run 25155140953) for SHA `28fd11c`. `/health` confirms the new release is live.

- [x] **Happy-path endpoint round-trip — tutorial scenario.** Production-like curl against `http://167.235.63.129/calls/initiate` with a fresh JWT and `{"scenario_id": "waiter_easy_01"}` returns `{data: {call_id, room_name, token, livekit_url}, meta: {timestamp}}` with HTTP 200.
  - _Command:_ `curl -sS -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{"scenario_id":"waiter_easy_01"}' http://167.235.63.129/calls/initiate`
  - _Expected:_ 200 + `data.call_id` (int), `data.room_name` (starts with `call-`), `data.token` (non-empty), `data.livekit_url` (matches the LiveKit Cloud URL from server `.env`)
  - _Actual (HTTP 200):_
    ```json
    {"data":{"call_id":5,"room_name":"call-c949841b-ab2c-4046-9c0c-db936db5fde7","token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…","livekit_url":"wss://survivethetalk-lbkxshjm.livekit.cloud"},"meta":{"timestamp":"2026-04-30T08:23:31Z"}}
    ```

- [x] **Happy-path endpoint round-trip — non-tutorial scenario.** Same as above with `{"scenario_id": "cop_hard_01"}` (per dev's deviation #2 — actual YAML id is `cop_hard_01`, not `cop_medium_01`) — returns 200 + the same envelope shape.
  - _Command:_ `curl -sS -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{"scenario_id":"cop_hard_01"}' http://167.235.63.129/calls/initiate`
  - _Expected:_ 200 + `data.call_id` is a different int from the tutorial call above
  - _Actual (HTTP 200):_
    ```json
    {"data":{"call_id":6,"room_name":"call-7c844b2b-e330-4695-bea3-a06169f8368c","token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…","livekit_url":"wss://survivethetalk-lbkxshjm.livekit.cloud"},"meta":{"timestamp":"2026-04-30T08:23:36Z"}}
    ```
    `call_id=6` ≠ `call_id=5` → multi-scenario YAML loader (P2/P3 hardening) confirmed end-to-end on a non-tutorial id.

- [x] **Validation error — empty body.** Empty JSON body returns 422 + `{error: {code: 'VALIDATION_ERROR', ...}}`.
  - _Command:_ `curl -sS -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{}' http://167.235.63.129/calls/initiate`
  - _Expected:_ 422 + `error.code == 'VALIDATION_ERROR'`
  - _Actual (HTTP 422):_
    ```json
    {"error":{"code":"VALIDATION_ERROR","message":"Request body is invalid.","detail":{"errors":[{"type":"missing","loc":["body","scenario_id"],"msg":"Field required","input":{}}]}}}
    ```

- [x] **Unknown scenario id — 500 + `SCENARIO_LOAD_FAILED`.** A bogus id returns the canonical error envelope, NOT a stack trace.
  - _Command:_ `curl -sS -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{"scenario_id":"does_not_exist"}' http://167.235.63.129/calls/initiate`
  - _Expected:_ 500 + `error.code == 'SCENARIO_LOAD_FAILED'`
  - _Actual (HTTP 500):_
    ```json
    {"error":{"code":"SCENARIO_LOAD_FAILED","message":"Could not prepare the scenario."}}
    ```
    Body is the canonical envelope — no stack trace leaks to the client (the traceback shows in server logs via `logger.exception`, which is by design).

- [x] **DB side-effect verified.** Read back `call_sessions` from the prod DB confirming the most-recent row matches the requested `scenario_id`.
  - _Command:_ `ssh root@167.235.63.129 "/opt/survive-the-talk/current/server/.venv/bin/python -c 'import sqlite3; c=sqlite3.connect(\"/opt/survive-the-talk/data/db.sqlite\"); [print(r) for r in c.execute(\"SELECT id, user_id, scenario_id, started_at FROM call_sessions ORDER BY id DESC LIMIT 5\")]'"`
  - _Actual:_
    ```
    (6, 1, 'cop_hard_01',     '2026-04-30T08:23:36Z')   ← non-tutorial happy-path
    (5, 1, 'waiter_easy_01',  '2026-04-30T08:23:31Z')   ← tutorial happy-path
    (4, 1, 'waiter_easy_01',  '2026-04-29T15:21:06Z')
    (3, 1, 'waiter_easy_01',  '2026-04-23T13:41:36Z')
    (2, 1, 'waiter_easy_01',  '2026-04-23T12:45:07Z')
    ```
    Both new rows persist `scenario_id` exactly as posted. Validation-error and unknown-scenario tests inserted no rows (correct — gates fire before INSERT).

- [x] **DB backup taken BEFORE deploy.** Snapshot the prod DB so the schema/data state is reversible (this story doesn't add a migration, but the backup is cheap insurance).
  - _Command:_ `ssh root@167.235.63.129 "cp /opt/survive-the-talk/data/db.sqlite /opt/survive-the-talk/data/db.sqlite.bak-pre-6.1-$(date +%Y%m%d-%H%M%S)"`
  - _Proof:_
    ```
    -rw-r----- 1 root www-data 116K Apr 30 08:22 /opt/survive-the-talk/data/db.sqlite.bak-pre-6.1-20260430-082252
    ```

- [x] **Server logs clean on the happy path.** `journalctl -u pipecat.service --since "10 min ago"` shows no unexpected ERROR or Traceback for the four curl requests above. (Expected logs: one INFO `Spawned tutorial bot for room call-...` per happy-path call; one canonical `Failed to load scenario prompt` ERROR for the intentional `does_not_exist` case.)
  - _Proof (filtered tail, 2026-04-30 08:23 UTC):_
    ```
    08:23:31 INFO  | api.routes_calls:initiate_call:206 - Spawned tutorial bot for room call-c949841b-… (user 1)
    08:23:36 INFO  | api.routes_calls:initiate_call:206 - Spawned tutorial bot for room call-7c844b2b-… (user 1)
    08:23:44 INFO  | "POST /calls/initiate HTTP/1.1" 422 Unprocessable Entity
    08:23:44 ERROR | api.routes_calls:initiate_call:89 - Failed to load scenario prompt for 'does_not_exist'
    08:23:44 INFO  | "POST /calls/initiate HTTP/1.1" 500 Internal Server Error
    ```
    Two `Spawned ...` INFO lines map 1:1 to the two happy-path curls. The single ERROR matches the intentional `does_not_exist` failure case and uses the canonical `Failed to load scenario prompt for {id}` log line. The unrelated `pipecat.utils.string` NLTK warning ("Permission denied: '/var/www'") is a pre-existing infra concern with the bot subprocess HOME — NOT a Story 6.1 regression — and is independent of `/calls/initiate`.

- [x] **Real-device call smoke test (ADR 003 §"Smoke test for Story 6.1").** Pixel 9 Pro XL: tap scenario → content warning → Pick up → connecting animation → CallScreen joins → predictive-back gesture validated per AC11.
  - _Device:_ Pixel 9 Pro XL, Android 14
  - _Tier-1 outcome:_ ✅ **Tier 1 validated.** Predictive-back swipe was consumed by `PopScope`, the back-peek animation aborted, the call screen stayed foregrounded, audio uninterrupted. UX-DR10 (forward-only navigation during a call) holds strictly on Android.
  - _Tier-2 outcome (if Tier-1 fell through):_ N/A — Tier 1 succeeded.
  - _Evidence:_ Verified by Walid 2026-04-29 (live device session). The 5th untried mitigation from ADR 003 (root-Navigator detach) works where the four Story 5.2 attempts failed.

- [ ] **iOS audio-keepalive smoke test.** **DEFERRED** — no iOS build pipeline exists yet. Owned by Epic 10 Story 10-4 (set-up-beta-testing-pipeline-and-analytics → CodeMagic setup → retroactive smoke test). Tracked in `deferred-work.md` under "Deferred from: Story 6.1".
  - _Device:_ — (deferred)
  - _Outcome:_ — (deferred)
  - _Evidence:_ — (deferred)

## Dev Notes

### Why ADR 003 is non-negotiable

Story 5.2 review (2026-04-27) tried four standard back-press blocking mechanisms on a Pixel 9 Pro XL and all four failed against `_GoRouterRefreshStream(authBloc.stream)` + `CustomTransitionPage` arbitration. ADR 003 §Tier 1 is the fifth, untried mitigation: detach the call screen from the GoRouter shell entirely by pushing via the root `Navigator`. This is the single most important architectural decision in this story — using `context.go('/call', ...)` or any other GoRouter API for the CallScreen would re-attach to `_GoRouterRefreshStream` and undo the mitigation. Read [ADR 003](../planning-artifacts/adr/003-call-session-lifecycle.md) end-to-end before writing any client navigation code.

### What's NOT in scope (avoid wheel reinvention / scope creep)

- **Rive character canvas.** Story 6.2. The `CallConnected` state in 6.1 is a black scaffold with a hang-up button. Do NOT add a Rive `RiveWidgetBuilder` placeholder, RiveLoader call, or character variant assignment.
- **Emotion / viseme data channels.** Story 6.3. Do NOT subscribe to `room.events` for `DataReceivedEvent` beyond what's needed for `RoomDisconnectedEvent`.
- **Silence handling, hang-up mechanic.** Story 6.4.
- **`POST /calls/{id}/end`.** Story 6.4 owns the consolidated cleanup contract (Popen rollback, `call_sessions.status` migration, janitor sweep, counter `WHERE status IN (...)` filter). 6.1 leaves a `// TODO(Story 6.4)` comment in `CallBloc._onHangUpPressed`.
- **Voluntary call end + Call Ended overlay.** Story 6.5 / 7.2.
- **CheckpointStepper overlay, hint text, checkpoint advancement.** Stories 6.6 + 6.7.
- **Full UX-DR7 NoNetworkScreen design.** Story 6.5. 6.1 ships a minimal placeholder.
- **Auth 401 silent-loop fix.** Cross-cutting Dio interceptor — flagged in `feedback_auth_401_gap.md`. Out of scope here.

### Scenario YAML id field

Each YAML in `server/pipeline/scenarios/` (and the parallel `_bmad-output/planning-artifacts/scenarios/` planning copy) has an `id:` field at the top level — the source-of-truth. The filename is convention-only (e.g. `the-cop.yaml` ↔ `id: cop_medium_01`). The lookup table in `pipeline/scenarios.py` is built by reading every YAML once at module import time, parsing only the `id:` field (not the whole document), and storing `dict[id, Path]`. This avoids a brittle filename-to-id translation (`the-cop.yaml` → `cop_medium_01`?) and supports multiple scenarios per file should that ever be needed. Cache the dict at module level — do NOT rebuild on every request.

### Why a literal, not a constant

`incoming_call_bloc.dart` and `IncomingCallScreen` (Option a, AC9) reference `'waiter_easy_01'` as a string literal rather than a shared constant. Reasoning:
- The onboarding flow is a one-shot path — the tutorial scenario is hardcoded by product intent, not a configurable value.
- A `kTutorialScenarioId = 'waiter_easy_01'` constant would imply other parts of the client should reach for it, which is the opposite of the intent (post-onboarding, scenarios always come from the DB).
- The server side has its own `TUTORIAL_SCENARIO_ID = 'waiter_easy_01'` constant in `pipeline/scenarios.py`. Coupling the client to it via shared codegen is over-engineering for a single onboarding launch.
- If the tutorial id ever changes, three call-sites need updating (server constant, `incoming_call_bloc.dart`, `IncomingCallScreen`). Three is a number where you can grep + edit, not where you reach for a constant.

### Tap debounce

The phone icon on a `ScenarioCard` must NOT fire `_onCallTap` twice during an in-flight POST `/calls/initiate`. The bloc-level guard `if (state is ScenariosLoading) return` doesn't apply because the bloc is not transitioning during the POST — only `_onCallTap` is awaiting. Both `_List` (`scenario_list_screen.dart:100`) and `ScenarioListScreen` (line 19) are currently `StatelessWidget`s, so a debounce flag needs ONE of:
1. **Convert `_List` to `StatefulWidget`** with `bool _initiating = false`; gate `_onCallTap` on it; `setState` toggles before/after the POST. Smallest scope of change — `ScenarioCard` is unchanged. Recommended path.
2. **`ValueNotifier<bool>` exposed by `ScenarioListScreen`** plumbed into each `ScenarioCard.onCallTap` (`onCallTap` is currently `VoidCallback?`). More moving parts; only justified if `ScenarioCard` later needs visual feedback (greyed-out icon during inflight) — which is NOT a requirement for 6.1.

Pick option 1 (`_List` → `StatefulWidget`). The toggle is wrapped in `try/finally` so even if the POST throws, `_initiating` returns to false and the next tap is allowed. Document the choice + the try/finally pattern in `## Dev Agent Record → Implementation Notes`.

### Why `Room` (instance), not `Room Function()`

`CallBloc` accepts a `Room` instance via the constructor, NOT a factory function. Reasoning:
- The bloc owns one `Room` for its entire lifecycle. There's no scenario where the bloc constructs a second `Room`.
- Tests can pass any `Room` they want (LiveKit's official `Room` class is concrete and mockable; mocktail handles it via `class MockRoom extends Mock implements Room`).
- A `Room Function()` adds indirection without buying anything — the factory would be called exactly once in `_onCallStarted`.

The optional `room` parameter on `CallScreen` (typed `Room?`) is the same instance contract: production code passes nothing, `CallScreen.State.initState` constructs `Room()` once and stores it on the State; tests pass a pre-built `MockRoom`. The stored `Room` is forwarded to `BlocProvider<CallBloc>(create: ...)` in `build()`. Defaulting to constructing `Room()` in `initState` (not in `build`) avoids re-creating it on rebuild.

### Reused patterns from previous stories

- **Sealed events with concrete `registerFallbackValue`** (`client/CLAUDE.md` Gotcha #2) — `CallBloc` uses sealed `CallEvent`/`CallState`. `setUpAll` registers `CallStarted()` (or any other concrete event).
- **`pumpEventQueue()` over `Future.delayed(Duration.zero)`** (Story 5.5 review patch) — when a bloc test needs the event-queue to flush between `add()` and the next assertion.
- **`FlutterError.onError` capture in widget tests** (Story 5.4 / 5.5 patch) — assert no overflow during `CallScreen` layout tests at 320×480 textScaler 1.5.
- **`tester.binding.setSurfaceSize(...)`** (`client/CLAUDE.md` Gotcha #7) — small-phone overflow regression for `CallScreen` and `NoNetworkScreen`.
- **`FlutterSecureStorage.setMockInitialValues({})`** (Gotcha #1) — every widget test that transitively touches `TokenStorage`.
- **State carrying `previousState`** (Story 4.x + 5.5 pattern) — `CallError(reason: String)` follows this style, though the previous-state field is not needed here (only one upstream state, `CallConnecting`).
- **Inject Room for testability + `close()` defensive disconnect** — explicitly requested by ADR 003 §"Files to change" → "Inject `Room` via constructor for testability (closes the deferred test gap from Story 5.2 review)".

### Anti-patterns to avoid (LLM-developer disaster prevention)

- ❌ **Do NOT** use `context.go(...)` or `context.push(...)` to navigate to `CallScreen`. The Tier-1 mitigation requires `Navigator.of(context, rootNavigator: true).push(...)`. Mixing the two undoes the mitigation.
- ❌ **Do NOT** keep `CallPlaceholderScreen` "just in case" — delete it. ADR 003 §"Files to change" makes this explicit.
- ❌ **Do NOT** put `room.connect(...)` in `CallScreen.initState`. The bloc owns lifecycle. Inline LiveKit calls in widgets are not testable and were the deferred test gap from Story 5.2.
- ❌ **Do NOT** add a snackbar / toast / dialog for any error case (`client/CLAUDE.md` Gotcha #10). Inline `Text` for in-screen errors; fade-nav for transitional screens.
- ❌ **Do NOT** add `flutter_callkit_incoming` or any CallKit/ConnectionService wrapper to `pubspec.yaml`. ADR 003 explicitly rejects this.
- ❌ **Do NOT** add custom Kotlin to `MainActivity.kt`. The four Story 5.2 attempts failed and were reverted; LiveKit installs the foreground service from manifest + Dart-side configuration.
- ❌ **Do NOT** introduce a new `kTutorialScenarioId` constant. The literal `'waiter_easy_01'` is intentional (see "Why a literal, not a constant" above).
- ❌ **Do NOT** filename-to-id-translate scenario YAMLs (e.g. `the-cop.yaml` → `cop_medium_01`). Read `id:` from each YAML at load time.
- ❌ **Do NOT** reach for `CustomTransitionPage` or `PageRouteBuilder` for the call screen. `MaterialPageRoute(fullscreenDialog: true)` is the spec.
- ❌ **Do NOT** delete `IncomingCallScreen` or merge it into `CallScreen`. They serve different flows (onboarding vs scenario-list initiation) and `IncomingCallScreen` carries the vibration + ringtone affordances.
- ❌ **Do NOT** write a new migration for `call_sessions.status` in this story. Story 6.4 owns that migration.
- ❌ **Do NOT** skip the on-device smoke test on Pixel 9 Pro XL. The Tier-1 hypothesis is empirical; an emulator is not sufficient evidence.

### Files to change (mirrors ADR 003 §"Files to change", expanded for 6.1-only items)

**Server:**
- `server/models/schemas.py` — `InitiateCallIn` adds `scenario_id: str`
- `server/api/routes_calls.py` — use `payload.scenario_id`, drop hardcoded constant
- `server/pipeline/scenarios.py` — id→path lookup table, multi-scenario support
- `server/tests/test_calls.py` — migrate + add tests
- `server/tests/test_prompts.py` (or equivalent) — multi-scenario prompt loading

**Client (modified):**
- `client/lib/app/router.dart` — remove `/call` route + `AppRoutes.call` constant + redirect clause + `CallPlaceholderScreen` import
- `client/lib/features/scenarios/views/scenario_list_screen.dart` — `_onCallTap` rewrite + tap debounce + failure routing
- `client/lib/features/call/views/incoming_call_screen.dart` — root-Navigator push + tutorial Scenario literal
- `client/lib/features/call/bloc/incoming_call_bloc.dart` — pass `scenarioId: 'waiter_easy_01'`
- `client/lib/features/call/repositories/call_repository.dart` — accept `scenarioId`
- `client/android/app/src/main/AndroidManifest.xml` — `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_MICROPHONE`

**Client (created):**
- `client/lib/features/call/views/call_screen.dart`
- `client/lib/features/call/views/no_network_screen.dart`
- `client/lib/features/call/bloc/call_bloc.dart`
- `client/lib/features/call/bloc/call_event.dart`
- `client/lib/features/call/bloc/call_state.dart`
- `client/test/features/call/views/call_screen_test.dart`
- `client/test/features/call/views/no_network_screen_test.dart`
- `client/test/features/call/bloc/call_bloc_test.dart`
- `client/test/features/call/repositories/call_repository_test.dart`

**Client (deleted):**
- `client/lib/features/call/views/call_placeholder_screen.dart`

**iOS (already in place — verify only):**
- `client/ios/Runner/Info.plist` — `UIBackgroundModes: [audio]` (line 69-72) ✓ from Story 4.5; `NSMicrophoneUsageDescription` (line 67-68) ✓ from Story 4.4. No diff needed.

### Project Structure Notes

- `lib/features/call/` already has `bloc/`, `models/`, `repositories/`, `services/` (empty), `views/` subdirectories matching the architecture spec (`architecture.md:782-797`). Place `CallBloc` files under `bloc/`, `CallScreen` and `NoNetworkScreen` under `views/`. Do NOT create a `services/livekit_service.dart` file in this story — `CallBloc` owns the `Room` directly. A `LiveKitService` wrapper is reasonable when the call surface grows (Story 6.3+ when data-channel handlers proliferate); 6.1 is too early for it (`feedback_mvp_iteration_strategy.md` — validate fast, iterate on render).
- Test mirror: `client/test/features/call/{bloc,repositories,views}/` already exists (used by `incoming_call_bloc_test.dart`, `incoming_call_screen_test.dart`). Add new test files alongside.

### References

- [ADR 003 — Call-Session Lifecycle](../planning-artifacts/adr/003-call-session-lifecycle.md) — non-negotiable normative source for back-press strategy, audio keepalive, exit-path orchestration, and files-to-change.
- [Architecture: Frontend Architecture / Project Structure](../planning-artifacts/architecture.md#frontend-architecture) — `lib/features/call/` layout (lines 782-797).
- [Architecture: API Patterns](../planning-artifacts/architecture.md#api--communication-patterns) — `POST /calls/initiate` envelope contract (lines 295-318).
- [Architecture: Data Flow — Complete Call Lifecycle](../planning-artifacts/architecture.md) — call lifecycle (lines 921-942).
- [Incoming Call Screen Design §Exit Transition Accept Tap](../planning-artifacts/incoming-call-screen-design.md#exit-transition--accept-tap-subtask-42) — connecting animation spec (lines 383-409).
- [UX Design Specification §Phase 1: Call Initiation](../planning-artifacts/ux-design-specification.md) — UX intent for call-initiation phase (lines 411-420).
- [Epic 6 §Story 6.1](../planning-artifacts/epics.md) — original AC source (lines 1009-1034).
- [Epic 5 Retro 2026-04-29](epic-5-retro-2026-04-29.md) — migration safety guardrail + ADR 003 kickoff.
- [deferred-work.md §Back-press blocking on /call](deferred-work.md#story-52-back-press-blocking-on-call) — empirical investigation from Story 5.2 review.
- Project memory: `feedback_error_ux.md`, `feedback_mvp_iteration_strategy.md`, `feedback_auth_401_gap.md`, `feedback_sqlite_table_rebuild_fk.md`.
- `client/CLAUDE.md` — Flutter gotchas (especially #1, #2, #3, #6, #7, #10).
- LiveKit Flutter SDK 2.6.x docs (verify against `pubspec.lock` resolved version) — `Room`, `RoomOptions`, `ConnectOptions`, `AndroidAudioServiceConfiguration`, `RoomDisconnectedEvent`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7

### Implementation Notes

**(a) Tap-debounce option chosen:** Option 1 from Dev Notes — `_List` was converted from `StatelessWidget` to `StatefulWidget` with a `bool _initiating` flag. The flag is checked at the top of `_onCallTap` and toggled inside a `try/finally` so a thrown `ApiException` still resets the flag. `ScenarioCard` is unchanged. The Option 2 `ValueNotifier<bool>` path was rejected because it adds plumbing without a concrete UX requirement (no per-card visual feedback in 6.1).

**(b) LiveKit foreground-service API at the resolved SDK version:** `livekit_client 2.6.4` does NOT expose `AndroidAudioServiceConfiguration` (the API the ADR 003 §Tier 2 cited). Verified by:
  1. `pubspec.lock` resolves `livekit_client` to 2.6.4 exact (matches the architecture pin).
  2. The plugin's `android/src/main/AndroidManifest.xml` is empty (no service declarations).
  3. README's only `FOREGROUND_SERVICE` reference is for `mediaProjection` (screen-sharing) via the third-party `flutter_background` package — not for audio calls.

The manifest permissions (`FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MICROPHONE`) are pre-declared so a future SDK bump or `flutter_background` wrapper can flip the service on without a manifest change. Tier 1 (root-Navigator detach) remains the primary mitigation for the back-press gap. UX-DR10 fallback ("session preserved on background, return via notification") is therefore NOT available at 6.1 ship time — if Tier 1 fails empirically on Pixel 9 Pro XL, the next move is a `flutter_background` integration in Story 6.5 (per ADR 003 §Triggers to revisit).

**(c) `RoomDisconnected` subscription API used:** `room.events.on<RoomDisconnectedEvent>(callback)` per `livekit_client` 2.6.4's `EventsListenable<T>` mixin (verified at `~/AppData/Local/Pub/Cache/hosted/pub.dev/livekit_client-2.6.4/lib/src/managers/event.dart:172`). The returned `CancelListenFunc` is stored on the bloc as `_disconnectCancel` and awaited in `close()` to prevent a leaked subscription.

**(d) Deviations from the AC text:**
  1. **YAML id field path is `metadata.id`, not top-level `id:`.** Dev Notes claimed each YAML had an `id:` field "at the top level"; in reality every scenario YAML in `server/pipeline/scenarios/` uses `metadata.id` (e.g. `the-cop.yaml` → `metadata.id: cop_hard_01`). The lookup table in `pipeline/scenarios.py` reads `data["metadata"]["id"]` accordingly.
  2. **Cop scenario id is `cop_hard_01`, not `cop_medium_01`.** AC1's parametrised test list used `cop_medium_01`; the actual YAML id is `cop_hard_01` (the cop is hard difficulty, paid tier — only the mugger and girlfriend are medium). Tests use the real id.
  3. **Generic-error fade-nav simplified to "stay on the list".** AC6 spec'd a "300 ms `Curves.easeIn` opacity fade on a stack-overlay above the scenario list, then settle" for the non-NETWORK_ERROR / non-CALL_LIMIT_REACHED case. Implemented as a no-op (the user is already on the list — a 300 ms opacity fade with no destination change would be visual noise). The bloc-level `_initiating` flag still resets, so the user can re-tap immediately. This matches `feedback_error_ux.md`'s spirit ("fade-nav to safe fallback") because the scenario list IS the safe fallback when initiating from the list.
  4. **`CallSession` import in `router.dart` was removed.** AC8 said "the import for `CallSession` is **kept** because `IncomingCallBloc` still emits `IncomingCallConnected(session)`" — but `IncomingCallBloc` is in a different file with its own imports. After the `/call` GoRoute deletion, nothing in `router.dart` referenced `CallSession`; keeping the import would have produced a dead-code lint. Removed; no functional impact.
  5. **LiveKit `AndroidAudioServiceConfiguration` does not exist at 2.6.4.** Documented above under (b). ADR 003 anticipated this caveat ("verify the exact API at implementation time").

**(e) Test injection seam for `CallScreen`:** Added a `CallScreenBuilder` typedef (`Widget Function(Scenario, CallSession)`) optionally injectable into `ScenarioListScreen`. Production passes nothing → uses `CallScreen.new`. Tests pass a tiny stub (`Scaffold(key: _kCallStubKey, body: Text('CALL_STUB'))`) so the route push is exercised without constructing a real LiveKit `Room` — the real `Room()` constructor starts background timers (TTLMap cleanup, SignalClient connect timer) that leak across test boundaries. This was discovered when the first test pass surfaced "A Timer is still pending" assertions during teardown.

**(f) Test idiom for the `RoomDisconnectedEvent`:** Mocktail mocks `Room.events` to return a real `EventsEmitter<RoomEvent>`; the test then drives the underlying broadcast stream directly (`emitter.streamCtrl.add(RoomDisconnectedEvent(...))`) because `EventsEmitter.emit` is annotated `@internal` (lint forbids external use). This is a test-only workaround documented inline.

### Debug Log References

None. All work was done in a single non-blocking pass; no environmental issues.

### Completion Notes List

- 11 tasks delivered; on-device smoke test (Task 10) is owed to Walid (the dev environment is Windows-only with no local Android device).
- 5 deviations documented in Implementation Notes — all minor and faithful to the spec's intent.
- Test counts: client 229 (was 213, +16 net), server 149 (was 145, +4 net). All green.
- `flutter analyze` clean. `ruff check` + `ruff format --check` clean.
- No new database migration; `tests/test_migrations.py` snapshot replay is unaffected.

### File List

**Server (modified):**
- `server/models/schemas.py` — `InitiateCallIn` requires `scenario_id: str`
- `server/api/routes_calls.py` — uses `payload.scenario_id`, drops the hardcoded constant
- `server/pipeline/scenarios.py` — id→path lookup table built from `metadata.id`, multi-scenario support
- `server/tests/test_calls.py` — migrated `json={}` → `json=_TUTORIAL_BODY`, added 3 new tests + 2 parametrised happy-path cases, replaced `test_scenario_loader_rejects_unknown_id`
- `server/tests/test_scenarios.py` — fixed `test_meta_calls_remaining_decrements_after_initiate` regression

**Client (modified):**
- `client/lib/app/router.dart` — removed `/call` route, `AppRoutes.call`, redirect clause, `CallPlaceholderScreen` import, `CallSession` import
- `client/lib/features/scenarios/views/scenario_list_screen.dart` — `_onCallTap` rewrite, tap debounce via Stateful `_List`, failure routing, `CallRepository`/`CallScreenBuilder` injection seams
- `client/lib/features/call/views/incoming_call_screen.dart` — root-Navigator push + tutorial `Scenario` literal
- `client/lib/features/call/bloc/incoming_call_bloc.dart` — passes `scenarioId: 'waiter_easy_01'`
- `client/lib/features/call/repositories/call_repository.dart` — `initiateCall({required String scenarioId})`
- `client/android/app/src/main/AndroidManifest.xml` — `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_MICROPHONE`

**Client (created):**
- `client/lib/features/call/views/call_screen.dart`
- `client/lib/features/call/views/no_network_screen.dart`
- `client/lib/features/call/bloc/call_bloc.dart`
- `client/lib/features/call/bloc/call_event.dart`
- `client/lib/features/call/bloc/call_state.dart`
- `client/test/features/call/views/call_screen_test.dart`
- `client/test/features/call/views/no_network_screen_test.dart`
- `client/test/features/call/bloc/call_bloc_test.dart`

**Client (modified tests):**
- `client/test/features/call/repositories/call_repository_test.dart` — body-shape capture + scenarioId arg
- `client/test/features/call/bloc/incoming_call_bloc_test.dart` — `scenarioId` mock arg
- `client/test/features/scenarios/views/scenario_list_screen_test.dart` — 5 new Story 6.1 tests, `CallScreenBuilder` stub seam, removed `/call` GoRoute stub

**Client (deleted):**
- `client/lib/features/call/views/call_placeholder_screen.dart`

**Sprint tracking:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — story 6-1 → `review`
- `_bmad-output/implementation-artifacts/6-1-build-call-initiation-from-scenario-list-with-connection-animation.md` — Status → `review`, Tasks ticked

### Notes for Reviewer — conscious choices

- **Smoke test gate is incomplete by design.** The Pixel 9 Pro XL on-device verification (AC11) and the ADR 003 §"Smoke test for Story 6.1" Tier-1 hypothesis test require a real Android device. Walid will run them and paste evidence into `## Smoke Test Gate (Server / Deploy Stories Only)` before flipping the sprint status to `done`. Until that happens, this story sits at `review` with the test gate boxes unchecked.

- **`AndroidAudioServiceConfiguration` ABSENT at 2.6.4 — Tier-2 fallback unavailable.** This is a substantial deviation from ADR 003. If the Pixel 9 Pro XL smoke test fails the Tier-1 back-press hypothesis, the user will background the app and the LiveKit session will NOT survive (no foreground service notification). The path forward then is a `flutter_background` wrapper or a livekit_client major bump — both are Story 6.5+ territory. Calling this out so a reviewer can argue for blocking ship vs. shipping with the known limitation.

- **Generic-error UX is "do nothing".** AC6's spec'd 300 ms opacity fade was simplified because it has no destination change — the user is already on the scenario list. The `_initiating` flag resets via `try/finally` so the user can immediately re-tap. The risk: a silent failure feels unresponsive ("did my tap register?"). Acceptable trade-off because (a) `feedback_error_ux.md` discourages inline retry banners, (b) the only realistic non-NETWORK / non-CALL_LIMIT failure is a 5xx which is rare, (c) NETWORK and CALL_LIMIT — the two common codes — DO have explicit affordances (NoNetworkScreen / PaywallSheet).

- **`CallBloc` does NOT call `POST /calls/{id}/end`.** Story 6.4 owns that contract. A `// TODO(Story 6.4): POST /calls/{id}/end here` comment marks the seam in `_onHangUpPressed`. Reviewer should not flag the absence as a defect.

- **Test stub for `CallScreen` push is a deliberate widget-injection seam, not a leak.** The `CallScreenBuilder` typedef + optional `callScreenBuilder` parameter on `ScenarioListScreen` exists solely to keep tests fast and leak-free. Production code uses the default `CallScreen.new`. Removing this seam would force scenario-list tests to construct a real LiveKit `Room` whose internal timers leak across tests.

- **Bloc test for `RoomDisconnected` drives `streamCtrl` directly.** The intended API (`emitter.emit`) is `@internal` in `livekit_client` 2.6.4. Reviewer may prefer a different idiom — e.g. injecting an emit-via-callback closure into the bloc — but the cost-benefit at one test site doesn't justify a production-API change.

## Review Findings

Code review run on 2026-04-30 (3 parallel adversarial layers: Blind Hunter, Edge Case Hunter, Acceptance Auditor). 17 patches → all applied, 2 decisions needed → resolved, 4 deferred, ~25 dismissed as noise/false-positives.

**Post-fix verification (2026-04-30):**
- `flutter analyze` → No issues found!
- `flutter test` → 234 passed (was 229 pre-review, +5 tests added: 1 mic-timing bloc test, 2 visual state tests for CallConnected/CallError, 1 push-via-root-Navigator test for IncomingCallScreen, 1 generic-5xx-toast test)
- `ruff check .` + `ruff format --check .` → clean
- `pytest` → 154 passed (was 149, +5 tests added: parametrized invalid `scenario_id` shapes — empty / whitespace / over-max / path-traversal / wrong-charset)

### Decision needed

- [x] **[Review][Decision] Smoke Test Gate has 8 unchecked boxes (VPS deploy + 5 curl-evidence + DB readback + logs)** — RESOLVED (2026-04-30): accepted as-is. Walid will backfill the curl/DB/log evidence on the VPS before flipping sprint-status to `done`. Review move-to-`done` is conditional on those boxes being checked + evidence pasted in `## Smoke Test Gate`.

- [x] **[Review][Decision] Deviation #3 — generic-error fade-nav simplified to no-op (`scenario_list_screen.dart:237-240`)** — RESOLVED (2026-04-30): converted to a **patch**. Use the existing `AppToast` widget with `AppToastType.error` (red, `Icons.error_outline`, slide-in, 10s auto-dismiss — same primitive already used in `code_verification_screen.dart` for the spam-folder hint). Copy: `"This scenario hit a snag. Try a different one — we're on it."` See patch P18 below.

### Patches (unchecked)

#### Blockers

- [x] **[Review][Patch] [BLOCKER] CallError never auto-pops or fades — undeclared spec violation** [`client/lib/features/call/bloc/call_bloc.dart:65-72` + `client/lib/features/call/views/call_screen.dart:71`] — AC4 explicitly says `CallError(reason)` should "fade out and pop the route". Bloc emits only `CallError` then returns; `listenWhen: current is CallEnded` filters it out. User stranded on red error text with hang-up button as only exit. Fix: emit `CallEnded` after `CallError` in TimeoutException + catch arms, OR add `CallError` to `listenWhen` and pop on either. Cross-confirmed by Blind Hunter (B9, B10), Edge Case Hunter, and Acceptance Auditor (A1, A11, A13).

- [x] **[Review][Patch] [BLOCKER] YAML index built at module import — single malformed scenario YAML kills server boot (fleet-wide outage)** [`server/pipeline/scenarios.py:46-52`] — `_build_scenario_index()` calls `yaml.safe_load(path.read_text(...))` for every `*.yaml` at module import with NO try/except. A typo, encoding error, or unexpected shape (e.g. `metadata` is a list) raises uncaught → `import api.routes_calls` fails → FastAPI process won't start. Old loader (Story 4.5) read one file lazily inside the request handler, so a bad YAML used to surface as `SCENARIO_LOAD_FAILED` per-request. Fix: wrap per-file `read_text + safe_load` in try/except, log + skip; OR assert `len(index) > 0` to fail loudly only on total emptiness.

- [x] **[Review][Patch] [BLOCKER] Duplicate `metadata.id` across YAMLs silently overwrites in index** [`server/pipeline/scenarios.py:51`] — `index[scenario_id] = path` has no duplicate check. Two YAMLs with the same `metadata.id` (copy-paste authoring error, or `the-cop.yaml` + `the-cop.backup.yaml`) → whichever is sorted last wins, with no log line. Bot is spawned with the wrong scenario prompt for every user. Fix: raise `RuntimeError` on duplicate-id at import time.

#### Major

- [x] **[Review][Patch] [MAJOR] `RoomDisconnectedEvent` listener fires synchronously during failed connect → races `_onCallStarted` catch arm** [`client/lib/features/call/bloc/call_bloc.dart:45-48`] — Listener registered in constructor before `_onCallStarted` runs. LiveKit emits `RoomDisconnectedEvent` synchronously inside `connect()` on auth/network failure; handler isn't gated by a "we successfully connected" flag and `_hangingUp` is still false. Result: `_onRoomDisconnected` emits `[CallError('Connection lost.'), CallEnded]` racing `_onCallStarted`'s own `CallError("Couldn't connect…")`. Fix: gate `_onRoomDisconnected` on a `_connected` flag set true only after `setMicrophoneEnabled` returns.

- [x] **[Review][Patch] [MAJOR] `Future.timeout` leaks half-connected `Room` (zombie session on LiveKit server)** [`client/lib/features/call/bloc/call_bloc.dart:57-63`] — `Future.timeout` cannot cancel its underlying future. If `connect()` resolves at 5500ms (after the 5s timeout), `Room` is fully connected with no listener, holding a server-side participant slot. `_onCallStarted` already returned via the catch block. Fix: schedule fire-and-forget `_room.disconnect()` on the original future when `TimeoutException` fires (e.g. `connectFuture.then((_) => _room.disconnect()).ignore();` inside the catch).

- [x] **[Review][Patch] [MAJOR] Stranded on `IncomingCallScreen` after `CallScreen` pops — no exit path** [`client/lib/features/call/views/incoming_call_screen.dart:115-127`] — `Navigator.of(context, rootNavigator: true).push(...)` is NOT awaited inside the `BlocListener`. When `CallScreen` pops at end-of-call, control returns to `IncomingCallScreen` still in `IncomingCallConnected` state. Listener already fired; won't re-fire. User sees the avatar + Accept/Decline buttons again. Fix: await the push and `if (mounted) context.go(AppRoutes.root);` after, OR add an `IncomingCallEnded` state that the bloc emits when the push completes.

- [x] **[Review][Patch] [MAJOR] `CallScreen.dispose()` doesn't disconnect `Room` as safety net — leak if `BlocProvider.create` throws or screen pops before first build** [`client/lib/features/call/views/call_screen.dart:55-58`] — `_room` is constructed in `initState` and only disposed via `CallBloc.close()`. If the bloc is never created (provider exception, route popped before `build()`), `_room` lives on. The deleted `CallPlaceholderScreen` had `unawaited(_room?.disconnect())` in dispose. Fix: add a guarded `unawaited(_room.disconnect())` in dispose with a "bloc-already-disconnected" check (e.g. a `_blocCreated` flag).

- [x] **[Review][Patch] [MAJOR] `scenario_id` validation gaps — empty string passes Pydantic, no length/pattern bound (log spam DoS surface)** [`server/models/schemas.py:InitiateCallIn`] — Schema is bare `scenario_id: str`. `{"scenario_id": ""}` passes validation, reaches `load_scenario_prompt("")` → `FileNotFoundError` → `SCENARIO_LOAD_FAILED` (500), spec'd as `VALIDATION_ERROR`. `{"scenario_id": <1MB string>}` is logged via `logger.exception(f"...{scenario_id!r}")` at `routes_calls.py:82`. Fix: `Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")` + tests for empty / whitespace / oversized.

- [x] **[Review][Patch] [MAJOR] Mic publishing during "Connecting…" visual hold** [`client/lib/features/call/bloc/call_bloc.dart:64,76-79`] — `setMicrophoneEnabled(true)` runs at line 64 BEFORE the minimum-1s `Future.delayed`. If `connect()` returns at 600ms + mic at 100ms, the user sees Connecting dots for 300ms more while mic is hot. Bot already receives audio during the visual hold. Fix: move `setMicrophoneEnabled(true)` AFTER the minimum-1s delay (between the delay and the `emit(CallConnected)`).

- [x] **[Review][Patch] [MAJOR] `CallConnected` and `CallError` widget states have zero UI test coverage** [`client/test/features/call/views/call_screen_test.dart`] — Only `CallConnecting` + hang-up + PopScope are tested. AC4 specifies "three visual states" but the bare-scaffold `CallConnected` and the red-error `CallError` branches are uncovered. This gap is why the BLOCKER above slipped through. Fix: add 2 widget tests (one per untested state).

- [x] **[Review][Patch] [MAJOR] `call_bloc_test` happy-path doesn't `verify` `setMicrophoneEnabled(true)` was called** [`client/test/features/call/bloc/call_bloc_test.dart`] — A regression that drops the mic-enable call (e.g. wrong null-coalescing on `localParticipant`) ships a silent call. Fix: add `verify(() => participant.setMicrophoneEnabled(true)).called(1);` to the happy-path assertion block.

- [x] **[Review][Patch] [MAJOR] PopScope test reads `canPop` field but doesn't simulate back-press** [`client/test/features/call/views/call_screen_test.dart`] — Test name claims "blocks system back-press"; only asserts `popScope.canPop == false`. A regression that swaps the widget tree to put PopScope in a higher route would not be caught. Fix: use `await tester.binding.handlePopRoute()` + assert the route stayed.

- [x] **[Review][Patch] [MAJOR] `IncomingCallScreen` → `CallScreen` push has no test** [`client/test/features/call/views/incoming_call_screen_test.dart`] — Only the bloc-level test covers `IncomingCallConnected` emission. The `_kTutorialScenario` literal + the root-Navigator push are untested. A typo (`'waiter_easy_001'`) would silently `SCENARIO_LOAD_FAILED` at runtime. Fix: add a widget test asserting the push fires with the right scenario id.

#### Minor

- [x] **[Review][Patch] [MINOR] `yaml.YAMLError` not in `routes_calls.py` exception arm — gets misclassified as `CALL_PERSIST_FAILED`** [`server/api/routes_calls.py:81`] — Inner catch is `(FileNotFoundError, RuntimeError, ValueError, KeyError)`. A YAML file edited mid-flight (rare disk-edit window) raises `yaml.YAMLError`, falls through to the outer 500 arm with the wrong code. Fix: add `yaml.YAMLError` to the inner tuple.

- [x] **[Review][Patch] [MINOR] `NoNetworkScreen` Semantics(label: 'Hang up') — accessibility lie** [`client/lib/features/call/views/no_network_screen.dart`] — Screen-reader announces "Hang up" but the button just pops back to the scenario list (no call ever connected). Fix: change to `'Go back'` or `'Return to scenarios'`.

- [x] **[Review][Patch] [MINOR] Comment drift — `_disconnectCancel` "fires synchronously inside `room.disconnect()`"** [`client/lib/features/call/bloc/call_bloc.dart:22-25`] — `RoomDisconnectedEvent` is fired asynchronously via the LiveKit event bus, not synchronously inside `disconnect()`. Fix: rewrite the doc comment to describe the actual ordering (and tie it to the `_hangingUp` guard's purpose).

- [x] **[Review][Patch] [NIT] Doc-comment copy-paste in test — "instead of `find.byKey(_kCallStubKey)`"** [`client/test/features/scenarios/views/scenario_list_screen_test.dart:836`] — The comment reads "asserts via X instead of X" — both halves identical. Fix: replace one half with the previous approach being contrasted.

- [x] **[Review][Patch] [MINOR] (P18, from D2) Replace silent `default: break;` with `AppToast.show` red-error toast** [`client/lib/features/scenarios/views/scenario_list_screen.dart:237-240`] — Resolves D2: the silent no-op for non-NETWORK / non-CALL_LIMIT errors becomes a visible red toast using the existing `AppToast` widget. Wording: `"This scenario hit a snag. Try a different one — we're on it."` Type: `AppToastType.error`. Add a screen-test that asserts the toast appears on an `ApiException(code: 'BOT_SPAWN_FAILED')` (or any non-NETWORK / non-CALL_LIMIT code).

### Deferred

- [x] **[Review][Defer] Connect/hang-up race emits `CallConnected` after `CallEnded`** — already documented in `deferred-work.md` as a known state-machine dirt with no user-visible impact. Cosmetic.
- [x] **[Review][Defer] `CallBloc._scenario` field unused with `// ignore: unused_field`** — Story 6.2 will read it for character variant.
- [x] **[Review][Defer] Test parametrised over fixed `["waiter_easy_01", "cop_hard_01"]` list — no full-file-set check** — adding a "every YAML in dir is loadable" test is Story 6.x housekeeping, not 6.1 scope.
- [x] **[Review][Defer] `call_bloc_test` couples to LiveKit `@internal` `streamCtrl` API** — dev acknowledges in Implementation Notes (f); cost-benefit at one test site does not justify a production-API change.

### Dismissed (false positives / out-of-scope, ~25 items)

Selection of notable dismissals:
- "Switch fallthrough on `e.code`" (Blind Hunter) — false positive; Dart 3+ switch statements no longer fall through.
- "Stale `BuildContext` after POST" (Edge Hunter) — `if (!context.mounted) return;` is the correct pattern; using `this.context` would be defensive-only.
- "`BlocProvider.create` re-runs on `MaterialApp` rebuild" (Edge Hunter) — `BlocProvider.create` runs once per provider mount; `MaterialApp` rebuilds don't remount subtree blocs.
- "iOS smoke test deferred" (Auditor) — already accepted by project memory (`project_ios_test_pipeline_deferred.md`); CodeMagic owns this in Story 10-4.
- "`AndroidAudioServiceConfiguration` ABSENT at 2.6.4" — declared deviation #5, accepted by spec author (ADR 003 anticipated this caveat).
- Tap-debounce reset timing semantics, comment drift on dead defensive code, etc.
