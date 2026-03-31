# Story 1.3: Create Minimal Flutter App with Voice Call

Status: review

## Story

As a user,
I want to tap a button on my phone and immediately be in a voice conversation with the AI character,
So that I can experience the core product interaction on a real mobile device.

## Acceptance Criteria

1. **AC1 — Single Call button on main screen:**
   Given the Flutter app is launched,
   When the main screen loads,
   Then a single "Call" button is displayed (no other UI elements, no navigation, no login).

2. **AC2 — LiveKit connection established on Call tap:**
   Given the user taps the Call button,
   When the app requests the room token from the server `POST /connect` endpoint,
   Then a LiveKit connection is established and the user's microphone audio streams to the Pipecat pipeline.

3. **AC3 — Remote audio plays through device speaker:**
   Given the pipeline generates a voiced response,
   When audio is received via LiveKit WebRTC,
   Then it plays through the device speaker in real-time.

4. **AC4 — Conversational latency within ceiling:**
   Given the call is active,
   When the user speaks in English,
   Then the AI character responds conversationally with perceived latency <2s (hard ceiling).

5. **AC5 — Clean disconnect via End Call button:**
   Given the call is active,
   When the user wants to end the conversation,
   Then they can tap an "End Call" button to disconnect cleanly.

6. **AC6 — Microphone permission requested if not granted:**
   Given the device has no microphone permission granted,
   When the user taps the Call button,
   Then the system microphone permission dialog is shown before proceeding.

## Tasks / Subtasks

