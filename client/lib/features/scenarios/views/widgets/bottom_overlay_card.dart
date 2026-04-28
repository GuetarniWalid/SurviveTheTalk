import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../models/call_usage.dart';

/// One of the three visible variants of [BottomOverlayCard]. The fourth
/// "paid with calls" state has no card — `_variantFor` returns null and
/// the widget short-circuits to [SizedBox.shrink].
enum _OverlayVariant { freeWithCalls, freeExhausted, paidExhausted }

_OverlayVariant? _variantFor(CallUsage usage) {
  if (usage.isFree) {
    return usage.hasCallsRemaining
        ? _OverlayVariant.freeWithCalls
        : _OverlayVariant.freeExhausted;
  }
  // paid
  if (usage.hasCallsRemaining) return null; // BOC absent
  return _OverlayVariant.paidExhausted;
}

class _CardCopy {
  final String title;
  final String subtitle;
  final bool isActionable;
  final String semanticLabel;

  const _CardCopy({
    required this.title,
    required this.subtitle,
    required this.isActionable,
    required this.semanticLabel,
  });
}

const String _kSubtitleSurvive =
    "If you can survive us, real humans don't stand a chance";
const String _kTapToView = 'Tap to view subscription options.';

const Map<_OverlayVariant, _CardCopy> _kCopyByVariant = {
  _OverlayVariant.freeWithCalls: _CardCopy(
    title: 'Unlock all scenarios',
    subtitle: _kSubtitleSurvive,
    isActionable: true,
    semanticLabel:
        'Unlock all scenarios. $_kSubtitleSurvive. $_kTapToView',
  ),
  _OverlayVariant.freeExhausted: _CardCopy(
    title: 'Subscribe to keep calling',
    subtitle: _kSubtitleSurvive,
    isActionable: true,
    semanticLabel:
        'Subscribe to keep calling. $_kSubtitleSurvive. $_kTapToView',
  ),
  _OverlayVariant.paidExhausted: _CardCopy(
    title: 'No more calls today',
    subtitle: 'Come back tomorrow',
    isActionable: false,
    semanticLabel: 'No more calls today. Come back tomorrow.',
  ),
};

// Figma `Frame 22` (393×128) — the BOC card itself, before adding the
// device's bottom safe-area inset. Spec: fill #F0F0F0, top corners
// rounded radius 42 (bottom corners square because the card hugs the
// screen edge), padding 20 / 20 / 40 / 20, gap 10 between the diamond
// image and the text column. Padding values come from `AppSpacing` overlay
// tokens; the bottom-padding is `2 × overlayCardPadding` because the card
// extends through the safe-area inset and needs more breathing room below.
const double _kCardTopRadius = 42.0;
const EdgeInsets _kCardPaddingBeforeInset = EdgeInsets.fromLTRB(
  AppSpacing.overlayCardPadding,
  AppSpacing.overlayCardPadding,
  AppSpacing.overlayCardPadding,
  AppSpacing.overlayCardPadding * 2,
);
const double _kDiamondImageWidth = 73.0;
const double _kDiamondImageHeight = 55.0;

// Figma diamond image fill: blue gem (Generated_Image_…-removebg-preview).
// The figma-export script only exports VECTOR nodes; this raster fill is
// not in the asset folder yet. When the PNG lands at this path, the
// errorBuilder fallback below disappears automatically.
const String _kDiamondAssetPath = 'assets/images/diamond.png';

/// Conservative height estimate of the rendered BOC, EXCLUDING the device's
/// bottom safe-area inset (callers add that themselves via
/// `MediaQuery.viewPaddingOf(context).bottom`).
///
/// Computed from the shipped layout constants (post Walid render-pass):
///   - 20 top padding (`AppSpacing.overlayCardPadding`)
///   - max(diamond image 55, two-line text column ≈ 80 — title 16 px ×
///     (17/14) ≈ 19.4 × 2 lines + 10 gap + subtitle 13 px × (13/11) ≈
///     15.4 × 2 lines ≈ 80 px on narrow phones) → 80
///   - 40 bottom padding (`AppSpacing.overlayCardPadding * 2`)
///   = 140
///
/// `ScenarioListScreen` adds the safe-area inset on top of this so the list's
/// bottom padding always equals the actual rendered card height. The text
/// column dominates on narrow phones (< 430 px wide) where the subtitle
/// wraps to 2 lines; the image (55 px) only dominates on wide tablets where
/// the subtitle fits on one line — and there the over-reserve is ~20 px,
/// invisible relative to the safe-area inset.
const double _kBocStaticHeight =
    AppSpacing.overlayCardPadding +
        80.0 +
        AppSpacing.overlayCardPadding * 2;

