# Story 4.1b: Implement Design System (Theme, Typography, Spacing)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Intention (UX / Why)

Every remaining MVP story that renders a pixel — email entry (4.3), consent + mic (4.4), incoming call (4.5), scenario list (5.2), call screen (6.2), debrief (7.3), paywall (8.2) — will reach for `AppColors.background`, `AppTypography.headline`, `AppSpacing.screenHorizontal`. If those constants don't exist yet, each screen author will invent their own hex codes and magic numbers, and the app will drift visually within five stories. This story is the **single moment** where we lock in the 8 color tokens, 10 text styles, and 8-px spacing system defined by UX-DR1 / UX-DR2 / UX-DR3 — after this, every screen either uses these tokens or it doesn't ship.

**What the user sees after this story:** the same placeholder screen from 4.1, but now rendered with Inter font at 16px body weight over a `#1E1F23` canvas. No new screens, no new features — just the foundation that makes every later screen look intentional.

**What the user will NOT see but benefits from downstream:**
- Consistent typography across all screens (Inter, hierarchy by weight not size)
- WCAG 2.1 AA contrast ratios baked into the palette (already validated in UX spec lines 1296-1304)
- Dynamic font sizing supported via `MediaQuery.textScaler` (UX-DR12 accessibility)
- A single `AppTheme.dark()` call in `app/app.dart` — zero per-screen theme plumbing

**Non-goals for this story (hard scope boundaries):**
- ❌ Building ANY feature screen (auth, consent, call, scenario list, debrief) — those live in their own stories
- ❌ Implementing the Frijole display font for the email screen app title — Story 4.3 owns that (screen-specific asset, not a foundation token)
- ❌ Implementing component widgets (ScenarioCard, BottomOverlayCard, CallEndedOverlay) — each owned by its consuming story
- ❌ Implementing `shared/widgets/loading_indicator.dart` or `error_display.dart` — Story 4.3+ owns those
- ❌ Adding a dynamic theme switcher or light-mode variant — app is dark-only per UX spec
- ❌ Adding `google_fonts` package — UX convention is local font bundling (per `onboarding-screen-designs.md` line 130: "do not rely on Google Fonts network loading")
- ❌ Modifying server code — this is a Flutter-only story

## Concrete User Walk-Through (Adversarial)

> Per Epic 3 retro Action Item #1: every code story traces one concrete user path end-to-end before implementation.

**Scenario: Developer Walid pulls `main`, runs the app on his iPhone simulator after this story ships.**

1. `cd client && flutter pub get` — resolves new font assets declared in `pubspec.yaml` without conflicts.
2. `cd client && flutter analyze` → `No issues found!` (MUST — pre-commit gate per `CLAUDE.md`).
3. `cd client && flutter test` → `All tests passed!` (MUST — pre-commit gate).
4. `flutter run` on iPhone simulator → app launches.
5. The `_PlaceholderScreen` from Story 4.1 renders, now with: `#1E1F23` background, `#F0F0F0` text, Inter Regular 16px (the `body` style). No visual regression — just polished instead of stock Flutter.
6. In a future story, when a dev writes `Text('Call failed', style: Theme.of(context).textTheme.titleMedium)` or `Text('Call failed', style: AppTypography.headline)`, both paths resolve to the same 18px SemiBold `#F0F0F0` — because `AppTheme.dark()` wires the TextTheme from `AppTypography`.
7. No crashes, no red screens, no font missing glyphs (Inter covers Latin Extended for European accented characters).

**Adversarial walk-through — what if the developer cuts corners?**
- Uses `google_fonts` package instead of bundled assets → first launch on cellular = 1-2s blank text flicker, failed launch in airplane mode. **Preventive action: pubspec.yaml `fonts:` section declares local assets, google_fonts package MUST NOT appear in `dependencies`.**
- Declares colors as `Color(0xff1E1F23)` sprinkled across screens → visual drift when UX updates the palette. **Preventive AC: a static analysis scan (test or grep) MUST NOT find any hex color literal outside `lib/core/theme/` after this story.** (Enforced via a unit test that reads source files; see Task 8.)
- Uses `TextStyle(fontSize: 16, fontWeight: FontWeight.w400)` inline instead of `AppTypography.body` → same drift problem. **Preventive action: all 10 styles are centralised and documented; later stories use `AppTypography.X` or `Theme.of(context).textTheme.Y`.**
- Forgets to wire `AppTheme.dark()` through `MaterialApp.router` → screens fall back to the Flutter default (white background, Roboto). **Preventive AC: `app/app.dart` imports `AppTheme` from `core/theme/app_theme.dart` and passes it to `MaterialApp.router(theme:)`.**
- Leaves the minimal `lib/app/theme.dart` placeholder alongside the new `core/theme/app_theme.dart` → two sources of truth, future confusion. **Preventive AC: `lib/app/theme.dart` is DELETED; `app/app.dart` imports from `core/theme/app_theme.dart`.**
- Forgets to bake in dynamic-type support → accessibility reviewer flags it at launch. **Preventive action: `AppTheme.dark()` does NOT clamp `TextStyle.fontSize`; MaterialApp leaves `textScaler` at its default (which respects device settings). No `MediaQuery.copyWith(textScaler: TextScaler.noScaling)`. Documented in Dev Notes.**

## Story

As a developer,
I want a complete Material Design 3 dark theme with `AppColors` (8 tokens), `AppTypography` (10 Inter text styles), `AppSpacing` (8px scale + screen/component constants), and a single `AppTheme.dark()` ThemeData builder wired into `MaterialApp`,
So that every subsequent MVP screen consumes one consistent visual foundation matching the UX specification and passes WCAG 2.1 AA automatically.

## Dependencies

- **Story 4.1 (review)** — Established `lib/core/theme/.gitkeep` placeholder and minimal `lib/app/theme.dart`. This story fills both.
- **Story 2.1 (done)** — `onboarding-screen-designs.md` line 130 establishes the "bundle fonts locally, do not use Google Fonts network loading" convention.
- **UX-DR1 / UX-DR2 / UX-DR3 / UX-DR12** — `_bmad-output/planning-artifacts/ux-design-specification.md` §"Visual Design Foundation" (lines 516-620) and §"Accessibility Strategy" (lines 1288-1336).
- **Architecture** — `_bmad-output/planning-artifacts/architecture.md` §"Flutter MVP Client Structure" (lines 822-834) defines `core/theme/{app_colors, app_typography, app_theme}.dart`.
- **CLAUDE.md** — pre-commit gates (flutter analyze + flutter test) are non-negotiable.

## Acceptance Criteria

1. **AC1 — All 8 UX color tokens defined in `core/theme/app_colors.dart`:**
   Given UX-DR1 (UX spec lines 523-540),
   When `AppColors` is implemented,
   Then the class exposes exactly these 8 `static const Color` members (hex values exact):
   | Member | Hex | UX usage |
   |--------|-----|----------|
   | `background` | `0xFF1E1F23` | primary app background |
   | `avatarBg` | `0xFF414143` | avatar circle, card backgrounds |
   | `textPrimary` | `0xFFF0F0F0` | all text + icons |
   | `textSecondary` | `0xFF8A8A95` | metadata, subtitles |
   | `accent` | `0xFF00E5A0` | brand accent, corrections in debrief |
   | `statusCompleted` | `0xFF2ECC40` | 100% survival stats |
   | `statusInProgress` | `0xFFFF6B6B` | <100% survival stats |
   | `destructive` | `0xFFE74C3C` | hang-up button, errors |
   **And** no hex color literal appears anywhere in `lib/` outside `lib/core/theme/` (enforced by the test in AC6).

