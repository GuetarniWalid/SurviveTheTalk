import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:rive/rive.dart' as rive;

import '../../../../core/theme/app_colors.dart';

/// Full-screen Rive character canvas for the in-call surface (Story 6.2).
///
/// Renders the `FaceTime` artboard from `assets/rive/characters.riv` — the
/// full-body in-call scene exposing the character variant + the in-canvas
/// 64×64 hang-up button. Mirrors `CharacterAvatar`'s 0.14.x integration
/// pattern (see `memory/rive-flutter-rules.md` §3, §6) with three deltas:
///
///   1. `artboardSelector: byName('FaceTime')` — different artboard from the
///      head-only `Picture` used by `CharacterAvatar`.
///   2. `Fit.cover` with `Alignment.bottomCenter` so the hang-up button at
///      the artboard's bottom edge stays on screen on tall viewports.
///   3. Listens for the Rive `onHangUp` event and forwards it to the parent
///      via the [onHangUp] callback (Rive→Flutter, one-way per
///      `rive-flutter-rules.md` §5).
///
/// Fallback contract: when `RiveNative.isInitialized` is false (widget tests
/// or rare prod bootstrap failures), renders a solid `AppColors.background`
/// container instead of the Rive canvas, and fires [onFallback] exactly once
/// so the parent can swap in a Flutter hang-up button (per AC7).
class RiveCharacterCanvas extends StatefulWidget {
  /// Rive `character` enum value (e.g. `'waiter'`, `'cop'`). Must match a
  /// case on the `character` enum on `ViewModel1` inside `characters.riv`.
  final String character;

  /// Fired when the user taps the in-canvas hang-up button (Rive `onHangUp`
  /// event). Wired by `CallScreen` to dispatch `HangUpPressed` to `CallBloc`.
  final VoidCallback? onHangUp;

  /// Fired exactly once if the canvas falls back to the solid container
  /// (Rive native unavailable). Lets the parent show a Flutter hang-up
  /// button so the user retains an exit affordance.
  final VoidCallback? onFallback;

  const RiveCharacterCanvas({
    super.key,
    required this.character,
    this.onHangUp,
    this.onFallback,
  });

  @override
  State<RiveCharacterCanvas> createState() => RiveCharacterCanvasState();
}

@visibleForTesting
class RiveCharacterCanvasState extends State<RiveCharacterCanvas> {
  static const String _assetPath = 'assets/rive/characters.riv';

  /// Name of the Rive event the in-canvas hang-up button fires. The .riv
  /// file (`assets/rive/characters.riv` → `FaceTime` artboard) must emit
  /// exactly this string when the user taps the in-canvas button.
  @visibleForTesting
  static const String hangUpEventName = 'onHangUp';

  rive.FileLoader? _riveLoader;

  /// Captured at `onLoaded` time so `dispose` removes the listener from the
  /// SAME StateMachine instance it was registered on (the controller can
  /// swap state machines if rebuilt).
  rive.StateMachine? _stateMachine;
  rive.ViewModelInstanceEnum? _characterEnum;
  bool _riveFallback = false;

  @override
  void initState() {
    super.initState();
    _initRive();
  }

  @override
  void didUpdateWidget(RiveCharacterCanvas oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.character != widget.character) {
      _characterEnum?.value = widget.character;
    }
  }

  @override
  void dispose() {
    _stateMachine?.removeEventListener(_onRiveEvent);
    _stateMachine = null;
    _riveLoader?.dispose();
    super.dispose();
  }

  Future<void> _initRive() async {
    if (!rive.RiveNative.isInitialized) {
      _enterFallback();
      return;
    }
    try {
      await rootBundle.load(_assetPath);
      if (!mounted) {
        // Widget unmounted during the await window — never assign the loader
        // because `dispose()` already ran (or won't run again) and the
        // FileLoader would leak.
        return;
      }
      _riveLoader = rive.FileLoader.fromAsset(
        _assetPath,
        riveFactory: rive.Factory.rive,
      );
      setState(() {});
    } catch (_) {
      _enterFallback();
    }
  }

  void _enterFallback() {
    // Idempotent — `_enterFallback` may be reached from BOTH the
    // `RiveNative.isInitialized` early-out AND the catch path. The
    // `onFallback` contract is "fired exactly once".
    if (_riveFallback) return;
    if (!mounted) return;
    // Defer the state flip + parent callback to after the current frame.
    // `_initRive` may run synchronously from `initState` (when `RiveNative
    // .isInitialized` is false in tests), so a synchronous setState here
    // would mark the parent dirty during its first build phase.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (_riveFallback) return;
      setState(() => _riveFallback = true);
      widget.onFallback?.call();
    });
  }

  void _onRiveLoaded(rive.RiveLoaded state) {
    // RiveWidgetBuilder may invoke onLoaded more than once across rebuilds.
    // Tear down any prior listener before re-registering, otherwise every
    // tap on the in-canvas hang-up button would dispatch HangUpPressed N
    // times.
    _stateMachine?.removeEventListener(_onRiveEvent);
    final viewModel = state.viewModelInstance;
    if (viewModel != null) {
      _characterEnum = viewModel.enumerator('character');
      _characterEnum?.value = widget.character;
    }
    _stateMachine = state.controller.stateMachine;
    _stateMachine?.addEventListener(_onRiveEvent);
  }

  void _onRiveEvent(rive.Event event) {
    _handleRiveEventName(event.name);
  }

  void _handleRiveEventName(String name) {
    if (name == hangUpEventName) {
      widget.onHangUp?.call();
    }
  }

  /// Test seam — simulates a Rive event firing without needing a real
  /// `rive.Event` instance (which the Rive package does not expose a
  /// public constructor for in 0.14.x). Lets widget tests prove the
  /// `onHangUp` event-name → `HangUpPressed` wiring stays correct even
  /// without RiveNative initialized.
  @visibleForTesting
  void debugDispatchRiveEventName(String name) =>
      _handleRiveEventName(name);

  @override
  Widget build(BuildContext context) {
    if (_riveFallback || _riveLoader == null) {
      return Container(color: AppColors.background);
    }
    return rive.RiveWidgetBuilder(
      fileLoader: _riveLoader!,
      artboardSelector: rive.ArtboardSelector.byName('FaceTime'),
      stateMachineSelector:
          rive.StateMachineSelector.byName('MainStateMachine'),
      dataBind: rive.DataBind.auto(),
      onLoaded: _onRiveLoaded,
      builder: (context, state) {
        if (state is rive.RiveLoaded) {
          return rive.RiveWidget(
            controller: state.controller,
            fit: rive.Fit.cover,
            alignment: Alignment.bottomCenter,
          );
        }
        return Container(color: AppColors.background);
      },
    );
  }
}
