# ADR 003 — Call-Session Lifecycle: Raw LiveKit (no CallKit/ConnectionService Wrapper)

**Status:** Accepted
**Date:** 2026-04-29
**Deciders:** Winston (Architect), Walid (Project Lead)
**Blocks resolved:** Story 6.1 kickoff (Action Item AI-2 from Epic 5 retrospective 2026-04-29)
**Related:** `deferred-work.md` §Story 5.2 (back-press), §Story 5.3 (Popen rollback / `call_sessions.status`)

---

## Context

Story 6.1 replaces `CallPlaceholderScreen` with the real Rive + LiveKit + Pipecat call experience. Two architectural drivers from Epic 5 converge on this story:

1. **Back-press blocking on `/call` is broken on Android.** During Story 5.2 review (2026-04-27), four standard mechanisms were tried on a Pixel 9 Pro XL (Android 14) and all failed: `PopScope(canPop: false)`, manifest `android:enableOnBackInvokedCallback="true"`, native `OnBackInvokedDispatcher.registerOnBackInvokedCallback(PRIORITY_OVERLAY, ...)` from `MainActivity.kt`, and AndroidX `OnBackPressedDispatcher.addCallback(...)` (via `FlutterFragmentActivity`). On every attempt, predictive-back swiped past the interceptor and `moveTaskToBack` ran. The probable root cause is a known interaction between Flutter's embedding, `go_router`'s `CustomTransitionPage`, the `_GoRouterRefreshStream(authBloc.stream)` listenable, and Android's predictive-back arbitration — `PopScope` is being torn down or de-prioritised at the moment the gesture commits.

2. **Five deferred items from Stories 5.1 and 5.3 concentrate on `POST /calls/{id}/end`** (Story 6.4): Popen rollback leaves LiveKit room/tokens minted; `call_sessions` orphan rows burn lifetime quota (no `status` column); `meta.calls_remaining` goes stale after `/calls/initiate` succeeds; `started_at` lex-comparison fragility; auth 401 cross-cutting. Story 6.4 will own the unified call-lifecycle contract.

Two options were on the table for Story 6.1's call-session lifecycle:

- **Option A — Raw LiveKit.** `livekit_client` Flutter SDK only. The client owns back-press blocking, audio-session keepalive, and `POST /calls/{id}/end` orchestration explicitly.
- **Option B — `flutter_callkit_incoming` wrapper.** Wraps CallKit (iOS) + ConnectionService (Android). The OS treats the session as a system-managed phone call: back-press blocking, audio-session keepalive, ongoing-call notification, lock-screen controls all "free."

Project constraints that shape the decision:

- Solo developer on Windows, no local Xcode, iOS testing limited to CodeMagic CI builds + an iPad.
- Outgoing-only call flow (user taps phone icon on a scenario card → `POST /calls/initiate`). No incoming push-driven calls planned for MVP — therefore no Apple `com.apple.developer.pushkit.unrestricted-voip` entitlement needed.
- Product intent (UX) is "immersive full-screen AI conversation," not "real phone call." No requirement for Recents-list integration, lock-screen controls, or coexistence with GSM calls.
- Tolerance for non-trivial native dependencies = low. Any package whose stack traces would land in Swift/Kotlin and require Xcode-side debugging is a productivity-killer in this dev setup.
- LiveKit Flutter SDK 2.4+ already provides `AndroidAudioServiceConfiguration` (foreground service installer for audio persistence) — audio-session keepalive is therefore not exclusive to CallKit/ConnectionService.

---

## Decision

**Adopt Option A — raw `livekit_client` for the call-session lifecycle.** No `flutter_callkit_incoming`, no CallKit, no ConnectionService wrapper.

The back-press blocking gap from Story 5.2 is addressed by a three-tier strategy specified in this ADR (§Implementation Strategy below). Audio-session keepalive uses LiveKit's built-in foreground service on Android and the `audio` background mode on iOS. `POST /calls/{id}/end` is invoked explicitly by the client at every exit path (Story 6.4 owns the consolidated cleanup contract).

---

## Rationale

The decision is driven by four product/operational facts that each disarm a central argument for Option B:

