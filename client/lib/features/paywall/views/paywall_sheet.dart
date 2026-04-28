import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';

/// Placeholder bottom sheet that the BottomOverlayCard opens when tapped.
/// Story 8.2 will replace [PaywallSheet.show]'s body with the real subscription
/// surface (StoreKit / Play Billing flow), but the entry point — a sheet that
/// slides up from the bottom and matches the BOC's visual treatment — stays
/// the same.
///
/// Anatomy mirrors the BOC: `AppColors.textPrimary` (#F0F0F0) fill, top corners
/// rounded 42, slide-up animation (Material default for `showModalBottomSheet`).
class PaywallSheet {
  const PaywallSheet._();

  /// Top-corner radius. Matches the BottomOverlayCard so the visual lineage
  /// reads as one continuous surface emerging from the bottom of the screen.
  static const double _topRadius = 42.0;

  /// Open the sheet. Returns when the user dismisses it (swipe-down,
  /// tap-outside, or Story 8.2's CTA closing programmatically).
  static Future<void> show(BuildContext context) {
    return showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppColors.textPrimary,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(_topRadius)),
      ),
      // Default Material slide-up animation; no override needed.
      builder: (_) => const _PaywallSheetBody(),
    );
  }
}

class _PaywallSheetBody extends StatelessWidget {
  const _PaywallSheetBody();

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return Padding(
      // Match the BOC's bottom-inset extension so the sheet hugs the screen
      // edge identically. Generous vertical padding keeps the placeholder
      // readable without imposing a layout that Story 8.2 would have to
      // re-wire.
      padding: EdgeInsets.fromLTRB(20, 32, 20, 32 + bottomInset),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Drag-handle affordance — a small grey pill the user can grab to
          // dismiss. Matches the iOS / Material 3 modal sheet convention.
          Container(
            width: 36,
            height: 4,
            decoration: BoxDecoration(
              color: AppColors.overlaySubtitle.withValues(alpha: 0.4),
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(height: 24),
          Text(
            'Paywall — coming in Story 8.2',
            textAlign: TextAlign.center,
            style: AppTypography.body.copyWith(
              color: AppColors.background,
            ),
          ),
        ],
      ),
    );
  }
}
