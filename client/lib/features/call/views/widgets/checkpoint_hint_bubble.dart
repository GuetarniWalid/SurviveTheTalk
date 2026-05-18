import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import 'checkpoint_snapshot.dart';

/// Story 6.7 Phase 2 retouche #11 (2026-05-19) — Flutter-native hint
/// bubble. Replaces the bubble that used to live inside the
/// `checkpoint_stepper.riv` file.
///
/// **Why a Flutter widget here, when the project default is Rive
/// (`feedback_hud_overlays_are_rive.md`)?** The Rive native runtime
/// (rive 0.14.3 / rive_native 0.1.2) does not re-evaluate
/// Hug-Contents Height on a layout element when its child text
/// content grows via ViewModel data binding. Verified against
/// rive-react-native issue #375 (open). The bubble in editor preview
/// grew correctly; on mobile it stayed clamped. Flutter's `Text`
/// widget natively hugs its content with zero ambiguity, so the
/// bubble is rendered here instead. See
/// `memory/feedback_rive_runtime_hug_height_bug.md` for the full
/// diagnosis and the documented exception to the HUD-is-Rive policy.
///
/// **What's still in Rive:** the 6 stepper circles + the connector
/// line + any state-machine animations on them. Those are static-
/// design or animation-driven content where the Rive runtime works
/// perfectly. Walid removed the bubble element from his `.riv` —
/// only the stepper row remains there.
///
/// Render contract: returns a [SizedBox.shrink] when `snapshot` is
/// null OR `snapshot.hintText` is empty. Otherwise renders an
/// [AnimatedSwitcher] cross-fading the bubble between hint changes,
/// so consecutive checkpoint advances animate gracefully.
class CheckpointHintBubble extends StatelessWidget {
  final CheckpointSnapshot? snapshot;

  const CheckpointHintBubble({super.key, required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final snap = snapshot;
    // Always render the AnimatedSwitcher so non-empty → empty
    // transitions also fade out gracefully (instead of an instant
    // pop). The empty-state child is a keyed SizedBox.shrink so the
    // switcher recognizes the switch.
    final isEmpty = snap == null || snap.hintText.isEmpty;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 250),
      switchInCurve: Curves.easeOut,
      switchOutCurve: Curves.easeIn,
      // Key on (currentIndex, hintText) so two consecutive checkpoints
      // sharing the same hint string still trigger a cross-fade. Pure
      // `ValueKey<String>(hintText)` collides on duplicate-hint advance.
      child: isEmpty
          ? const SizedBox.shrink(key: ValueKey<String>('empty'))
          : _Bubble(
              key: ValueKey<String>(
                '${snap.currentIndex}-${snap.hintText}',
              ),
              text: snap.hintText,
            ),
    );
  }
}

/// The actual bubble visual. Separated so [AnimatedSwitcher] can
/// swap distinct instances on hint change.
class _Bubble extends StatelessWidget {
  final String text;

  const _Bubble({super.key, required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      // Hug-Contents-equivalent: padding around the text, no width
      // constraint. The bubble grows horizontally to fit the text up
      // to the parent's max width, then wraps and grows vertically.
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        // Fill = off-white (AppColors.textPrimary, #F0F0F0) — reusing
        // an existing token rather than introducing a new one.
        color: AppColors.textPrimary,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        text,
        textAlign: TextAlign.center,
        // Bound the bubble against an unexpectedly long server hint
        // and against high system textScaler — without this, a verbose
        // YAML or accessibility scale 2.0 can blow the bubble up to
        // 30%+ of the screen and visually overlap the character.
        maxLines: 3,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
          fontFamily: 'Inter',
          fontSize: 18,
          fontWeight: FontWeight.w500,
          // Text color = the app's background dark (AppColors.background,
          // #1E1F23). Contrast against textPrimary fill is 13.5 : 1
          // (AA + AAA per `app_colors.dart` header table).
          color: AppColors.background,
          height: 1.25,
        ),
      ),
    );
  }
}
