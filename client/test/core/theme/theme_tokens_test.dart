import 'dart:io';

import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/app_spacing.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/core/theme/app_typography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('AppColors', () {
    test('exposes exactly 13 tokens with exact UX-DR1 hex values', () {
      expect(AppColors.values, hasLength(13));
      // Direct Color equality avoids the Flutter 3.27+ `toARGB32()` API;
      // compatible with any Flutter SDK that matches pubspec's sdk floor.
      expect(AppColors.background, const Color(0xFF1E1F23));
      expect(AppColors.avatarBg, const Color(0xFF414143));
      expect(AppColors.textPrimary, const Color(0xFFF0F0F0));
      expect(AppColors.textSecondary, const Color(0xFF8A8A95));
      expect(AppColors.accent, const Color(0xFF00E5A0));
      expect(AppColors.statusCompleted, const Color(0xFF2ECC40));
      expect(AppColors.statusInProgress, const Color(0xFFFF6B6B));
      expect(AppColors.destructive, const Color(0xFFE74C3C));
      expect(AppColors.warning, const Color(0xFFF59E0B));
      expect(AppColors.overlaySubtitle, const Color(0xFF4C4C4C));
      expect(AppColors.headsUpBg, const Color(0xFFF5FFAD));
      expect(AppColors.headsUpAccent, const Color(0xFF8F8621));
      expect(AppColors.errorBody, const Color(0xFFD8D8D8));
    });

    test('all 13 tokens are distinct (no accidental duplicates)', () {
      expect(AppColors.values.toSet(), hasLength(AppColors.values.length));
    });
  });

  group('AppTypography', () {
    void expectStyle(
      TextStyle s, {
      required double size,
      required FontWeight weight,
      FontStyle style = FontStyle.normal,
    }) {
      expect(s.fontFamily, 'Inter');
      expect(s.fontSize, size);
      expect(s.fontWeight, weight);
      // fontStyle is null when not explicitly set; Flutter renders it as
      // FontStyle.normal. Normalize for comparison.
      expect(s.fontStyle ?? FontStyle.normal, style);
      // Colors are intentionally NOT baked into TextStyle — Material 3
      // applies ColorScheme.onX based on the surface each widget sits on.
      expect(s.color, isNull);
    }

    test('exposes all 10 UX-DR2 styles with exact size/weight/style', () {
      expectStyle(AppTypography.cardTitle, size: 12, weight: FontWeight.w700);
      expectStyle(
        AppTypography.cardTagline,
        size: 12,
        weight: FontWeight.w400,
        style: FontStyle.italic,
      );
      expectStyle(AppTypography.cardStats, size: 12, weight: FontWeight.w400);
      expectStyle(AppTypography.display, size: 64, weight: FontWeight.w700);
      expectStyle(AppTypography.headline, size: 18, weight: FontWeight.w600);
      expectStyle(
        AppTypography.sectionTitle,
        size: 14,
        weight: FontWeight.w600,
      );
      expectStyle(AppTypography.body, size: 16, weight: FontWeight.w400);
      expectStyle(
        AppTypography.bodyEmphasis,
        size: 16,
        weight: FontWeight.w500,
      );
      expectStyle(AppTypography.caption, size: 13, weight: FontWeight.w400);
      expectStyle(AppTypography.label, size: 12, weight: FontWeight.w500);
    });
  });

  group('AppSpacing', () {
    test('8-px base + screen padding constants match UX-DR3', () {
      expect(AppSpacing.base, 8.0);
      expect(AppSpacing.screenHorizontal, 20.0);
      expect(AppSpacing.screenHorizontalScenarioList, 18.0);
      expect(AppSpacing.screenVerticalList, 30.0);
      expect(AppSpacing.screenVerticalTopSafe, 60.0);
      expect(AppSpacing.minTouchTarget, 44.0);
      expect(AppSpacing.hangUpButtonSize, 64.0);
      // Scenario card row padding (distinct from inter-child gaps below).
      expect(AppSpacing.cardPaddingVertical, 5.0);
      expect(AppSpacing.cardPaddingHorizontal, 20.0);
      // Context-named icon sizes (see AppSpacing doc comments for why
      // iconHangUp is smaller than iconOffline).
      expect(AppSpacing.iconHangUp, 28.0);
      expect(AppSpacing.iconOffline, 40.0);
      // Error screen horizontal padding (Story 5.5 Figma iphone-16-8).
      expect(AppSpacing.screenHorizontalErrorView, 36.0);
    });
  });

  group('AppTheme.dark() wiring', () {
    test('ColorScheme pulls from AppColors', () {
      final ThemeData t = AppTheme.dark();
      expect(t.brightness, Brightness.dark);
      expect(t.useMaterial3, isTrue);
      expect(t.scaffoldBackgroundColor, AppColors.background);
      expect(t.colorScheme.surface, AppColors.background);
      expect(t.colorScheme.onSurface, AppColors.textPrimary);
      expect(t.colorScheme.primary, AppColors.accent);
      expect(t.colorScheme.onPrimary, AppColors.background);
      expect(t.colorScheme.secondary, AppColors.textSecondary);
      expect(t.colorScheme.onSecondary, AppColors.background);
      expect(t.colorScheme.error, AppColors.destructive);
      expect(t.colorScheme.onError, AppColors.background);
      // ThemeData.fontFamily has no getter in Flutter 3.27+ — verify the
      // family propagated by sampling any TextTheme entry (all AppTypography
      // styles already have fontFamily: 'Inter').
      expect(t.textTheme.bodyLarge?.fontFamily, AppTypography.fontFamily);
    });

    test('TextTheme maps to AppTypography slots', () {
      // ThemeData merges Flutter's default TextTheme (whiteMountainView)
      // with the slots we pass — the resulting TextStyle objects are NOT
      // reference-equal to our AppTypography constants (they carry inherited
      // color + decoration from the ColorScheme). Assert the identifying
      // properties instead: fontFamily + fontSize + fontWeight + fontStyle.
      final TextTheme tt = AppTheme.dark().textTheme;
      void expectSlot(TextStyle? slot, TextStyle reference) {
        expect(slot, isNotNull);
        expect(slot!.fontFamily, reference.fontFamily);
        expect(slot.fontSize, reference.fontSize);
        expect(slot.fontWeight, reference.fontWeight);
        expect(slot.fontStyle ?? FontStyle.normal,
            reference.fontStyle ?? FontStyle.normal);
      }

      expectSlot(tt.displayLarge, AppTypography.display);
      expectSlot(tt.displaySmall, AppTypography.cardTagline);
      expectSlot(tt.titleLarge, AppTypography.headline);
      expectSlot(tt.titleMedium, AppTypography.sectionTitle);
      expectSlot(tt.bodyLarge, AppTypography.body);
      // Critical assertion for BS-1: bodyMedium (Material's default for
      // bare Text) must be Regular (w400), NOT bodyEmphasis (w500).
      expectSlot(tt.bodyMedium, AppTypography.body);
      expectSlot(tt.bodySmall, AppTypography.caption);
      expectSlot(tt.labelLarge, AppTypography.label);
      expectSlot(tt.labelMedium, AppTypography.cardTitle);
      expectSlot(tt.labelSmall, AppTypography.cardStats);
      // bodyEmphasis is intentionally not mapped — access via
      // AppTypography.bodyEmphasis directly.
    });
  });

  group('No hex color literals outside lib/core/theme/', () {
    /// Resolve `lib/` reliably whether the test runs from `client/`
    /// (default for `flutter test`) or from the repo root.
    Directory resolveLibDir() {
      final Directory cwdLib = Directory('lib');
      if (cwdLib.existsSync()) return cwdLib;
      final Directory clientLib = Directory('client/lib');
      if (clientLib.existsSync()) return clientLib;
      throw StateError(
        'Cannot locate lib/ directory. Run tests from client/ or repo root.',
      );
    }

    /// Strip line and block comments so hex literals inside `///` or `//`
    /// documentation do not trigger false positives.
    String stripComments(String src) {
      return src
          .replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '')
          .replaceAll(RegExp(r'//[^\n]*'), '');
    }

    bool isGeneratedFile(String normalizedPath) {
      return normalizedPath.endsWith('.g.dart') ||
          normalizedPath.endsWith('.freezed.dart') ||
          normalizedPath.endsWith('.mocks.dart');
    }

    test(
      'any 0xRRGGBB / 0xAARRGGBB literal appears ONLY in lib/core/theme',
      () {
        // Match any 6- or 8-digit hex literal. This is deliberately
        // broader than `Color(0x…)` so it also catches
        // `Color.fromRGBO`, `Color.from`, and bare int constants later
        // fed into a Color constructor.
        final RegExp hexLiteral = RegExp(r'0x[0-9A-Fa-f]{6,8}\b');

        final Directory libDir = resolveLibDir();
        final List<String> offenders = <String>[];
        for (final FileSystemEntity entity in libDir.listSync(
          recursive: true,
        )) {
          if (entity is! File || !entity.path.endsWith('.dart')) continue;
          final String normalized = entity.path.replaceAll(r'\', '/');
          if (isGeneratedFile(normalized)) continue;
          if (normalized.contains('/core/theme/')) continue;

          final String content = stripComments(entity.readAsStringSync());
          if (hexLiteral.hasMatch(content)) {
            offenders.add(entity.path);
          }
        }
        expect(
          offenders,
          isEmpty,
          reason:
              'Hex color literals are only allowed in lib/core/theme/. '
              'Move these to AppColors: ${offenders.join(', ')}',
        );
      },
    );
  });
}