1. **Outgoing-only call flow** removes the only case where CallKit would be unavoidable (incoming push-driven calls require `PushKit`, which Apple ties to `CallKit`). Outgoing-only sessions are perfectly servable by raw WebRTC.

2. **User-mental-model is "immersive AI conversation," not "real phone call."** CallKit/ConnectionService side-effects — Recents-list entry, lock-screen "ongoing call" controls, GSM-call interruption — are *unwanted* here, not just unneeded. Option B would spend implementation effort to acquire behaviours the product explicitly rejects.

3. **Native-dep tolerance is low and the dev setup amplifies the cost.** `flutter_callkit_incoming` ships Swift + Kotlin code pinned to specific iOS/Android SDKs; debugging a `MethodChannel` failure on iOS without local Xcode, via CodeMagic round-trips and an iPad, would dominate Story 6.1's schedule. Raw LiveKit keeps the surface area in Dart.

4. **Audio-session keepalive is not exclusive to CallKit/ConnectionService.** LiveKit Flutter SDK ≥ 2.4 installs a foreground service via `AndroidAudioServiceConfiguration`; iOS gets the same property via `UIBackgroundModes: [audio]` in `Info.plist`. Option B would deliver this twice (once via LiveKit, once via the wrapper) — risk of conflicting foreground services on Android.

The remaining gap — back-press blocking on Android — is real, but it has a fifth, untried mitigation: **detach the call screen from `go_router`'s navigation stack** by pushing it via `Navigator.of(context, rootNavigator: true).push(MaterialPageRoute(...))`. This bypasses `_GoRouterRefreshStream` and `CustomTransitionPage` (the suspected root cause), letting the root Navigator arbitrate the back gesture against `PopScope(canPop: false)` directly. This was not attempted in the four Story 5.2 sessions and is cheap to validate. Even if it fails empirically, the LiveKit foreground service guarantees the session survives backgrounding — so the worst case is a softened UX-DR10 ("session preserved on background, user returns via notification") rather than a broken call.

The five deferred items orbiting Story 6.4 are **independent of this decision**: Popen rollback, `call_sessions.status` migration, `meta.calls_remaining` refresh seam, `started_at` format CHECK, and auth 401 are all server-side or cross-cutting concerns whose fix shape does not change between Option A and Option B. Story 6.4 enumerates them under its "consolidated cleanup contract" regardless.

---

## Implementation Strategy

The back-press gap is closed by three tiers, applied in order. Story 6.1 ships tier 1 + tier 2; tier 3 is iOS-side parity.

### Tier 1 — Detach the call screen from go_router (the new, untried mitigation)

Push `CallScreen` via the root Navigator instead of routing to `/call`:

```dart
// In ScenarioListScreen, replacing context.go('/call', extra: {...})
Navigator.of(context, rootNavigator: true).push(
  MaterialPageRoute(
    builder: (_) => CallScreen(scenario: scenario, callSession: session),
    fullscreenDialog: true,
  ),
);
```

The call screen lives above the `GoRouter` shell. `_GoRouterRefreshStream(authBloc.stream)` no longer has the screen in scope at gesture commit time. The root Navigator consults `PopScope(canPop: false)` natively. **Hypothesis to validate empirically on Pixel 9 Pro XL during Story 6.1**: predictive-back is now blocked.

If validated: UX-DR10 (forward-only navigation) holds strictly on both iOS and Android, no further work needed.

If not validated: tier 2 still keeps the session alive — UX-DR10 is reinterpreted as "session preserved if user backgrounds, return via foreground-service notification."

### Tier 2 — LiveKit foreground service (Android audio keepalive)

Configure LiveKit ≥ 2.4's `AndroidAudioServiceConfiguration` when joining the room:

```dart
final room = Room(
  roomOptions: const RoomOptions(
    defaultAudioPublishOptions: AudioPublishOptions(...),
  ),
);
await room.connect(
  url,
  token,
  connectOptions: const ConnectOptions(
    // Ensures audio survives app backgrounding via Android foreground service
    autoSubscribe: true,
  ),
);
```

LiveKit installs a `MediaProjection`-style foreground service with a persistent "Call in progress" notification. Required permissions in `AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MICROPHONE" />
<!-- Android 14+ requires explicit foreground service type -->
```