class BottomOverlayCard extends StatelessWidget {
  /// Public re-export of the static rendered height (excluding safe area).
  /// Use this in callers that pin the BOC at the screen edge to size their
  /// own bottom padding.
  static const double staticContentHeight = _kBocStaticHeight;

  /// Whether the BOC is visible for the given usage. Callers (e.g.
  /// `ScenarioListScreen`) use this to skip the bottom-padding reservation
  /// when the BOC short-circuits to `SizedBox.shrink()` (the
  /// `paidWithCalls` state has no overlay — see `_variantFor`).
  static bool isVisibleFor(CallUsage usage) => _variantFor(usage) != null;

  final CallUsage usage;
  final VoidCallback? onPaywallTap;

  const BottomOverlayCard({
    super.key,
    required this.usage,
    this.onPaywallTap,
  });

  @override
  Widget build(BuildContext context) {
    final variant = _variantFor(usage);
    if (variant == null) return const SizedBox.shrink();

    final copy = _kCopyByVariant[variant]!;
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;

    final body = Container(
      width: double.infinity,
      decoration: const BoxDecoration(
        color: AppColors.textPrimary,
        // Top corners only — the card hugs the bottom edge of the screen
        // and extends INTO the safe-area inset.
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(_kCardTopRadius),
        ),
      ),
      padding: _kCardPaddingBeforeInset.copyWith(
        bottom: _kCardPaddingBeforeInset.bottom + bottomInset,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          const _DiamondImage(),
          const SizedBox(width: AppSpacing.overlayIconTextGap),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  copy.title,
                  // Bumped from Figma 14 → 16 for on-device legibility
                  // (Walid's render-pass iteration). Line-height ratio
                  // (≈1.214×) preserved from spec.
                  style: AppTypography.cardTitle.copyWith(
                    fontSize: 16,
                    height: 17 / 14,
                    color: AppColors.background,
                  ),
                ),
                const SizedBox(height: AppSpacing.overlayLineGap),
                Text(
                  copy.subtitle,
                  // Bumped from Figma 11 → 13 for on-device legibility.
                  // Line-height ratio (≈1.182×) preserved; reference shows
                  // the subtitle wrapping naturally onto a 2nd line.
                  style: AppTypography.cardStats.copyWith(
                    fontSize: 13,
                    height: 13 / 11,
                    color: AppColors.overlaySubtitle,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );

    final tappable = copy.isActionable && onPaywallTap != null;
    final interactiveBody = tappable
        ? Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: onPaywallTap,
              // Match the visual rounded-top so ripples don't bleed past
              // the card outline.
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(_kCardTopRadius),
              ),
              child: body,
            ),
          )
        : body;

    // Semantic `button` flag must match actual interactivity. If the variant
    // is informational OR the caller didn't wire a tap callback, announce
    // the label without the button affordance — otherwise screen readers
    // promise an action that doesn't fire.
    return Semantics(
      container: true,
      button: tappable,
      label: copy.semanticLabel,
      child: interactiveBody,
    );
  }
}

/// Figma `Frame 22 → Generated_Image_…removebg-preview 1` (RECTANGLE 73×55,
/// blue diamond gem image fill).
///
/// The asset is loaded from `assets/images/diamond.png`. If the file is
/// missing (figma-export.js doesn't extract raster image fills today —
/// only VECTOR nodes), `errorBuilder` shows a Material `Icons.diamond_outlined`
/// in the design-system accent so the layout never breaks. The placeholder
/// is intentionally NOT the Figma blue (no token for it in AppColors); the
/// real PNG replaces it as soon as it lands.
class _DiamondImage extends StatelessWidget {
  const _DiamondImage();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: _kDiamondImageWidth,
      height: _kDiamondImageHeight,
      child: Image.asset(
        _kDiamondAssetPath,
        width: _kDiamondImageWidth,
        height: _kDiamondImageHeight,
        fit: BoxFit.contain,
        errorBuilder: (context, error, stackTrace) {
          return const Icon(
            Icons.diamond_outlined,
            color: AppColors.accent,
            size: _kDiamondImageHeight,
          );
        },
      ),
    );
  }
}

