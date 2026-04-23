import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:rive/rive.dart' as rive;

import '../../../../core/theme/call_colors.dart';

/// Circular character avatar rendered from the shared `characters.riv` file.
///
/// Rive integration pattern — see `memory/rive-flutter-rules.md` §3, §6:
///   1. `RiveNative.isInitialized` gate so widget tests (which don't call
///      `bootstrap()`) always fall back to the plain colored circle.
///   2. `rootBundle.load(...)` pre-check so a missing asset surfaces as a
///      fallback rather than an ANR at the first render.
///   3. `artboardSelector: byName('Picture')` + `stateMachineSelector:
///      byName('MainStateMachine')` select the head-only artboard that ships
///      with the characters puppet file (Epic 2 Story 2.6). Full-body scenes
///      used by Epic 6's call screen live on a different artboard.
///   4. `DataBind.auto()` — never `.byName()`, which hangs indefinitely.
///   5. `viewModel.enumerator('character').value = character` — tells Rive
///      which character to render (shared enum across all character-bearing
///      artboards so the waiter here matches the waiter on the call screen).
class CharacterAvatar extends StatefulWidget {
  /// Rive enum value identifying the character (e.g. `'waiter'`, `'cop'`).
  /// Must match one of the values in the `character` enum on `ViewModel1`
  /// inside `characters.riv`.
  final String character;
  final double size;

  const CharacterAvatar({
    super.key,
    required this.character,
    this.size = 166,
  });

  @override
  State<CharacterAvatar> createState() => _CharacterAvatarState();
}

class _CharacterAvatarState extends State<CharacterAvatar> {
  static const String _assetPath = 'assets/rive/characters.riv';

  rive.FileLoader? _riveLoader;
  rive.ViewModelInstanceEnum? _characterEnum;
  bool _riveFallback = false;

  @override
  void initState() {
    super.initState();
    _initRive();
  }

  @override
  void didUpdateWidget(CharacterAvatar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.character != widget.character) {
      _characterEnum?.value = widget.character;
    }
  }

  @override
  void dispose() {
    _riveLoader?.dispose();
    super.dispose();
  }

  Future<void> _initRive() async {
    if (!rive.RiveNative.isInitialized) {
      if (mounted) setState(() => _riveFallback = true);
      return;
    }
    try {
      await rootBundle.load(_assetPath);
      _riveLoader = rive.FileLoader.fromAsset(
        _assetPath,
        riveFactory: rive.Factory.rive,
      );
      if (mounted) setState(() {});
    } catch (_) {
      if (mounted) setState(() => _riveFallback = true);
    }
  }

  void _onRiveLoaded(rive.RiveLoaded state) {
    final viewModel = state.viewModelInstance;
    if (viewModel != null) {
      _characterEnum = viewModel.enumerator('character');
      _characterEnum?.value = widget.character;
    }
  }

  @override
  Widget build(BuildContext context) {
    return ClipOval(
      child: Container(
        width: widget.size,
        height: widget.size,
        color: CallColors.avatarBackground,
        child: _buildChild(),
      ),
    );
  }

  Widget _buildChild() {
    if (_riveFallback || _riveLoader == null) {
      return const SizedBox.shrink();
    }
    return rive.RiveWidgetBuilder(
      fileLoader: _riveLoader!,
      artboardSelector: rive.ArtboardSelector.byName('Picture'),
      stateMachineSelector:
          rive.StateMachineSelector.byName('MainStateMachine'),
      dataBind: rive.DataBind.auto(),
      onLoaded: _onRiveLoaded,
      builder: (context, state) {
        if (state is rive.RiveLoaded) {
          return rive.RiveWidget(
            controller: state.controller,
            fit: rive.Fit.cover,
          );
        }
        return const SizedBox.shrink();
      },
    );
  }
}
