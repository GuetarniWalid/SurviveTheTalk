import 'package:flutter/material.dart';
import 'package:rive/rive.dart' as rive;

import 'checkpoint_snapshot.dart';

/// Story 6.7 — Rive-driven checkpoint stepper row (the 6 circles +
/// connector). Renders `assets/rive/checkpoint_stepper.riv` (single
/// artboard + single state machine — default selectors).
///
/// ViewModel semantics (`Checkboxes` ViewModel in the `.riv`):
///   - `stepsCount`     (number) — TOTAL number of checkpoints. The
///                                  state machine draws this many
///                                  circles + connectors.
///   - `lastCheckIndex` (number) — Index of the LAST completed
///                                  checkpoint, 0-based. 0 = no
///                                  progress yet; N = first N
///                                  circles are "checked".
///
/// **The hint bubble used to live in this same `.riv` and is now a
/// Flutter widget — see [CheckpointHintBubble] + the documented
/// exception in `memory/feedback_hud_overlays_are_rive.md` + the
/// runtime-bug analysis in `memory/feedback_rive_runtime_hug_height_bug.md`.**
/// Walid's `.riv` was edited (2026-05-19) to remove the bubble; only
/// the stepper row remains. The `hintText` ViewModel write below is
/// kept defensively in case the `.riv` design ever re-introduces a
/// text element bound to it.
///
/// Integration pattern mirrors [RiveCharacterCanvas]'s Rive 0.14.x
/// shape with these documented deltas:
///   1. Default artboard + default state machine (no `.byName()`).
///   2. No Rive→Flutter events (the stepper emits nothing upstream).
///   3. `Fit.layout` for responsive layout artboards.
///   4. Pre-loads the file in `_initRive` to read
///      `widthOriginal/heightOriginal` and drive an [AspectRatio]
///      wrapper that matches the design proportions — the layout
///      engine then reflows in the same proportions as Rive Editor
///      preview.
///
/// Snapshot null OR Rive native unavailable ⇒ [SizedBox.shrink]
/// (graceful absence; stepper is non-critical UX).
class CheckpointStepperCanvas extends StatefulWidget {
  final CheckpointSnapshot? snapshot;

  const CheckpointStepperCanvas({super.key, required this.snapshot});

  @override
  State<CheckpointStepperCanvas> createState() =>
      _CheckpointStepperCanvasState();
}

class _CheckpointStepperCanvasState extends State<CheckpointStepperCanvas> {
  static const String _assetPath = 'assets/rive/checkpoint_stepper.riv';

  rive.FileLoader? _riveLoader;

  /// ViewModel handles cached on first `onLoaded`. Null-safe writes via
  /// `?.value =` mean a mismatched/renamed property in the .riv is a
  /// silent no-op (`memory/rive-flutter-rules.md` §5).
  rive.ViewModelInstanceNumber? _stepsCount;
  rive.ViewModelInstanceNumber? _lastCheckIndex;
  rive.ViewModelInstanceString? _hintText;

  /// Design ratio of the artboard, read once from
  /// `file.defaultArtboard()` during pre-load. Drives the
  /// [AspectRatio] wrapper in [build] so Rive's `Fit.layout` engine
  /// reflows in design proportions. Null until pre-load completes.
  double? _artboardAspectRatio;

  bool _riveFallback = false;

  @override
  void initState() {
    super.initState();
    _initRive();
  }

  @override
  void didUpdateWidget(CheckpointStepperCanvas oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.snapshot != widget.snapshot) {
      _applySnapshot(widget.snapshot);
    }
  }

  @override
  void dispose() {
    _riveLoader?.dispose();
    super.dispose();
  }

  Future<void> _initRive() async {
    if (!rive.RiveNative.isInitialized) {
      _enterFallback();
      return;
    }
    // Hoist the loader into outer scope so the catch block can dispose
    // it on `loader.file()` failure (avoids a native handle leak).
    rive.FileLoader? loader;
    try {
      loader = rive.FileLoader.fromAsset(
        _assetPath,
        riveFactory: rive.Factory.rive,
      );
      // Pre-load the file so we can read `widthOriginal/heightOriginal`
      // BEFORE mounting the RiveWidget. The FileLoader caches the
      // decoded file, so RiveWidgetBuilder reuses it at zero cost.
      final file = await loader.file();
      if (!mounted) {
        loader.dispose();
        return;
      }
      final artboard = file.defaultArtboard();
      final w = artboard?.widthOriginal;
      final h = artboard?.heightOriginal;
      if (artboard == null || w == null || h == null || w <= 0 || h <= 0) {
        loader.dispose();
        _enterFallback();
        return;
      }
      // Re-check mounted between the prior check and setState — there is
      // a microtask window where the widget can be disposed (route pop
      // racing with the async pre-load completion).
      if (!mounted) {
        loader.dispose();
        return;
      }
      setState(() {
        _riveLoader = loader;
        _artboardAspectRatio = w / h;
      });
    } catch (_) {
      loader?.dispose();
      _enterFallback();
    }
  }

  void _enterFallback() {
    // Idempotent — same pattern as RiveCharacterCanvas._enterFallback.
    // Deferred to post-frame because `_initRive` can run synchronously
    // from `initState` (when RiveNative.isInitialized is false in tests).
    if (_riveFallback) return;
    if (!mounted) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (_riveFallback) return;
      setState(() => _riveFallback = true);
    });
  }

  void _onRiveLoaded(rive.RiveLoaded state) {
    final viewModel = state.viewModelInstance;
    if (viewModel != null) {
      _stepsCount = viewModel.number('stepsCount');
      _lastCheckIndex = viewModel.number('lastCheckIndex');
      // Walid's .riv uses camelCase per Rive's recommended naming
      // convention; the data-channel field is `next_hint` (snake_case)
      // and the Dart-side getter is `hintText` — the latter matches
      // the .riv input name verbatim.
      _hintText = viewModel.string('hintText');
    }
    // Apply any snapshot present at the time the file finished loading
    // (the data-channel envelope may have landed before the .riv was
    // ready, so the handles were null when the first didUpdateWidget
    // tried to write).
    _applySnapshot(widget.snapshot);
  }

  void _applySnapshot(CheckpointSnapshot? snap) {
    if (snap == null) return;
    // Class docstring documents the semantics. `?.value =` is
    // null-safe (missing-property = silent no-op per
    // `memory/rive-flutter-rules.md` §5).
    _stepsCount?.value = snap.total.toDouble();
    _lastCheckIndex?.value = snap.currentIndex.toDouble();
    // Defensive write — the current .riv removed the bubble element.
    // WARNING: if a future .riv re-introduces a bubble bound to
    // `hintText`, you MUST also remove `CheckpointHintBubble` from
    // `call_screen.dart`. Leaving both in place would render TWO
    // bubbles on screen (one Rive + one Flutter).
    _hintText?.value = snap.hintText;
  }

  @override
  Widget build(BuildContext context) {
    if (widget.snapshot == null) return const SizedBox.shrink();
    if (_riveFallback || _riveLoader == null) {
      return const SizedBox.shrink();
    }
    final ratio = _artboardAspectRatio;
    if (ratio == null) {
      // Pre-load not finished yet — render nothing for ~1 frame.
      return const SizedBox.shrink();
    }
    // AspectRatio = design ratio of the stepper-only artboard. The
    // hint bubble lives in [CheckpointHintBubble] (Flutter widget) —
    // see story file Dev Agent Record for the Phase 2 retouche
    // history that led to that split.
    return AspectRatio(
      aspectRatio: ratio,
      child: rive.RiveWidgetBuilder(
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
      ),
    );
  }
}
