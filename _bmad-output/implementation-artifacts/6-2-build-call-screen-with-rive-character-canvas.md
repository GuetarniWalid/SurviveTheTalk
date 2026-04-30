# Story 6.2: Build Call Screen with Rive Character Canvas

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to see an animated character on a visually immersive full-screen call,
so that the experience feels like talking to a real person, not using an app.

## Background

Story 6.1 lands the call lifecycle plumbing — `CallScreen` exists, `CallBloc` owns the `Room`, the back-press strategy detaches from `go_router`, and the LiveKit foreground service is wired. But the `CallConnected` state in 6.1 is intentionally a black scaffold with a Flutter-built hang-up button. Story 6.2 is the **render layer** for that scaffold: scenario-specific blurred background, full-screen Rive character canvas with the correct character variant, and the Rive-native hang-up button replacing the Flutter one.

The Rive asset (`client/assets/rive/characters.riv`) shipped in Story 2.6 already exposes everything 6.2 needs: a `character` EnumInput with 5 variants (mugger, waiter, girlfriend, cop, landlord), a built-in 64×64 #E74C3C hang-up button on the canvas, and an `onHangUp` event that fires when the user taps it. Story 4.5 already proved out the Rive 0.14.x integration on the **`Picture`** artboard (head-only avatar for `IncomingCallScreen`); Story 6.2 uses a **different artboard on the same file** — the full-body in-call scene — and is the first place in the app to wire a Rive→Flutter event listener (`onHangUp` → dispatch `HangUpPressed` to `CallBloc`).

This is the second story of Epic 6. Story 6.3 layers on emotion + viseme data channels (Rive ViewModel input updates from LiveKit `DataReceivedEvent`); 6.4 owns silence handling and the `POST /calls/{id}/end` cleanup contract; 6.7 adds the `CheckpointStepper` overlay. The `RiveLoader` + `manifest.json` hot-update infrastructure described in `architecture.md` is **explicitly deferred** out of 6.2 (see "Scope decision: bundled-only Rive load" in Dev Notes).

**Critical reading before starting:**
- `_bmad-output/implementation-artifacts/2-6-create-rive-character-puppet-file.md` — the Rive contract (artboard layout, `character`/`emotion`/`visemeId` EnumInputs, `onHangUp` event, `Fit.cover` design intent).
- `memory/rive-flutter-rules.md` (5 days old at story creation — re-verify against current code) — the 0.14.x integration pattern, fallback gate, enumerator API.
- `client/lib/features/call/views/widgets/character_avatar.dart` — the working reference implementation of the same pattern at smaller scope (head-only avatar, same `characters.riv`).
- `client/CLAUDE.md` Gotcha #6 (token-enforcement test rejects hex literals outside `lib/core/theme/`).

## Acceptance Criteria (BDD)

**AC1 — `CallScreen.CallConnected` renders the layered canvas (background + blur + Rive):**
Given Story 6.1 ships `client/lib/features/call/views/call_screen.dart` with a `CallConnected` state that is currently `Scaffold(backgroundColor: AppColors.background, body: <hang-up button only>)`
When this story lands
Then the `CallConnected` branch of the `BlocBuilder<CallBloc, CallState>` renders the **CallScreenCanvas** layer stack (UX-DR6):
```
Stack(fit: StackFit.expand, children: [
  // Layer 1 — scenario background image (Image.asset)
  Image.asset(<resolved jpg path>, fit: BoxFit.cover, errorBuilder: ...),
  // Layer 2 — gaussian blur (no overlay color, no tint)
  BackdropFilter(filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20), child: const SizedBox.expand()),
  // Layer 3 — full-screen Rive canvas (character + Rive-native hang-up button)
  Positioned.fill(child: <RiveCharacterCanvas widget — see AC3>),
])
```
And the blur sigma uses `20` (mid-point of UX-DR6's 15–25 px range; SizedBox.expand() is required to give BackdropFilter a child to clip against — without one, BackdropFilter is a no-op).
And `Image.asset(...)` uses `BoxFit.cover` (NOT `BoxFit.contain` — would leave bars on tall phones); `errorBuilder` falls back to `Container(color: AppColors.background)` (a solid `#1E1F23`) so a missing JPG never crashes the screen.
And the 60-px Flutter-built hang-up button + `SizedBox(height: 40)` from Story 6.1's `CallConnected` state are **deleted** — the only hang-up affordance in `CallConnected` is the Rive-native button on the canvas (AC4 wires the listener). The `_buildHangUpButton` helper is **kept** because the `CallConnecting` state still needs it (the Rive canvas isn't loaded yet during connect).
And `CallConnecting` is unchanged from Story 6.1 — the dial animation + Flutter hang-up button is still the spec for the connecting moment (the Rive canvas is over-investment for a 1-second state that masks pipeline init).