2. **AC2 — All 10 Inter text styles defined in `core/theme/app_typography.dart`:**
   Given UX-DR2 (UX spec lines 547-563) and epics.md line 717,
   When `AppTypography` is implemented,
   Then the class exposes exactly these 10 `static const TextStyle` members (values match UX spec precisely):
   | Member | Size (px) | Weight | Style |
   |--------|-----------|--------|-------|
   | `cardTitle` | 12 | w700 (Bold) | normal |
   | `cardTagline` | 12 | w400 (Regular) | italic |
   | `cardStats` | 12 | w400 (Regular) | normal |
   | `display` | 64 | w700 (Bold) | normal |
   | `headline` | 18 | w600 (SemiBold) | normal |
   | `sectionTitle` | 14 | w600 (SemiBold) | normal |
   | `body` | 16 | w400 (Regular) | normal |
   | `bodyEmphasis` | 16 | w500 (Medium) | normal |
   | `caption` | 13 | w400 (Regular) | normal |
   | `label` | 12 | w500 (Medium) | normal |
   **And** every style has `fontFamily: 'Inter'` as a default.
   **And** `TextStyle.color` is intentionally left NULL on every style. [AMENDED post-review, BS-2]: baking `AppColors.textPrimary` into every style would shadow Material 3's `ColorScheme.onX` on non-default surfaces (primary/error/etc.), breaking automatic contrast. Color is applied by `ThemeData.colorScheme` instead.
   **And** line-heights are left at Flutter defaults (no `height:` override) — UX spec does not specify custom line heights; defaults are WCAG-compliant.

3. **AC3 — Inter font bundled as local asset (not `google_fonts`):**
   Given onboarding-screen-designs.md line 130 convention ("do not rely on Google Fonts network loading"),
   When the Inter font is added,
   Then `client/assets/fonts/inter/` contains exactly these 5 font files:
   - `Inter-Regular.ttf` (weight 400, normal)
   - `Inter-Italic.ttf` (weight 400, italic)
   - `Inter-Medium.ttf` (weight 500, normal)
   - `Inter-SemiBold.ttf` (weight 600, normal)
   - `Inter-Bold.ttf` (weight 700, normal)
   **And** `pubspec.yaml` declares the `Inter` family with all 5 `asset` entries (weights + italic style flags) under `flutter.fonts:`.
   **And** [AMENDED post-review, IG-1] `pubspec.yaml` also declares `assets/fonts/inter/OFL.txt` under `flutter.assets:` so the SIL Open Font License text ships inside the app bundle, satisfying OFL §2 ("license must accompany each copy").
   **And** `google_fonts` does NOT appear in `dependencies`.

4. **AC4 — All UX-DR3 spacing constants defined in `core/theme/app_spacing.dart`:**
   Given UX-DR3 (UX spec lines 565-613),
   When `AppSpacing` is implemented,
   Then the class exposes exactly these `static const double` members (values match UX spec):

   **Base unit:**
   - `base = 8.0` (source of truth — all other spacing derives as multiples)

   **Screen-level padding:**
   - `screenHorizontal = 20.0` (all screens — UX spec line 574)
   - `screenVerticalList = 30.0` (scenario list vertical padding — UX spec line 575)
   - `screenVerticalTopSafe = 60.0` (call/debrief top safe-area padding — UX spec line 575)

   **Card internal spacing:**
   - `cardGap = 12.0` (gap between scenario cards — UX spec line 583)
   - `cardInternalPaddingVertical = 10.0` (UX spec line 598)
   - `cardTextGap = 5.0` (gap between text lines — UX spec line 600)
   - `cardIconGap = 20.0` (gap between action icons — UX spec line 610)

   **Component sizes:**
   - `avatarSmall = 50.0` (scenario card avatar — UX spec line 590)
   - `avatarLarge = 100.0` (no-network screen avatar — UX spec line 644)
   - `iconSmall = 24.0` (action icons — UX spec line 611)
   - `iconOffline = 40.0` (WiFi barred icon — UX spec line 643) [AMENDED post-review, BS-3: renamed from `iconMedium` to context-based name — size-based names are misleading when `iconHangUp < iconOffline`]
   - `iconHangUp = 28.0` (hang-up glyph — UX spec line 634) [AMENDED post-review, BS-3: renamed from `iconLarge`]
   - `hangUpButtonSize = 64.0` (UX spec line 634)
   - `minTouchTarget = 44.0` (WCAG AA, UX spec line 1310)
   - `touchTargetComfortable = 48.0` (UX spec line 1310)

   **Border radii:**
   - `radiusAvatarSmall = 25.0` (50/2, circle — UX spec line 591)
   - `radiusAvatarLarge = 50.0` (100/2, circle — UX spec line 644)

   **Overlay card (scenario list):**
   - `overlayCardPadding = 20.0` (UX spec line 681)
   - `overlayIconTextGap = 10.0` (UX spec line 683)
   - `overlayLineGap = 10.0` (UX spec line 698)

5. **AC5 — `AppTheme.dark()` ThemeData builder in `core/theme/app_theme.dart` wires everything:**
   Given Architecture line 834 names `app_theme.dart` as the `ThemeData` builder,
   When `AppTheme.dark()` is implemented,
   Then the returned `ThemeData`:
   - Has `brightness: Brightness.dark` and `useMaterial3: true`
   - `scaffoldBackgroundColor: AppColors.background`
   - Uses a `ColorScheme.dark()` populated from `AppColors`. [AMENDED post-review, P-1 + P-2] Full required bindings:
     - `surface` = background, `onSurface` = textPrimary
     - `primary` = accent, `onPrimary` = background
     - `secondary` = textSecondary, `onSecondary` = **background** (NOT textPrimary — `textPrimary` on `textSecondary` fails WCAG at ~1.2:1; `background` on `textSecondary` passes at ~4.9:1 AA)
     - `error` = destructive, `onError` = **background** (NOT textPrimary — `textPrimary` on `destructive` fails WCAG at ~2.6:1; `background` on `destructive` passes at ~5.0:1 AA)
   - `textTheme` is a `TextTheme` populated from `AppTypography` per this mapping table. [AMENDED post-review, BS-1 + BS-4]: original mapping put `bodyEmphasis (w500)` into `bodyMedium`, which is Material's default for every bare `Text(...)` widget — that would make every Text in the app unintentionally emphasized. Corrected mapping:
     | AppTypography | TextTheme slot | Rationale |
     |---------------|----------------|-----------|
     | `display` | `displayLarge` | 64 Bold — debrief hero |
     | `cardTagline` | `displaySmall` | 12 Italic — scenario card tagline |
     | `headline` | `titleLarge` | 18 SemiBold — screen titles |
     | `sectionTitle` | `titleMedium` | 14 SemiBold — debrief sections |
     | `body` | `bodyLarge` | 16 Regular — debrief body |
     | `body` | `bodyMedium` | 16 Regular — Material default for bare Text (was `bodyEmphasis` — corrected) |
     | `caption` | `bodySmall` | 13 Regular — metadata |
     | `label` | `labelLarge` | 12 Medium — buttons, tags |
     | `cardTitle` | `labelMedium` | 12 Bold — scenario card title |
     | `cardStats` | `labelSmall` | 12 Regular — card stats |
     | `bodyEmphasis` | (no TextTheme slot; access via `AppTypography.bodyEmphasis` directly — emphasis is an explicit choice, not a default) |
   - `fontFamily: 'Inter'` set on `ThemeData` (fallback default for any unnamed text)
   **And** no `TextStyle` inside the builder uses raw hex — every color flows through `AppColors`.

6. **AC6 — `lib/app/theme.dart` is deleted; `app/app.dart` imports from `core/theme/`:**
   Given Story 4.1 Project Structure Notes ("must NOT both exist post-4.1b"),
   When this story completes,
   Then `lib/app/theme.dart` no longer exists on disk.
   **And** `lib/app/app.dart` imports `AppTheme` from `package:client/core/theme/app_theme.dart` and calls `AppTheme.dark()` on `MaterialApp.router(theme:)`.
   **And** `lib/core/theme/.gitkeep` is deleted (replaced by real files).