No custom Kotlin. LiveKit owns the service implementation.

### Tier 3 — iOS background audio mode

In `client/ios/Runner/Info.plist`:

```xml
<key>UIBackgroundModes</key>
<array>
    <string>audio</string>
</array>
```

LiveKit's `iOSAudioConfiguration` (default in 2.6+) requests `AVAudioSession` category `.playAndRecord` with `.allowBluetooth` and `.defaultToSpeaker`. Audio survives app backgrounding (e.g. user pulls Control Center, locks screen briefly) without a CallKit handoff. iOS does not have the predictive-back-equivalent gesture that motivated tier 1 — the home-indicator swipe is intentional and uncommon mid-call.

### Exit-path orchestration (handed to Story 6.4)

Every call termination path explicitly calls `POST /calls/{id}/end`:

| Exit trigger | Handler |
|---|---|
| User taps Rive hang-up button | `CallBloc.onHangUp` → `room.disconnect()` → `POST /calls/{id}/end` → `Navigator.pop` |
| Pipecat sends `{"type": "call_end"}` data channel message | `CallBloc.onRemoteHangUp` → same as above |
| LiveKit `Room.onDisconnected` (network drop / server kill) | `CallBloc.onConnectionLost` → `POST /calls/{id}/end {reason: "connection_lost"}` |
| App backgrounded > N seconds (Android only, fallback if tier 1 failed) | LiveKit foreground service keeps room alive; if user does not return within 5 min, server-side janitor (Story 6.4) flips `call_sessions.status` to `'failed'` |
| App killed cold (process death) | Server-side janitor sweep (Story 6.4) |

Story 6.4's spec is the authoritative home for the failure-mode janitor and the `call_sessions.status` migration referenced above.

---

## Consequences

**Positive**

- Zero new native dependencies. All call-lifecycle code lives in Dart + manifest/Info.plist edits. Solo-dev maintainability protected.
- Audio-session keepalive solved without writing custom Kotlin/Swift — LiveKit ≥ 2.4 does it.
- User-mental-model stays clean: no Recents-list pollution, no GSM-call interruption, no lock-screen "ongoing call" affordance the product never asked for.
- iOS testing path (CodeMagic + iPad) remains viable. No Xcode-only debugging surface added.
- Decision reversible: if a future epic introduces incoming-push calls (Epic 9+? not currently planned), CallKit/ConnectionService can be layered over the existing raw LiveKit base without a rewrite.
- Five Epic-6.4 deferred items remain orthogonal to this decision — they are server-side/cross-cutting and resolve identically under Option A.

**Negative / trade-offs**

- The Tier-1 fix (detach call screen from go_router) is **hypothesis-driven** and must be empirically validated on a real Android device during Story 6.1. If it fails, UX-DR10 is reinterpreted from "back-press impossible" to "session preserved on background." This is a softening of the original AC, not a regression — the session does not break.
- Client owns more orchestration than under Option B: every exit path must explicitly `room.disconnect()` and `POST /calls/{id}/end`. Story 6.4 must enumerate these paths in its spec to prevent silent drift.
- No system-managed call indicator on lock screen / status bar (beyond the LiveKit foreground service notification on Android). User-visible "you are in a call" state is owned by the app's own UI, not the OS.
- iPad Air 2 / older iOS hardware may need verification of the LiveKit Flutter SDK 2.6.0 minimum-iOS-version contract. Trigger check at Story 6.1 smoke-test time on the actual test iPad.

---

## Files to change

### Story 6.1 (this story — applies the decision)

- **`client/lib/features/scenarios/views/scenario_list_screen.dart`** — replace `context.go('/call', extra: {...})` with `Navigator.of(context, rootNavigator: true).push(MaterialPageRoute(...))`. Update existing widget tests for the new navigation contract.
- **`client/lib/app/router.dart`** — remove the `/call` route from the GoRouter tree (it is no longer routed via go_router). Keep `/scenarios` as the post-call landing.
- **`client/lib/features/call/views/call_screen.dart`** (new, replaces `call_placeholder_screen.dart`) — wrap the Scaffold in `PopScope(canPop: false)`. Inject `Room` via constructor for testability (closes the deferred test gap from Story 5.2 review).
- **`client/lib/features/call/bloc/call_bloc.dart`** (new) — owns `Room` lifecycle, `room.disconnect()`, `POST /calls/{id}/end` invocation on every exit path.
- **`client/android/app/src/main/AndroidManifest.xml`** — add `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_MICROPHONE` permissions; remove the `enableOnBackInvokedCallback` flag added during Story 5.2 review (already reverted, verify).
- **`client/ios/Runner/Info.plist`** — add `UIBackgroundModes: [audio]` and `NSMicrophoneUsageDescription` if not already set.
- **`client/lib/features/call/views/call_placeholder_screen.dart`** — delete.