**AC2 — Background image is resolved from `scenario.riveCharacter` via a 5-entry constant map:**
Given the 5 scenario backgrounds shipped in Story 2.7 are already registered in `pubspec.yaml:81` (`assets/images/scenario_backgrounds/`) and live at `client/assets/images/scenario_backgrounds/{dark_alley,restaurant,apartment_night,street_police,building_hallway}.jpg`
And neither the server scenario YAMLs nor the client `Scenario` model carry a `background_image` field today
And Story 5.2 already established the convention of mapping by `scenario.riveCharacter` for visual assets (`assets/images/characters/${scenario.riveCharacter}.jpg`)
When this story lands
Then a NEW const map lives in `client/lib/features/call/views/scenario_backgrounds.dart`:
```dart
/// Maps a scenario's `riveCharacter` enum value to its background image asset.
/// Keep in sync with `client/assets/images/scenario_backgrounds/`. Adding a
/// new character means adding both the JPG and an entry here.
const Map<String, String> kScenarioBackgrounds = {
  'mugger':     'assets/images/scenario_backgrounds/dark_alley.jpg',
  'waiter':     'assets/images/scenario_backgrounds/restaurant.jpg',
  'girlfriend': 'assets/images/scenario_backgrounds/apartment_night.jpg',
  'cop':        'assets/images/scenario_backgrounds/street_police.jpg',
  'landlord':   'assets/images/scenario_backgrounds/building_hallway.jpg',
};
```
And `CallScreen` reads `kScenarioBackgrounds[widget.scenario.riveCharacter]` when building Layer 1; if the lookup returns null (unknown character), Layer 1 falls back to `Container(color: AppColors.background)` and the Rive canvas still renders normally.
And **DO NOT** add a `background_image` field to `server/pipeline/scenarios/*.yaml`, the `scenarios` DB table, the `/scenarios` API contract, or the `Scenario` Flutter model — the 5 backgrounds are a closed set tied 1:1 to `riveCharacter`, and a server round-trip for what is purely a client visual asset is over-engineering (`feedback_mvp_iteration_strategy.md` — validate fast).

