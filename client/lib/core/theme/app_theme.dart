// AppTheme — ThemeData builder that composes AppColors + AppTypography
// into a Material 3 dark theme.
//
// Wired into MaterialApp.router in lib/app/app.dart. Every screen
// downstream uses either Theme.of(context).textTheme.X or
// AppTypography.Y directly — see the mapping table below.

import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_typography.dart';

class AppTheme {
  const AppTheme._();

  /// MD3 dark theme — the only theme the app ships with.
  ///
  /// TextTheme slot → AppTypography mapping (stable for feature stories):
  ///   displayLarge  → display        (64 Bold — debrief hero)
  ///   displaySmall  → cardTagline    (12 Italic — scenario card tagline)
  ///   titleLarge    → headline       (18 SemiBold — screen titles)
  ///   titleMedium   → sectionTitle   (14 SemiBold — debrief sections)
  ///   bodyLarge     → body           (16 Regular — debrief body)
  ///   bodyMedium    → body           (16 Regular — Material default for Text)
  ///   bodySmall     → caption        (13 Regular — metadata)
  ///   labelLarge    → label          (12 Medium — buttons, tags)
  ///   labelMedium   → cardTitle      (12 Bold — scenario card title)
  ///   labelSmall    → cardStats      (12 Regular — card stats)
  /// bodyEmphasis has no TextTheme slot — access via
  /// AppTypography.bodyEmphasis directly.
  ///
  /// ColorScheme pairings are chosen so every `onX` color meets WCAG AA
  /// (≥ 4.5:1) against its base surface:
  ///   onError on error (destructive #E74C3C) → background #1E1F23 (~5.0:1 AA)
  ///   onSecondary on secondary (textSecondary #8A8A95)
  ///                                         → background #1E1F23 (~4.9:1 AA)
  static ThemeData dark() {
    const ColorScheme scheme = ColorScheme.dark(
      surface: AppColors.background,
      onSurface: AppColors.textPrimary,
      primary: AppColors.accent,
      onPrimary: AppColors.background,
      secondary: AppColors.textSecondary,
      onSecondary: AppColors.background,
      error: AppColors.destructive,
      onError: AppColors.background,
    );

    const TextTheme textTheme = TextTheme(
      displayLarge: AppTypography.display,
      displaySmall: AppTypography.cardTagline,
      titleLarge: AppTypography.headline,
      titleMedium: AppTypography.sectionTitle,
      bodyLarge: AppTypography.body,
      bodyMedium: AppTypography.body,
      bodySmall: AppTypography.caption,
      labelLarge: AppTypography.label,
      labelMedium: AppTypography.cardTitle,
      labelSmall: AppTypography.cardStats,
    );

    return ThemeData(
      brightness: Brightness.dark,
      useMaterial3: true,
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: scheme,
      fontFamily: AppTypography.fontFamily,
      textTheme: textTheme,
    );
  }
}