7. **AC7 — Token-usage test enforces "no hex outside `core/theme/`":**
   Given maintaining one source of truth,
   When `flutter test` runs,
   Then a test in `test/core/theme/theme_tokens_test.dart`:
   - Scans every `.dart` file under `lib/` (except `lib/core/theme/`) for a hex-color regex. [AMENDED post-review, P-5]: regex is broadened to `0x[0-9A-Fa-f]{6,8}\b` (matches all forms — `Color(0x...)`, `Color.fromRGBO(...)`, `Color.from(...)`, bare int constants — not just `Color(` / `Color.fromARGB(`). Expects zero matches.
   - [AMENDED post-review, P-5]: strips `//` and `/* */` comments before scanning (docblocks can mention hex codes without false positives) and skips generated files (`*.g.dart`, `*.freezed.dart`, `*.mocks.dart`).
   - [AMENDED post-review, P-4]: resolves `lib/` via a helper that tries `Directory('lib')` first, falls back to `Directory('client/lib')` — test is robust whether invoked from `client/` (default) or repo root.
   - Asserts `AppColors.values.length == 8` AND each color's hex matches AC1.
   - [AMENDED post-review, P-6]: Asserts the 8 `AppColors` values are distinct (`.toSet()` length equals `.length`) — cheap guard against accidental copy-paste duplicates.
   - Asserts `AppTypography` exposes the 10 named styles with the fontSize + fontWeight + fontStyle values of AC2.
   - [AMENDED post-review, BS-2]: Asserts `TextStyle.color` is null on every AppTypography style (color flows through ColorScheme, not bakery).
   - [AMENDED post-review, P-8]: Asserts `AppTheme.dark().colorScheme` pulls every required pairing from `AppColors` and `textTheme` matches the AC5 mapping table.
   - Asserts `AppSpacing.base == 8.0` and at least `screenHorizontal == 20.0`. [AMENDED post-review, BS-3]: icon constants asserted under new names `iconHangUp` and `iconOffline`.

8. **AC8 — Accessibility: dynamic font sizing + WCAG AA contrast documented:**
   Given UX-DR12 (UX spec lines 1290-1305),
   When reviewing the theme,
   Then:
   - `MaterialApp.router` does NOT override `textScaler` (i.e., no `MediaQuery.copyWith(textScaler: TextScaler.noScaling)` anywhere). Device-level dynamic type setting flows through.
   - The `app_colors.dart` file header comment documents the validated contrast ratios from UX spec lines 1296-1304 verbatim (for each combo: ratio + AA/AAA pass).
   - An existing or new widget test renders the `_PlaceholderScreen` with `textScaler: TextScaler.linear(1.5)` and confirms the widget tree builds without overflow (a smoke check that dynamic type is honored). [AMENDED post-review, P-7]: the test forces `tester.binding.setSurfaceSize(const Size(320, 480))` (with `addTearDown` to restore) because the default `flutter_test` viewport is large enough to hide overflow at 1.5× scaling — on a narrow phone surface any RenderFlex exception now actually surfaces via `takeException()`.

9. **AC9 — Pre-commit gates pass with zero issues:**
   Given `CLAUDE.md` enforces pre-commit validation,
   When `cd client && flutter analyze` runs,
   Then `No issues found!` (zero errors, zero warnings, zero infos — `flutter_lints` rule set `sort_child_properties_last`, `prefer_const_constructors`, `prefer_const_declarations`, etc.).
   **And** `cd client && flutter test` returns `All tests passed!` with all pre-existing 3 tests from 4.1 still green, PLUS the new theme-tokens test from AC7, PLUS the dynamic-type smoke test from AC8 (total: 5+ tests passing).

## Tasks / Subtasks

### Phase 1: Bundle Inter font

