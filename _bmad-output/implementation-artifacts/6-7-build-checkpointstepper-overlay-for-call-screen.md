# Story 6.7: Build CheckpointStepper Overlay for Call Screen

Status: done  <!-- 2026-05-20: Smoke Test Gate 11/11 boxes validated on Pixel 9 Pro XL post Deviation #8 server fix. Code review complete (16/16 patches applied + 3 decisions resolved + 5 deferred + 4 dismissed). -->


<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to see my progress through scenario checkpoints and a hint about what to do next during the call,
so that I understand what's expected of me and feel a sense of progression.

## Background

Story 6.6 turned the call into a state machine: `CheckpointManager` (server-side Pipecat FrameProcessor) judges every finalized user turn against the current checkpoint's `success_criteria`, swaps `llm._settings.system_instruction` in-place on advance, and broadcasts `{"type":"checkpoint_advanced","data":{"checkpoint_id","index","total","next_hint"}}` over the LiveKit data channel. **6.6 is the server brain. 6.7 is the matching client face.** Today that envelope hits the `default` branch of `client/lib/features/call/services/data_channel_handler.dart:129-138` and falls into `dev.log(level: 700)` — `journalctl` on the VPS confirms the wire is alive (call_id=108 emitted 5× `checkpoint_advanced` lines on 2026-05-18) but the user sees nothing on screen.

**Major architectural pivot from the original spec draft: the visual stepper is a Rive file (`checkpoint_stepper.riv`), NOT a custom Flutter widget.** Walid designs and animates the entire HUD in Rive — circles, connecting lines, fill transitions. Flutter's only job is to load the file once and set 2 ViewModel properties when data-channel envelopes arrive. This pattern is now project policy (see project memory `feedback_hud_overlays_are_rive.md`).

