// AppSpacing — UX-DR3 foundation: 8px base unit plus named constants for
// every screen/component measurement referenced by later stories.
//
// Most constants are multiples of `base`, but a few come from UX-DR3
// verbatim and are not (e.g., cardTextGap = 5). Those are kept as-is to
// honour the UX spec; do not "round to the grid" without updating UX-DR3.
//
// Source: ux-design-specification.md lines 565-713 and 1306-1314.
// Touch targets obey WCAG 2.1 AA (min 44 logical px).

class AppSpacing {
  const AppSpacing._();

  /// 8-px base grid (UX-DR3 reference unit).
  static const double base = 8.0;

  // Screen-level padding
  static const double screenHorizontal = 20.0;

  /// Horizontal padding on the scenario list screen (UX-DR3 + Figma spec
  /// `iPhone 16 - 5`: padding `30 18 0 18`). Slightly tighter than
  /// `screenHorizontal` so the 357-px-wide cards breathe inside a 393-px
  /// device.
  static const double screenHorizontalScenarioList = 18.0;

  static const double screenVerticalList = 30.0;
  static const double screenVerticalTopSafe = 60.0;

  // Scenario card internals
  static const double cardGap = 12.0;
  static const double cardInternalPaddingVertical = 10.0;

  /// Vertical / horizontal padding inside a scenario card row (Figma
  /// `iPhone 16 - 5`: padding 5 20). Distinct from [cardTextGap] /
  /// [cardIconGap] which describe inter-child gaps, not the row's own
  /// padding — they happen to share the same numeric values today but
  /// shouldn't be conflated semantically.
  static const double cardPaddingVertical = 5.0;
  static const double cardPaddingHorizontal = 20.0;

  static const double cardTextGap = 5.0;
  static const double cardIconGap = 20.0;

  /// Horizontal gap between the avatar and the text column inside a
  /// ScenarioCard (UX-DR4). Same numeric value as [overlayIconTextGap]
  /// today but kept distinct so a Story 5.3 retune of the bottom-overlay
  /// token cannot silently shift this card's layout.
  static const double cardAvatarTextGap = 10.0;

  /// Horizontal gap between the text column and the action-icons row
  /// inside a ScenarioCard. Same value as [cardAvatarTextGap]; named for
  /// the same reason — keep ScenarioCard's spacing decoupled from the
  /// BottomOverlayCard tokens.
  static const double cardTextActionsGap = 10.0;

  // Component sizes
  static const double avatarSmall = 50.0;
  static const double avatarLarge = 100.0;

  /// Action icons on the scenario card (UX spec line 611).
  static const double iconSmall = 24.0;

  /// Hang-up glyph inside the hang-up button (UX spec line 634).
  ///
  /// Named by context, not by pixel size: this glyph is 28pt, which is
  /// *smaller* than [iconOffline] (40pt). Future icons should follow the
  /// same context-first naming convention.
  static const double iconHangUp = 28.0;

  /// Wifi-barred icon on the no-network screen (UX spec line 643).
  static const double iconOffline = 40.0;

  static const double hangUpButtonSize = 64.0;
  static const double minTouchTarget = 44.0;
  static const double touchTargetComfortable = 48.0;

  // Border radii (circles)
  static const double radiusAvatarSmall = 25.0;
  static const double radiusAvatarLarge = 50.0;

  // Bottom overlay card (scenario list)
  static const double overlayCardPadding = 20.0;
  static const double overlayIconTextGap = 10.0;
  static const double overlayLineGap = 10.0;

  /// Horizontal padding on the empathetic error screen (Story 5.5 Figma
  /// `iPhone 16 - 8`: padding `30 36` outer column, vertical replaced by
  /// SafeArea). Wider than `screenHorizontalScenarioList` (18) to give the
  /// hero title and multi-line body more breathing room — error screens
  /// should read calm, not cramped.
  static const double screenHorizontalErrorView = 36.0;
}