- [x] **Task 1: Add `http` dependency and configure server URL** (AC: #2)
  - [x] 1.1 Run `flutter pub add http` in `client/`
  - [x] 1.2 Create `client/lib/config.dart` with a `serverUrl` constant pointing to the VPS (`http://167.235.63.129`)
  - [x] 1.3 Add `android:usesCleartextTraffic="true"` to `<application>` in `client/android/app/src/main/AndroidManifest.xml` (required for HTTP to IP during PoC)
  - [x] 1.4 Add `NSAppTransportSecurity` / `NSAllowsArbitraryLoads` to `client/ios/Runner/Info.plist` (required for HTTP during PoC)

- [x] **Task 2: Add microphone and network permissions** (AC: #6)
  - [x] 2.1 Add to `AndroidManifest.xml` before `<application>`:
    ```xml
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
    <uses-permission android:name="android.permission.BLUETOOTH" />
    <uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
    ```
  - [x] 2.2 Add to `Info.plist`:
    ```xml
    <key>NSMicrophoneUsageDescription</key>
    <string>SurviveTheTalk needs your microphone for voice calls with AI characters</string>
    ```
  - [x] 2.3 Add Background Audio capability: add `UIBackgroundModes` with `audio` to `Info.plist` (prevents audio stopping when screen locks)

- [x] **Task 3: Replace placeholder main.dart with Call screen** (AC: #1, #2, #3, #5, #6)
  - [x] 3.1 Replace `client/lib/main.dart` entirely — remove counter demo
  - [x] 3.2 Implement `SurviveTheTalkApp` as a `StatelessWidget` wrapping `MaterialApp` with dark theme
  - [x] 3.3 Implement `CallScreen` as a `StatefulWidget` with states: `idle`, `connecting`, `connected`, `error`
  - [x] 3.4 In `idle` state: display a centered green "Call" `FloatingActionButton` with phone icon
  - [x] 3.5 In `connecting` state: display a `CircularProgressIndicator` with "Connecting..." text
  - [x] 3.6 In `connected` state: display call duration timer + red "End Call" `FloatingActionButton` with phone-off icon
  - [x] 3.7 In `error` state: display error message + "Retry" button to return to idle
  - [x] 3.8 Call flow on tap:
    1. Set state to `connecting`
    2. HTTP POST to `{serverUrl}/connect` — parse JSON response for `token`, `livekit_url`
    3. Create `Room()` instance, call `room.connect(livekitUrl, token)`
    4. Call `room.localParticipant?.setMicrophoneEnabled(true)` — this triggers OS permission dialog if needed
    5. Set state to `connected`
    6. Remote audio auto-plays (LiveKit default behavior)
  - [x] 3.9 End call flow: call `room.disconnect()`, dispose room, set state back to `idle`
  - [x] 3.10 Add `EventsListener<RoomEvent>` for disconnect handling (`RoomDisconnectedEvent` — set state to idle)
  - [x] 3.11 Dispose listener and room in `dispose()`

- [x] **Task 4: Update existing test** (AC: #1)
  - [x] 4.1 Replace `client/test/widget_test.dart` — the counter test will fail since `MyApp` no longer exists
  - [x] 4.2 New test: verify `SurviveTheTalkApp` renders without errors
  - [x] 4.3 New test: verify Call button is displayed on initial screen
  - [x] 4.4 New test: verify End Call button is NOT displayed on initial screen (only appears during active call)
  - [x] 4.5 Keep tests simple — do NOT attempt to mock LiveKit Room (native plugin, not testable in widget tests). Test only UI state rendering

- [x] **Task 5: Run pre-commit validation** (AC: all)
  - [x] 5.1 `cd client && flutter analyze` — zero issues (errors, warnings, AND infos)
  - [x] 5.2 `cd client && flutter test` — all tests pass

## Dev Notes

### Architecture Compliance

This is the **Flutter client half** of the PoC. It connects to the voice pipeline built in Story 1.2. [Source: architecture.md#Frontend Architecture]

**PoC scope (non-negotiable):**
- Single `main.dart` file — no architecture layers, no BLoC, no routing, no feature folders
- No state management library — plain `setState()` is sufficient
- No Rive animation — PoC validates voice pipeline only
- No scenario selection — single hardcoded call to the sarcastic character
- No auth, no JWT, no user accounts
- No offline handling beyond basic error display
- No debrief screen — just call and end

**Server endpoint (from Story 1.2):**
- `POST /connect` → returns `{"room_name": str, "token": str, "livekit_url": str}`
- Server is at `http://167.235.63.129` (Hetzner VPS, no domain yet)
- CORS is already enabled (all origins allowed for PoC)

### Critical Technical Specifications

**LiveKit Flutter SDK (livekit_client ^2.6.4):**

```dart
import 'package:livekit_client/livekit_client.dart';
```

Core API pattern:
```dart
// Create room
final room = Room();

// Listen for events
final listener = room.createListener();
listener.on<RoomDisconnectedEvent>((_) { /* handle disconnect */ });

// Connect (token and URL from /connect response)
await room.connect(livekitUrl, token, roomOptions: const RoomOptions(
  adaptiveStream: true,
  dynacast: true,
));

// Enable microphone — triggers OS permission dialog if not granted
await room.localParticipant?.setMicrophoneEnabled(true);

// Remote audio auto-plays — no explicit setup needed for playback

// Disconnect
await room.disconnect();

// Cleanup
listener.dispose();
room.dispose();
```

**HTTP call to server:**
```dart
import 'package:http/http.dart' as http;
import 'dart:convert';

final response = await http.post(Uri.parse('$serverUrl/connect'));
final data = jsonDecode(response.body) as Map<String, dynamic>;
final token = data['token'] as String;
final livekitUrl = data['livekit_url'] as String;
```

**Key LiveKit behaviors:**
- `Room.connect()` establishes WebRTC connection to LiveKit Cloud
- `setMicrophoneEnabled(true)` publishes local audio track AND triggers permission dialog if needed
- Remote audio tracks auto-play when subscribed — no `AudioTrackRenderer` needed for audio-only
- `RoomDisconnectedEvent` fires when server-side bot disconnects (e.g., when Pipecat pipeline ends)
- `room.dispose()` cleans up all resources

**Permission handling flow:**
1. User taps Call → app calls server `/connect`
2. App calls `room.connect()` → establishes WebRTC connection
3. App calls `setMicrophoneEnabled(true)` → if permission not granted, OS dialog appears
4. If user grants permission → mic publishes audio → pipeline hears user
5. If user denies → `setMicrophoneEnabled` throws → catch error → show error state

### Platform Configuration (Android)

Add to `AndroidManifest.xml` BEFORE `<application>` tag:
```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
<uses-permission android:name="android.permission.BLUETOOTH" />
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
```

Add `android:usesCleartextTraffic="true"` to `<application>` tag (PoC only — removed in MVP when HTTPS is configured).

### Platform Configuration (iOS)

Add to `Info.plist`:
```xml
<key>NSMicrophoneUsageDescription</key>
<string>SurviveTheTalk needs your microphone for voice calls with AI characters</string>
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsArbitraryLoads</key>
    <true/>
</dict>
<key>UIBackgroundModes</key>
<array>
    <string>audio</string>
</array>
```

`NSAllowsArbitraryLoads` is PoC only — removed in MVP when HTTPS with valid domain is configured.

`UIBackgroundModes: audio` prevents the call from dropping when user switches apps or locks screen.

### File Structure

All changes in `client/`:

```
client/
├── lib/
│   ├── main.dart          # REPLACED — Call screen with LiveKit integration
│   └── config.dart        # NEW — Server URL constant
├── test/
│   └── widget_test.dart   # REPLACED — Tests for new Call screen UI
├── pubspec.yaml           # MODIFIED — add http dependency
├── android/app/src/main/
│   └── AndroidManifest.xml # MODIFIED — permissions + cleartext traffic
└── ios/Runner/
    └── Info.plist          # MODIFIED — mic description + ATS + background audio
```

### What NOT to Do

- **DO NOT** add `dio` — use `http` package for PoC simplicity. `dio` is for MVP when we need interceptors and JWT injection
- **DO NOT** add `permission_handler` — LiveKit handles mic permission request internally via `setMicrophoneEnabled()`
- **DO NOT** add BLoC, Provider, Riverpod, or any state management — plain `setState()` for PoC
- **DO NOT** add GoRouter or any routing — single screen only
- **DO NOT** add Rive integration — voice pipeline validation only, no animation until Epic 6
- **DO NOT** create feature folders (`features/call/`, etc.) — single `main.dart` for PoC
- **DO NOT** add error handling beyond basic try/catch with error state display
- **DO NOT** add a "connecting..." animation — simple `CircularProgressIndicator` is sufficient
- **DO NOT** add auth or JWT — PoC has no authentication
- **DO NOT** hardcode the LiveKit URL — it comes from the server `/connect` response
- **DO NOT** attempt to mock LiveKit `Room` in tests — it's a native plugin. Test UI states only
- **DO NOT** use `ColorScheme.fromSeed()` — the counter demo syntax. Use explicit dark `ThemeData` matching the project colors (`#1E1F23` background, `#F0F0F0` text)
- **DO NOT** lock orientation programmatically — keep system default for now

### Testing Strategy

Widget tests CANNOT test LiveKit integration (native plugin). Tests should verify:
1. App renders without crashing
2. Call button is visible in idle state
3. End Call button is NOT visible in idle state

Do NOT test:
- LiveKit connection (requires native platform)
- HTTP calls to server (would need mock server)
- Microphone permission flow (platform-specific)

Integration testing on a real device is required for end-to-end validation (manual, not automated for PoC).

### Pre-Commit Checks (Non-Negotiable)

```bash
cd client && flutter analyze  # Must return "No issues found!" — fix ALL issues including infos
cd client && flutter test     # Must show "All tests passed!"
```

CI/CD fails on ANY `flutter analyze` issue (errors, warnings, OR infos). Even info-level lints must be fixed.

### Previous Story Intelligence

**From Story 1.2 (Build Pipecat Voice Pipeline with Sarcastic Character):**

- Server endpoint: `POST /connect` at `http://167.235.63.129`
- Returns: `{"room_name": str, "token": str, "livekit_url": str}`
- CORS enabled for all origins
- Bot is spawned as subprocess per room — each call creates a new room
- Bot joins as `marcus-bot`, user joins as `user`
- Character speaks first (greeting) via `on_first_participant_joined` event handler
- Character: Marcus, jaded game show host with sarcastic personality
- Cartesia voice: Jace (`6776173b-fd72-460d-89b3-d85812ee518d`) — expressive male
- Barge-in: requires 3+ words to interrupt bot speech
- VAD: `stop_secs=0.3` — slightly longer pause tolerance for non-native speakers

**From Story 1.1 (Initialize Monorepo):**

- VPS IP: `167.235.63.129` (Hetzner CPX22, Nuremberg, Ubuntu 24.04)
- No domain/HTTPS yet — test via IP only (HTTP cleartext needed)
- Flutter project created with `flutter create --org com.surviveTheTalk --platforms ios,android`
- `livekit_client: ^2.6.4` already in pubspec.yaml
- `rive: ^0.14.2` already in pubspec.yaml (not used in this story)
- `analysis_options.yaml` has strict rules: `strict-casts: true`, `strict-raw-types: true`, many lints enabled
- Current `main.dart` is the default counter demo — must be entirely replaced
- Current `widget_test.dart` tests the counter demo — must be entirely replaced

**Debug lessons from previous stories:**
- `flutter analyze` fails on infos too — not just errors/warnings. Fix everything
- pytest exit code 5 when no tests collected — always have at least one test
- Pre-commit validation is strictly enforced before every commit

### Git Intelligence

Recent commits:
```
7145643 feat: build Pipecat voice pipeline with sarcastic character
5be3cea feat: initialize monorepo and deploy server infrastructure
fb5d310 feat: initialize project with complete BMAD planning artifacts
```

Patterns: `feat:` prefix + bulleted list body, no Co-Authored-By.

### Library Versions

| Library | Version | Notes |
|---------|---------|-------|
| livekit_client | ^2.6.4 | Already in pubspec.yaml |
| http | latest | New dependency — add via `flutter pub add http` |
| rive | ^0.14.2 | Already in pubspec.yaml — NOT used in this story |
| flutter_lints | ^6.0.0 | Already in dev_dependencies |

### References

- [Source: architecture.md#Frontend Architecture] — PoC: Zero Architecture, single main.dart
- [Source: architecture.md#Phased Architecture Constraint] — PoC scope: single screen, voice call only
- [Source: architecture.md#Infrastructure & Deployment] — VPS at 167.235.63.129
- [Source: architecture.md#API & Communication Patterns] — /connect endpoint contract
- [Source: epics.md#Story 1.3] — Story requirements and acceptance criteria
- [Source: prd.md#Phase 0 — Proof of Concept] — PoC validation gates
- [Source: 1-2-build-pipecat-voice-pipeline-with-sarcastic-character.md] — Server endpoint details, bot config
- [Source: 1-1-initialize-monorepo-and-deploy-server-infrastructure.md] — VPS setup, Flutter project structure

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

- `roomOptions` parameter deprecated in `Room.connect()` — moved to `Room()` constructor (livekit_client ^2.6.4)
- `EventsListener.dispose()` and `Room.dispose()` return `Future<void>` — must be awaited to satisfy `unawaited_futures` lint
- VPS firewall blocks port 8000 — must use port 80 via Caddy reverse proxy
- Qwen 3.5 Flash thinking mode causes ~16s TTFT — disabled via `extra_body.reasoning.enabled=false` → 1.1s TTFT
- `on_participant_left` handler receives 3 args in pipecat 0.0.108, not 2 — added `reason` param

### Completion Notes List

- Replaced default counter demo with minimal Call screen (single main.dart, no architecture layers)
- Implemented 4-state CallScreen: idle (green Call FAB), connecting (spinner), connected (timer + red End Call FAB), error (message + Retry)
- LiveKit integration: Room connect with adaptive stream/dynacast, mic enable triggers OS permission, RoomDisconnectedEvent listener
- HTTP POST to server /connect endpoint parses token and livekit_url from JSON response
- Dark theme with project colors (#1E1F23 background, #F0F0F0 text), no ColorScheme.fromSeed
- Platform configs: Android permissions (RECORD_AUDIO, INTERNET, BLUETOOTH, etc.) + cleartext traffic; iOS mic description + ATS bypass + background audio
- 3 widget tests verify app renders, Call button visible, End Call button hidden in idle state
- flutter analyze: No issues found; flutter test: 3/3 passed
- Server-side fixes during E2E testing: disabled Qwen thinking mode (reasoning.enabled=false), added /no_think to prompt, fixed on_participant_left signature, switched voice to Preston
- Measured conversational latency: 0.6s–1.6s (AC4 target < 2s satisfied)

### Change Log

- 2026-03-30: Story implementation complete — all 5 tasks done, all ACs satisfied
- 2026-03-30: E2E testing fixes — server URL port 80, Qwen thinking disabled, voice switched to Preston, handler signature fix

### File List

- client/lib/main.dart (REPLACED — Call screen with LiveKit integration)
- client/lib/config.dart (NEW — server URL constant, port 80 via Caddy)
- client/test/widget_test.dart (REPLACED — 3 widget tests for Call screen UI)
- client/pubspec.yaml (MODIFIED — added http dependency)
- client/pubspec.lock (MODIFIED — resolved http dependency)
- client/android/app/src/main/AndroidManifest.xml (MODIFIED — permissions + cleartext traffic)
- client/ios/Runner/Info.plist (MODIFIED — mic description + ATS + background audio)
- server/pipeline/bot.py (MODIFIED — reasoning disabled, on_participant_left fix)
- server/pipeline/prompts.py (MODIFIED — /no_think prefix, voice switched to Preston)
- _bmad-output/implementation-artifacts/sprint-status.yaml (MODIFIED — story status updated)
- .vscode/launch.json (NEW — Flutter debug config for monorepo)
- .vscode/settings.json (NEW — dart.projectSearchDepth for monorepo)