> ⚠️ **2026-05-19 amendment (Deviation #5):** The hint bubble that originally lived inside the `.riv` was moved to a Flutter widget (`CheckpointHintBubble`) after the Rive native runtime Hug-Height bug was confirmed (see `memory/feedback_rive_runtime_hug_height_bug.md`). The bubble fill (`#F0F0F0`), text color, visibility logic, and cross-fade animation now live in Dart code. Walid re-exported the `.riv` 2026-05-19 with the bubble element removed; only the stepper row remains there.

**The Rive file contract** (authored by Walid, delivered to dev when Phase 1 is done):
- **File:** `client/assets/rive/checkpoint_stepper.riv` (bundled asset, same delivery channel as `characters.riv`, NOT hot-update).
- **ViewModel inputs** (names exactly as below — Rive 0.14.x's null-safe writes silently no-op on a typo):
  - `stepsCount` — `number`. Total checkpoint count for the scenario (CONSTANT per call). The state machine draws this many circles + connectors. (Per Deviation #6 — previously documented in Deviation #3 as 1-based current step.)
  - `lastCheckIndex` — `number`. Index of the last completed checkpoint, 0-based. `0` = first checkpoint just became current; `N` = all N checkpoints completed (call ended in survival).
  - ~~`hint_text` — `string`. Current hint to display. Empty string `""` ⇒ the Rive file hides the hint bubble entirely; non-empty ⇒ bubble appears with the new text.~~ **SUPERSEDED 2026-05-19 by Deviation #5** — the bubble is now a Flutter widget. The Dart code still writes `hintText` to the ViewModel defensively (`?.value =` is null-safe), so a future `.riv` that re-introduces a bound element would pick it up; if you do that, you MUST remove `CheckpointHintBubble` from `call_screen.dart` to avoid double-render.
- **Visual contract** (everything inside the Rive file, NOT in Flutter):
  - Horizontal rectangle, positioned at the top of the call screen above the character.
  - Animates progress between `lastCheckIndex` values automatically.
  - ~~Hint bubble visibility is driven by `hint_text` emptiness — Flutter writes `""` to hide, the hint string to show.~~ **Bubble is now Flutter-side per Deviation #5.**
  - Color tokens used inside the `.riv`: `#F0F0F0` (off-white typo), ~~`#1E1F23` (background — bubble fill at ~80% opacity)~~ *(bubble removed from .riv per Deviation #5)*, `#8A8A95` (grey — future state), `#00E5A0` (accent — completed). All already exist as `AppColors` tokens server-side of any Flutter glue layer. The Flutter bubble fill reuses `AppColors.textPrimary` (`#F0F0F0`).
- **Asset selectors** (verify on delivery; dev to confirm with Walid if names diverge): default artboard + default state machine is acceptable for a single-purpose file; if Walid ships named selectors (`ArtboardSelector.byName('Stepper')`, `StateMachineSelector.byName('Main')`), dev plumbs them. Default works as long as the `.riv` ships with a single artboard + single state machine.

**Two-phase delivery so the dev is never blocked on the `.riv` arriving:**

- **Phase 1** — Everything that does NOT touch the `.riv` file. Dev can complete this in isolation, run the full pre-commit gate (analyze + test + ruff + pytest), and push. Order: server emit + payload typing + state plumbing + reconcile logic + non-Rive tests.
- **Phase 2** — The Rive widget itself. Dev requests the `.riv` from Walid, Walid drops it at `client/assets/rive/checkpoint_stepper.riv`, dev wires the loader + ViewModel binding + Stack integration + smoke gate on device.

**Three up-front spec deviations to document in Implementation Notes:**

1. **(Deviation #1)** No `v: 1` schema version field on the `checkpoint_advanced` envelope — retires deferred-work.md line 396. Rationale: no precedent (no `v` on `emotion`, `viseme`, `hang_up_warning`, `call_end`, `bot_speaking_ended`). Future field additions go under `data.{}` (additive — old clients silently ignore unknown keys). Breaking changes use a new `type` string.
2. **(Deviation #2)** Client reconciles stepper state from `call_end.checkpoints_passed` to close Story 6.6 deferred-work line 406 (cancel-mid-flight envelope-lost race). Triggered before `RemoteCallEnded` is dispatched.
3. ~~**(Deviation #3)** **The Rive file uses 1-based `stepsCount`, NOT 0-based.** The server emits 0-based `index` (Story 6.6 convention: `index=0` = first checkpoint just became current). The Flutter glue translates `index → index + 1` before writing `stepsCount`. Walid designs the `.riv` against 1-based for human-readable authoring ("step 1 of 6" reads naturally). Wire stays 0-based for backward compatibility with Story 6.6 server code. Translation lives in exactly one place (the `onCheckpointAdvanced` callback in `_CallScreenState`); document with an inline comment.~~ **SUPERSEDED 2026-05-19 by Deviation #6** — `stepsCount` is now the TOTAL number of checkpoints (constant per call) and `lastCheckIndex` carries the 0-based index. See AC Amendments + Deviation #6 below.

**Critical reading before starting:**

- `_bmad-output/planning-artifacts/epics.md` lines 1203-1230 — canonical AC source for 6.7.
- `_bmad-output/planning-artifacts/ux-design-specification.md` lines 1073-1106 — original component spec. Now superseded for the visual layer (the Rive file owns everything). The spec is still useful as the **functional contract** (when to show what state, accessibility expectations).
- `_bmad-output/implementation-artifacts/6-6-build-checkpointmanager-and-checkpoint-aware-exchangeclassifier.md` AC2 #4-6 — canonical `checkpoint_advanced` envelope shape (`checkpoint_id`, `index`, `total`, `next_hint`).
- `_bmad-output/planning-artifacts/architecture.md` lines 606-618 — data channel envelope formats.
- `client/lib/features/call/views/widgets/rive_character_canvas.dart` (entire file, 275 lines) — **the reference implementation pattern.** Story 6.7's Rive widget mirrors this file's structure: `StatefulWidget`, `_initRive()` in `initState`, `FileLoader.fromAsset` + `RiveWidgetBuilder` + `DataBind.auto()` + `onLoaded` caching ViewModel handles, `_riveFallback` flag + `_enterFallback()` for `RiveNative.isInitialized == false`. The hang-up event listener pattern is the only piece you DON'T need (the stepper emits no events upstream).
- `client/lib/features/call/services/data_channel_handler.dart` (entire file, 165 lines) — the envelope dispatcher you extend. **Existing pattern:** every case validates the `data` map shape, defaults gracefully, logs at `dev.log(level: 700)` on shape drift. Match this rigor for `checkpoint_advanced`.
- `client/lib/features/call/views/call_screen.dart` lines 680-744 — the `_buildConnected` Stack you compose into. The Rive stepper goes as a NEW Stack child AFTER the Rive character `Positioned.fill` (so it paints ON TOP) BUT BEFORE the conditional `if (_canvasInFallback)` fallback hang-up button. See AC4 below.
- `client/CLAUDE.md` (whole file) — every Flutter gotcha that bit a prior story. §1 (FlutterSecureStorage mock — N/A here, no storage coupling), §3 (`pumpAndSettle` hangs on continuous animations — Rive animations are continuous, NEVER use `pumpAndSettle` in stepper tests), §7 (force phone surface size).
- `memory/rive-flutter-rules.md` (24 days old — verify against current `rive_character_canvas.dart` before asserting any specific API) — Rive 0.14.x integration rules. **§5 critical traps:** `DataBind.byName()` is forbidden (infinite hang — always `DataBind.auto()`); `Fit.contain` for full-screen causes black bars (use `Fit.cover` or `Fit.layout`); bidirectional events are forbidden (Rive→Flutter via `addEventListener`, Flutter→Rive via ViewModel properties only). **§6 test fallback:** widget tests can't load Rive natively — gate on `RiveNative.isInitialized` and fall back to a `SizedBox.shrink()` or `Container`.
- `client/pubspec.yaml` (around the `assets/rive/` block) — assets are listed individually (`- assets/rive/characters.riv`), not by directory. Add `- assets/rive/checkpoint_stepper.riv` in Phase 2 when the file arrives.
- `_bmad-output/implementation-artifacts/deferred-work.md` lines 396 (envelope versioning — retired by Deviation #1), 406 (envelope partial-execution race — retired by Deviation #2).
- Project memory `feedback_hud_overlays_are_rive.md` — the policy this story established.

**Hard prerequisite: Story 6.6 must be `done` before opening dev-story 6.7.** Verify via `grep -E "^\s+6-6.*: done" _bmad-output/implementation-artifacts/sprint-status.yaml`. (6.6 was flipped to `done` 2026-05-18 — should be safe.)

## Acceptance Criteria (BDD)

### Phase 1 — Independent of the `.riv` file

**AC1 — Server: emit `checkpoint_advanced` at index=0 on bot startup (initial state):**

Given `server/pipeline/checkpoint_manager.py` already exposes `_classify_and_advance` which pushes an `OutputTransportMessageFrame` envelope on intermediate advances
And `server/pipeline/bot.py::run_bot` has the `on_first_participant_joined` callback hook where Story 6.4 queues the canned greeting `TTSSpeakFrame`
When this story lands
Then `CheckpointManager` gains a NEW public async method `emit_initial_state() -> None` that pushes:

```python
await self.push_frame(
    OutputTransportMessageFrame(message={
        "type": "checkpoint_advanced",
        "data": {
            "checkpoint_id": self._checkpoints[0]["id"],
            "index": 0,
            "total": len(self._checkpoints),
            "next_hint": self._checkpoints[0]["hint_text"],
        },
    }),
    FrameDirection.DOWNSTREAM,
)
logger.info(
    "checkpoint_initial_state total={} first_id={}",
    len(self._checkpoints), self._checkpoints[0]["id"],
)
```

And `bot.py::run_bot::on_first_participant_joined` is extended to call `checkpoint_manager.schedule_initial_emit()` AFTER the existing greeting `TTSSpeakFrame` queue. No mutation of `self._index` (still 0); the envelope is purely informational. **AMENDED 2026-05-19 (Deviation #7)** — original spec required `await emit_initial_state()`; replaced with the synchronous `schedule_initial_emit()` flag pattern because the direct call raced with pipecat's `StartFrame` propagation. `emit_initial_state()` is kept for legacy push-path test coverage but not invoked from `bot.py` anymore.

And 2 net new server tests land (**AMENDED test names 2026-05-19 per Deviation #7**):
1. `server/tests/test_checkpoint_manager.py::test_build_initial_envelope_returns_index_zero_frame` + `test_schedule_initial_emit_pushes_envelope_on_first_process_frame` (legacy `test_emit_initial_state_pushes_index_zero_envelope` retained for push-path coverage) — load The Waiter, assert the built/pushed envelope has `index=0`, `total=6`, `checkpoint_id="greet"`, `next_hint=` the YAML's first hint. Use the existing `_capture_pushed` pattern from `test_emotion_emitter.py`.
2. ~~`server/tests/test_bot_pipeline_wiring.py::test_on_first_participant_joined_calls_emit_initial_state`~~ → `test_on_first_participant_joined_queues_initial_envelope_via_task` (renamed per Deviation #7) — source-text assertion: `bot.py::on_first_participant_joined` calls `schedule_initial_emit()` and does NOT call `emit_initial_state()` (regression-guard against reinstating the broken pattern).

**AC2 — Client: `DataChannelHandler` routes `checkpoint_advanced` to a typed callback:**

Given `client/lib/features/call/services/data_channel_handler.dart:129-138` currently silently ignores `checkpoint_advanced` via the `default` branch
And the file's established pattern is: validate every `data` field with `is String` / `is num` / `is Map` checks, default on missing/wrong-type, log at `dev.log(level: 700)` on drift, NEVER throw, NEVER surface to UI
When this story lands
Then the `DataChannelHandler` constructor signature gains a new required callback:

```dart
required void Function(CheckpointAdvancedPayload payload) onCheckpointAdvanced,
```

And a NEW value class lives at `client/lib/features/call/services/checkpoint_advanced_payload.dart`:

```dart
/// Story 6.7 — typed payload for the `checkpoint_advanced` data-channel
/// envelope (server-side emitter: pipeline/checkpoint_manager.py).
///
/// Wire format: `{type: "checkpoint_advanced", data: {checkpoint_id,
/// index, total, next_hint}}`. The `data` map is validated by
/// [DataChannelHandler] before this class is constructed; consumers
/// receive a fully-shaped, non-null instance.
///
/// `index` is the position the stepper has JUST entered (0-based).
/// `total` is the total checkpoint count. `hintText` is the hint
/// to show for the CURRENT checkpoint (server-side field name
/// `next_hint` is retained on the wire; renamed here for clarity).
class CheckpointAdvancedPayload {
  final String checkpointId;
  final int index;
  final int total;
  final String hintText;

  const CheckpointAdvancedPayload({
    required this.checkpointId,
    required this.index,
    required this.total,
    required this.hintText,
  });
}
```

And the `case 'checkpoint_advanced':` block parses with the SAME rigor as `case 'hang_up_warning'`:

```dart
case 'checkpoint_advanced':
  // Story 6.7 — server emits this on initial-state (index=0 at bot
  // startup) AND on every checkpoint advance (index>0). Single
  // envelope shape for both; client treats them identically.
  final id = data['checkpoint_id'];
  final idx = data['index'];
  final total = data['total'];
  final hint = data['next_hint'];
  if (id is! String ||
      idx is! num ||
      total is! num ||
      hint is! String) {
    dev.log(
      'DataChannelHandler: checkpoint_advanced malformed payload: '
      'id=${id.runtimeType} idx=${idx.runtimeType} '
      'total=${total.runtimeType} hint=${hint.runtimeType}',
      name: 'call.data',
      level: 700,
    );
    return;
  }
  final idxInt = idx.toInt();
  final totalInt = total.toInt();
  // Defensive: server-side bug or future spec drift that sends
  // index > total-1, or total <= 0, must not crash the stepper.
  if (totalInt <= 0 || idxInt < 0 || idxInt >= totalInt) {
    dev.log(
      'DataChannelHandler: checkpoint_advanced out-of-range: '
      'idx=$idxInt total=$totalInt',
      name: 'call.data',
      level: 700,
    );
    return;
  }
  _onCheckpointAdvanced(CheckpointAdvancedPayload(
    checkpointId: id,
    index: idxInt,
    total: totalInt,
    hintText: hint,
  ));
```

And the existing `default` branch comment line referencing Story 6.7 is REMOVED (replaced by the case body).

And 4 net new tests land in `client/test/features/call/services/data_channel_handler_test.dart`:
1. `test_checkpoint_advanced_invokes_callback_with_typed_payload` — well-formed envelope; callback called with exact field values.
2. `test_checkpoint_advanced_malformed_payload_silently_dropped` — `{"checkpoint_id":42,"index":"abc"}` → no callback, no throw.
3. `test_checkpoint_advanced_out_of_range_index_dropped` — `{"index":10,"total":5}` → no callback.
4. `test_checkpoint_advanced_zero_total_dropped` — `{"total":0}` → no callback.

**AC3 — Client: `_CallScreenState` owns a `ValueNotifier<CheckpointSnapshot?>`, NOT a bloc field:**

Given the existing `CallBloc` sealed-state contract is `CallConnecting` / `CallConnected` / `CallError` / `CallEnded` and `client/CLAUDE.md` §2 + §4 reflect that bloc test churn is expensive
And mid-call checkpoint progression is a pure UI artifact (the bloc has zero behavior keyed off it)
And the existing `_CallScreenState` already owns `_dataChannelHandler`, `_visemeScheduler`, `_awaitingPlaybackIdle` — precedent for UI-only state living on the State
When this story lands
Then a NEW value class lives in `client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart` (or a sibling file — dev's call):

```dart
/// Story 6.7 — snapshot of the checkpoint stepper's state. Mirrors
/// the data-channel envelope but stored as Dart-idiomatic fields.
/// Pushed to the Rive `.riv` via 3 ViewModel writes on every update.
///
/// `currentIndex` is server-side 0-based (matches the wire). The
/// Flutter widget that consumes this translates to 1-based before
/// writing the Rive `stepsCount` property (Deviation #3 — Walid
/// authors the .riv against 1-based for human-readable design).
class CheckpointSnapshot {
  final int currentIndex;
  final int total;
  final String hintText;

  const CheckpointSnapshot({
    required this.currentIndex,
    required this.total,
    required this.hintText,
  });
}
```

And `_CallScreenState` gains a `final ValueNotifier<CheckpointSnapshot?> _checkpointNotifier = ValueNotifier(null);`.

And the `DataChannelHandler` factory in `_CallScreenState.build → BlocConsumer.listener` is extended with:

```dart
onCheckpointAdvanced: (payload) {
  if (!context.mounted) return;
  _checkpointNotifier.value = CheckpointSnapshot(
    currentIndex: payload.index,
    total: payload.total,
    hintText: payload.hintText,
  );
},
```

And `_CallScreenState.dispose()` disposes the notifier BEFORE `super.dispose()`:

```dart
@override
void dispose() {
  // ... existing handler + scheduler disposal stays unchanged.
  _checkpointNotifier.dispose();
  // ... existing super.dispose() at the bottom.
}
```

**AC4 — Client: reconcile from `call_end.checkpoints_passed` (Deviation #2 — envelope-loss recovery):**

Given Story 6.6 deferred-work item 406 names the "cancel-mid-flight envelope partial-execution" race
And the `call_end` envelope already carries `data.checkpoints_passed` (architecture.md line 614)
When this story lands
Then the `onCallEnd` callback in `_CallScreenState.build` is extended to reconcile the stepper BEFORE the existing `RemoteCallEnded` dispatch:

```dart
onCallEnd: (reason, data) {
  if (!context.mounted) return;
  // Story 6.7 Deviation #2 — recover from envelope-loss race. If
  // the server advanced N checkpoints but one `checkpoint_advanced`
  // push was cancelled mid-flight (deferred-work line 406), the
  // local stepper would lag. Reconcile visually to the server-
  // authoritative count before the call-ended screen appears.
  final passed = data['checkpoints_passed'];
  final total = data['total_checkpoints'];
  final current = _checkpointNotifier.value;
  if (passed is num && total is num && current != null) {
    final pi = passed.toInt();
    final ti = total.toInt();
    // Only reconcile UP. NEVER walk back (would mask a genuine
    // future server-side regression).
    if (pi > current.currentIndex && ti > 0 && pi <= ti) {
      _checkpointNotifier.value = CheckpointSnapshot(
        currentIndex: pi,
        total: ti,
        hintText: current.hintText,  // last known hint stays
      );
    }
  }
  context.read<CallBloc>().add(RemoteCallEnded(reason, data));
},
```

**AC5 — Client: 2 integration tests for the data-flow plumbing (Rive-free):**

Given Phase 1 wraps without needing the `.riv` file
And the integration boundary that matters is "envelope → notifier value updated correctly"
When this story lands
Then 2 net new tests land in `client/test/features/call/views/call_screen_test.dart` (or a new sibling — dev's call):
1. `test_checkpoint_envelope_updates_notifier` — pump `CallScreen` with a `debugHandlerBuilder` that captures the `onCheckpointAdvanced` callback; invoke the callback with a typed payload; assert the `_checkpointNotifier.value` matches (drill in via a `Key`/test seam or expose a `@visibleForTesting` getter on `_CallScreenState`).
2. `test_call_end_reconciles_stepper_to_checkpoints_passed` — set notifier to `currentIndex=2, total=6`; invoke `onCallEnd("survived", {"checkpoints_passed": 6, "total_checkpoints": 6})`; assert notifier became `currentIndex=6` BEFORE `RemoteCallEnded` was dispatched (verify the bloc's last dispatched event AND the notifier value in the same assertion).

### Phase 2 — Requires `client/assets/rive/checkpoint_stepper.riv`

**AC6 — Client: `CheckpointStepperCanvas` widget loads the Rive file and binds ViewModel inputs:**

Given the `.riv` file has been delivered at `client/assets/rive/checkpoint_stepper.riv` with 3 ViewModel inputs: `stepsCount` (number), `lastCheckIndex` (number), `hint_text` (string)
And `memory/rive-flutter-rules.md` §3 + §5 + §6 mandate the canonical 0.14.x integration pattern (mirrored by `rive_character_canvas.dart`)
And `pubspec.yaml` lists Rive assets individually (not by directory)
When this story lands
Then `client/pubspec.yaml` is extended with `- assets/rive/checkpoint_stepper.riv` in the `flutter.assets:` block, placed alphabetically with the existing Rive entries.

And a NEW widget lives at `client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart`:

```dart
/// Story 6.7 — Rive-driven checkpoint progress HUD overlay for the
/// in-call surface. Renders `assets/rive/checkpoint_stepper.riv`
/// (single artboard + single state machine — default selectors).
/// All visual design + animation lives inside the .riv; this widget
/// is purely glue: load the file, cache 3 ViewModel handles, write
/// to them when [snapshot] changes.
///
/// Mirrors [RiveCharacterCanvas]'s 0.14.x integration pattern
/// (see `memory/rive-flutter-rules.md` §3, §6) with three deltas:
///   1. Default artboard + default state machine (no .byName()).
///   2. No Rive→Flutter events (the stepper emits nothing upstream).
///   3. `Fit.layout` instead of `Fit.cover` — the stepper is a HUD
///      element sized by its parent SizedBox, not a full-screen
///      immersive surface.
///
/// Snapshot null ⇒ no envelope received yet ⇒ widget renders an
/// empty SizedBox.shrink() (graceful absence; the .riv author
/// can't be asked to render meaningful "no data" content). Once
/// the first envelope arrives, the widget mounts the Rive canvas
/// and stays mounted for the call's lifetime — re-renders are
/// driven by ViewModel writes, not widget recreation.
///
/// Fallback contract: when `RiveNative.isInitialized` is false
/// (widget tests or rare prod bootstrap failures), renders a
/// SizedBox.shrink() — the stepper is non-critical UX, so silent
/// absence is acceptable (vs. RiveCharacterCanvas which falls
/// back to a Flutter hang-up button because the canvas IS the
/// critical exit affordance).
class CheckpointStepperCanvas extends StatefulWidget {
  final CheckpointSnapshot? snapshot;
  const CheckpointStepperCanvas({super.key, required this.snapshot});

  @override
  State<CheckpointStepperCanvas> createState() =>
      _CheckpointStepperCanvasState();
}
```

And the State enforces:

1. **Asset path constant.** `static const String _assetPath = 'assets/rive/checkpoint_stepper.riv';`
2. **Init in `initState`** following `RiveCharacterCanvas._initRive` shape: `RiveNative.isInitialized` guard → `rootBundle.load(_assetPath)` verify → `FileLoader.fromAsset(_assetPath, riveFactory: Factory.rive)` → `setState({})`. On any catch path, set `_riveFallback = true` (idempotent, post-frame). NO `onFallback` callback up the tree — silent fallback is the contract.
3. **`onLoaded` caches the 3 ViewModel handles** ONCE:
   ```dart
   void _onRiveLoaded(rive.RiveLoaded state) {
     final vm = state.viewModelInstance;
     if (vm != null) {
       _stepsCount = vm.number('stepsCount');
       _lastCheckIndex = vm.number('lastCheckIndex');
       _hintText = vm.string('hint_text');
     }
     // Apply initial snapshot if one is already present (the snapshot
     // may have been set before the file finished loading).
     _applySnapshot(widget.snapshot);
   }
   ```
4. **`didUpdateWidget` writes when the snapshot changes:**
   ```dart
   @override
   void didUpdateWidget(CheckpointStepperCanvas oldWidget) {
     super.didUpdateWidget(oldWidget);
     if (oldWidget.snapshot != widget.snapshot) {
       _applySnapshot(widget.snapshot);
     }
   }
   ```
5. **`_applySnapshot` is the ONE place the wire-to-Rive translation lives** (Deviation #3 — 0-based wire → 1-based Rive):
   ```dart
   // SUPERSEDED 2026-05-19 by Deviation #6 — see AC Amendments below.
   // Current implementation: `_stepsCount = snap.total` (constant),
   // `_lastCheckIndex = snap.currentIndex` (0-based). No translation.
   void _applySnapshot(CheckpointSnapshot? snap) {
     if (snap == null) return;
     _stepsCount?.value = snap.total.toDouble();
     _lastCheckIndex?.value = snap.currentIndex.toDouble();
     _hintText?.value = snap.hintText;
   }
   ```
   `?.value =` is null-safe — if the .riv doesn't expose the property (mismatched name, version drift), the write silently no-ops. This matches the project-wide Rive contract (`memory/rive-flutter-rules.md` §5).
6. **`build()` renders:**
   ```dart
   @override
   Widget build(BuildContext context) {
     if (widget.snapshot == null) return const SizedBox.shrink();
     if (_riveFallback || _riveLoader == null) return const SizedBox.shrink();
     return rive.RiveWidgetBuilder(
       fileLoader: _riveLoader!,
       dataBind: rive.DataBind.auto(),
       onLoaded: _onRiveLoaded,
       builder: (context, state) {
         if (state is rive.RiveLoaded) {
           return rive.RiveWidget(
             controller: state.controller,
             fit: rive.Fit.layout,
           );
         }
         return const SizedBox.shrink();
       },
     );
   }
   ```
   No `artboardSelector` / `stateMachineSelector` — single-purpose file uses defaults. If the `.riv` ships with named selectors and the dev needs them to load correctly, plumb them at this call site and document.
7. **`dispose()` releases the loader:**
   ```dart
   @override
   void dispose() {
     _riveLoader?.dispose();
     super.dispose();
   }
   ```
   No state-machine event listener to remove (the stepper emits nothing upstream).

**AC7 — Client: position the canvas at the top of the call screen via `Positioned.fill > SafeArea > Align(topCenter) > SizedBox`:**

Given the existing `_buildConnected` Stack has 3 fixed layers (background image, blur, Rive character) + 1 conditional layer (`if (_canvasInFallback)` → Flutter hang-up button at bottom)
And the Rive stepper is a top-aligned horizontal rectangle that paints ABOVE the character but should NOT capture taps that should fall to the hang-up button
When this story lands
Then `_buildConnected` adds a NEW Stack child AFTER the Rive character `Positioned.fill` AND BEFORE the conditional fallback:

```dart
// Layer 4 — Rive checkpoint stepper HUD (Story 6.7). Bound to
// `_checkpointNotifier`; renders SizedBox.shrink() when null.
// `IgnorePointer` lets taps fall through to the Rive canvas
// underneath (which owns the in-canvas hang-up button) — the
// stepper is display-only HUD with zero interactive surface.
Positioned.fill(
  child: SafeArea(
    bottom: false,
    child: Align(
      alignment: Alignment.topCenter,
      child: IgnorePointer(
        ignoring: true,
        child: ValueListenableBuilder<CheckpointSnapshot?>(
          valueListenable: _checkpointNotifier,
          builder: (context, snap, _) => SizedBox(
            // The Rive file's intrinsic aspect ratio governs the
            // final visual size; SizedBox here just gives the
            // RiveWidget a parent to compute Fit.layout against.
            // Height/width values are placeholders Walid may
            // refine after the first visual smoke test.
            height: 120,
            width: double.infinity,
            child: CheckpointStepperCanvas(snapshot: snap),
          ),
        ),
      ),
    ),
  ),
),
```

The `SizedBox(height: 120)` is a placeholder — Walid's `.riv` file's intrinsic aspect ratio decides what looks right at delivery. Dev tweaks on the first device smoke test, no spec churn needed. If the `.riv` self-clips because the SizedBox is too small, expand. If it leaves dead space, contract. **DO NOT** introduce an `AppSpacing.stepperHeight` token — this is a one-shot tuning value, not a reusable measurement.

**AC8 — Client: Phase 2 widget tests (Rive-aware, ~3 tests):**

Given `memory/rive-flutter-rules.md` §6 — Rive does not load in widget tests; gate on `RiveNative.isInitialized` and assert the fallback path
And the substance of the stepper's correctness is "writes the correct values to the ViewModel" which CAN'T be tested without a real Rive runtime
When this story lands
Then 3 net new widget tests land in `client/test/features/call/views/widgets/checkpoint_stepper_canvas_test.dart`:
1. `test_renders_shrink_when_snapshot_null` — pump `CheckpointStepperCanvas(snapshot: null)`; expect a `SizedBox.shrink()` (or specifically: no `RiveWidgetBuilder` finder in the tree).
2. `test_renders_shrink_in_fallback_when_RiveNative_uninitialized` — pump with a non-null snapshot in the widget-test env (`RiveNative` never inits in tests); expect `SizedBox.shrink()`. **This is the "no crash on Rive-less environment" guard** — without it, every other test in the project that incidentally pumps `CheckpointStepperCanvas` (e.g. integration tests for the parent call screen) would crash.
3. `test_snapshot_changes_do_not_throw_in_fallback` — pump with `snapshot: A`, re-pump with `snapshot: B`; assert no exception (the `didUpdateWidget` path runs but `_applySnapshot` no-ops because the cached ViewModel handles are null in fallback mode).

**No widget test verifies the visual correctness of circles / lines / animation timings / hint bubble visibility — those are owned by the `.riv` file's design + the device smoke gate.**

**AC9 — Pre-commit gates + Smoke Test Gate:**

Given the dual-side discipline (root CLAUDE.md: `flutter analyze` + `flutter test` for client, `ruff check .` + `ruff format --check .` + `pytest` for server)
And this story changes BOTH client (substantial new widget + state + tests) AND server (1 new method + 1 new call site + 2 tests) — therefore a VPS deploy IS required for the initial-state envelope to fire in prod
When the story lands
Then ALL of the following pass before flipping the story to `review`:

- `cd server && python -m ruff check .` → zero issues.
- `cd server && python -m ruff format --check .` → zero issues.
- `cd server && .venv/Scripts/python -m pytest` → all green; expect **~2 net new server tests** on top of Story 6.6's baseline (321) → target **≥ 323 passing**.
- `cd client && flutter analyze` → "No issues found!".
- `cd client && flutter test` → "All tests passed!" — expect **~9 net new client tests** (4 handler + 2 integration in Phase 1 + 3 widget in Phase 2) → target **≥ 366 passing** (baseline 357).
- `tests/test_migrations.py` → still 4/4 (no schema change).

The Smoke Test Gate below is **mandatory** — the server-side `emit_initial_state` change AND the Rive file's visual correctness MUST be observed end-to-end on a real device before the story flips to `done`.

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** Story 6.7 ships a small server change (`emit_initial_state`) alongside the Rive client overlay. Gate is **mandatory** because (a) the initial-state envelope is the contract that lets the stepper render at all on call boot, and (b) the visual correctness of the Rive file is unverifiable without a real device.
>
> **Transition rule (per Story 6.5 review D6):** Pre-commit code gates are the stop-ship for `in-progress → review`. Deploy-side gates below are stop-ship for `review → done` — Walid owns the proof-pasting before the story flips to `done`. Paste the actual command run and its output as proof — a checked box without evidence does not count.

- [x] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ `Active: active (running) since Wed 2026-05-20 08:39:45 UTC` on SHA `a9db4c2` (Story 6.7 amended commit post-`checkpoints_passed` server fix per Deviation #8). Validated 2026-05-20.

- [x] **Initial-state envelope fires on bot start.** `journalctl -u pipecat.service --since "5 min ago" | grep checkpoint_initial_state` shows at least one match per call started in the test window; `total=` matches the scenario's checkpoint count.
  - _Proof:_ `2026-05-20 08:17:16.543 | INFO | pipeline.checkpoint_manager:process_frame:245 - checkpoint_initial_state total=6 first_id=greet` (call_id=133 — survival run).

- [x] **Rive stepper renders on call connect.** Dial The Waiter on Pixel 9 Pro XL. Within 1-2 seconds of the `connecting → connected` transition, the stepper (Rive) appears at the top of the screen above the character — 6 circles visible. Below it, the Flutter `CheckpointHintBubble` displays "Tell the waitress you want to order." **AMENDED 2026-05-19 (Deviation #5):** the bubble lives BELOW the stepper as a separate Flutter widget, not inside the Rive row.
  - _Proof:_ Validated visually on Pixel 9 Pro XL 2026-05-20 (call_id=133 survival run).

- [x] **Stepper advances on checkpoint pass.** Speak "I'd like a grilled chicken please." The Rive stepper animates (`lastCheckIndex` advances by 1 per Deviation #6 — 0-based current index, `stepsCount` stays constant at total). The Flutter hint bubble cross-fades to the new hint via `AnimatedSwitcher` (Deviation #5). **AMENDED 2026-05-19** — Deviation #3 (1-based translation) was retired; bubble text crossfade is Flutter-side, not Rive-side.
  - _Proof:_ Validated visually 2026-05-20. journalctl call_id=133: `checkpoint_advanced index=1 total=6 id=main_course`, then `index=2 id=clarify`, `index=3 id=drink`, `index=4 id=confirm`, `index=5 id=close` — 5 organic advances + terminal completion path.

- [x] **Hint bubble hides on empty `hint_text`.** **AMENDED 2026-05-19** — bubble is now a Flutter widget (Deviation #5), no longer in `.riv`. Covered by `checkpoint_hint_bubble_test.dart::renders SizedBox.shrink() when hintText is empty`. No on-device verification needed.
  - _Proof:_ Covered by Flutter widget test (no on-device check required).

- [x] **No visible error chrome during normal call flow.** Confirm no toasts, no banners, no error indicators (UX-DR6). The only on-screen text is the stepper's hint bubble (gameplay content, not system feedback).
  - _Proof:_ Validated visually 2026-05-20 across the post-fix retest call.

- [x] **Reconcile on `call_end` works (Deviation #2).** Survive The Waiter end-to-end. The stepper should end at step 6 of 6 just before the Call-Ended overlay appears (whether or not any envelope was lost along the way — `call_end.checkpoints_passed=6` reconciles).
  - _Proof:_ Validated 2026-05-20 on the post-Deviation-#8 retest call (after server fix wired `checkpoints_passed` through `PatienceTracker.set_checkpoints_passed`). Pre-fix smoke (call_id=133, 2026-05-20 08:17) initially showed `lastCheckIndex=5` lingering because the legacy hardcoded `checkpoints_passed=0` blocked the reconcile guard `pi > current.currentIndex`; fix shipped as Deviation #8 + redeployed at SHA `a9db4c2` + revalidated visually with `lastCheckIndex=6` reached pre-overlay.

- [x] **Rive file loads cleanly — no native crash.** Logcat `adb logcat | grep -iE "(rive|FileLoader)"` shows no `RiveException` / `null pointer` / "factory mismatch" lines during call boot.
  - _Proof:_ No crash observed visually across the survival run; no Rive-related errors surfaced in the test window.

- [x] **Fallback is graceful when Rive native unavailable.** This is widget-test-only enforcement (AC8 #2) — flag this box as covered-by-test rather than running it on device.
  - _Proof:_ Covered by `test_renders_shrink_in_fallback_when_RiveNative_uninitialized`.

- [x] **Server logs clean on the happy path.** `journalctl -u pipecat.service --since "5 min ago" | grep -iE "(error|traceback|exception)" | grep -v INFO` returns zero matches across the test calls.
  - _Proof:_ `journalctl -u pipecat.service --since '60 min ago' | grep -iE '(error|traceback|exception)' | grep -v INFO` → empty output 2026-05-20.

- [x] **Migration test still green.** `pytest tests/test_migrations.py` → 4/4 (no schema change; regression check).
  - _Proof:_ `tests\test_migrations.py .... [100%]  4 passed in 2.27s` (2026-05-20).

## Tasks / Subtasks

### Phase 1 — Dev works in isolation, no `.riv` needed

- [x] **Task 1 — Server: `CheckpointManager.emit_initial_state` + bot.py wiring** (AC: #1)
  - [x] 1.1 — Add `async def emit_initial_state(self) -> None:` to `server/pipeline/checkpoint_manager.py`. Push the `OutputTransportMessageFrame` per AC1 shape. Log `checkpoint_initial_state total={} first_id={}`.
  - [x] 1.2 — In `server/pipeline/bot.py::run_bot::on_first_participant_joined`, append `await checkpoint_manager.emit_initial_state()` AFTER the existing greeting `TTSSpeakFrame` queue.
  - [x] 1.3 — Add `test_emit_initial_state_pushes_index_zero_envelope` to `server/tests/test_checkpoint_manager.py` (use `_capture_pushed` per `test_emotion_emitter.py` pattern).
  - [x] 1.4 — Add `test_on_first_participant_joined_calls_emit_initial_state` to `server/tests/test_bot_pipeline_wiring.py`.
  - [x] 1.5 — Verify `ruff check .` + `ruff format --check .` + `pytest` all green.

- [x] **Task 2 — Client: `DataChannelHandler` typed callback** (AC: #2)
  - [x] 2.1 — Create `client/lib/features/call/services/checkpoint_advanced_payload.dart` with the `CheckpointAdvancedPayload` value class.
  - [x] 2.2 — Extend `DataChannelHandler` constructor with `required onCheckpointAdvanced` callback. Add the `case 'checkpoint_advanced':` branch with full payload validation + range checks + FINE-level logging.
  - [x] 2.3 — Update `DataChannelHandlerBuilder` typedef in `call_screen.dart:39-47` to include the new parameter.
  - [x] 2.4 — Update the `default` branch comment (remove the "Owned by Story 6.7" line).
  - [x] 2.5 — Write 4 tests per AC2 in `client/test/features/call/services/data_channel_handler_test.dart`.

- [x] **Task 3 — Client: `_CallScreenState` notifier + onCallEnd reconcile** (AC: #3, #4)
  - [x] 3.1 — Add the `CheckpointSnapshot` value class (in `checkpoint_stepper_canvas.dart` or a sibling — dev's call). **Dev call**: shipped in a sibling `widgets/checkpoint_snapshot.dart` so Phase 1 can ship + tests can pass before Phase 2's Rive widget lands.
  - [x] 3.2 — Add `_checkpointNotifier` field to `_CallScreenState`.
  - [x] 3.3 — Wire `onCheckpointAdvanced` in the `DataChannelHandler` factory inside `BlocConsumer.listener`.
  - [x] 3.4 — Extend `onCallEnd` with the reconcile-from-`checkpoints_passed` logic (Deviation #2).
  - [x] 3.5 — Dispose `_checkpointNotifier` in `dispose()` (BEFORE `super.dispose()`).
  - [x] 3.6 — Write 2 integration tests per AC5. **Shipped 3** (+1 defensive "no walk-back" assertion for the reconcile guard — see Dev Agent Record).

- [x] **Task 4 — Phase 1 pre-commit gate** (AC: #9)
  - [x] 4.1 — `cd server && python -m ruff check .` + `ruff format --check .` + `pytest` → all green (target ≥323). **Result: 323 passed.**
  - [x] 4.2 — `cd client && flutter analyze` → "No issues found!".
  - [x] 4.3 — `cd client && flutter test` → "All tests passed!" (target ≥363 net). **Result: 364 passed.**
  - [ ] 4.4 — Push the commit. **Notify Walid: "Phase 1 done, ready for `checkpoint_stepper.riv`."** (Awaiting `/commit` from Walid — project memory rule. Story stays `in-progress` until Phase 2 closes.)

### Phase 2 — `.riv` file delivered by Walid

- [x] **Task 5 — Receive the Rive file from Walid** (AC: #6)
  - [x] 5.1 — File placed at `client/assets/rive/checkpoint_stepper.riv`. **Verified: 880671 bytes, dropped 2026-05-18 15:51.**
  - [x] 5.2 — Confirm with Walid: 3 ViewModel inputs named exactly `stepsCount` (number), `lastCheckIndex` (number), `hint_text` (string). **Walid amendment 2026-05-18**: renamed `hint_text` → `hintText` (camelCase per Rive's recommended naming convention). Dev code updated accordingly — see Deviation #4 below.
  - [x] 5.3 — Confirm: single artboard + single state machine (default selectors OK). **Default selectors used in code** (no `.byName()` calls); will be confirmed on first device smoke.

- [x] **Task 6 — Client: `CheckpointStepperCanvas` widget** (AC: #6)
  - [x] 6.1 — Create `client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart` following the `RiveCharacterCanvas` pattern.
  - [x] 6.2 — Implement `_initRive`, `_enterFallback`, `_onRiveLoaded` (cache 3 ViewModel handles), `_applySnapshot` (translate 0-based → 1-based per Deviation #3), `didUpdateWidget`, `dispose`.
  - [x] 6.3 — Register the asset in `client/pubspec.yaml` under `flutter.assets:` (alphabetical with the existing Rive entries).
  - [x] 6.4 — Write 3 widget tests per AC8 (+1 sanity test asserting the fallback precondition `RiveNative.isInitialized == false`).

- [x] **Task 7 — Client: integrate into `_buildConnected` Stack** (AC: #7)
  - [x] 7.1 — Add Layer 4 (Positioned.fill → SafeArea → Align(topCenter) → IgnorePointer → ValueListenableBuilder → SizedBox(120) → CheckpointStepperCanvas) AFTER the Rive character layer, BEFORE the `if (_canvasInFallback)` block.
  - [ ] 7.2 — On the first device smoke, tune the `SizedBox(height: ...)` based on what the `.riv` looks like at the target viewport. Document the final value inline. **Deferred to Walid's first device smoke.**

- [x] **Task 8 — Retire deferred-work carry-forwards** (AC: #1 background + #2 background)
  - [x] 8.1 — Document deferred-work.md line 396 as RESOLVED in Implementation Notes (Deviation #1: no `v` field; additive evolution via `data.{}`). See Dev Agent Record → Completion Notes.
  - [x] 8.2 — Document deferred-work.md line 406 as RESOLVED in Implementation Notes (Deviation #2: `call_end` reconcile). Leave the `deferred-work.md` file untouched per historical-record convention.

- [x] **Task 9 — Phase 2 pre-commit + Smoke Test gates** (AC: #9)
  - [x] 9.1 — `cd client && flutter analyze` → clean (still). **No issues found!**
  - [x] 9.2 — `cd client && flutter test` → all green (target ≥366 net). **Result: 368 passed.** Net new since Story 6.6 baseline 357: 4 handler + 3 integration + 4 widget = 11.
  - [x] 9.3 — `cd server && pytest` → still green (no Phase 2 server changes). **323 passed (stable since Phase 1 close).**
  - [ ] 9.4 — Deploy server to VPS via CI/CD (one-time for the Phase 1 server change; Phase 2 is client-only). **Walid-owned.**
  - [ ] 9.5 — Execute the 11-box Smoke Test Gate above on Pixel 9 Pro XL. Paste proofs. **Walid-owned per Story 6.5 D6 (deploy-side gates are stop-ship for `review → done`).**
  - [x] 9.6 — Flip `sprint-status.yaml` AND story `Status:` to `review` simultaneously (then to `done` post-smoke-gate). **Done 2026-05-18 post pre-commit-gate green.**
  - [ ] 9.7 — Await `/commit` from Walid. **DO NOT** commit autonomously — project memory rule.

## Dev Notes

**Architectural intent (the one paragraph):** The CheckpointStepperCanvas is a **3-property pipe to a Rive file**. It doesn't render anything itself — every pixel of design and every frame of animation lives inside `checkpoint_stepper.riv`. Flutter loads the file, caches 3 ViewModel handles in `onLoaded`, and writes to them when the data-channel envelope arrives. If the file isn't loaded yet, writes queue (set the snapshot; `onLoaded` applies it). If the file fails to load (test env, native init failure), the widget silently renders nothing — the stepper is non-critical UX, the user can still complete the call without it.

**Why a Rive file, not a Flutter widget?** Walid owns end-to-end design. Translating UX deltas (a different easing curve, a different bubble shape, a new color blend) into widget-tree edits creates a dev-design coupling that slows iteration. With the `.riv` approach, Walid re-exports the file, drops it in, and the visual change ships without a code review on the rendering layer. This is now project policy for in-call HUD overlays — see `memory/feedback_hud_overlays_are_rive.md`.

**Why a `ValueNotifier` instead of a Bloc field?** Same as the original Story 6.7 reasoning that survived the pivot: bloc state is the *call lifecycle* (connecting/connected/error/ended). Stepper state is *UI-only mid-call progression*. Extending `CallConnected` with stepper fields would force every `BlocConsumer.builder` to rebuild on every advance — including the Rive character canvas, the most expensive widget on the screen. A scoped `ValueNotifier<CheckpointSnapshot?>` rebuilds only the stepper subtree. Precedent: Story 6.2 `_canvasInFallback`, Story 6.4 `_awaitingPlaybackIdle`.

~~**Why translate 0-based → 1-based in `_applySnapshot`?** Walid designs the `.riv` against human-readable step numbering ("step 1 of 6", "step 2 of 6"). The server's wire stays 0-based for backward compatibility with Story 6.6's prod code. The translation lives in exactly one place; everywhere else (envelope, `CheckpointSnapshot`, reconcile logic, logging) uses the server's 0-based convention. The +1 is a single line at the Rive boundary.~~ **SUPERSEDED 2026-05-19 by Deviation #6** — the `.riv` was re-authored to use `stepsCount` (total constant) + `lastCheckIndex` (0-based current index). No translation lives in Flutter anymore.

**Why no `v: 1` on the envelope?** Two reasons. (1) No precedent — none of `emotion`, `viseme`, `hang_up_warning`, `call_end`, or `bot_speaking_ended` carries a version. Introducing one here would be a one-off. (2) Additive evolution is sufficient: future fields go under `data.{}`; old clients ignore unknown keys. Breaking changes use a new `type` string (e.g. `checkpoint_advanced_v2`) — itself a coordination event regardless of a `v` field.

**Why no `AppSpacing.stepperHeight` token for the SizedBox(height: 120)?** It's a one-shot tuning value, not a reusable measurement. Once the `.riv` file is delivered and the device smoke test confirms the final value, it gets hard-coded inline with a comment naming the tuning context. Token discipline (UX-DR3) is for measurements that appear in two or more places; a single inline value with a comment is fine.

**Why does the stepper canvas NOT render anything when `snapshot == null`?** The server only emits the first `checkpoint_advanced` envelope when `on_first_participant_joined` fires server-side, which happens AFTER the LiveKit room is bound. Between `CallConnecting` and that envelope arriving, there's a 1-2 second window where the call screen is live but stepper data isn't ready. Rendering an empty/loading Rive canvas during that window would either show a default-state stepper (misleading) or require the `.riv` to have a "blank" state (extra design burden on Walid). `SizedBox.shrink()` is the cleanest absence-of-data state — the user sees the character + background, and the stepper materializes when there's data to show.

**Why no Semantics wrapper at the Flutter layer?** Rive 0.14.x doesn't currently expose Semantics through its widget tree, AND the stepper is display-only (no taps to label). The hint bubble's accessible label is a known gap — if TalkBack/VoiceOver users need spoken progression announcements, a follow-up story can add a `Semantics(label: 'Step ${index+1} of $total. Hint: $hintText')` invisible sibling (size 1×1, off-screen, screen-reader-only). For 6.7, the visual stepper is the contract. Documented as a deferred concern in Implementation Notes if Walid prioritizes a11y for a future iteration.

### Project Structure Notes

**Client (new files — Phase 1):**
- `client/lib/features/call/services/checkpoint_advanced_payload.dart` — typed payload value class (~30 LOC).
- `client/test/features/call/services/data_channel_handler_test.dart` — UPDATE; +4 tests.
- `client/test/features/call/views/call_screen_test.dart` — UPDATE; +2 integration tests.

**Client (new files — Phase 2):**
- `client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart` — Rive-loader widget + `CheckpointSnapshot` value class (~150 LOC).
- `client/test/features/call/views/widgets/checkpoint_stepper_canvas_test.dart` — 3 widget tests.
- `client/assets/rive/checkpoint_stepper.riv` — delivered by Walid.

**Client (modified files — Phase 1):**
- `client/lib/features/call/services/data_channel_handler.dart` — add `onCheckpointAdvanced` callback + `case 'checkpoint_advanced':` branch.
- `client/lib/features/call/views/call_screen.dart` — extend `DataChannelHandlerBuilder` typedef + add `_checkpointNotifier` field + extend `dispose()` + wire `onCheckpointAdvanced` + extend `onCallEnd` with reconcile.

**Client (modified files — Phase 2):**
- `client/lib/features/call/views/call_screen.dart` — add Layer 4 Stack child in `_buildConnected`.
- `client/pubspec.yaml` — register the new Rive asset alphabetically in `flutter.assets:`.

**Server (modified files — Phase 1):**
- `server/pipeline/checkpoint_manager.py` — add `emit_initial_state()` method.
- `server/pipeline/bot.py` — extend `on_first_participant_joined` with the new emit call.
- `server/tests/test_checkpoint_manager.py` — add `test_emit_initial_state_pushes_index_zero_envelope`.
- `server/tests/test_bot_pipeline_wiring.py` — add `test_on_first_participant_joined_calls_emit_initial_state`.

**Server (NO changes):**
- `server/db/migrations/` — no new migration.
- `server/models/schemas.py` — no schema changes.
- `server/api/routes_calls.py` — no API changes; envelope is data-channel only.

**Alignment with established patterns:** Phase 1 stays inside the conventions established by Stories 6.3 (`DataChannelHandler` extension), 6.4 (`_CallScreenState` state-on-State for UI-only flags), and 6.5 (`onCallEnd` callback extension). Phase 2 mirrors Story 6.2's `RiveCharacterCanvas` integration verbatim with three documented deltas (no events, no named selectors, `Fit.layout` instead of `Fit.cover`).

**Detected conflicts or variances:** None expected. The `checkpoint_advanced` envelope shape is locked in Story 6.6's production-deployed code (smoke-gate validated 2026-05-18). The Rive 0.14.x integration pattern is locked in `rive_character_canvas.dart` (Story 6.2 smoke-gate validated 2026-04-30).

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.7: Build CheckpointStepper Overlay for Call Screen`] lines 1203-1230.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#6. CheckpointStepper`] lines 1073-1106 — original functional spec (visual layer now owned by Rive file).
- [Source: `_bmad-output/planning-artifacts/architecture.md#Communication Patterns — LiveKit Data Channel Messages`] lines 606-618 — `checkpoint_advanced` envelope shape.
- [Source: `_bmad-output/implementation-artifacts/6-6-build-checkpointmanager-and-checkpoint-aware-exchangeclassifier.md#AC2 #4-6`] — canonical wire format (server emitter reference).
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md` lines 396, 406] — two carry-forwards Story 6.7 retires.
- [Source: `client/lib/features/call/views/widgets/rive_character_canvas.dart`] — canonical Rive 0.14.x integration pattern reference (mirror its shape with documented deltas).
- [Source: `client/lib/features/call/services/data_channel_handler.dart:65-138`] — the `switch (type)` dispatch pattern the new case joins.
- [Source: `client/lib/features/call/views/call_screen.dart:680-744`] — the `_buildConnected` Stack composition the stepper integrates into.
- [Source: `client/CLAUDE.md`] — Flutter gotchas (§3 pumpAndSettle, §7 surface size).
- [Source: `memory/rive-flutter-rules.md`] — Rive 0.14.x integration rules (verify against current `rive_character_canvas.dart` — memory is 24 days old).
- [Source: `memory/feedback_hud_overlays_are_rive.md`] — the project policy this story established.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context) — `claude-opus-4-7[1m]`

### Debug Log References

**Phase 1 RED→GREEN cycle (2026-05-18):**

1. **Server test RED.** Added `test_emit_initial_state_pushes_index_zero_envelope` first; ran → `AttributeError: 'CheckpointManager' object has no attribute 'emit_initial_state'`. Confirmed RED.
2. **Server GREEN.** Added `async def emit_initial_state(self) -> None:` to `checkpoint_manager.py` re-using the existing `OutputTransportMessageFrame` shape; logged `checkpoint_initial_state total=N first_id=...`. Wired the call into `bot.py::on_first_participant_joined` AFTER the canned greeting `TTSSpeakFrame`. Both server tests green; full server pytest = 323 passing.
3. **Client analyzer drift.** After widening `DataChannelHandlerBuilder` typedef with the new `onCheckpointAdvanced` parameter, all 4 existing builder call sites in `call_screen_test.dart` errored on `argument_type_not_assignable`. Patched each builder closure to include `required onCheckpointAdvanced` — no production code drift.
4. **Test fixture trap.** The pre-existing `'unknown envelope type is silently dropped'` test in `data_channel_handler_test.dart` used `checkpoint_advanced` as the synthetic "unknown" payload. Once 6.7 routed `checkpoint_advanced` to its own typed callback, that test became a false-positive (would have invoked the new handler, not the default branch). Replaced the synthetic type with `future_unknown_type_v9` to keep the test a true "unknown-type drop" regression guard.
5. **Timer-pending teardown.** The two Story 6.7 integration tests in `call_screen_test.dart` (reconcile-up + no-walk-back) fired `onCallEnd` which dispatches `RemoteCallEnded` to the bloc, which arms a playback-drain timer. The framework asserted `!timersPending` at teardown. Mirrored the Story 6.4 existing pattern (line ~620): explicitly dispatch `PlaybackDrained` after the assertion so the bloc completes its transition to `CallEnded` before widget teardown.

**Phase 2 (2026-05-18, after Walid dropped `checkpoint_stepper.riv`):**

6. **Walid amendment — camelCase Rive input.** The story spec called for ViewModel input `hint_text` (snake_case). Walid's actual `.riv` ships with `hintText` (camelCase per Rive's recommended naming convention). Implemented as authored — see Deviation #4 in Completion Notes. The other two inputs (`stepsCount`, `lastCheckIndex`) were already camelCase in the spec.
7. **Phase 2 widget — pattern mirror.** `CheckpointStepperCanvas` mirrors `RiveCharacterCanvas` verbatim with the three documented deltas: no `.byName()` selectors (default artboard + default state machine), no Rive→Flutter event listener, `Fit.layout` instead of `Fit.cover`. Fallback path uses `SizedBox.shrink()` (per AC6 — stepper is non-critical UX), not the colored container `RiveCharacterCanvas` uses.
8. **Stack Layer 4 — IgnorePointer + SafeArea(bottom:false) + topCenter.** Inserted between Layer 3 (Rive character) and the conditional `if (_canvasInFallback)` block. `IgnorePointer(ignoring: true)` lets taps fall through to the Rive canvas's in-canvas hang-up button (stepper has zero interactive surface). `SafeArea(bottom: false)` keeps the stepper clear of the status bar at the top but doesn't reserve bottom-insets space (the character + hang-up button own the bottom region).
9. **3 widget tests + 1 sanity precondition.** All 3 substantive tests run against `RiveNative.isInitialized == false` (widget tests can't load Rive natively per `memory/rive-flutter-rules.md` §6). The sanity test up top asserts the precondition so a future Rive-test-runtime upgrade fails loudly here rather than silently changing the meaning of every other test in the file. Substantive correctness — actual ViewModel writes with correct 1-based translation — is validated on-device via the Smoke Test Gate.

**Phase 2 follow-up retouches (2026-05-19, post-deploy smoke test iterations):**

10. **Server retouche — `emit_initial_state` rejected by pipecat `_check_started`.** First smoke gate revealed an `ERROR | CheckpointManager#0 Trying to process OutputTransportMessageFrame but StartFrame not received yet` log. `on_first_participant_joined` fired BEFORE the pipeline's StartFrame had propagated to the `CheckpointManager` processor (confirmed 378ms gap in journalctl); `push_frame` was silently rejected → client never received the `index=0` envelope → stepper stayed invisible until the first real advance.
11. **Server retouche — refactor to `schedule_initial_emit` self-trigger pattern.** Replaced `emit_initial_state` (called eagerly from `on_first_participant_joined`) with `schedule_initial_emit` (sets a flag; the actual `push_frame` runs from inside `process_frame` on the first post-StartFrame tick, when `_started=True`). Routes the initial envelope through the SAME downstream chain as the working advance envelopes. New test `test_schedule_initial_emit_pushes_envelope_on_first_process_frame` lands.
12. **Client retouche — semantic swap.** Initial code wrote `_stepsCount = currentIndex + 1` + `_lastCheckIndex = total` per the original story spec. Rive Editor screenshot (call_id=125, 2026-05-19) confirmed Walid's `.riv` actually expects the OPPOSITE: `stepsCount = total` + `lastCheckIndex = currentIndex`. Swapped + retired Deviation #3's 1-based +1 translation. Bubble + circles started rendering correctly after this fix.
13. **Client retouches #7-#10 — `Fit.layout` / `layoutScaleFactor` / AspectRatio / LayoutBuilder tuning.** Iteratively tried `Fit.fitWidth`, `Fit.contain` + AspectRatio(393/219), `Fit.layout` + LayoutBuilder with 60% vertical slack, `layoutScaleFactor: 0.5`. None of the variations made the bubble's Hug-Contents Height re-evaluate after data-bound text growth. Each amend documented inline via "Phase 2 retouche #N" comments (since consolidated).
14. **Diagnostic logs via `debugPrint` (visible in `adb logcat`) confirmed the issue is in Rive's native runtime**, not the Flutter parent constraints: artboard runtime dimensions matched the SizedBox exactly (e.g. `parent_max=448x931, sizedBox=448x399, artboard_runtime=448x399`), but the bubble child stayed clamped regardless. Web research (3 searches + 2 GitHub issue fetches) confirmed [rive-react-native#375](https://github.com/rive-app/rive-react-native/issues/375): **CONFIRMED open Rive runtime limitation across all native runtimes** — data-bound text growth does not trigger Hug-Height re-evaluation. No code-side fix exists.
15. **Retouche #11 — Bubble→Flutter split.** The hint bubble was removed from the `.riv` (Walid edited the design to leave only the 6 circles + connector) and re-implemented as a Flutter widget `CheckpointHintBubble` (`Container` + `Text` + `AnimatedSwitcher`). Flutter `Text` natively hugs its content with zero ambiguity. The project policy `feedback_hud_overlays_are_rive.md` was updated with a documented exception: "data-bound auto-sizing text → Flutter; static animation → Rive". `MEMORY.md` flagged with 🐛 pointing to the new memory `feedback_rive_runtime_hug_height_bug.md` for full diagnosis.
16. **Color tokens reused.** Walid's request to reuse existing `AppColors` tokens for the bubble: fill = `AppColors.textPrimary` (`#F0F0F0`), text = `AppColors.background` (`#1E1F23`). Contrast 13.5:1 (AA + AAA) already validated in the `app_colors.dart` WCAG header table. No new theme tokens introduced.
17. **Composite Layer 4 — Column[stepper, bubble] with edge-to-edge stepper.** `CheckpointStepperCanvas` (Rive) and `CheckpointHintBubble` (Flutter) composed in a `Column` with 8px gap. Stepper has NO horizontal padding (edge-to-edge by Walid's request); bubble has 16px horizontal padding so long-text wraps don't touch screen edges.
18. **5 widget tests for the Flutter bubble** including the critical `long hint text wraps to multiple lines and the bubble grows vertically` test — the contre-régression that explicitly validates the reason for the split. Phase 2 widget-test count: 4 stepper canvas + 5 bubble = 9.

### AC Amendments (Phase 2 final, 2026-05-19)

The original AC list described the CheckpointStepper as a single Rive widget with the bubble inside. The Rive runtime bug (see retouche #14-15 above) forced a pivot to a hybrid architecture. The following ACs are amended as shipped:

- **AC6 (`CheckpointStepperCanvas` widget)** — amended. The widget now loads a `.riv` containing ONLY the stepper row (6 circles + connector); the hint bubble was moved out. The 3 ViewModel inputs are still cached in `_onRiveLoaded` but only `stepsCount` + `lastCheckIndex` actively render; `hintText` write is kept as defensive no-op (`?.value =`) in case a future `.riv` re-introduces a text element bound to it.
- **AC7 (Stack Layer 4 integration)** — amended. The layer is no longer a single `SizedBox(height: 120) → CheckpointStepperCanvas`. It's now a `Column` with the Rive stepper (edge-to-edge, no horizontal padding) above a `Padding(horizontal: 16) → CheckpointHintBubble` (the new Flutter widget), separated by an 8px `SizedBox`. The `SizedBox(height: 120)` placeholder mentioned in the original AC is retired — the stepper sizes itself via an internal `AspectRatio` reading `widthOriginal/heightOriginal` from the pre-loaded file.
- **AC8 (widget tests)** — amended count. Original spec: 3 widget tests. Final shipped: 9 tests (4 in `checkpoint_stepper_canvas_test.dart` covering Rive-fallback path, 5 in `checkpoint_hint_bubble_test.dart` covering the Flutter bubble including the multi-line wrap regression guard).
- **Smoke Test Gate Box 5 (Hint bubble hides on empty `hint_text`)** — amended. Now covered by `checkpoint_hint_bubble_test.dart::renders SizedBox.shrink() when hintText is empty` (no longer Rive-design-contract-only). Box can be marked "Covered by Flutter widget test" with rationale.

The 3 newly recorded deviations from the original spec:

- **Deviation #5** (Bubble→Flutter split, 2026-05-19) — see retouche #15 above. Documented in `memory/feedback_rive_runtime_hug_height_bug.md` + `memory/feedback_hud_overlays_are_rive.md` (exception added).
- **Deviation #6** (semantic swap stepsCount↔lastCheckIndex, 2026-05-19) — see retouche #12 above. The original spec text was inverted; the `.riv` design is the source of truth.
- **Deviation #7** (server `schedule_initial_emit` self-trigger, 2026-05-19) — see retouche #11 above. Replaces the spec's "call `emit_initial_state` from `on_first_participant_joined`" approach which raced with pipecat's StartFrame propagation.

### Completion Notes List

**Phase 1 complete (2026-05-18).**

✅ **AC1 (server emit_initial_state).** `CheckpointManager.emit_initial_state()` pushes a `checkpoint_advanced` envelope with `index=0`, `total=N`, `checkpoint_id=<first>`, `next_hint=<first hint>` via the existing data-channel mechanism. Hooked into `bot.py::on_first_participant_joined` AFTER the canned greeting `TTSSpeakFrame`. No mutation of `self._index` — purely informational. `journalctl` will see `checkpoint_initial_state total=6 first_id=greet` per call start (smoke gate AC2).

✅ **AC2 (client typed callback).** `DataChannelHandler` ctor extended with `required onCheckpointAdvanced`. `case 'checkpoint_advanced':` validates every field's type with `is String` / `is num` / `is String`, defends against out-of-range index (`idx < 0`, `idx >= total`, `total <= 0`), logs at FINE on drift, NEVER throws, NEVER routes to default. `CheckpointAdvancedPayload` value class lives at `client/lib/features/call/services/checkpoint_advanced_payload.dart`.

✅ **AC3 (UI-only notifier on State).** `_CallScreenState._checkpointNotifier` is a `ValueNotifier<CheckpointSnapshot?>` initialized to `null`; disposed BEFORE `super.dispose()`. Exposed under `@visibleForTesting` getter `checkpointNotifierForTest` so the Phase 1 integration tests can drill in without pumping the Phase 2 Rive subtree. `CheckpointSnapshot` value class lives at `client/lib/features/call/views/widgets/checkpoint_snapshot.dart` (NEW sibling file — Phase 2 widget will import from same path).

✅ **AC4 (Deviation #2 — call_end reconcile).** `onCallEnd` callback parses `data.checkpoints_passed` + `data.total_checkpoints`, walks the notifier UP to the server-authoritative count BEFORE dispatching `RemoteCallEnded` to the bloc. Defensive: only walks UP (`pi > current.currentIndex && ti > 0 && pi <= ti`); the no-walk-back guard is enforced by integration test #3 and would mask a genuine future server-side regression if removed.

✅ **AC5 (integration tests).** 3 tests in `call_screen_test.dart`:
  1. `checkpoint_advanced envelope updates _checkpointNotifier with typed snapshot`
  2. `call_end reconciles _checkpointNotifier UP to server-authoritative checkpoints_passed`
  3. `call_end with checkpoints_passed LOWER than current does NOT walk back` (extra defensive coverage beyond spec's 2)

✅ **AC9 Phase 1 pre-commit gates.** Server: `ruff check .` clean, `ruff format --check .` 56 files clean, pytest = **323 passed** (target ≥323 — Story 6.6 baseline 321 + 2 net new). Client: `flutter analyze` "No issues found!", `flutter test` = **364 passed** (baseline 357 + 4 handler + 3 integration = 364; target was ≥363).

**Phase 2 complete (2026-05-18, same day post-Phase-1).**

✅ **AC6 (`CheckpointStepperCanvas` widget).** Created at `client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart` (~150 LOC). Mirrors `RiveCharacterCanvas`'s 0.14.x integration pattern verbatim with the 3 documented deltas: no `.byName()` selectors, no Rive→Flutter event listener, `Fit.layout` instead of `Fit.cover`. `_initRive` / `_enterFallback` / `_onRiveLoaded` (caches 3 ViewModel handles) / `_applySnapshot` (the SOLE 0→1-based translation site) / `didUpdateWidget` / `dispose` all implemented. Pubspec asset registered alphabetically.

✅ **AC7 (Stack Layer 4 integration).** `_buildConnected` extended with Layer 4: `Positioned.fill → SafeArea(bottom:false) → Align(topCenter) → IgnorePointer(true) → ValueListenableBuilder<CheckpointSnapshot?> → SizedBox(height: 120, width: ∞) → CheckpointStepperCanvas`. Placed AFTER the Rive character layer (paints on top), BEFORE the conditional `if (_canvasInFallback)` block. `SizedBox(height: 120)` is a one-shot placeholder per spec — tune on first device smoke.

✅ **AC8 (3 widget tests + 1 sanity).** `client/test/features/call/views/widgets/checkpoint_stepper_canvas_test.dart` — 4 tests total: precondition assertion (RiveNative not initialized), shrink-when-null, shrink-in-fallback, snapshot-changes-do-not-throw-in-fallback. All pass on the fallback path; visual correctness owned by the Smoke Test Gate.

✅ **AC9 Phase 2 pre-commit gates.** `flutter analyze` "No issues found!". `flutter test` = **368 passed** (target ≥366; baseline 357 + 11 net = 368). Server pytest still **323 passed** (no Phase 2 server changes).

✅ **AC9 Phase 2 final (post-2026-05-19 retouches).** `flutter analyze` "No issues found!". `flutter test` = **373 passed** (baseline 357 + 16 net: 4 handler + 3 integration + 4 stepper canvas + 5 hint bubble). Server pytest = **325 passed** (baseline 321 + 4 net: `test_build_initial_envelope_returns_index_zero_frame`, `test_emit_initial_state_pushes_index_zero_envelope` (legacy), `test_schedule_initial_emit_pushes_envelope_on_first_process_frame`, `test_on_first_participant_joined_queues_initial_envelope_via_task`).

**Deviations recorded:**

- **Deviation #1** (no `v: 1` on envelope) — retires deferred-work.md line 396. Rationale: no precedent across emotion/viseme/hang_up_warning/call_end/bot_speaking_ended; additive evolution via `data.{}`; breaking changes use a new `type`. Documented in code (envelope `case 'checkpoint_advanced':` block comment in `data_channel_handler.dart`).
- **Deviation #2** (`call_end` reconcile) — retires deferred-work.md line 406. The `onCallEnd` callback now walks the local stepper UP to `data.checkpoints_passed` before `RemoteCallEnded`. Test #3 ("no walk-back") guards the defensive read.
- ~~**Deviation #3** (1-based `stepsCount` translation) — lives in exactly one place: `CheckpointStepperCanvas._applySnapshot`, `_stepsCount?.value = (snap.currentIndex + 1).toDouble();`. Server emit + client envelope + `CheckpointSnapshot` + `_checkpointNotifier` all use 0-based; the +1 is only applied at the Rive boundary. Walid authors the .riv against human-readable "step 1 of 6" numbering.~~ **SUPERSEDED 2026-05-19 by Deviation #6** — `.riv` re-authored to consume `stepsCount = total` (constant) + `lastCheckIndex = currentIndex` (0-based). No translation lives in Flutter.
- **Deviation #4** (`hint_text` → `hintText` rename, **NEW 2026-05-18**) — Walid's `.riv` ships with `hintText` (camelCase) instead of the spec's `hint_text` (snake_case). Rationale: Rive's recommended naming convention. Owner is the `.riv` source-of-truth — Dart code updated to `viewModel.string('hintText')` accordingly. The data-channel wire field (`next_hint`) and the Dart-side `CheckpointSnapshot.hintText` are unaffected by this rename; the change is purely the string passed to `viewModel.string(...)` at the Rive boundary. Documented in `checkpoint_stepper_canvas.dart::_onRiveLoaded` inline comment.
- **Deviation #8** (`checkpoints_passed` server wiring, **NEW 2026-05-20 from smoke-test finding**) — Smoke call_id=133 surfaced that `call_end.checkpoints_passed` was always emitted as `0` regardless of progress, because `patience_tracker.py:926` had a Story-6.4-era hardcoded placeholder waiting to be wired by Story 6.6. The Story 6.7 Deviation #2 client-side reconcile depends on this field being live (the guard `pi > current.currentIndex` falls through when `pi=0`). Fix: added `PatienceTracker.set_checkpoints_passed(count)`; CheckpointManager calls it after every `self._index += 1` (intermediate) and before `schedule_completion` (terminal). Retires the long-standing TODO from Story 6.4 (`patience_tracker.py:65,74,213`). Tests: extended `test_schedule_completion_speaks_survived_line_and_emits_envelope` to assert `checkpoints_passed == 6` on survival; new `test_set_checkpoints_passed_threads_through_character_hung_up_envelope` covers the mid-flight path (`checkpoints_passed == 2` when meter drains after 2 passes); extended `test_emits_advance_envelope_with_full_metadata` + `test_last_checkpoint_passed_routes_to_schedule_completion` to verify the CheckpointManager wiring + call order. Net: 325 → 326 tests passing.

**Halt point for `review → done`:** Smoke Test Gate (11 boxes above) is Walid-owned per Story 6.5 D6. The Phase 1 server change (`emit_initial_state`) requires a VPS deploy before live testing; Phase 2 is client-only. Pre-commit code gates are green; deploy + smoke validation are the stop-ship for `review → done`. Awaiting `/commit` from Walid + smoke-gate proofs.

### File List

**Server (modified — Phase 1):**
- `server/pipeline/checkpoint_manager.py` — added `async def emit_initial_state(self) -> None:` (lines ~325-365); re-uses existing `OutputTransportMessageFrame` shape + `FrameDirection.DOWNSTREAM`.
- `server/pipeline/bot.py` — added 1-line `await checkpoint_manager.emit_initial_state()` inside `on_first_participant_joined` AFTER the existing greeting queue.
- `server/tests/test_checkpoint_manager.py` — added `test_emit_initial_state_pushes_index_zero_envelope` under new "Story 6.7 — AC1" section.
- `server/tests/test_bot_pipeline_wiring.py` — added `test_on_first_participant_joined_calls_emit_initial_state` (source-text assertion).

**Client (new — Phase 1):**
- `client/lib/features/call/services/checkpoint_advanced_payload.dart` — `CheckpointAdvancedPayload` value class (~25 LOC).
- `client/lib/features/call/views/widgets/checkpoint_snapshot.dart` — `CheckpointSnapshot` value class with `==` / `hashCode` (~40 LOC). Phase 2 widget will import from this path.

**Client (modified — Phase 1):**
- `client/lib/features/call/services/data_channel_handler.dart` — added `onCheckpointAdvanced` required callback + `case 'checkpoint_advanced':` branch with defensive parse + range-check; removed Story-6.7-marker comment from `default` branch.
- `client/lib/features/call/views/call_screen.dart` — extended `DataChannelHandlerBuilder` typedef; added `_checkpointNotifier` field + `@visibleForTesting` getter; extended `dispose()`; wired `onCheckpointAdvanced` + extended `onCallEnd` with Deviation #2 reconcile.
- `client/test/features/call/services/data_channel_handler_test.dart` — added 4 tests for `checkpoint_advanced` routing; threaded `onCheckpointAdvanced: (_) {},` through every existing builder; replaced synthetic-type fixture in `'unknown envelope type'` test from `checkpoint_advanced` → `future_unknown_type_v9`.
- `client/test/features/call/views/call_screen_test.dart` — added 3 tests under "CallScreen — checkpoint stepper plumbing (Story 6.7)" group; threaded `onCheckpointAdvanced` through the 4 existing `debugHandlerBuilder` closures.

**Client (new — Phase 2 shipped 2026-05-18, mutated through 2026-05-19 final state):**
- `client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart` — Rive-loader widget (~120 LOC after cleanup). Renders the stepper row only (bubble was split out per retouche #15). `AspectRatio` driven by pre-loaded `widthOriginal/heightOriginal`. ViewModel writes use the corrected `stepsCount = total` / `lastCheckIndex = currentIndex` semantics (Deviation #6).
- `client/test/features/call/views/widgets/checkpoint_stepper_canvas_test.dart` — 4 widget tests (RiveNative-fallback path).
- **NEW 2026-05-19** `client/lib/features/call/views/widgets/checkpoint_hint_bubble.dart` — Flutter-native bubble widget (~75 LOC). `Container` + `Text` + `AnimatedSwitcher` cross-fade. Replaces the Rive bubble after Deviation #5.
- **NEW 2026-05-19** `client/test/features/call/views/widgets/checkpoint_hint_bubble_test.dart` — 5 widget tests including the multi-line wrap regression guard.
- `client/assets/rive/checkpoint_stepper.riv` — delivered by Walid 2026-05-18, **re-exported 2026-05-19 with the bubble element removed** (per Deviation #5).

**Client (modified — Phase 2 final state 2026-05-19):**
- `client/lib/features/call/views/call_screen.dart` — Layer 4 in `_buildConnected` is now a composite: `Column[CheckpointStepperCanvas (edge-to-edge), SizedBox(height: 8), Padding(horizontal: 16) → CheckpointHintBubble]`. Imports extended with `widgets/checkpoint_hint_bubble.dart`.
- `client/pubspec.yaml` — added `- assets/rive/checkpoint_stepper.riv`; re-sorted the Rive block alphabetically.

**Server (modified — Phase 2 final state 2026-05-19):**
- `server/pipeline/checkpoint_manager.py` — added `build_initial_envelope()` (pure builder) and `schedule_initial_emit()` (sets flag for self-trigger from `process_frame`). The deferred-emit pattern routes the initial envelope through the same downstream chain as the working advance envelopes. The original `emit_initial_state()` is kept for legacy push-path test coverage.
- `server/pipeline/bot.py` — `on_first_participant_joined` now calls `checkpoint_manager.schedule_initial_emit()` after the canned greeting `TTSSpeakFrame` queue (replaces the original `await checkpoint_manager.emit_initial_state()` which raced with pipecat's StartFrame propagation per Deviation #7).
- `server/tests/test_checkpoint_manager.py` — added `test_build_initial_envelope_returns_index_zero_frame` + `test_schedule_initial_emit_pushes_envelope_on_first_process_frame` (legacy `test_emit_initial_state_pushes_index_zero_envelope` retained for push-path coverage).
- `server/tests/test_bot_pipeline_wiring.py` — `test_on_first_participant_joined_queues_initial_envelope_via_task` renamed and rewritten to assert the `schedule_initial_emit` wiring + regression-guard against the broken `emit_initial_state` direct-call pattern.

**Test count final (2026-05-20, post-Deviation #8 smoke fix):**
- Server pytest: **326 passed** (Story 6.6 baseline 321 + 4 net new for emit/schedule/wiring + 1 net new for `set_checkpoints_passed` mid-flight wiring per Deviation #8)
- Client `flutter test`: **373 passed** (Story 6.6 baseline 357 + 16 net new: 4 handler + 3 integration + 4 stepper canvas + 5 hint bubble)
- `flutter analyze` + `ruff check` + `ruff format`: all clean

### Review Findings (2026-05-19)

Sources: 3 parallel reviewers (Blind Hunter / Edge Case Hunter / Acceptance Auditor). 33 raw findings → 3 decision-needed, 15 patch, 5 defer, 4 dismissed.

**Decision-needed (resolved 2026-05-20):**

- [x] [Review][Decision][DISMISSED] Smoke Test Box 5 self-checked without Walid proof — Walid resolution 2026-05-20: widget-test coverage accepted as sufficient proof for non-deploy items. Box 5 `[x]` stands.

- [x] [Review][Decision][DISMISSED] Reconcile drives `lastCheckIndex == total` (off-the-end) — Walid resolution 2026-05-20: Rive state machine handles `lastCheckIndex = N` correctly ("all checked" semantics). Behavior is intentional; no clamp needed.

- [x] [Review][Decision][→ PATCH] Defensive `hintText` Rive ViewModel write — Walid resolution 2026-05-20: keep the write, strengthen the comment to warn future devs that re-adding the bubble to `.riv` requires removing `CheckpointHintBubble` from `call_screen.dart` to avoid double-render.

**Patch:**

- [x] [Review][Patch] `_initRive` post-await race — missing `mounted` check before `_enterFallback` AND `setState`-after-dispose window [client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart:108-127] — after `await loader.file()`, the `if (artboard == null || w == null || h == null || w <= 0 || h <= 0)` branch calls `_enterFallback()` without re-checking `mounted`. Also the `setState((){_riveLoader = loader; _artboardAspectRatio = w / h;})` two lines below has no mounted re-check between the prior `if (!mounted)` and the assignment, opening a microtask-window dispose race. Fix: add `if (!mounted) { loader.dispose(); return; }` before both `_enterFallback()` and the `setState`.

- [x] [Review][Patch] FileLoader leaked when `loader.file()` throws during pre-load [client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart:104-126] — if `await loader.file()` throws (corrupt `.riv`, decoder bug, OOM), control jumps to the outer `catch (_) { _enterFallback(); }` without `loader.dispose()`. Native Rive file handle leaks on every call session that hits this branch. Fix: move `final loader` allocation inside its own try/catch that disposes on throw, OR `catch (e) { loader.dispose(); ... }` with the loader hoisted into scope.

- [x] [Review][Patch] Bubble `Text` has no `maxLines` / `overflow` — unbounded server hint × textScaler blows up the bubble [client/lib/features/call/views/widgets/checkpoint_hint_bubble.dart:79-92] — long YAML hint or high textScaler (2.0 on iPhone SE) → bubble occupies 30%+ of screen, visually overlaps avatar. Fix: add `maxLines: 3, overflow: TextOverflow.ellipsis` on the `Text` widget; consider also clamping `MediaQuery.textScalerOf(context).clamp(maxScaleFactor: 1.4)` for the bubble subtree.

- [x] [Review][Patch] Spec contradiction — strike Deviation #3 (1-based) per Deviation #6 [_bmad-output/implementation-artifacts/6-7-build-checkpointstepper-overlay-for-call-screen.md:41,376,593,737] — line 41 Background, line 376 (AC6 step 5), line 593 (Dev Notes "Why translate 0-based → 1-based"), line 737 (Completion Notes deviation list) all still document Deviation #3 (`_stepsCount = currentIndex + 1`). Deviation #6 retires it (`_stepsCount = total`, `_lastCheckIndex = currentIndex`). The current code at `checkpoint_stepper_canvas.dart:167-168` follows Deviation #6. Strike or visibly mark Deviation #3 as superseded everywhere.

- [x] [Review][Patch] Spec — Background "Visual contract" still claims bubble is in Rive [_bmad-output/implementation-artifacts/6-7-build-checkpointstepper-overlay-for-call-screen.md:17,24,29] — line 17 "Walid designs and animates the entire HUD in Rive — circles, connecting lines, fill transitions, hint bubble, visibility logic", line 24 `hint_text` empty-string-hides contract, line 29 lists `#1E1F23` as bubble fill — all contradicted by Deviation #5 (bubble moved to Flutter widget with `AppColors.textPrimary` fill). Amend the Background block visibly so a fresh reader doesn't follow the obsolete contract.

- [x] [Review][Patch] Spec — Smoke Test Box 3 wording stale ("First hint bubble shows…") [_bmad-output/implementation-artifacts/6-7-build-checkpointstepper-overlay-for-call-screen.md:496] — bubble is rendered by `CheckpointHintBubble` below the stepper row, not inside it. Update wording to describe the Flutter widget below the stepper.

- [x] [Review][Patch] Spec — Smoke Test Box 4 references retired Deviation #3 and "animation runs entirely inside Rive" [_bmad-output/implementation-artifacts/6-7-build-checkpointstepper-overlay-for-call-screen.md:499] — bubble crossfade is now a Flutter `AnimatedSwitcher`. Box 4 wording must reflect Deviation #6 numerics + Flutter-side animation.

- [x] [Review][Patch] Spec — strike AC1 source-text contract for `emit_initial_state` per Deviation #7 [_bmad-output/implementation-artifacts/6-7-build-checkpointstepper-overlay-for-call-screen.md:90] — AC1 still states `await checkpoint_manager.emit_initial_state()` must be called from `on_first_participant_joined`. Actual code at `bot.py:288` calls `schedule_initial_emit()` (sync). Mark AC1 superseded.

- [x] [Review][Patch] Spec — AC1 test name amendment for renamed test [_bmad-output/implementation-artifacts/6-7-build-checkpointstepper-overlay-for-call-screen.md:94] — AC1 requires `test_on_first_participant_joined_calls_emit_initial_state`. Actual test renamed to `test_on_first_participant_joined_queues_initial_envelope_via_task` (line 775). Add an inline amendment line.

- [x] [Review][Patch] AnimatedSwitcher key uses `hintText` only — identical hint across consecutive checkpoints suppresses any visual feedback [client/lib/features/call/views/widgets/checkpoint_hint_bubble.dart:51-54] — `ValueKey<String>(snap.hintText)` collides when two scenarios share a hint string. Fix: key on `('${snap.currentIndex}-${snap.hintText}')` so any checkpoint change triggers the cross-fade.

- [x] [Review][Patch] Test `Container.firstWhere` throws `StateError` on implementation drift [client/test/features/call/views/widgets/checkpoint_hint_bubble_test.dart:81-87] — `containers.firstWhere((c) => dec.color == AppColors.textPrimary)` throws an uncaught `StateError: No element` if the implementation ever wraps in `DecoratedBox`/`Material`. Replace with `find.byType(_Bubble)` (via testable export) or `find.descendant(of: find.byType(CheckpointHintBubble), matching: find.byType(Container))`.

- [x] [Review][Patch] Redundant `rootBundle.load` sanity-check pre-decodes the 880KB asset twice [client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart:103-105] — `rootBundle.load(_assetPath)` then `FileLoader.fromAsset(_assetPath, ...).file()` — both decode the asset bytes. `FileLoader.fromAsset` already throws if the asset is missing. Remove the explicit `rootBundle.load` OR comment why it's kept (e.g., catches asset-not-bundled before allocating a loader).

- [x] [Review][Patch] Test `renders SizedBox.shrink() when hintText is empty` does not actually verify `SizedBox.shrink` [client/test/features/call/views/widgets/checkpoint_hint_bubble_test.dart:55-66] — asserts only `find.byType(Text) == nothing`. A future refactor returning `Container()` instead of `SizedBox.shrink()` would still pass. Add `expect(find.byType(SizedBox), findsWidgets);` or assert the rendered size is zero.

- [x] [Review][Patch] Bubble non-empty → empty transition has no fade-out animation [client/lib/features/call/views/widgets/checkpoint_hint_bubble.dart:38-42] — when `hintText` becomes empty, `build()` short-circuits to `SizedBox.shrink()` BEFORE the `AnimatedSwitcher`, so the previous `_Bubble` unmounts instantly. Fix: keep `AnimatedSwitcher` always; switch child to `SizedBox.shrink(key: ValueKey('empty'))` when empty so the switcher fades out the old bubble.

- [x] [Review][Patch] Edge-to-edge claim relies on artboard aspect ratio + loose constraints — make the contract explicit [client/lib/features/call/views/call_screen.dart:828-838] — `Column(mainAxisSize: MainAxisSize.min)` inside `Align(topCenter)` defaults to `CrossAxisAlignment.center`. Today's wide artboard renders edge-to-edge by coincidence (AspectRatio fills max width). If the `.riv` is ever re-exported tall/narrow, the stepper centers and shrinks. Fix: wrap stepper child in `SizedBox(width: double.infinity, child: AspectRatio(...))` to make the "edge-to-edge" intent enforced rather than emergent.

- [x] [Review][Patch] Strengthen defensive `hintText` Rive ViewModel write comment [client/lib/features/call/views/widgets/checkpoint_stepper_canvas.dart:151] — resolved from Decision #3. The defensive write stays, but the comment must warn future devs: re-introducing a bubble element bound to `hintText` in the `.riv` requires REMOVING `CheckpointHintBubble` from `call_screen.dart` to prevent double-render (one Rive bubble + one Flutter bubble).

**Deferred (pre-existing or as-designed):**

- [x] [Review][Defer] `deferred-work.md` lines 396 / 406 not pointer-linked from Completion Notes [_bmad-output/implementation-artifacts/6-7-build-checkpointstepper-overlay-for-call-screen.md:573-574] — spec explicitly opted to keep historical record untouched per Task 8 convention. As-designed.

- [x] [Review][Defer] AnimatedSwitcher cross-fade test assertion semantics — `findsOneWidget` at 100ms during 250ms cross-fade [client/test/features/call/views/widgets/checkpoint_hint_bubble_test.dart:91-128] — test passes today; assertion catches the incoming widget. Test-only concern.

- [x] [Review][Defer] Bubble test relies on Inter font being available at test runtime [client/test/features/call/views/widgets/checkpoint_hint_bubble_test.dart:130-168] — `expect(textBox.size.height, greaterThan(45))` is font-metric-dependent. Flutter's test fallback font may produce different wrap. Not currently broken.

- [x] [Review][Defer] Future test-ticker leak fragility if AnimatedSwitcher duration is ever bumped past 400ms [client/test/features/call/views/widgets/checkpoint_hint_bubble_test.dart:91-128] — not present today; flag if duration ever changes.

- [x] [Review][Defer] `CheckpointHintBubble` does not defensively guard against `snap.total <= 0` or `currentIndex < 0` [client/lib/features/call/views/widgets/checkpoint_hint_bubble.dart] — `data_channel_handler.dart` enforces upstream. Defensive duplication not warranted.

**Dismissed (4):** AC4 reconcile non-Map `data` guard (Auditor self-withdrew on closer look); Blind Hunter B5 pre-load mounted check (author self-withdrew); Server `schedule_initial_emit` verify-by-trust (meta-advice, scope was client-only); `onCallEnd` ValueNotifier-after-dispose (Edge Case Hunter self-withdrew after verification).