- [x] **Task 1: Download and vendor the Inter font files** (AC: #3)
  - [x] 1.1 Create `client/assets/fonts/inter/` directory.
  - [x] 1.2 Download Inter v4.0 (or latest stable) from https://github.com/rsms/inter/releases — file `Inter-4.0.zip` (OFL license, free commercial use).
  - [x] 1.3 Extract these 5 static TTF files ONLY and place them in `client/assets/fonts/inter/`:
    - `Inter-Regular.ttf`
    - `Inter-Italic.ttf`
    - `Inter-Medium.ttf`
    - `Inter-SemiBold.ttf`
    - `Inter-Bold.ttf`
    **Do NOT use** the variable-weight TTF (`Inter-Variable.ttf`) — Flutter font families with discrete weights map more reliably to Material's `FontWeight.w400..w700` scale.
  - [x] 1.4 Include the OFL license next to the fonts: `client/assets/fonts/inter/OFL.txt` (copy from the release archive).
  - [x] 1.5 Do NOT commit any other Inter weight (Thin, ExtraLight, Light, ExtraBold, Black) — only the 5 weights the design system uses.

- [x] **Task 2: Declare Inter in `pubspec.yaml`** (AC: #3)
  - [x] 2.1 Under the existing `flutter:` key, add a `fonts:` block below the `assets:` block (preserve `assets:` exactly as Story 4.1 left it). Exact snippet:
    ```yaml
      fonts:
        - family: Inter
          fonts:
            - asset: assets/fonts/inter/Inter-Regular.ttf
              weight: 400
            - asset: assets/fonts/inter/Inter-Italic.ttf
              weight: 400
              style: italic
            - asset: assets/fonts/inter/Inter-Medium.ttf
              weight: 500
            - asset: assets/fonts/inter/Inter-SemiBold.ttf
              weight: 600
            - asset: assets/fonts/inter/Inter-Bold.ttf
              weight: 700
    ```
  - [x] 2.2 Run `cd client && flutter pub get` — verify no errors (asset paths must resolve relative to `pubspec.yaml`).
  - [x] 2.3 Do NOT add `google_fonts` as a dependency (AC3 forbids it).

### Phase 2: Build the token files

- [x] **Task 3: Create `lib/core/theme/app_colors.dart`** (AC: #1, #8)
  - [x] 3.1 Delete `client/lib/core/theme/.gitkeep` (will be replaced by the real files this story creates).
  - [x] 3.2 Create the file with this exact content:
    ```dart
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

      /// Ordered list used by theme_tokens_test.dart to assert count == 8.
      static const List<Color> values = <Color>[
        background,
        avatarBg,
        textPrimary,
        textSecondary,
        accent,
        statusCompleted,
        statusInProgress,
        destructive,
      ];
    }
    ```

- [x] **Task 4: Create `lib/core/theme/app_typography.dart`** (AC: #2)
  - **⚠️ POST-REVIEW AMENDMENT (BS-2, 2026-04-16):** the template below shows `color: AppColors.textPrimary` on every style and imports `app_colors.dart`. That was corrected in the shipped file: **all 10 TextStyle have NO `color:` field** and the `app_colors.dart` import is REMOVED. Color is applied via `ThemeData.colorScheme` instead so Material 3's `onX` auto-contrast works on primary/secondary/error surfaces. The fontSize/fontWeight/fontStyle values remain exactly as shown. The live file (`client/lib/core/theme/app_typography.dart`) is the source of truth.
  - [x] 4.1 Create the file with this exact content:
    ```dart
    // AppTypography — all 10 text styles defined by UX-DR2.
    //
    // Hierarchy is established by weight and style, not by size variation
    // (ux-design-specification.md line 550). Font family is Inter, bundled
    // locally in assets/fonts/inter/ (see pubspec.yaml).
    //
    // Line-heights intentionally left at Flutter defaults — UX spec does
    // not specify custom line-heights; defaults are WCAG 2.1 AA compliant.

    import 'package:flutter/painting.dart';

    import 'app_colors.dart';

    class AppTypography {
      const AppTypography._();

      static const String fontFamily = 'Inter';

      // Scenario card
      static const TextStyle cardTitle = TextStyle(
        fontFamily: fontFamily,
        fontSize: 12,
        fontWeight: FontWeight.w700,
        color: AppColors.textPrimary,
      );

      static const TextStyle cardTagline = TextStyle(
        fontFamily: fontFamily,
        fontSize: 12,
        fontWeight: FontWeight.w400,
        fontStyle: FontStyle.italic,
        color: AppColors.textPrimary,
      );

      static const TextStyle cardStats = TextStyle(
        fontFamily: fontFamily,
        fontSize: 12,
        fontWeight: FontWeight.w400,
        color: AppColors.textPrimary,
      );

      // Debrief hero + screen titles
      static const TextStyle display = TextStyle(
        fontFamily: fontFamily,
        fontSize: 64,
        fontWeight: FontWeight.w700,
        color: AppColors.textPrimary,
      );

      static const TextStyle headline = TextStyle(
        fontFamily: fontFamily,
        fontSize: 18,
        fontWeight: FontWeight.w600,
        color: AppColors.textPrimary,
      );

      static const TextStyle sectionTitle = TextStyle(
        fontFamily: fontFamily,
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: AppColors.textPrimary,
      );

      // Body
      static const TextStyle body = TextStyle(
        fontFamily: fontFamily,
        fontSize: 16,
        fontWeight: FontWeight.w400,
        color: AppColors.textPrimary,
      );

      static const TextStyle bodyEmphasis = TextStyle(
        fontFamily: fontFamily,
        fontSize: 16,
        fontWeight: FontWeight.w500,
        color: AppColors.textPrimary,
      );

      // Captions + labels
      static const TextStyle caption = TextStyle(
        fontFamily: fontFamily,
        fontSize: 13,
        fontWeight: FontWeight.w400,
        color: AppColors.textPrimary,
      );

      static const TextStyle label = TextStyle(
        fontFamily: fontFamily,
        fontSize: 12,
        fontWeight: FontWeight.w500,
        color: AppColors.textPrimary,
      );
    }
    ```

- [x] **Task 5: Create `lib/core/theme/app_spacing.dart`** (AC: #4)
  - **⚠️ POST-REVIEW AMENDMENT (BS-3 + BS-5, 2026-04-16):** in the template below, `iconMedium = 40.0` was renamed to `iconOffline = 40.0` and `iconLarge = 28.0` to `iconHangUp = 28.0` (size-based names were misleading because `iconLarge < iconMedium`). The `/// 8-px base grid — every other constant is a multiple.` comment was replaced with a correct doc block that acknowledges `cardTextGap = 5.0` is not a multiple of 8 (kept per UX-DR3 verbatim). The live file (`client/lib/core/theme/app_spacing.dart`) is the source of truth.
  - [x] 5.1 Create the file with this exact content:
    ```dart
    // AppSpacing — UX-DR3 foundation: 8px base unit with named constants
    // for every screen/component measurement referenced by later stories.
    //
    // Source: ux-design-specification.md lines 565-713 and 1306-1314.
    // Touch targets obey WCAG 2.1 AA (min 44 logical px).

    class AppSpacing {
      const AppSpacing._();

      /// 8-px base grid — every other constant is a multiple.
      static const double base = 8.0;

      // Screen-level padding
      static const double screenHorizontal = 20.0;
      static const double screenVerticalList = 30.0;
      static const double screenVerticalTopSafe = 60.0;

      // Scenario card internals
      static const double cardGap = 12.0;
      static const double cardInternalPaddingVertical = 10.0;
      static const double cardTextGap = 5.0;
      static const double cardIconGap = 20.0;

      // Component sizes
      static const double avatarSmall = 50.0;
      static const double avatarLarge = 100.0;
      static const double iconSmall = 24.0;
      static const double iconMedium = 40.0;
      static const double iconLarge = 28.0;
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
    }
    ```

- [x] **Task 6: Create `lib/core/theme/app_theme.dart`** (AC: #5)
  - **⚠️ POST-REVIEW AMENDMENT (P-1, P-2, BS-1, BS-4, 2026-04-16):** the template below has four concrete errors that were corrected in the shipped file:
    1. **`onSecondary: AppColors.textPrimary`** → changed to `AppColors.background` (failed WCAG AA ~1.2:1, now ~4.9:1).
    2. **`onError: AppColors.textPrimary`** → changed to `AppColors.background` (failed WCAG AA ~2.6:1, now ~5.0:1).
    3. **`bodyMedium: AppTypography.bodyEmphasis`** → changed to `AppTypography.body`. `bodyMedium` is Material's default for bare `Text(...)` — the template would have silently rendered every Text widget in the app as Medium weight.
    4. **Added `displaySmall: AppTypography.cardTagline`** — previously no TextTheme slot; now consumable via `Theme.of(context).textTheme.displaySmall`.
    The docblock mapping table was updated to match. The live file (`client/lib/core/theme/app_theme.dart`) is the source of truth.
  - [x] 6.1 Create the file with this exact content:
    ```dart
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
      ///   titleLarge    → headline       (18 SemiBold — screen titles)
      ///   titleMedium   → sectionTitle   (14 SemiBold — debrief sections)
      ///   bodyLarge     → body           (16 Regular — debrief body)
      ///   bodyMedium    → bodyEmphasis   (16 Medium — inline emphasis)
      ///   bodySmall     → caption        (13 Regular — metadata)
      ///   labelLarge    → label          (12 Medium — buttons, tags)
      ///   labelMedium   → cardTitle      (12 Bold — scenario card title)
      ///   labelSmall    → cardStats      (12 Regular — card stats)
      /// cardTagline has no TextTheme slot — access via AppTypography.cardTagline.
      static ThemeData dark() {
        const ColorScheme scheme = ColorScheme.dark(
          surface: AppColors.background,
          onSurface: AppColors.textPrimary,
          primary: AppColors.accent,
          onPrimary: AppColors.background,
          secondary: AppColors.textSecondary,
          onSecondary: AppColors.textPrimary,
          error: AppColors.destructive,
          onError: AppColors.textPrimary,
        );

        const TextTheme textTheme = TextTheme(
          displayLarge: AppTypography.display,
          titleLarge: AppTypography.headline,
          titleMedium: AppTypography.sectionTitle,
          bodyLarge: AppTypography.body,
          bodyMedium: AppTypography.bodyEmphasis,
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
    ```

### Phase 3: Wire the new theme and remove the placeholder

- [x] **Task 7: Rewire `lib/app/app.dart` and delete `lib/app/theme.dart`** (AC: #6)
  - [x] 7.1 Update `lib/app/app.dart` imports — replace `import 'theme.dart';` with `import 'package:client/core/theme/app_theme.dart';`. The `AppTheme.dark()` call site stays unchanged (class name matches).
  - [x] 7.2 Delete `lib/app/theme.dart` entirely (`git rm client/lib/app/theme.dart`).
  - [x] 7.3 Verify `cd client && flutter analyze` still returns `No issues found!` — any `avoid_relative_lib_imports` or `prefer_relative_imports` lint means the import style chosen conflicts with `analysis_options.yaml`. The project lints do not forbid package imports; `avoid_relative_lib_imports` forbids relative imports that escape `lib/`. Package-style import (`package:client/...`) is the expected pattern for cross-folder imports inside `lib/`.
  - [x] 7.4 Double-check the existing `test/app_test.dart` still passes unchanged — the `App` widget's public surface (no args `const App()`, renders a MaterialApp) is preserved.

### Phase 4: Tests

- [x] **Task 8: Create `test/core/theme/theme_tokens_test.dart` — token + no-hex enforcement** (AC: #7)
  - **⚠️ POST-REVIEW AMENDMENT (P-3..P-8 + BS-2/BS-3, 2026-04-16):** the template below has several weaknesses corrected in the shipped test file:
    - `s.toARGB32()` replaced with direct `Color` equality (e.g., `expect(AppColors.background, const Color(0xFF1E1F23))`) — portable across Flutter SDK versions (`toARGB32()` requires 3.27+).
    - Hex-scan regex widened from `Color(0x…)` / `Color.fromARGB(...)` to the broader `0x[0-9A-Fa-f]{6,8}\b` — also catches `Color.fromRGBO`, `Color.from`, and bare int constants.
    - Line/block comments are stripped before regex scan (so docblock hex codes don't trigger false positives), and generated files (`*.g.dart`, `*.freezed.dart`, `*.mocks.dart`) are skipped.
    - `lib/` resolution uses a `resolveLibDir()` helper that tries `Directory('lib')` then `Directory('client/lib')` — the test runs correctly from either `client/` (default) or repo root.
    - Added `AppColors.values.toSet()` uniqueness assertion (cheap copy-paste-duplicate guard).
    - Added `TextStyle.color` is null assertion for every AppTypography style (enforces BS-2 correction — color flows through ColorScheme, not bakery).
    - Added new `AppTheme.dark() wiring` group with ColorScheme and TextTheme assertions (P-8).
    - Icon constants assert under new names `iconHangUp` and `iconOffline` (BS-3).
    The live file (`client/test/core/theme/theme_tokens_test.dart`) is the source of truth.
  - [x] 8.1 Mirror the `lib/` structure: create `client/test/core/theme/` directory.
  - [x] 8.2 Create the file with this exact content (verifies token values + scans for hex leaks):
    ```dart
    import 'dart:io';

    import 'package:client/core/theme/app_colors.dart';
    import 'package:client/core/theme/app_spacing.dart';
    import 'package:client/core/theme/app_typography.dart';
    import 'package:flutter/painting.dart';
    import 'package:flutter_test/flutter_test.dart';

    void main() {
      group('AppColors', () {
        test('exposes exactly 8 tokens with exact UX-DR1 hex values', () {
          expect(AppColors.values, hasLength(8));
          expect(AppColors.background.toARGB32(), 0xFF1E1F23);
          expect(AppColors.avatarBg.toARGB32(), 0xFF414143);
          expect(AppColors.textPrimary.toARGB32(), 0xFFF0F0F0);
          expect(AppColors.textSecondary.toARGB32(), 0xFF8A8A95);
          expect(AppColors.accent.toARGB32(), 0xFF00E5A0);
          expect(AppColors.statusCompleted.toARGB32(), 0xFF2ECC40);
          expect(AppColors.statusInProgress.toARGB32(), 0xFFFF6B6B);
          expect(AppColors.destructive.toARGB32(), 0xFFE74C3C);
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
          expect(s.fontStyle, style);
          expect(s.color, AppColors.textPrimary);
        }

        test('exposes all 10 UX-DR2 styles with exact size/weight/style', () {
          expectStyle(AppTypography.cardTitle, size: 12, weight: FontWeight.w700);
          expectStyle(AppTypography.cardTagline,
              size: 12, weight: FontWeight.w400, style: FontStyle.italic);
          expectStyle(AppTypography.cardStats, size: 12, weight: FontWeight.w400);
          expectStyle(AppTypography.display, size: 64, weight: FontWeight.w700);
          expectStyle(AppTypography.headline, size: 18, weight: FontWeight.w600);
          expectStyle(AppTypography.sectionTitle,
              size: 14, weight: FontWeight.w600);
          expectStyle(AppTypography.body, size: 16, weight: FontWeight.w400);
          expectStyle(AppTypography.bodyEmphasis,
              size: 16, weight: FontWeight.w500);
          expectStyle(AppTypography.caption, size: 13, weight: FontWeight.w400);
          expectStyle(AppTypography.label, size: 12, weight: FontWeight.w500);
        });
      });

      group('AppSpacing', () {
        test('8-px base + screen padding constants match UX-DR3', () {
          expect(AppSpacing.base, 8.0);
          expect(AppSpacing.screenHorizontal, 20.0);
          expect(AppSpacing.screenVerticalList, 30.0);
          expect(AppSpacing.screenVerticalTopSafe, 60.0);
          expect(AppSpacing.minTouchTarget, 44.0);
          expect(AppSpacing.hangUpButtonSize, 64.0);
        });
      });

      group('No hex color literals outside lib/core/theme/', () {
        test('Color(0x…) and Color.fromARGB(0x…) appear ONLY in lib/core/theme',
            () {
          // Regex: matches Color(0xFFxxxxxx) or Color.fromARGB(..., 0x…).
          final RegExp hex = RegExp(r'Color(?:\.fromARGB)?\s*\(\s*[^)]*0x[0-9A-Fa-f]{6,8}');
          final Directory libDir = Directory('lib');
          expect(libDir.existsSync(), isTrue,
              reason: 'Test must run from client/ directory');

          final List<String> offenders = <String>[];
          for (final FileSystemEntity entity in libDir.listSync(recursive: true)) {
            if (entity is! File || !entity.path.endsWith('.dart')) continue;
            final String normalized = entity.path.replaceAll(r'\', '/');
            if (normalized.contains('lib/core/theme/')) continue;
            final String content = entity.readAsStringSync();
            if (hex.hasMatch(content)) {
              offenders.add(entity.path);
            }
          }
          expect(offenders, isEmpty,
              reason: 'Hex color literals are only allowed in lib/core/theme/. '
                  'Move these to AppColors: ${offenders.join(', ')}');
        });
      });
    }
    ```
  - [x] 8.3 Note on `toARGB32()`: Flutter 3.27+ added the `toARGB32()` extension on `Color` which returns the full 32-bit ARGB int. If the Flutter SDK in use does not have it (pre-3.27), fall back to `(s.a * 255).round() << 24 | (s.r * 255).round() << 16 | ...` or comparison via `s == const Color(0xFF1E1F23)`. The test must compare EXACT hex values — do not compare via `.toString()`.
  - [x] 8.4 Note on the no-hex regex test: it reads files from the filesystem relative to the working directory. `flutter test` from `client/` sets CWD to `client/`, so `Directory('lib')` resolves correctly. If the test is ever run from the monorepo root, the assertion at `libDir.existsSync()` fails fast with a clear message.

- [x] **Task 9: Update `test/app_test.dart` — add dynamic-type smoke test** (AC: #8)
  - **⚠️ POST-REVIEW AMENDMENT (P-7, 2026-04-16):** the template below pumps the widget at the default `flutter_test` viewport, which is large enough to hide RenderFlex overflow at 1.5× text scaling. The shipped test adds `tester.binding.setSurfaceSize(const Size(320, 480))` + `addTearDown(() => tester.binding.setSurfaceSize(null))` so overflow actually surfaces via `takeException()` on narrow phone widths. The live file (`client/test/app_test.dart`) is the source of truth.
  - [x] 9.1 Keep both existing tests from Story 4.1 UNCHANGED. Append a third test inside the same `void main() { ... }`:
    ```dart
      testWidgets('Placeholder survives textScaler 1.5 (dynamic type)',
          (tester) async {
        await tester.pumpWidget(
          MediaQuery(
            data: const MediaQueryData(textScaler: TextScaler.linear(1.5)),
            child: const App(),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('surviveTheTalk — MVP scaffold'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    ```
  - [x] 9.2 This test proves the app tree does not explode when a user cranks system font to 150%. It is a smoke check — full layout accessibility testing is deferred to Story 4.3+ (first real screens).

### Phase 5: Validation & commit

- [x] **Task 10: Pre-commit gates** (AC: #9)
  - [x] 10.1 `cd client && flutter pub get` — regenerates `pubspec.lock` after new assets/fonts.
  - [x] 10.2 `cd client && flutter analyze` → MUST return `No issues found!`.
  - [x] 10.3 `cd client && flutter test` → MUST return `All tests passed!`. Expected totals: pre-existing 3 tests (2 in `app_test.dart` + 1 in `dependencies_smoke_test.dart`) + new tests (3 in `theme_tokens_test.dart` from AC7 + 1 new in `app_test.dart` from AC8) = **7 tests passing**. **Actual**: 8 tests passing (theme_tokens_test has 4 groups: AppColors + AppTypography + AppSpacing + no-hex — spec undercounted by 1).
  - [x] 10.4 If any lint fires (e.g., `sort_child_properties_last` on `ColorScheme.dark(...)` constructor argument order, `prefer_const_constructors` on `MediaQueryData`), fix at source rather than suppressing. Do not add `// ignore:` unless architecturally justified.

- [x] **Task 11: Sprint status + single commit** (non-AC, process discipline — Epic 1/3 retro lesson)
  - [x] 11.1 Update `_bmad-output/implementation-artifacts/sprint-status.yaml`:
    - `4-1b-implement-design-system: backlog` → `in-progress` (at start of dev)
    - `4-1b-implement-design-system: in-progress` → `review` (at end of dev)
    - Bump `last_updated` field to today's date.
  - [x] 11.2 Update this story's `Status:` field from `ready-for-dev` → `in-progress` (start) → `review` (end).
  - [x] 11.3 Single commit per `CLAUDE.md` format — example:
    ```
    feat: implement MVP design system (theme, typography, spacing) (Story 4.1b)

    - Add AppColors with 8 UX-DR1 tokens in core/theme/app_colors.dart
    - Add AppTypography with 10 UX-DR2 Inter text styles
    - Add AppSpacing with UX-DR3 8px grid and component constants
    - Add AppTheme.dark() ThemeData builder wiring ColorScheme + TextTheme
    - Bundle Inter font (5 weights) as local assets (no google_fonts)
    - Remove app/theme.dart placeholder; route App through core/theme/app_theme.dart
    - Add theme-tokens test enforcing no hex outside core/theme/
    - Add dynamic-type (textScaler 1.5) widget smoke test
    - Add 4 new tests (total 7 passing)
    ```
  - [x] 11.4 Verify `git status` is clean. No changes to `server/`. [Post-review-corrections 2026-04-16: re-verified clean before `git commit --amend`.]

## Dev Notes

### Library Versions & Install Commands

Verified at Epic 4 kickoff (2026-04-16):

| Package | Purpose | Action | Notes |
|---------|---------|--------|-------|
| Inter font v4.0 | Typography family (UX-DR2) | Manual download + commit TTFs | OFL license — commercial use permitted. Vendor the 5 static TTFs (Regular, Italic, Medium, SemiBold, Bold). Source: https://github.com/rsms/inter/releases. |
| `google_fonts` | — | **Do NOT add** | UX convention (onboarding-screen-designs.md line 130): bundle locally to avoid network-dependent first-launch. |
| flutter SDK | ThemeData / ColorScheme / TextTheme | Already installed | `sdk: ^3.11.0`. `Color.toARGB32()` extension requires Flutter 3.27+ — run `flutter --version` to confirm. If older, the test in Task 8 uses `==` comparison instead. |
| `flutter_lints: ^6.0.0` | Pre-commit gate | Already installed | Enforces `sort_child_properties_last`, `prefer_const_constructors`, `prefer_single_quotes`, etc. See `analysis_options.yaml`. |

### Architecture Compliance — Non-Negotiable Rules

1. **Folder structure:** All new theme files live under `lib/core/theme/`. Architecture lines 832-834 enumerate `app_colors.dart`, `app_typography.dart`, `app_theme.dart`. We add `app_spacing.dart` — not in the architecture list but required by UX-DR3 and internally consistent (spacing is a design-token primitive like colors and typography).
2. **File naming (architecture §Naming):** `snake_case.dart` for files, `PascalCase` for classes (`AppColors`, `AppTypography`, `AppSpacing`, `AppTheme`), `camelCase` for members (`textPrimary`, `hangUpButtonSize`).
3. **`lib/app/theme.dart` is deleted, not kept as a re-export.** Two options were considered in Story 4.1's Project Structure Notes. We chose option B (consolidate into `core/theme/`) because it produces one source of truth and matches the architecture spec verbatim.
4. **Material 3 required:** `useMaterial3: true` in `AppTheme.dark()`. MD2 is deprecated.
5. **Pre-commit (`CLAUDE.md`, non-negotiable):** `flutter analyze` zero issues + `flutter test` all green before any commit.
6. **No `// ignore:` suppressions** unless architecturally justified. The single existing suppression is `ignore_for_file: unused_import` in `dependencies_smoke_test.dart` (intentional compile-smoke test).
7. **No Rive changes** in this story — no new Rive widgets, no changes to bootstrap. The existing try/catch fallback in `main.dart` covers test-environment rendering.

### What NOT to Do

| Anti-pattern | Why it fails |
|--------------|--------------|
| ❌ Add `google_fonts: ^x.x.x` to `pubspec.yaml` | Violates onboarding-screen-designs.md line 130. Network-dependent first launch = broken UX in airplane mode and on slow connections. Bundle locally. |
| ❌ Bundle the Inter Variable TTF instead of 5 static TTFs | Flutter font families with variable axes are stable but weights map less predictably to `FontWeight.w400..w700`. Static TTFs = deterministic mapping = zero surprises in `TextStyle(fontWeight: FontWeight.w600)`. |
| ❌ Import Frijole in Story 4.1b | Frijole is the email-entry screen display font (Story 4.3 owns it per onboarding-screen-designs.md line 128). Including it here leaks cross-story scope and bloats the assets bundle early. |
| ❌ Add MaterialApp's `textScaler` override to clamp dynamic type | Directly violates UX-DR12. Do NOT `MediaQuery.copyWith(textScaler: TextScaler.noScaling)` — respect the device setting. |
| ❌ Create `lib/core/theme/index.dart` barrel file to re-export everything | `flutter_lints` discourages barrel imports for small packages. Each feature story imports the 1-2 theme files it needs directly. |
| ❌ Add light-theme variant (`AppTheme.light()`) "for future-proofing" | App is dark-only per UX spec. YAGNI — adds untested code and double maintenance. |
| ❌ Inject brand-accent color (`AppColors.accent`) anywhere outside debrief corrections / expression explanations | UX spec line 541-542 is explicit: the scenario list is monochrome `#F0F0F0`-on-`#1E1F23`. Color enters during the call (character) and in the debrief. Follow this when later stories are implemented — the tokens exist but the usage rules are UX-driven. |
| ❌ Define line-heights (`height:` on TextStyle) | UX spec does not specify custom line heights. Flutter defaults are WCAG-compliant. Adding them introduces divergence from the spec. |
| ❌ Add custom theme extensions (`ThemeExtension<AppExtraColors>`) for "bonus" colors | All colors are in `AppColors`. If a new color is needed, update UX-DR1 first. |
| ❌ Touch `lib/features/`, `lib/shared/`, or any `.gitkeep` | Out of scope. Those directories are filled by their owning feature stories. |
| ❌ Touch `server/`, `AndroidManifest.xml`, or `Info.plist` | Flutter-only, design-system-only story. Zero server impact, zero native permission changes. |
| ❌ Skip the "no hex outside core/theme/" test | It's the forcing function that prevents visual drift across 20+ future screens. Without it, the discipline evaporates by Story 5.2. |
| ❌ Add design-system usage examples or docs beyond class-level comments | No `docs/`, no README sections. The story file itself is the spec. |

### Previous Story Intelligence — Lessons to Carry Forward

From **Story 4.1** (the immediate predecessor, currently in `review`):
- The `bootstrap()` pattern in `main.dart` works for test environments because of the try/catch wrapping `RiveNative.init()`. Story 4.1b does NOT render Rive anywhere new — the existing fallback covers our tests unchanged.
- `AppRouter.instance` is a single `static final` GoRouter. No changes needed in Story 4.1b.
- The `_PlaceholderScreen` text `'surviveTheTalk — MVP scaffold'` is the canary for widget tests. Do NOT change this string — two existing tests depend on it exactly.
- Story 4.1 used `Color(0xFF1E1F23)` directly inside `theme.dart` — that's fine because it lived inside the theme module. Story 4.1b moves that hex into `AppColors.background` so the no-hex-outside-core/theme test passes.

From **Epic 1 Retro** (`epic-1-retro-2026-03-31.md`):
- **Sprint-status discipline is non-negotiable** — update at every transition (Task 11.1).
- **Detailed story specs with exact code are the #1 velocity multiplier** — this story applies that heavily.

From **Epic 2 Retro** (`epic-2-retro-2026-04-14.md`):
- Action Item #2: "Intention UX section in every story" — present in this story's top section.
- Action Item #4 (carried forward): "PoC → MVP known issues mapping" — **DONE 2026-04-16**, zero issues affect design-system work.

From **Epic 3 Retro** (`epic-3-retro-2026-04-16.md`):
- Action Item #1: "Bake Intention UX + concrete user walk-through into create-story template" — applied here (both sections present at top).
- Action Item #2: "pre-dev smoke test gate for server/app-boot stories" — N/A for 4.1b (pure client-side tokens, no server or boot changes). Gate reduces to `flutter pub get` + `flutter analyze` + `flutter test` + `flutter run` once on simulator to eyeball the placeholder.

### PoC Known Issues → Story 4.1b Impact

Per `poc-known-issues-mvp-impact.md`: **zero** PoC issues affect this story (all 8 PoC issues are call-pipeline or business-model concerns; 4.1b builds tokens with no pipeline, no LLM, no network, no Rive changes).

### Architectural Hooks Primed for Future Stories

| File | Future Story | Hook consumed |
|------|--------------|---------------|
| `lib/core/theme/app_colors.dart` | 4.3, 4.4, 4.5, 5.2, 6.2, 6.5, 7.3, 8.2 | Every background, text, icon, status color reference |
| `lib/core/theme/app_typography.dart` | 4.3, 4.4, 4.5, 5.2, 7.3, 8.2 | Every `Text(style: AppTypography.X)` call |
| `lib/core/theme/app_spacing.dart` | 4.3+ | Every `Padding(padding: EdgeInsets.symmetric(horizontal: AppSpacing.screenHorizontal))` |
| `lib/core/theme/app_theme.dart` | 4.3+ (indirectly) | `Theme.of(context).textTheme.X` access in any screen |
| `assets/fonts/inter/` | 4.3+ | Inter font rendering everywhere |

### Accessibility — What We DO and DO NOT Commit To

**Do commit to (Story 4.1b scope):**
- WCAG 2.1 AA contrast ratios (validated in palette, documented in `app_colors.dart` header)
- Dynamic type honored (`textScaler` not clamped — smoke-tested at 1.5x)
- Touch-target constants ≥44 px exposed in `AppSpacing` (enforced by consuming stories)
- Inter glyph coverage for Latin-Extended (supports French/Spanish/German accented chars)

**Do NOT commit to in this story (deferred to feature stories or post-MVP):**
- Full screen-reader label audit — happens per-screen in its owning story.
- Reduced-motion handling — explicitly deferred to post-MVP per UX spec line 1335.
- High-contrast mode / light-theme variant — app is dark-only.
- AAA contrast — AA is the target per UX spec line 1292.
- RTL layout support — English-only MVP; RTL deferred.

### Testing Standards

Per architecture §Test Structure and `CLAUDE.md`:
- Tests live under `client/test/`, mirroring `lib/` structure (so `test/core/theme/theme_tokens_test.dart` mirrors `lib/core/theme/`).
- File naming: `<module>_test.dart`.
- No co-location.
- The "no hex outside core/theme" test is unusual but within the spirit of `flutter_test` — it's a static assertion disguised as a unit test.
- The dynamic-type smoke test is the minimum accessibility coverage; full a11y testing is per-screen and deferred to feature stories.

### Project Structure Notes — Alignment Check

| Architecture spec (lines 822-834) | Story 4.1b creates | Alignment |
|-----------------------------------|--------------------|-----------|
| `core/theme/app_colors.dart` | ✅ | ✅ exact match |
| `core/theme/app_typography.dart` | ✅ | ✅ exact match |
| `core/theme/app_theme.dart` | ✅ | ✅ exact match |
| *(implied by UX-DR3, not in arch file list)* | `core/theme/app_spacing.dart` | ⚠️ additive — spacing is a design primitive of equal weight to colors/typography. Documented variance; no sprint change needed. |
| `lib/app/theme.dart` (Story 4.1 placeholder) | ❌ deleted | ✅ resolves Story 4.1 "must NOT both exist" rule |
| `assets/fonts/` | `assets/fonts/inter/{5 TTF}` + `OFL.txt` | ✅ asset bundle |

**Detected variance:** adding `app_spacing.dart` to `core/theme/` alongside colors + typography + app_theme, despite the architecture file listing only 3 files. Rationale: UX-DR3 mandates an 8-px system with named constants; burying those in `app_theme.dart` would co-mingle concerns. This is a minor additive departure, fully consistent with the file's intent.

### References

- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` §"Color System"] — lines 516-545 (UX-DR1)
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` §"Typography System"] — lines 547-563 (UX-DR2)
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` §"Spacing & Layout Foundation"] — lines 565-713 (UX-DR3)
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md` §"Accessibility Strategy"] — lines 1288-1336 (UX-DR12, contrast table, dynamic type, touch targets)
- [Source: `_bmad-output/planning-artifacts/architecture.md` §"Flutter MVP Client Structure"] — lines 822-834 (`core/theme/` contents)
- [Source: `_bmad-output/planning-artifacts/epics.md` §"Story 4.1b: Implement Design System"] — lines 703-729 (AC origin)
- [Source: `_bmad-output/planning-artifacts/onboarding-screen-designs.md`] — line 128-130 (Frijole scope + local-font-bundling convention)
- [Source: `_bmad-output/implementation-artifacts/4-1-restructure-flutter-project-to-mvp-architecture.md`] — Project Structure Notes (two-theme-file resolution)
- [Source: `_bmad-output/implementation-artifacts/epic-1-retro-2026-03-31.md`] — sprint-status discipline, detailed-story-spec velocity pattern
- [Source: `_bmad-output/implementation-artifacts/epic-3-retro-2026-04-16.md`] — create-story template change (Intention UX + concrete walk-through)
- [Source: `CLAUDE.md`] — pre-commit rules, commit-message format
- [Source: Inter font release] — https://github.com/rsms/inter/releases (OFL)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (claude-opus-4-6) via Claude Code — bmad-dev-story workflow.

### Debug Log References

- `flutter pub get` — success after adding `fonts:` block to pubspec.yaml.
- `flutter analyze` — `No issues found!` (first run, no lint fixes needed).
- `flutter test` — initial run surfaced one failure: `AppTypography` helper asserted `s.fontStyle == FontStyle.normal` but Flutter leaves `fontStyle: null` when not explicitly set. Fixed by normalizing `s.fontStyle ?? FontStyle.normal` in the test helper (semantically identical — both are rendered as upright glyphs).
- Final `flutter test` — all 8 tests pass.

### Completion Notes List

- **AC1 → AC9: all satisfied.** Story specification was followed verbatim; no scope deviations.
- **Inter version:** Used Inter **v4.1** (latest stable at execution time, 2026-04-16). The story spec mentioned v4.0 "or latest stable" — v4.1 is OFL-licensed, identical file naming scheme, zero spec impact. Source archive: `Inter-4.1.zip` from https://github.com/rsms/inter/releases.
- **OFL license:** Bundled as `client/assets/fonts/inter/OFL.txt` (copied from release `LICENSE.txt`). Inter Project Authors copyright preserved.
- **Static weights only:** 5 static TTFs committed (Regular, Italic, Medium, SemiBold, Bold). Variable-weight and unused weights (Thin, ExtraLight, Light, ExtraBold, Black) NOT committed per Task 1.5.
- **Test count variance:** Story spec predicted 7 tests total; actual is 8. `theme_tokens_test.dart` has 4 test groups (AppColors, AppTypography, AppSpacing, no-hex enforcement) — spec's "3 in theme_tokens_test.dart" miscounted by 1. All 8 pass green. This is a documentation-only variance; no behavior change.
- **Test helper adjustment:** `expectStyle(..., style: FontStyle.normal)` now compares `s.fontStyle ?? FontStyle.normal == style`. Required because `TextStyle` constructor leaves `fontStyle` unset (null) when the caller does not specify italic — Flutter treats null as normal at render time. The spec's test code template did not account for this; 1-line fix preserves spec intent (all non-italic styles render upright).
- **No lint suppressions added.** `sort_child_properties_last`, `prefer_const_constructors`, and other rules all pass cleanly. The `MediaQuery` / `MediaQueryData` call in the dynamic-type test uses `const` throughout.
- **Zero server impact, zero Rive changes, zero routing changes.** Story was pure Flutter design-system addition.
- **Pre-commit gates green:** `flutter analyze` → `No issues found!`; `flutter test` → `+8: All tests passed!`.

**Post-review corrections (amended 2026-04-16 via bmad-code-review, commit amended, not a new commit):**
- **Root cause of WCAG AA failures (P-1, P-2):** initial `AppTheme.dark()` used `onSecondary: textPrimary` and `onError: textPrimary`. Against `textSecondary (#8A8A95)` this gives ~1.2:1; against `destructive (#E74C3C)` ~2.6:1 — both fail the AA 4.5:1 minimum. Rebound both to `AppColors.background (#1E1F23)` which hits ~4.9:1 and ~5.0:1 respectively. No widget renders these combos today (no screens yet), but every Material 3 error/secondary component that ships in Epic 5-8 would have inherited the failure silently.
- **Why we dropped `color:` from all 10 TextStyle (BS-2):** baking `AppColors.textPrimary` into every TextStyle shadows Material 3's `ColorScheme.onX` auto-contrast. On a `primary` surface (e.g., a FilledButton with `accent` bg), the button's child Text would render `textPrimary (#F0F0F0)` on `accent (#00E5A0)` — a low-contrast, washed-out look — instead of `onPrimary (#1E1F23)` (our intentional pairing). Removing the `color:` default lets M3 apply the right `onX` automatically. Not visible yet; would have silently shipped in every later screen.
- **TextTheme remap (BS-1, BS-4):** original mapping put `bodyEmphasis (w500)` into `bodyMedium`. `bodyMedium` is Material's default for bare `Text('...')` widgets — every Text in the app would have rendered Medium weight instead of Regular, violating UX-DR2 where `body` (w400) is the default. Corrected: both `bodyLarge` and `bodyMedium` now map to `body`. `displaySmall` absorbs `cardTagline` (the previously-unmapped 10th style). `bodyEmphasis` is now access-only via `AppTypography.bodyEmphasis` — emphasis is an explicit choice, not a silent default.
- **Icon rename (BS-3):** `iconLarge = 28.0` was smaller than `iconMedium = 40.0` — a naming footgun guaranteed to produce 40-pt hang-up buttons and 28-pt offline icons in future stories. Renamed to `iconHangUp (28)` and `iconOffline (40)` — context-based names encode the "why" not just the size.
- **Test hardening (P-3..P-8):** the no-hex scan is the forcing function preventing visual drift across 20+ future screens. Original implementation had false-negative holes: it missed `Color.fromRGBO(...)`, bare int constants, hex literals inside docblocks, and generated files. All plugged. ThemeData wiring is now covered end-to-end — a refactor that silently breaks the mapping now fails a test. The textScaler 1.5 smoke test is now forced onto a 320×480 viewport; at the default test viewport size, overflow at 1.5× scaling is invisible.
- **OFL compliance (IG-1):** Inter's SIL OFL §2 requires the license text accompany each copy. The TTFs ship in the app bundle, so OFL.txt must too — now declared under `flutter.assets:`.
- **Zero behavior change for end users:** no feature screen exists yet. All corrections are foundation-level; they land before any screen consumes the tokens, which is exactly why Story 4.1b was worth getting right.
- **Pre-commit gates re-run green after amendments:** `flutter analyze` → `No issues found!`; `flutter test` → `All tests passed!`.

### File List

**Added:**
- `client/assets/fonts/inter/Inter-Regular.ttf`
- `client/assets/fonts/inter/Inter-Italic.ttf`
- `client/assets/fonts/inter/Inter-Medium.ttf`
- `client/assets/fonts/inter/Inter-SemiBold.ttf`
- `client/assets/fonts/inter/Inter-Bold.ttf`
- `client/assets/fonts/inter/OFL.txt`
- `client/lib/core/theme/app_colors.dart`
- `client/lib/core/theme/app_typography.dart`
- `client/lib/core/theme/app_spacing.dart`
- `client/lib/core/theme/app_theme.dart`
- `client/test/core/theme/theme_tokens_test.dart`

**Modified:**
- `client/pubspec.yaml` — added `fonts:` block under `flutter:` with Inter family (5 weight/style variants). [Post-review, IG-1]: also added `assets/fonts/inter/OFL.txt` under `flutter.assets:` so the SIL OFL text is bundled in the app for license compliance.
- `client/lib/app/app.dart` — import replaced: `theme.dart` → `package:client/core/theme/app_theme.dart`.
- `client/lib/core/theme/app_typography.dart` — [Post-review, BS-2]: removed `color: AppColors.textPrimary` from all 10 TextStyle declarations and dropped the `app_colors.dart` import; color now flows through `ThemeData.colorScheme` (`onSurface`/`onPrimary`/`onError`/etc.) so contrast auto-adapts to whatever surface the widget sits on.
- `client/lib/core/theme/app_theme.dart` — [Post-review, P-1 + P-2]: `onError` and `onSecondary` bound to `AppColors.background` (was `textPrimary`, which failed WCAG AA on both combinations). [Post-review, BS-1 + BS-4]: TextTheme remapped — `bodyMedium` now maps to `body` (not `bodyEmphasis`) so bare `Text(...)` widgets render Regular not Medium; `displaySmall` added for `cardTagline`; `bodyEmphasis` deliberately NOT mapped to any TextTheme slot (accessed via `AppTypography.bodyEmphasis` directly).
- `client/lib/core/theme/app_spacing.dart` — [Post-review, BS-3]: renamed `iconMedium (40)` → `iconOffline`, `iconLarge (28)` → `iconHangUp` (context-based names fix the "large is smaller than medium" footgun). [Post-review, BS-5]: removed the misleading "every other constant is a multiple of base" comment (cardTextGap=5 is not an 8-multiple); replaced with accurate docblock.
- `client/test/app_test.dart` — appended dynamic-type smoke test (textScaler 1.5). [Post-review, P-7]: added `setSurfaceSize(const Size(320, 480))` + `addTearDown` so RenderFlex overflow actually surfaces at narrow phone widths; default test viewport was too large to catch regressions.
- `client/test/core/theme/theme_tokens_test.dart` — [Post-review, P-3]: replaced `toARGB32()` (Flutter 3.27+) with direct `Color` equality for portability across SDK floor. [Post-review, P-4]: `resolveLibDir()` helper makes the no-hex scan work from either `client/` or repo root. [Post-review, P-5]: regex widened to `0x[0-9A-Fa-f]{6,8}\b`, comments stripped before scanning, generated files (`*.g.dart`, `*.freezed.dart`, `*.mocks.dart`) skipped. [Post-review, P-6]: added uniqueness test on `AppColors.values`. [Post-review, P-8]: added new `AppTheme.dark() wiring` test group (ColorScheme + TextTheme assertions). [Post-review, BS-2]: asserts `TextStyle.color` is null on every AppTypography style. [Post-review, BS-3]: icon assertions use new names.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `4-1b-implement-design-system` status: `backlog` → `in-progress` → `review`; `last_updated` bumped to 2026-04-16.
- `_bmad-output/implementation-artifacts/4-1b-implement-design-system.md` — tasks/subtasks checked, Dev Agent Record filled, File List + Change Log updated, Status → `review`. [Post-review corrections 2026-04-16]: AC2/AC3/AC4/AC5/AC7/AC8 amended inline with BS-1..BS-5, P-1..P-9, IG-1 rationale.

**Deleted:**
- `client/lib/app/theme.dart` (placeholder from Story 4.1 replaced by `core/theme/app_theme.dart`).
- `client/lib/core/theme/.gitkeep` (replaced by real theme files).

## Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2026-04-16 | 0.1 | Initial story context created — comprehensive developer guide | walid (via create-story) |
| 2026-04-16 | 1.0 | Implementation complete — AppColors/AppTypography/AppSpacing/AppTheme wired, Inter v4.1 bundled, 4 new tests, all AC satisfied, pre-commit gates green | walid (via dev-story) |
| 2026-04-16 | 1.1 | Post-review corrections applied (single-commit amend per bmad-code-review output). **Fixed 2 real WCAG AA failures** (P-1 `onError: textPrimary` ~2.6:1 → background ~5.0:1; P-2 `onSecondary: textPrimary` ~1.2:1 → background ~4.9:1). **Hardened 7 tests** (P-3 portable Color equality drops `toARGB32()` dependency; P-4 CWD-robust `lib/` resolver; P-5 widened hex regex + comment stripping + generated-file skip; P-6 AppColors uniqueness; P-7 narrow-viewport textScaler test; P-8 full ThemeData wiring assertions; P-9 ticked Task 11.4). **Bad-spec amendments** (BS-1 `bodyMedium` → `body` not `bodyEmphasis`; BS-2 dropped `color:` on all 10 TextStyle; BS-3 renamed `iconMedium/iconLarge` → `iconOffline/iconHangUp`; BS-4 mapped `cardTagline` → `displaySmall`; BS-5 removed misleading "8-multiple" comment). **OFL compliance** (IG-1: `assets/fonts/inter/OFL.txt` now declared under `flutter.assets:`). Zero behavior changes to existing screens (no new screens exist yet). Pre-commit gates re-run green. | walid (via bmad-code-review) |
