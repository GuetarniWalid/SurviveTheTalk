// AppTypography — all 10 text styles defined by UX-DR2.
//
// Hierarchy is established by weight and style, not by size variation
// (ux-design-specification.md line 550). Font family is Inter, bundled
// locally in assets/fonts/inter/ (see pubspec.yaml).
//
// Line-heights intentionally left at Flutter defaults — UX spec does
// not specify custom line-heights; defaults are WCAG 2.1 AA compliant.
//
// Text color is intentionally NOT baked into these styles. Material 3
// pulls foreground colors from `ColorScheme.onX` based on the surface
// a widget sits on (onSurface, onPrimary, onError, …). Baking a color
// here would override those and break accessibility on colored
// surfaces. Widgets that need a specific color should use
// `style.copyWith(color: …)` or rely on their component's default.

import 'package:flutter/painting.dart';

class AppTypography {
  const AppTypography._();

  static const String fontFamily = 'Inter';

  // Scenario card
  static const TextStyle cardTitle = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w700,
  );

  static const TextStyle cardTagline = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w400,
    fontStyle: FontStyle.italic,
  );

  static const TextStyle cardStats = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w400,
  );

  // Debrief hero + screen titles
  static const TextStyle display = TextStyle(
    fontFamily: fontFamily,
    fontSize: 64,
    fontWeight: FontWeight.w700,
  );

  static const TextStyle headline = TextStyle(
    fontFamily: fontFamily,
    fontSize: 18,
    fontWeight: FontWeight.w600,
  );

  static const TextStyle sectionTitle = TextStyle(
    fontFamily: fontFamily,
    fontSize: 14,
    fontWeight: FontWeight.w600,
  );

  // Body
  static const TextStyle body = TextStyle(
    fontFamily: fontFamily,
    fontSize: 16,
    fontWeight: FontWeight.w400,
  );

  static const TextStyle bodyEmphasis = TextStyle(
    fontFamily: fontFamily,
    fontSize: 16,
    fontWeight: FontWeight.w500,
  );

  // Captions + labels
  static const TextStyle caption = TextStyle(
    fontFamily: fontFamily,
    fontSize: 13,
    fontWeight: FontWeight.w400,
  );

  static const TextStyle label = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w500,
  );

  // Call Ended overlay (Story 7.2 — call-ended-screen-design.md). The
  // duration shares the 38px size of the character name (a prominent data
  // point, not secondary info); "Call Ended" stays understated at 20
  // Regular (design P-10 — SemiBold would compete with the 38px elements);
  // the percentage and theatrical phrase form the variant-colored result
  // block, the phrase in italic for its stage-direction quality.
  static const TextStyle callEndedDuration = TextStyle(
    fontFamily: fontFamily,
    fontSize: 38,
    fontWeight: FontWeight.w400,
  );

  static const TextStyle callEndedLabel = TextStyle(
    fontFamily: fontFamily,
    fontSize: 20,
    fontWeight: FontWeight.w400,
  );

  static const TextStyle callEndedPercent = TextStyle(
    fontFamily: fontFamily,
    fontSize: 24,
    fontWeight: FontWeight.w400,
  );

  static const TextStyle callEndedPhrase = TextStyle(
    fontFamily: fontFamily,
    fontSize: 24,
    fontWeight: FontWeight.w400,
    fontStyle: FontStyle.italic,
  );

  // Debrief screen (Story 7.3 — debrief-screen-design.md). The hesitation
  // duration number ("4.2 seconds") is its card's focal point — same 24px
  // as callEndedPercent but Bold, per the design's big-number-then-context
  // reading flow.
  static const TextStyle debriefDuration = TextStyle(
    fontFamily: fontFamily,
    fontSize: 24,
    fontWeight: FontWeight.w700,
  );
}