**AC3 — `RiveCharacterCanvas` widget renders the full-body artboard with `Fit.cover`:**
Given Story 4.5's `CharacterAvatar` (`client/lib/features/call/views/widgets/character_avatar.dart`) is the reference 0.14.x pattern at smaller scope (head-only `Picture` artboard for `IncomingCallScreen`)
And the full-body artboard for the in-call scene lives on the **same** `characters.riv` file but at a different artboard name (verify on the actual file — see Dev Notes → "Full-body artboard discovery")
When this story lands
Then a NEW `client/lib/features/call/views/widgets/rive_character_canvas.dart` exposes:
```dart
class RiveCharacterCanvas extends StatefulWidget {
  /// Rive `character` enum value (e.g. 'waiter', 'cop') — must match a value
  /// on the `character` ViewModel enum inside characters.riv.
  final String character;
  /// Fired when the user taps the in-canvas hang-up button (Rive `onHangUp`
  /// event). Wired by CallScreen to dispatch HangUpPressed to CallBloc.
  final VoidCallback? onHangUp;
  const RiveCharacterCanvas({super.key, required this.character, this.onHangUp});
  @override State<RiveCharacterCanvas> createState() => _RiveCharacterCanvasState();
}
```
And the implementation mirrors `CharacterAvatar`'s structure (proven pattern, same Rive file, same gotchas) with **three** differences:
  1. `artboardSelector: rive.ArtboardSelector.byName('<full-body name from Dev Notes>')` instead of `byName('Picture')`. The state-machine selector is verified at implementation time — likely still `'MainStateMachine'` since Story 2.6 specified a single state machine shared across artboards, but it MUST be confirmed by opening the .riv (or by reading Story 2.6's deliverable validation notes).
  2. `Fit.cover` on the `RiveWidget` (same as `CharacterAvatar`) but **without** the `ClipOval` wrapper — the canvas fills the entire screen, not a circle.
  3. After `_onRiveLoaded`, register the hang-up event listener:
```dart
state.controller.stateMachine.addEventListener(_onRiveEvent);
// ...
void _onRiveEvent(rive.RiveEvent event) {
  if (event.name == 'onHangUp') widget.onHangUp?.call();
}
```
And the existing `RiveNative.isInitialized` test gate from `CharacterAvatar` is preserved verbatim (Gotcha #8 + `rive-flutter-rules.md` §6 — Rive native does not load in widget tests).
And the test fallback widget is `Container(color: AppColors.background)` (a solid black-ish surface) — NOT a placeholder Rive avatar (no second-tier asset to load), NOT `SizedBox.shrink()` (would leave the blurred background visible behind, breaking the layer-3 contract).
And the `_riveLoader?.dispose()` call in `dispose()` is preserved AND the event listener is unsubscribed first:
```dart
@override
void dispose() {
  _controller?.stateMachine.removeEventListener(_onRiveEvent);
  _riveLoader?.dispose();
  super.dispose();
}
```
This matches `rive-flutter-rules.md` §5 — failing to unsubscribe leaks the controller for the lifetime of the page route.
And `DataBind.auto()` is used (NEVER `DataBind.byName()` — `rive-flutter-rules.md` §5 says it hangs indefinitely).

**AC4 — Rive `onHangUp` event dispatches `HangUpPressed` through `CallBloc`:**
Given Story 6.1's `CallBloc` already defines `HangUpPressed` as a sealed `CallEvent` and handles it via `_onHangUpPressed` (`await room.disconnect()` → emit `CallEnded`)
When the user taps the hang-up button on the Rive canvas
Then the `onHangUp` Rive event fires (Rive→Flutter, one-way per `rive-flutter-rules.md` §5)
And `CallScreen` (which owns the bloc context) passes a closure into `RiveCharacterCanvas` that reads `context.read<CallBloc>().add(const HangUpPressed())` — this is exactly the same dispatch path as Story 6.1's Flutter button, just triggered from a different source:
```dart
RiveCharacterCanvas(
  character: widget.scenario.riveCharacter,
  onHangUp: () => context.read<CallBloc>().add(const HangUpPressed()),
)
```
And the resulting state transition (`CallConnected` → `CallEnded`) and the root-`Navigator.pop` flow are unchanged from Story 6.1 — Story 6.2 is purely the render-layer rewire, not a lifecycle change.
And the event listener is wired ONLY in the `CallConnected` state — when the bloc is in `CallConnecting` the Rive canvas isn't mounted, so there is no listener to attach. (`CallConnecting` keeps the Flutter `_buildHangUpButton` for connect-cancellation; cancelling during connect already maps to `HangUpPressed` per Story 6.1 AC7.)

**AC5 — `character` EnumInput is set BEFORE the canvas paints the first frame:**
Given the Rive `character` ViewModel enum drives which of the 5 visual variants is rendered (Story 2.6 AC8) and a wrong value silently no-ops (the variant defaults to the first enum case, which can render a different character)
When `RiveCharacterCanvas` loads
Then `_characterEnum?.value = widget.character` is called inside `_onRiveLoaded` BEFORE returning — this is the same contract as `CharacterAvatar` (`character_avatar.dart:87`).
And `didUpdateWidget` updates the enum value when `widget.character` changes (defensive — the call screen never rebuilds with a different scenario in 6.2's flow, but the contract matches `CharacterAvatar` for symmetry and tests will exercise the path).
And NO viseme or emotion EnumInput is touched in this story — those wires belong to Story 6.3 and are explicitly out of scope. Cache the `_characterEnum` reference (`viewModel.enumerator('character')`) but do NOT cache `_emotionEnum` or `_visemeEnum`.
And the `character` enum value used is `scenario.riveCharacter` — the same string the YAML carries (`metadata.rive_character`), the same string the server returns in `/scenarios`, and the same string `CharacterAvatar` already consumes. Zero translation layer.

**AC6 — Zero text on screen during the call (UX-DR6 hard rule):**
Given UX-DR6 mandates "Zero text on screen during calls"
When `CallConnected` is rendering
Then **NO** `Text`, `RichText`, `Tooltip`, `MaterialBanner`, `SnackBar`, `AlertDialog`, `BottomSheet`, or any other text-bearing widget is in the `CallConnected` widget tree.
And `Semantics(label: 'End call', ...)` is wired on the Rive canvas region for screen readers (UX-DR12 / `client/CLAUDE.md` Gotcha #10 alignment) — this is `Semantics`, not `Text`, and is invisible visually.
And the existing `CallConnecting` Flutter "Connecting..." text is unchanged from Story 6.1 — it is NOT in `CallConnected` and the UX-DR6 rule is scoped to the in-call render only (UX-DR11 explicitly allows "Connecting..." as the masking affordance).
And the `CheckpointStepper` overlay is **NOT** added in this story (Story 6.7) — the only on-screen elements during `CallConnected` are: scenario background, blur, Rive canvas (which contains the character + the in-canvas hang-up button), and the invisible `Semantics` node.

**AC7 — Rive native unavailability degrades gracefully (test gate + prod fallback):**
Given `RiveNative.isInitialized` returns `false` in widget tests (test environment never calls `bootstrap()`) and may legitimately return false in prod if `RiveNative.init()` threw at startup (Gotcha #8 — failures are reported via `FlutterError.reportError` but the app continues)
When `RiveNative.isInitialized == false`
Then `RiveCharacterCanvas` skips loading the file and renders `Container(color: AppColors.background)` — a solid layer 3 that hides the blurred background but does not crash.
And the in-canvas hang-up button is unavailable in this fallback path. To preserve the user's exit, `CallScreen.CallConnected` shows the Flutter `_buildHangUpButton` IF AND ONLY IF the Rive canvas is in fallback mode. Implementation: `RiveCharacterCanvas` exposes a `bool get isInFallback` via a `ValueListenable<bool>` or a callback (`onFallback: VoidCallback?`); pick the smaller-API option and document the choice in Dev Notes. NOT acceptable: always rendering the Flutter button on top of a working Rive canvas (would double up the hang-up affordance and break UX-DR6).
And the test plan for AC9 covers the fallback path: a widget test asserts that when `RiveNative.isInitialized` is false, the Flutter hang-up button is mounted and tapping it dispatches `HangUpPressed`.

**AC8 — Performance: 60fps target on Pixel 9 Pro XL, no jank from blur:**
Given the architecture (lines 1020-1024) targets 60fps Rive animation with a 30fps hard floor and `BackdropFilter` is known to be expensive on lower-tier devices
When the call screen is on a real Pixel 9 Pro XL during the smoke test
Then the dev validates with **Flutter DevTools Performance overlay** (or `flutter run --profile` + the on-screen FPS counter) that the `CallConnected` frame rate is sustained at ≥ 55 fps during 30 seconds of character idle animation. Document the observed frame rate range in the smoke-test section below.
And if the blur sigma at 20 px causes jank below the 30 fps floor: **first** try lowering sigma to 15 px (still within UX-DR6 range), and only if that fails revisit a static pre-blurred image asset. Do NOT attempt to disable Impeller or tweak Flutter render settings — those are global concerns out of this story's scope. Document the chosen sigma in Dev Notes.
And the `Image.asset` is loaded once via `precacheImage` in `CallScreen.didChangeDependencies` so the first frame of `CallConnected` doesn't pay the disk read cost. (Optional but recommended — flag in Dev Notes if skipped.)

**AC9 — Test coverage:**
Given the project's test discipline (`client/CLAUDE.md` + Story 5.5 patches: `pumpEventQueue × 8`, `FlutterError.onError` overflow capture, `tester.binding.setSurfaceSize`)
When the story lands
Then the following NEW / UPDATED tests are green:
  - **`client/test/features/call/views/widgets/rive_character_canvas_test.dart`** (NEW) — one test: in the test environment (`RiveNative.isInitialized == false`), the widget renders the fallback `Container(color: AppColors.background)` and does NOT crash. Per `rive-flutter-rules.md` §6, do NOT mock `RiveWidgetBuilder`; only the fallback path is tested.
  - **`client/test/features/call/views/call_screen_test.dart`** (UPDATED from Story 6.1) — add three tests:
    1. `CallConnected` mounts the Stack with three layers in order (Image.asset, BackdropFilter, RiveCharacterCanvas-fallback) — assert via `find.byType(BackdropFilter)` and that it's a sibling of the canvas.
    2. `CallConnected` does NOT render the Flutter `_buildHangUpButton` when `RiveCharacterCanvas` is on the working path (mocked here as: assume `isInFallback == false`). Use a test seam (e.g. expose `bool _isCanvasInFallback` on the State or via a debug constructor parameter) — document the seam in Dev Notes.
    3. `CallConnected` DOES render the Flutter `_buildHangUpButton` when the canvas is in fallback (`RiveNative.isInitialized == false`), and tapping it dispatches `HangUpPressed`. Use the existing `MockCallBloc` pattern from Story 6.1.
  - **`client/test/features/call/views/scenario_backgrounds_test.dart`** (NEW, tiny) — one test asserting the const map has exactly the 5 expected entries with the expected paths. This is a regression net for "someone added a new character but forgot the JPG entry."
  - The 320×480 surface-size + textScaler-1.5 overflow regression test (Story 5.4 / 5.5 pattern) is added to `call_screen_test.dart` — `CallConnected` must not overflow at the smallest supported viewport. Use `tester.binding.setSurfaceSize` per Gotcha #7.
  - `FlutterError.onError` overflow capture (Story 5.4 / 5.5 patch) wraps any new layout test that exercises the layered Stack.
  - `pumpEventQueue()` is used (NOT `Future.delayed(Duration.zero)` and NOT `pumpAndSettle` — the Rive canvas in fallback mode is fine for `pumpAndSettle` but a future test that exercises any continuous animation will hang per Gotcha #3) wherever event-queue flushing is needed.
  - `FlutterSecureStorage.setMockInitialValues({})` is in every test setUp that transitively touches `TokenStorage` (Gotcha #1).
  - `registerFallbackValue` for sealed `CallEvent` is called in `setUpAll` per Gotcha #2 (Story 6.1 already does this; Story 6.2's tests inherit the pattern).

**AC10 — Pre-commit gates:**
Given the project's commit discipline (CLAUDE.md root + `client/CLAUDE.md`)
When the story lands
Then ALL of the following pass before marking the story `review`:
  - `cd client && flutter analyze` → "No issues found!"
  - `cd client && flutter test` → "All tests passed!" — full suite. Story 6.1's baseline (~225-230 tests after its 12-18 net adds) is the floor; this story adds approximately 5-8 net tests (the new + updated cases enumerated in AC9). Final count documented in `## Dev Agent Record → Completion Notes`.
  - The token-enforcement test (`test/core/theme/theme_tokens_test.dart`) passes — Story 6.2 introduces NO hex literals (the only colors used are `AppColors.background` from layer 3 fallback and `BoxFit.cover`-default). Per Gotcha #6, any new color goes in `lib/core/theme/`. Verify with `grep -rn "Color(0x\|Color\\.fromARGB\|Color\\.fromRGBO" client/lib/features/call/views/` returns zero new hits.
  - `flutter analyze` does NOT flag `unused_import` for the deleted `_buildHangUpButton` references in `CallConnected` (the helper itself is kept for `CallConnecting`).
  - **No server changes** — verify `git diff --name-only -- server/` is empty for this story. The Smoke Test Gate is therefore **omitted** below (Flutter-client-only change).

## Tasks / Subtasks

- [ ] **Task 1 — Background image mapping** (AC: #2)
  - [ ] 1.1 — Create `client/lib/features/call/views/scenario_backgrounds.dart` with the `kScenarioBackgrounds` const map (5 entries).
  - [ ] 1.2 — Verify all 5 JPG paths resolve at runtime: `flutter run` and tap each scenario; the layer-1 image renders. Document any missing/renamed asset (none expected — Story 2.7 shipped them).
  - [ ] 1.3 — Add `client/test/features/call/views/scenario_backgrounds_test.dart` asserting the 5 entries.

- [ ] **Task 2 — Discover full-body artboard name on `characters.riv`** (AC: #3)
  - [ ] 2.1 — Open `client/assets/rive/characters.riv` in the Rive editor (Walid has access since Story 2.6) OR write a one-shot inspector script (`flutter run lib/scripts/inspect_rive.dart` style — delete after use). List artboard names and state-machine names.
  - [ ] 2.2 — Identify the full-body artboard (NOT `Picture` — that's the head-only avatar). The Story 2.6 design intent says "single artboard with all states" but the actual file ships ≥2 artboards. Pick the one designed for `Fit.cover` full-screen.
  - [ ] 2.3 — Document the chosen artboard name + state-machine name in Dev Notes → "Full-body artboard discovery" — these become the values inside `RiveCharacterCanvas`.

- [ ] **Task 3 — Build `RiveCharacterCanvas` widget** (AC: #3, #5, #7)
  - [ ] 3.1 — Create `client/lib/features/call/views/widgets/rive_character_canvas.dart`. Copy the structure of `widgets/character_avatar.dart` verbatim, then change: artboard selector, drop the `ClipOval`, drop the `size` parameter (uses parent constraints), add the `onHangUp` callback parameter.
  - [ ] 3.2 — In `_onRiveLoaded`: cache the `_characterEnum`, set `_characterEnum?.value = widget.character`, then `state.controller.stateMachine.addEventListener(_onRiveEvent)` and store `_controller = state.controller` for the dispose unsubscription.
  - [ ] 3.3 — Implement `_onRiveEvent(rive.RiveEvent event)` — if `event.name == 'onHangUp'`, fire `widget.onHangUp?.call()`. No other event names handled in this story (Story 6.3 will add emotion/viseme handling on the same `RiveCharacterCanvas` or move that to a sibling widget).
  - [ ] 3.4 — Implement `dispose()` — unsubscribe the listener BEFORE `_riveLoader?.dispose()`; call `super.dispose()` last.
  - [ ] 3.5 — Implement `didUpdateWidget` — update `_characterEnum?.value` when `widget.character` changes.
  - [ ] 3.6 — Implement the `RiveNative.isInitialized` gate (copy from `character_avatar.dart:67-70`); set `_riveFallback = true` to render the `Container(color: AppColors.background)` fallback.
  - [ ] 3.7 — Expose the fallback signal to the parent: pick ONE of (a) `bool isInFallback` accessed via a `GlobalKey<_RiveCharacterCanvasState>`, (b) `ValueNotifier<bool>` parameter, (c) `onFallback: VoidCallback?` parameter fired once on init when fallback is decided. Recommended: option (c) — fewer moving parts, fires exactly once. Document the choice in Dev Notes.
  - [ ] 3.8 — Add `client/test/features/call/views/widgets/rive_character_canvas_test.dart` — fallback render only (per `rive-flutter-rules.md` §6: never mock `RiveWidgetBuilder`).

- [ ] **Task 4 — Layer the Stack into `CallScreen.CallConnected`** (AC: #1, #4, #6)
  - [ ] 4.1 — In `CallScreen` (`client/lib/features/call/views/call_screen.dart`, owned by Story 6.1), modify the `CallConnected` branch of the `BlocBuilder` to render the Stack of (Image.asset → BackdropFilter → RiveCharacterCanvas) per AC1.
  - [ ] 4.2 — Wire `RiveCharacterCanvas.onHangUp` to `() => context.read<CallBloc>().add(const HangUpPressed())`.
  - [ ] 4.3 — Wrap the canvas in a `Semantics(label: 'End call', button: true, child: ...)` for AC6 / UX-DR12.
  - [ ] 4.4 — Implement the conditional Flutter hang-up button: render `_buildHangUpButton` ONLY when the canvas is in fallback (per AC7 + Task 3.7).
  - [ ] 4.5 — Delete the unconditional `_buildHangUpButton` from the `CallConnected` branch (it stays in `CallConnecting`).
  - [ ] 4.6 — Add `precacheImage(AssetImage(<resolved path>), context)` in `didChangeDependencies` (recommended — saves first-frame disk read). Skip if the dev decides the optimization isn't worth the line; document in Dev Notes.

- [ ] **Task 5 — Test coverage** (AC: #9)
  - [ ] 5.1 — Add the three new `call_screen_test.dart` cases (Stack layers, hang-up source under canvas-working, hang-up source under canvas-fallback). Use `MockCallBloc` from Story 6.1.
  - [ ] 5.2 — Add the 320×480 + textScaler 1.5 overflow regression test (Gotcha #7 + Story 5.4/5.5 pattern; capture overflow via `FlutterError.onError`).
  - [ ] 5.3 — Add the `rive_character_canvas_test.dart` fallback render test.
  - [ ] 5.4 — Add the `scenario_backgrounds_test.dart` map-content regression test.
  - [ ] 5.5 — Run `flutter test` and confirm ALL tests pass (not just the new ones).

- [ ] **Task 6 — Performance verification on Pixel 9 Pro XL** (AC: #8)
  - [ ] 6.1 — `flutter run --profile` on Pixel 9 Pro XL.
  - [ ] 6.2 — Tap a scenario (waiter or any other), enter the call, observe the on-screen FPS counter (or DevTools Performance overlay) for 30 seconds during character idle animation.
  - [ ] 6.3 — Document observed FPS range in the smoke-test verification block (e.g. "55-60 fps sustained at sigma 20") AND in `## Dev Agent Record → Implementation Notes`.
  - [ ] 6.4 — If FPS < 30, lower blur sigma to 15. If still < 30, escalate to Walid before shipping (a static pre-blurred asset is a Plan C requiring a re-run of Story 2.7).

- [ ] **Task 7 — Pre-commit gates and sprint-status update** (AC: #10)
  - [ ] 7.1 — `cd client && flutter analyze` clean.
  - [ ] 7.2 — `cd client && flutter test` green; document new total in completion notes.
  - [ ] 7.3 — Verify no server diff (`git status --porcelain server/` is empty).
  - [ ] 7.4 — Verify no new hex literals leaked outside `lib/core/theme/`: `grep -rn "Color(0x\|Color\\.fromARGB\|Color\\.fromRGBO" client/lib/features/call/views/ | grep -v "^.*:[0-9]*://"` returns zero new hits compared to the Story 6.1 baseline.
  - [ ] 7.5 — Flip `sprint-status.yaml` for `6-2-...` from `in-progress` → `review` (story file frontmatter Status field updated simultaneously per project memory `## Sprint-Status Discipline`).
  - [ ] 7.6 — Wait for explicit `/commit` from Walid (per project memory `## Git Commit Rules`).

## Dev Notes

### Story is Flutter-client-only — Smoke Test Gate omitted

This story modifies only `client/lib/features/call/views/`, `client/lib/features/call/views/widgets/`, and `client/test/features/call/...`. No server endpoint changes, no DB migration, no VPS deployment. Per the workflow's gate scope rule, the **Smoke Test Gate section is omitted entirely**. The on-device performance verification (Task 6) is covered inside this story's body, not as a server-deploy gate.

### Scope decision: bundled-only Rive load (hot-update deferred)

**The epic AC text** (line 1051 of `epics.md`) says the character "is loaded via the Rive hot-update pattern: check manifest.json → download if newer → cache locally → load from bytes (File.decode)." **This story ships bundled-only loading** via `FileLoader.fromAsset`, mirroring the working `CharacterAvatar` pattern. The hot-update infrastructure (manifest endpoint, `RiveLoader`, version arbitration, cache invalidation) is deferred.

**Why deferred:**
1. The bundled file works today (Story 4.5 proved it on the same `characters.riv`). Shipping the simpler path first matches `feedback_mvp_iteration_strategy.md` ("validate fast, iterate on render").
2. The hot-update path requires server work (`server/static/rive/manifest.json`, version-bump tooling, Caddy static-file route) that Story 6.2 does not own. Adding it would double the surface area.
3. Story 2.6's own deliverable note says: "for development/this story: file placed in `client/assets/rive/character.riv` as bundled asset" — bundled-first is the established pragmatic path.
4. Epic 9 (Offline Access & Data Sync) is the natural home for the hot-update infrastructure: Story 9.1 builds a local cache with sqflite, and the manifest+riv hot-update is a near-relative of that cache pattern. **Recommended follow-up:** add an issue in `deferred-work.md` titled "Rive hot-update infrastructure (manifest + RiveLoader + bundled fallback)" pointing at the `architecture.md` lines 359-365 + `2-6-create-rive-character-puppet-file.md` Hot-Update section.

This is a documented deviation from the literal epic AC text; surface it in `## Dev Agent Record → Implementation Notes → Deviation #1` per Story 5.4's pattern.

### Full-body artboard discovery (Task 2)

`characters.riv` (58 KB, exported by Story 2.6) ships ≥2 artboards. Only `Picture` is documented and used today (`character_avatar.dart:109` — head-only avatar for `IncomingCallScreen`). The full-body artboard for the in-call full-screen scene is on the same file but at a different name — Story 2.6's design spec said "single artboard" but the actual deliverable diverged.

**How to discover the name** — pick the path that fits the dev's environment:
- **Path A (recommended if Walid has Rive editor open):** open `client/assets/rive/characters.riv` in the Rive editor; the artboard list is in the left panel. Pick the one whose canvas is full-body (not the `Picture` head crop). Note its name and the name of its state machine (likely still `MainStateMachine` from Story 2.6).
- **Path B (programmatic):** write a one-shot inspector that calls `rive.File.decode(bytes)` and iterates `file.artboards`. Run it once via `dart run` (Flutter not required), capture stdout, then **delete** the script (it has no place in `lib/`).
- **Path C (last resort):** if neither path works, ship with `ArtboardSelector.byDefault()` and the first artboard wins. This is the same default used everywhere except `CharacterAvatar`. **Risk:** the default may be `Picture` (head-only), in which case the call screen would show a tight head crop instead of a full-body scene — a visible regression. Path C is a fallback; document the choice in Dev Notes if used.

Once discovered, the names are passed verbatim to `ArtboardSelector.byName(...)` and `StateMachineSelector.byName(...)` inside `RiveCharacterCanvas`. A wrong name throws at render time (per `rive-flutter-rules.md` §8 — "no silent fallback") with a "artboard not found" / "state machine not found" message.

### Hang-up affordance: Rive-native primary, Flutter fallback secondary (AC4 + AC7)

The hang-up button has been a Flutter `_buildHangUpButton` since Story 4.5's `CallPlaceholderScreen`. Story 6.1 kept that helper because the bare `CallConnected` scaffold needed something to tap. Story 6.2 transitions to the Rive-native button — but only when the Rive canvas is actually working. The matrix:

| Bloc state | Rive canvas | Hang-up button source |
|---|---|---|
| `CallConnecting` | Not mounted | Flutter `_buildHangUpButton` (Story 6.1, unchanged) |
| `CallConnected` (Rive working) | Mounted, `RiveNative.isInitialized == true` | Rive-native button on canvas → fires `onHangUp` event |
| `CallConnected` (Rive fallback) | Mounted but in `_riveFallback` mode | Flutter `_buildHangUpButton` overlaid on the fallback Container |
| `CallError(...)` | Not mounted | Story 6.1's fade-out + pop (unchanged) |

The "Rive working" branch is the production path 99% of the time. The fallback branch matters in two cases: widget tests (no `RiveNative.init()` ever ran) and any prod device where `RiveNative.init()` failed at bootstrap (logged via `FlutterError.reportError` per Gotcha #8 — extremely rare but real).

Do NOT show both buttons at once. The fallback signal from `RiveCharacterCanvas` (option (c) `onFallback` callback per Task 3.7) gates the Flutter button render in `CallScreen.State`.

### Why a constant map, not a server field (AC2)

The 5 background JPGs are a closed set (one per character, 1:1). Adding a `background_image` column to `scenarios` (DB) + a field to the YAML + a field to the API contract + a field to the Flutter `Scenario` model would:
- Touch the server (migration, schema, route validation)
- Refresh `tests/fixtures/prod_snapshot.sqlite`
- Modify `/scenarios` envelope contract (and downstream tests in `scenarios_test.dart`)
- Add zero product value — the path is uniquely determined by `riveCharacter`

Story 5.2 already settled this idiomatically: `scenario_card.dart` resolves `assets/images/characters/${scenario.riveCharacter}.jpg` for the avatar thumbnail with no DB field. Story 6.2 mirrors that pattern. Adding a new character (e.g. a sixth scenario) means adding the JPG, the `kScenarioBackgrounds` entry, and the Rive variant — three local edits, no server touch. This is exactly the right amount of friction for an asset that is a client visual concern.

If a future product requirement makes background images dynamic (per-scenario theming, A/B variants, user-uploaded backgrounds), the field promotion is straightforward and isolated. Today, premature.

### Reused patterns from previous stories

- **Rive 0.14.x integration with `RiveNative.isInitialized` gate** — `character_avatar.dart` is the canonical reference. Copy its structure verbatim and edit the three deltas (artboard, ClipOval, hang-up listener).
- **Sealed events with concrete `registerFallbackValue`** (Gotcha #2) — Story 6.1's `CallEvent` is sealed; `setUpAll` registers a concrete event. Story 6.2 inherits this pattern through the existing `MockCallBloc` test helpers.
- **`pumpEventQueue()` over `Future.delayed(Duration.zero)`** (Story 5.5 patch) — used for any test that needs the event queue to flush. Avoid `pumpAndSettle` for any continuous animation (Gotcha #3); the Rive canvas in fallback mode doesn't animate, so `pumpAndSettle` is safe there only.
- **`FlutterError.onError` capture in widget tests** (Story 5.4 / 5.5) — assert no overflow during `CallScreen` Stack tests at 320×480 textScaler 1.5.
- **`tester.binding.setSurfaceSize(...)`** (Gotcha #7) — small-phone overflow regression for the layered Stack.
- **`FlutterSecureStorage.setMockInitialValues({})`** (Gotcha #1) — every test setUp that transitively touches `TokenStorage`.
- **State carrying `previousState`** (Story 4.x + 5.5 pattern) — not directly applicable here (no new error state), but a `CallError(reason: String)` from Story 6.1 already follows this style and Story 6.2 doesn't change it.

### Anti-patterns to avoid (LLM-developer disaster prevention)

- ❌ **Do NOT** add a `background_image` field to `server/pipeline/scenarios/*.yaml`, the DB schema, the `/scenarios` API contract, or the `Scenario` Flutter model. The const map is the spec. (See AC2 + "Why a constant map" above.)
- ❌ **Do NOT** build out the `core/rive/rive_loader.dart` + `core/rive/rive_manifest.dart` + server `static/rive/manifest.json` infrastructure in this story. That's deferred (see "Scope decision: bundled-only Rive load" above).
- ❌ **Do NOT** mock `RiveWidgetBuilder` or any Rive widget in tests. `rive-flutter-rules.md` §6 — test the fallback widget only. The `RiveNative.isInitialized` gate is the test boundary.
- ❌ **Do NOT** use `DataBind.byName()` — `rive-flutter-rules.md` §5 says it hangs indefinitely. Always `DataBind.auto()`.
- ❌ **Do NOT** use `Fit.contain` on the Rive canvas — `rive-flutter-rules.md` §4 says it leaves black bars. Always `Fit.cover` for full-screen.
- ❌ **Do NOT** subscribe to `emotion`, `visemeId`, or any LiveKit `DataReceivedEvent` in this story — those wires are Story 6.3. Cache `_characterEnum` only.
- ❌ **Do NOT** keep BOTH the Rive-native and Flutter hang-up buttons rendered at the same time. The fallback signal gates the Flutter one — see "Hang-up affordance" above.
- ❌ **Do NOT** add `Text`, `SnackBar`, `Tooltip`, `MaterialBanner`, `AlertDialog`, or any text-bearing widget to the `CallConnected` widget tree. UX-DR6 is a hard rule and `client/CLAUDE.md` Gotcha #10 reinforces it. `Semantics(label: ...)` is invisible and IS allowed.
- ❌ **Do NOT** introduce a hex-color literal anywhere in `lib/features/call/`. Token-enforcement test (Gotcha #6) will fail the build. Use `AppColors.background` for the fallback Container, no other colors are needed.
- ❌ **Do NOT** call `Navigator.of(context).pop()` from `CallScreen.build` or any handler in this story. Story 6.1's exit flow is unchanged — `HangUpPressed` → `CallEnded` → root-Navigator pop is owned by Story 6.1's plumbing.
- ❌ **Do NOT** forget `state.controller.stateMachine.removeEventListener(_onRiveEvent)` in `dispose()`. `rive-flutter-rules.md` §5 — leaks the controller for the lifetime of the page route.
- ❌ **Do NOT** assume the full-body artboard is named `MainArtboard`, `Stage`, `Body`, or `FullBody` without verifying. The Story 2.6 design spec said "single artboard," the actual file ships ≥2 artboards, and only `Picture` is documented. Verify via Path A/B from Task 2.

### Files to change

**Client (created):**
- `client/lib/features/call/views/scenario_backgrounds.dart` (NEW — `kScenarioBackgrounds` const map)
- `client/lib/features/call/views/widgets/rive_character_canvas.dart` (NEW)
- `client/test/features/call/views/scenario_backgrounds_test.dart` (NEW)
- `client/test/features/call/views/widgets/rive_character_canvas_test.dart` (NEW)

**Client (modified):**
- `client/lib/features/call/views/call_screen.dart` — `CallConnected` branch rebuilt as the layered Stack; conditional Flutter hang-up button per AC7; optional `precacheImage` in `didChangeDependencies`
- `client/test/features/call/views/call_screen_test.dart` — add Stack-layers test, hang-up-source-canvas-working test, hang-up-source-canvas-fallback test, 320×480 + textScaler 1.5 overflow test

**No changes to:**
- Server (any path)
- DB schema or migrations
- `pubspec.yaml` (assets and rive package already declared)
- `client/lib/app/router.dart` (Story 6.1 already removed `/call`)
- `client/lib/features/call/bloc/call_bloc.dart` (Story 6.1's lifecycle is the spec)
- `client/lib/features/call/bloc/call_event.dart` / `call_state.dart` (`HangUpPressed` already exists)
- `client/lib/features/call/repositories/call_repository.dart` (Story 6.1's contract)
- `client/lib/features/scenarios/views/scenario_list_screen.dart` (already passes scenario to `CallScreen`)
- `client/lib/features/call/views/widgets/character_avatar.dart` (head-only avatar continues to work for `IncomingCallScreen`; ZERO drift between this story and Story 4.5's pattern)
- `client/android/app/src/main/AndroidManifest.xml` (Story 6.1 already added the foreground-service permissions)

### Project Structure Notes

- `lib/features/call/views/widgets/` already exists and contains `character_avatar.dart` (Story 4.5). Adding `rive_character_canvas.dart` alongside is consistent. The two widgets share zero code by intent — they consume the same `.riv` file but at different artboards and with different surface contracts (head circle vs. full-screen scene). Refactoring out a common base is **not** justified at N=2 (`feedback_mvp_iteration_strategy.md` — three similar lines is better than premature abstraction); the third Rive widget would be the trigger to revisit.
- `lib/features/call/views/scenario_backgrounds.dart` is a tiny module — could equivalently live in `lib/core/scenarios/` or `lib/features/scenarios/`. **Place it in `lib/features/call/views/`** because the only consumer is `CallScreen` and the data is a render concern, not a scenario-domain concern. Co-locating with the consumer keeps the call surface self-contained.
- Test mirror: `client/test/features/call/views/widgets/` does NOT exist today (verified at story-creation time). The dev creates it for `rive_character_canvas_test.dart`. This matches the `lib/` mirror convention.

### References

- [Epic 6 §Story 6.2](../planning-artifacts/epics.md) — original AC source (lines 1036-1065).
- [Story 6.1 Implementation](6-1-build-call-initiation-from-scenario-list-with-connection-animation.md) — `CallScreen`, `CallBloc`, `CallEvent.HangUpPressed`, root-Navigator push, `_buildHangUpButton`, `_buildPulsingDots`. Read end-to-end before starting.
- [Story 2.6 Rive Character Puppet](2-6-create-rive-character-puppet-file.md) — the `.riv` contract: `character` / `emotion` / `visemeId` EnumInputs, `onHangUp` event, hang-up button visual spec, file placement, design intent for `Fit.cover`.
- [Story 4.5 First-Call Incoming Call Experience](4-5-build-first-call-incoming-call-experience.md) — `CharacterAvatar` reference implementation, `Picture` artboard convention, `ViewModelInstanceEnum` API.
- [Architecture: Rive 0.14.x Integration Rules](../planning-artifacts/architecture.md) — non-negotiable rules (lines 184-208).
- [Architecture: Frontend Architecture / Rive Hot-Update Pattern](../planning-artifacts/architecture.md) — design intent for hot-update (lines 359-365). **Deferred — see "Scope decision" above.**
- [Architecture: Performance Targets — 60fps Rive](../planning-artifacts/architecture.md) — frame-rate floor (lines 1019-1024).
- [UX Design Specification §Phase 1: Call Screen](../planning-artifacts/ux-design-specification.md) — UX-DR6 CallScreenCanvas spec (lines 211, 627-634, 1020-1041).
- [UX Design Specification §Visual Design / Component Inventory](../planning-artifacts/ux-design-specification.md) — `BackdropFilter` declared as the gaussian-blur primitive (line 959).
- [Rive Character Creation Guide](../planning-artifacts/rive-character-creation-guide.md) — Story 2.6's manual handoff document; artboard configuration (line 40), hang-up button position (line 141).
- `memory/rive-flutter-rules.md` — Rive 0.14.x integration patterns (5 days old at story creation; verify against current code).
- `memory/feedback_mvp_iteration_strategy.md` — "validate fast, iterate on render."
- `client/CLAUDE.md` — Flutter gotchas (especially #1, #2, #3, #6, #7, #8, #10).
- LiveKit Flutter SDK 2.6.x — no new touch in 6.2; the `Room` is owned by Story 6.1's `CallBloc`.

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Implementation Notes

<!-- Populated during implementation. Document:
(a) full-body artboard name + state-machine name discovered (Task 2);
(b) fallback-signal API chosen (option a/b/c per Task 3.7);
(c) blur sigma chosen + observed FPS range on Pixel 9 Pro XL;
(d) whether `precacheImage` was applied;
(e) Deviation #1 from literal epic AC text — bundled-only Rive load (hot-update deferred) — per "Scope decision" in Dev Notes;
(f) any other deviation from the AC text and why. -->

### Debug Log References

### Completion Notes List

### File List

### Notes for Reviewer — conscious choices

<!-- Populated during implementation. -->
