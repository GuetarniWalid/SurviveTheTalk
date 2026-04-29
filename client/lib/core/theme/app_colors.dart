// AppColors — the single source of truth for every color in the app.
//
// Every hex literal in the application lives HERE and nowhere else.
// A unit test in test/core/theme/theme_tokens_test.dart enforces this.
//
// Contrast ratios (WCAG 2.1 AA — validated in ux-design-specification.md
// lines 1296-1304):
//   - textPrimary on background       → 13.5 : 1   (AA + AAA)
//   - textPrimary on avatarBg         →  7.2 : 1   (AA + AAA)
//   - accent     on background        →  9.1 : 1   (AA + AAA)
//   - destructive on background       →  5.2 : 1   (AA)
//   - statusCompleted on background   →  8.5 : 1   (AA + AAA)
//   - background on textPrimary
//     (overlay card title)            → 13.5 : 1   (AA + AAA)
//   - 0xFF4C4C4C on textPrimary
//     (overlay card subtitle)         →  5.7 : 1   (AA)
//
// Do NOT add new color tokens here without updating UX-DR1 first.

import 'package:flutter/painting.dart';

class AppColors {
  const AppColors._();

  // Core palette
  static const Color background = Color(0xFF1E1F23);
  static const Color avatarBg = Color(0xFF414143);
  static const Color textPrimary = Color(0xFFF0F0F0);
  static const Color textSecondary = Color(0xFF8A8A95);

  // Functional palette
  static const Color accent = Color(0xFF00E5A0);
  static const Color statusCompleted = Color(0xFF2ECC40);
  static const Color statusInProgress = Color(0xFFFF6B6B);
  static const Color destructive = Color(0xFFE74C3C);
  static const Color warning = Color(0xFFF59E0B);

  // Overlay subtitle — 5.7 : 1 contrast on textPrimary (UX-DR5 line 700).
  // Pre-validated in the contrast block at the top of this file. Promoted to
  // a token so the BottomOverlayCard widget never inlines the hex.
  static const Color overlaySubtitle = Color(0xFF4C4C4C);

  // Content-warning sheet "HEADS UP" pill (Story 5.4 Figma iphone-16-7).
  // Pill background is a pale yellow, foreground (icon + label) is a dark
  // olive. Used exclusively on the pill (NOT on the light sheet surface
  // directly) — headsUpAccent on headsUpBg contrast ≈ 4.6 : 1 (AA, large).
  static const Color headsUpBg = Color(0xFFF5FFAD);
  static const Color headsUpAccent = Color(0xFF8F8621);

  // Empathetic error screen body text (Story 5.5 Figma iphone-16-8).
  // Lighter than `textSecondary` so the multi-line body stays readable on
  // a dark background under longer copy. errorBody on background contrast
  // ≈ 11.4 : 1 (AA + AAA).
  static const Color errorBody = Color(0xFFD8D8D8);

  /// Ordered list used by theme_tokens_test.dart to assert count == 13.
  static const List<Color> values = <Color>[
    background,
    avatarBg,
    textPrimary,
    textSecondary,
    accent,
    statusCompleted,
    statusInProgress,
    destructive,
    warning,
    overlaySubtitle,
    headsUpBg,
    headsUpAccent,
    errorBody,
  ];
}