### Story 6.4 (downstream — consumes the decision)

- **`server/db/migrations/008_call_sessions_status.sql`** (new) — `ALTER TABLE call_sessions ADD COLUMN status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','failed'))`. Replays cleanly against `tests/fixtures/prod_snapshot.sqlite` (CLAUDE.md migration rule).
- **`server/api/routes_calls.py`** — `POST /calls/{id}/end` flips `status` to `'completed'` and triggers LiveKit `delete_room`. Popen rollback path also deletes the LiveKit room (closes Story 4.5 deferred item). Counter queries (`server/api/usage.py`) add `WHERE status IN ('pending','completed')`.
- **`server/api/usage.py`** + **`server/db/queries.py`** — update `count_user_call_sessions_*` helpers per the new status filter.
- **Janitor sweep** — flip `call_sessions.status` from `'pending'` to `'failed'` when older than 1h (covers app-killed / process-death case).

### Files NOT changed

- `client/pubspec.yaml` — no new dependency. `livekit_client` (already pinned at 2.6.0 per `architecture.md`) is sufficient.
- `client/android/app/src/main/kotlin/.../MainActivity.kt` — stays at the empty `FlutterActivity` default. No `OnBackInvokedDispatcher` or AndroidX `OnBackPressedDispatcher` registration. The four Story 5.2 review attempts remain reverted.
- `_bmad-output/planning-artifacts/architecture.md` — call-flow sections (lines 322, 606, 920-940) already describe raw LiveKit; no diff. ADR cross-referenced from `architecture.md:247`-style ADR ledger if one exists.

---

## Smoke test for Story 6.1 (the validation gate for this ADR)

The Tier-1 hypothesis must be empirically tested before Story 6.1 ships:

1. Build Story 6.1 on a real Android device (Pixel 9 Pro XL or equivalent, Android 13+).
2. Tap a scenario → content warning sheet → Pick up → Connecting animation → call screen renders.
3. Perform predictive-back gesture from the right edge.
4. **Expected (Tier-1 success):** the gesture is consumed by `PopScope`, the back peek animation aborts, the call screen stays foregrounded, audio continues uninterrupted.
5. **Acceptable fallback (Tier-2 active):** the app backgrounds, but the LiveKit foreground service notification appears in the status bar; tapping it returns to the live call screen with audio uninterrupted. UX-DR10 is reinterpreted as documented above.
6. **Failure mode (must block ship):** app backgrounds AND audio cuts AND notification absent — this means LiveKit's foreground service is not installed correctly. Fix the manifest/`AndroidAudioServiceConfiguration` setup before merging.

The Story 6.1 spec must include this smoke-test sequence in its Definition of Done.

---

## Triggers to revisit this decision

- **Tier-1 empirically fails AND Tier-2 fallback is judged unacceptable by Walid during Story 6.1 dogfood.** Re-open the option matrix; ConnectionService self-managed (Android-only, without iOS CallKit) becomes a viable narrower scope.
- **MVP closed-beta surfaces a "where did my call go?" mental-model bug.** Users repeatedly background and lose track of an active session → the foreground-service notification is insufficient affordance, reconsider system-call surface.
- **A future epic introduces incoming push-driven calls** (e.g. an "AI calls you back when ready" mechanic — not currently planned in Epics 6-10). At that point CallKit + PushKit + the VoIP entitlement become unavoidable and this ADR is superseded.
- **LiveKit Flutter SDK drops or changes `AndroidAudioServiceConfiguration`** in a future major version. Audit the foreground-service guarantee at every LiveKit upgrade.
