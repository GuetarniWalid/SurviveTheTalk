import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_typography.dart';
import '../../models/scenario.dart';

/// Modal bottom-sheet gate shown before initiating a call on a scenario whose
/// `content_warning` column is non-null. Resolves to `true` when the user
/// taps "Pick up" (proceed to /call), `false` otherwise (Not now, swipe-down,
/// scrim tap, system back-press, or any non-explicit dismissal).
///
/// Visual frame is locked by the Figma "iPhone 16 - 7" mock at
/// `C:\Users\gueta\Documents\figma-export\.figma\iphone-16-7\reference.png`:
/// drag handle, "HEADS UP" pill, static title "Buckle up", per-scenario body
/// (`scenario.contentWarning`), italic disclaimer "You can hang up anytime",
/// and the two-button row (Not now / Pick up).
Future<bool> showContentWarningSheet(
  BuildContext context,
  Scenario scenario,
) async {
  // Release-safe guard: assert is stripped in release builds, so an
  // accidental null-warning caller would crash on `scenario.contentWarning!`
  // downstream. Resolve early to `false` (the cancel branch) instead.
  final cw = scenario.contentWarning;
  if (cw == null) return false;
  final result = await showModalBottomSheet<bool>(
    context: context,
    // Sheet provides its own surface (dark) — keep the modal background
    // transparent so the rounded corners aren't double-clipped.
    backgroundColor: Colors.transparent,
    // Sized to its content; required for the column layout to expand
    // beyond the default half-screen ceiling.
    isScrollControlled: true,
    // Both default to true; spelled out so behavior is the contract.
    // Tap outside the sheet → null (cancel). Swipe the sheet down → null.
    isDismissible: true,
    enableDrag: true,
    builder: (ctx) => _ContentWarningSheet(contentWarning: cw),
  );
  // Coerce null (swipe-down, scrim tap, or any non-explicit pop) to `false`.
  // The only path to `true` is an explicit "Pick up" tap.
  return result ?? false;
}

class _ContentWarningSheet extends StatelessWidget {
  final String contentWarning;

  const _ContentWarningSheet({required this.contentWarning});

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: AppColors.textPrimary,
        borderRadius: BorderRadius.vertical(top: Radius.circular(42)),
      ),
      child: Padding(
        padding: EdgeInsets.fromLTRB(36, 24, 36, 36 + bottomInset),
        // SingleChildScrollView guards against vertical overflow at narrow
        // viewports + large text scale (AC7): on 320×480 with 1.5× scaler
        // the column intrinsic height exceeds the bottom-sheet rect, and
        // without scrolling the action row would be unreachable.
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const _DragHandle(),
              const SizedBox(height: 15),
              const _HeadsUpPill(),
              const SizedBox(height: 15),
              const _Title(),
              const SizedBox(height: 15),
              _Body(text: contentWarning),
              const SizedBox(height: 15),
              const _HangUpDisclaimer(),
              const SizedBox(height: 31),
              const _ActionRow(),
            ],
          ),
        ),
      ),
    );
  }
}

class _DragHandle extends StatelessWidget {
  const _DragHandle();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: 40,
        height: 4,
        decoration: const BoxDecoration(
          color: AppColors.overlaySubtitle,
          borderRadius: BorderRadius.all(Radius.circular(18)),
        ),
      ),
    );
  }
}

class _HeadsUpPill extends StatelessWidget {
  const _HeadsUpPill();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      decoration: const BoxDecoration(
        color: AppColors.headsUpBg,
        borderRadius: BorderRadius.all(Radius.circular(999)),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.shield_outlined,
            size: 16,
            color: AppColors.headsUpAccent,
          ),
          SizedBox(width: 6),
          Text(
            'HEADS UP',
            style: TextStyle(
              fontFamily: AppTypography.fontFamily,
              fontSize: 12,
              fontWeight: FontWeight.w400,
              color: AppColors.headsUpAccent,
              height: 15 / 12,
            ),
          ),
        ],
      ),
    );
  }
}

class _Title extends StatelessWidget {
  const _Title();

  @override
  Widget build(BuildContext context) {
    return const Text(
      'Buckle up',
      style: TextStyle(
        fontFamily: AppTypography.fontFamily,
        fontSize: 24,
        fontWeight: FontWeight.w700,
        color: AppColors.background,
        height: 29 / 24,
      ),
    );
  }
}

class _Body extends StatelessWidget {
  final String text;

  const _Body({required this.text});

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontFamily: AppTypography.fontFamily,
        fontSize: 14,
        fontWeight: FontWeight.w400,
        color: AppColors.background,
        height: 17 / 14,
      ),
    );
  }
}

class _HangUpDisclaimer extends StatelessWidget {
  const _HangUpDisclaimer();

  @override
  Widget build(BuildContext context) {
    return Text(
      'You can hang up anytime',
      style: TextStyle(
        fontFamily: AppTypography.fontFamily,
        fontSize: 14,
        fontWeight: FontWeight.w400,
        fontStyle: FontStyle.italic,
        color: AppColors.background.withValues(alpha: 0.7),
        height: 17 / 14,
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow();

  @override
  Widget build(BuildContext context) {
    // SizedBox(width: double.infinity) forces the Wrap to fill the column's
    // content width — without it, the parent Column's crossAxisAlignment.start
    // shrink-wraps the Wrap to its children's intrinsic width, leaving
    // `WrapAlignment.end` no room to push the buttons to the right.
    //
    // Wrap (not Row) so the buttons gracefully drop to a second line if the
    // current text-scale or fallback font widens them past the sheet's
    // content rect — instead of throwing a RenderFlex overflow.
    return SizedBox(
      width: double.infinity,
      child: Wrap(
        alignment: WrapAlignment.end,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 13,
        runSpacing: 8,
        children: [
          TextButton(
            style: TextButton.styleFrom(
              padding: const EdgeInsets.symmetric(
                horizontal: 24,
                vertical: 16,
              ),
              shape: const StadiumBorder(),
              foregroundColor: AppColors.background,
              textStyle: const TextStyle(
                fontFamily: AppTypography.fontFamily,
                fontSize: 14,
                fontWeight: FontWeight.w700,
                height: 17 / 14,
              ),
            ),
            onPressed: () => Navigator.pop(context, false),
            child: const Opacity(
              opacity: 0.7,
              child: Text('Not now'),
            ),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.accent,
              foregroundColor: AppColors.background,
              padding: const EdgeInsets.symmetric(
                horizontal: 24,
                vertical: 16,
              ),
              shape: const StadiumBorder(),
              elevation: 0,
              textStyle: const TextStyle(
                fontFamily: AppTypography.fontFamily,
                fontSize: 14,
                fontWeight: FontWeight.w700,
                height: 17 / 14,
              ),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.phone_outlined, size: 24),
                SizedBox(width: 10),
                Text('Pick up'),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
