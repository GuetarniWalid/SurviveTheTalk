# Story 5.4: Build Content Warning Display for Intense Scenarios

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to see a content warning before attempting scenarios involving threat, confrontation, or authority pressure,
so that I can make an informed choice about whether to proceed.

## Acceptance Criteria (BDD)

**AC1 — Dialog gate fires only when `scenario.contentWarning != null`:**
Given the scenario list is rendered (`ScenariosLoaded` state, Story 5.2)
When the user taps the phone icon on a `ScenarioCard`
Then `_onCallTap` checks `scenario.contentWarning`:
  - **non-null** (e.g. The Mugger, The Cop, The Landlord, The Girlfriend) → `showContentWarningDialog(context, scenario)` is awaited BEFORE any `context.go(AppRoutes.call, ...)` call
  - **null** (e.g. The Waiter — calibrated for near-guaranteed success per Story 5.2 AC6) → call initiation continues directly with NO dialog (`context.go(AppRoutes.call, extra: scenario)` runs unchanged)
And the gate is the ONLY change to `_onCallTap` — the briefing tap (`_onCardTap`) and report tap (`_onReportTap`) are NOT gated (briefing is a read-only preview, debrief is post-call) and stay byte-for-byte identical to Story 5.2.

**AC2 — Dialog renders the canonical UX-decision copy:**
Given `_bmad-output/planning-artifacts/ux-decisions/content-warning-dialog.md` (UX Decision, accepted 2026-04-24) is the locked spec
When the dialog is presented
Then it MUST match this exact frame:
  - **Title**: NONE (no `title:` argument passed to `AlertDialog` — the body alone carries the message)
  - **Body**: `Text(scenario.contentWarning!)` rendered verbatim from the DB (no prefix, no suffix, no emoji, no "Avertissement :" header)
  - **Primary action**: `ElevatedButton` labelled `"Continuer"` (exact French string, capital C, no period)
  - **Secondary action**: `TextButton` labelled `"Revenir"` (exact French string, capital R, no period)
  - **Action order**: secondary on the LEFT, primary on the RIGHT — `actions: [TextButton(Revenir), ElevatedButton(Continuer)]` per Material convention
And `barrierDismissible: false` — tapping the scrim outside the dialog does NOT dismiss it (forces explicit choice; UX decision §"Cross-cutting rules")
And there is NO "don't show again" checkbox, NO toggle, NO preference write — the dialog re-fires on every tap (UX decision §"Cross-cutting rules" point 3).

**AC3 — Confirm path proceeds to call initiation:**
Given the dialog is open
When the user taps `"Continuer"`
Then `Navigator.pop(ctx, true)` closes the dialog returning `true`
And the awaiting caller (`_onCallTap`) checks the result and dispatches `context.go(AppRoutes.call, extra: scenario)` — the SAME navigation Story 5.2 ships
And no other side effect happens (no analytics, no preference write, no bloc event — Epic 5 scope is gating only).

**AC4 — Cancel path returns to list with zero side effects:**
Given the dialog is open
When the user taps `"Revenir"`
Then `Navigator.pop(ctx, false)` closes the dialog returning `false`
And `_onCallTap` returns early — NO `context.go(AppRoutes.call)` call
And the user is back on the scenario list with no visible state change (the bloc has not been touched, the card is still pressable, the BOC if present is unchanged).

**AC5 — Result-typed `showContentWarningDialog` helper:**
Given a single helper function is the public API for the gate
When `showContentWarningDialog(BuildContext context, Scenario scenario) async` is called
Then it returns `Future<bool>`:
  - resolves to `true` when the user tapped `"Continuer"`
  - resolves to `false` when the user tapped `"Revenir"`
  - resolves to `false` when the dialog is dismissed by any other means (e.g. system back-press on Android — `barrierDismissible: false` only blocks scrim-tap, NOT the OS back gesture, so the helper coerces a `null` from `showDialog<bool>` into `false` defensively)
And the helper asserts `scenario.contentWarning != null` at entry (`assert(scenario.contentWarning != null, '...')` — debug-only guard against accidental call from a null-warning code path; release builds skip the assert and still navigate via the cancel branch if the body is empty)
And the helper lives in `client/lib/features/scenarios/views/widgets/content_warning_dialog.dart` — co-located with `bottom_overlay_card.dart` and `scenario_card.dart` (per Story 5.2 / 5.3 file-tree convention).

**AC6 — Material theming, zero hex literals (UX Decision §Design system):**
Given the project's `theme_tokens_test.dart` enforces "every hex literal lives in `lib/core/theme/`" (client/CLAUDE.md gotcha §6)
When the dialog renders
Then it inherits the dialog surface, button, and text colours EXCLUSIVELY from `Theme.of(context)` (i.e. `AppTheme.dark()`'s `ColorScheme` and `TextTheme`):
  - body text style: `Theme.of(context).textTheme.bodyLarge` (which maps to `AppTypography.body` per `app_theme.dart:55-56`)
  - button styles: framework defaults (`ElevatedButton` / `TextButton`) — they pull from the theme's `ColorScheme.primary` (`AppColors.accent`) and `ColorScheme.onSurface` (`AppColors.textPrimary`)
  - dialog scrim / surface: framework defaults (Material 3 `surface` token via `ColorScheme.surface = AppColors.background`)
And `theme_tokens_test.dart` stays green — the new `content_warning_dialog.dart` file contains ZERO `Color(0x…)`, `Color.fromARGB`, `Color.fromRGBO`, or bare-int colour constants.

**AC7 — Accessibility (UX Decision §Accessibility, UX-DR12):**
Given screen readers are enabled (VoiceOver / TalkBack)
When the dialog opens
Then Material's default `AlertDialog` semantics apply: focus moves to the dialog, the body `Text` is announced on focus, and the two buttons are reachable as siblings — verbs `"Continuer"` and `"Revenir"` are distinct enough to disambiguate without an "OK / Cancel" override (UX decision §Accessibility point 1)
And on a 320-wide viewport with `MediaQueryData(textScaler: TextScaler.linear(1.5))`, the body wraps without overflow (UX decision §Accessibility point 2; client/CLAUDE.md gotcha §7 mandates `setSurfaceSize` in tests)
And tap targets satisfy ≥ 48×48 dp by virtue of `AlertDialog`'s built-in button padding — NO custom `minimumSize` overrides.

**AC8 — Five widget tests covering the four dialog branches + the no-warning bypass:**
Given client/CLAUDE.md gotcha §7 (force phone size) + §1 (`FlutterSecureStorage.setMockInitialValues({})`) + §3 (use explicit `pump(...)` for non-terminating frames, but `pumpAndSettle` is OK here — `AlertDialog` enter/exit animations terminate)
When `client/test/features/scenarios/views/widgets/content_warning_dialog_test.dart` runs
Then it covers:
  1. `dialog body renders scenario.contentWarning verbatim` — pump a harness with `Scenario(contentWarning: 'CW body 12345')`, tap a trigger button that calls `showContentWarningDialog`, assert `find.text('CW body 12345').findsOneWidget` AND assert NO `find.text('Avertissement')` / `find.text('Content notice')` / `find.byType(SizedBox)` masquerading as a title slot
  2. `dialog has no title slot` — assert `find.descendant(of: find.byType(AlertDialog), matching: find.byType(Text))` returns the body Text + the two button labels = 3 Text widgets (no fourth title Text)
  3. `tap Continuer resolves the future to true` — pump, tap `find.text('Continuer')`, await the `Future<bool>`, assert `true`
  4. `tap Revenir resolves the future to false` — pump, tap `find.text('Revenir')`, await, assert `false`
  5. `barrierDismissible: false — tap on scrim does NOT dismiss the dialog` — pump, `await tester.tapAt(const Offset(20, 20))` (clearly outside the dialog rect on a 320×480 surface), assert the dialog is STILL on-screen (`find.byType(AlertDialog).findsOneWidget`)
And EACH test starts with:
```dart
setUp(() {
  FlutterSecureStorage.setMockInitialValues({});
});
testWidgets('...', (tester) async {
  await tester.binding.setSurfaceSize(const Size(320, 480));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  // ...
});
```

**AC9 — Two integration tests on `ScenarioListScreen` covering the gate branch:**
Given `client/test/features/scenarios/views/scenario_list_screen_test.dart` (Story 5.2) already covers the no-warning path (the existing `_build()` helper hardcodes `contentWarning: null` — line 33), but does NOT cover the dialog path
When this story extends that file
Then it adds:
  1. `tapping phone icon on a scenario WITH content_warning shows the dialog` — `_build(id: ..., contentWarning: 'X')` (extend the helper to accept a `String? contentWarning` param), pump screen with one card, `tester.tap(find.byIcon(Icons.phone_outlined))`, `await tester.pumpAndSettle()`, assert `find.byType(AlertDialog).findsOneWidget` AND `find.text('X').findsOneWidget` AND assert the route is STILL `/` (not yet `/call`) — `find.text('CALL_STUB').findsNothing`
  2. `tapping Continuer in the dialog navigates to /call with the scenario as extra` — same setup, then `tester.tap(find.text('Continuer'))`, `await tester.pumpAndSettle()`, assert `find.text('CALL_STUB').findsOneWidget` (the GoRouter test stub at `/call` from Story 5.2 line 51-55)
  3. `tapping Revenir in the dialog returns to the list without navigating` — same setup, `tester.tap(find.text('Revenir'))`, `await tester.pumpAndSettle()`, assert `find.text('CALL_STUB').findsNothing` AND `find.byType(ScenarioCard).findsOneWidget` (still on the list)
  4. `tapping phone icon on a scenario WITHOUT content_warning skips the dialog and navigates directly` — REGRESSION GUARD for the existing path: `_build(contentWarning: null)`, `tester.tap(find.byIcon(Icons.phone_outlined))`, `await tester.pumpAndSettle()`, assert `find.byType(AlertDialog).findsNothing` AND `find.text('CALL_STUB').findsOneWidget`
And the existing 6 Story-5.2 tests in this file STAY GREEN — the `_build()` signature widening is backward-compat (default `contentWarning = null` matches today's behavior).

**AC10 — Pre-commit validation gates:**
Given pre-commit requirements from CLAUDE.md (project root) + client/CLAUDE.md
When the story is complete
Then `cd client && flutter analyze` prints "No issues found!" — every info-level lint fixed (especially `prefer_const_constructors` on the new `Text('Continuer')` / `Text('Revenir')` literals, and `no_leading_underscores_for_local_identifiers` if any locals are introduced)
And `cd client && flutter test` prints "All tests passed!" — 5 new dialog tests + 4 new list-screen tests + ALL existing tests (Stories 5.1 / 5.2 / 5.3 if 5.3 has landed) still green; expected count delta is +9
And `cd server` checks (`python -m ruff check . && python -m ruff format --check . && pytest`) STILL pass — this story ships ZERO server changes, but pre-commit runs the full server suite anyway to catch any cross-cutting drift (e.g. project-wide `ruff` config tweaks).

## Tasks / Subtasks

- [x] Task 1: Client — `showContentWarningDialog` helper (AC: 2, 5, 6, 7)
  - [x] 1.1 Create `client/lib/features/scenarios/views/widgets/content_warning_dialog.dart`:
    ```dart
    import 'package:flutter/material.dart';

    import '../../models/scenario.dart';

    /// Material AlertDialog gate shown before initiating a call on a
    /// scenario whose `content_warning` column is non-null. Resolves to
    /// `true` when the user taps "Continuer" (proceed to /call), `false`
    /// otherwise (Revenir, system back-press, or any non-explicit
    /// dismissal).
    ///
    /// Frame, copy, and behavior are locked by:
    /// `_bmad-output/planning-artifacts/ux-decisions/content-warning-dialog.md`
    /// (UX Decision, accepted 2026-04-24). Do NOT add a title slot, a
    /// "don't show again" toggle, or `barrierDismissible: true`.
    Future<bool> showContentWarningDialog(
      BuildContext context,
      Scenario scenario,
    ) async {
      assert(
        scenario.contentWarning != null,
        'showContentWarningDialog called for a scenario with no content_warning. '
        'Caller must guard with `if (scenario.contentWarning != null)` first.',
      );
      final result = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          content: Text(scenario.contentWarning!),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Revenir'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Continuer'),
            ),
          ],
        ),
      );
      return result ?? false;
    }
    ```
  - [x] 1.2 DO NOT pass a `title:` argument. UX Decision §"Copy spec" line 23 states `Title` = `(none — dialog has no title, body carries the message)`.
  - [x] 1.3 DO NOT add `style:` overrides on either button. The default `ElevatedButton` / `TextButton` styles consume `Theme.of(context).colorScheme` (which is `AppColors.accent` / `AppColors.textPrimary` per `app_theme.dart`). Adding inline colour styles violates AC6 + client/CLAUDE.md gotcha §6 + would silently break `theme_tokens_test.dart` if any hex slipped through.
  - [x] 1.4 DO NOT pass `barrierDismissible: true` or omit it (default is `true`!). The explicit `false` is the gate-decision spec — see UX Decision §"Cross-cutting rules" point 1.
  - [x] 1.5 Coerce `null → false` at the return site (`result ?? false`). System back-press on Android resolves the `showDialog<bool>` future to `null`; we treat that as "user wants out", same as Revenir. NOT `null → true` (would be a serious safety regression — back-press should NEVER auto-confirm an intense scenario).
  - [x] 1.6 The function is a top-level free function (NOT a static method on a class, NOT a singleton). One file, one export, no state — mirrors `buildCardDescriptionLabel` in `scenario_card.dart:16` and `_variantFor` in Story 5.3's BOC.

- [x] Task 2: Client — wire the gate into `ScenarioListScreen._onCallTap` (AC: 1, 3, 4)
  - [x] 2.1 In `client/lib/features/scenarios/views/scenario_list_screen.dart`, change `_onCallTap` from sync to async + insert the dialog gate:
    ```dart
    Future<void> _onCallTap(BuildContext context, Scenario scenario) async {
      if (scenario.contentWarning != null) {
        final proceed = await showContentWarningDialog(context, scenario);
        if (!proceed) return;
        if (!context.mounted) return;
      }
      context.go(AppRoutes.call, extra: scenario);
    }
    ```
  - [x] 2.2 Add the import at the top of the file: `import 'widgets/content_warning_dialog.dart';` (alphabetical order within the `widgets/` cluster — currently only `widgets/scenario_card.dart` is imported there).
  - [x] 2.3 The `ScenarioCard.onCallTap: () => _onCallTap(context, scenario)` callback in the `_List.itemBuilder` (line 68) STAYS unchanged. The async return value of `_onCallTap` is fire-and-forget from the `VoidCallback` perspective — Dart silently discards a returned `Future<void>` from a `VoidCallback` arrow body (it's fine here because we don't need to await user-side; the dialog manages its own lifecycle).
  - [x] 2.4 The `if (!context.mounted) return;` guard between `await` and `context.go` is REQUIRED — `flutter analyze` flags `use_build_context_synchronously` otherwise (one of the lints client/CLAUDE.md §9 explicitly calls out as a CI blocker).
  - [x] 2.5 DO NOT also gate `_onCardTap` (briefing) or `_onReportTap` (debrief). Briefing is a pre-call read-only preview screen — no warning needed there. Debrief is post-call (user has already seen the warning + completed the scenario) — no warning needed there either. The gate exists EXCLUSIVELY at the threshold of starting a live LiveKit + Pipecat session.
  - [x] 2.6 DO NOT add a Snackbar / Toast on cancel ("Call cancelled"). UX Decision §"Cross-cutting rules" point 5: "On cancel: close dialog, return to scenario list. No state change." A toast confirming the cancel is feature creep.

- [x] Task 3: Client — extend `ScenariosBloc` test fixtures? NO. (AC: regression scope check)
  - [x] 3.1 `scenarios_bloc_test.dart` already references `contentWarning: null` (line 21) and `contentWarning: 'violence'` (line 34) in its fixtures. NO changes needed — the bloc layer is unaware of the dialog gate (the gate lives in the screen, not in the state machine).
  - [x] 3.2 `scenarios_repository_test.dart` already exercises `'content_warning': null` and `'content_warning': 'violence'` envelope shapes (lines 35-79). NO changes needed.
  - [x] 3.3 `scenario_test.dart` already covers `contentWarning: null` parse + the `'violence'` parse (line 11, 27). NO changes needed.
  - [x] 3.4 If Story 5.3 has landed BEFORE this story (sprint order: 5-3 ready-for-dev, then 5-4 backlog), the bloc / repo test fixtures have ALREADY been widened to carry `CallUsage` — the fact that THEY didn't need touching here proves the gate is a clean separation of concerns. Confirm by running `flutter test test/features/scenarios/bloc/` after each change in this story.

- [x] Task 4: Client — widget tests for `showContentWarningDialog` (AC: 8)
  - [x] 4.1 Create `client/test/features/scenarios/views/widgets/content_warning_dialog_test.dart`:
    ```dart
    import 'package:client/core/theme/app_theme.dart';
    import 'package:client/features/scenarios/models/scenario.dart';
    import 'package:client/features/scenarios/views/widgets/content_warning_dialog.dart';
    import 'package:flutter/material.dart';
    import 'package:flutter_secure_storage/flutter_secure_storage.dart';
    import 'package:flutter_test/flutter_test.dart';

    Scenario _scenario({String? contentWarning = 'CW body 12345'}) {
      return Scenario(
        id: 's1',
        title: 'The Mugger',
        difficulty: 'hard',
        isFree: true,
        riveCharacter: 'mugger',
        languageFocus: const <String>[],
        contentWarning: contentWarning,
        bestScore: null,
        attempts: 0,
        tagline: 'Tagline',
      );
    }

    /// Renders a tiny harness whose body button calls
    /// `showContentWarningDialog` and stores the result. Tests assert on
    /// the result via the closure-captured `bool? capturedResult`.
    Future<({bool? Function() get, Future<void> Function() trigger})>
        _pumpHarness(
      WidgetTester tester, {
      required Scenario scenario,
    }) async {
      bool? captured;
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.dark(),
          home: Builder(
            builder: (ctx) => Scaffold(
              body: Center(
                child: ElevatedButton(
                  onPressed: () async {
                    captured = await showContentWarningDialog(ctx, scenario);
                  },
                  child: const Text('OPEN'),
                ),
              ),
            ),
          ),
        ),
      );
      return (
        get: () => captured,
        trigger: () async {
          await tester.tap(find.text('OPEN'));
          await tester.pumpAndSettle();
        },
      );
    }

    void main() {
      setUp(() {
        FlutterSecureStorage.setMockInitialValues({});
      });

      // ... 5 testWidgets blocks per AC8
    }
    ```
  - [x] 4.2 Each `testWidgets` MUST start with the 320×480 setSurfaceSize pattern (client/CLAUDE.md gotcha §7) — even though the dialog is centred and small, the body Text wrap behaviour at narrow widths is the whole point of UX-DR1's 320-px floor.
  - [x] 4.3 DO NOT use `pumpAndSettle()` to wait for `setUp` — only after the `tap('OPEN')` to flush the dialog enter animation. AlertDialog has a terminating animation (~150 ms); `pumpAndSettle` is safe here (client/CLAUDE.md gotcha §3 only blocks it for non-terminating animations like `CircularProgressIndicator`).
  - [x] 4.4 The barrier-dismiss test (#5) uses `tester.tapAt(const Offset(20, 20))` to hit the scrim corner. On a 320×480 viewport the dialog occupies the central ~280×140 box, so (20, 20) is unambiguously off-dialog. Then `await tester.pump()` (NOT `pumpAndSettle` — barrier tap with `barrierDismissible: false` produces zero animation, so `pumpAndSettle` would idle correctly but `pump` is more honest about the assertion: "after one frame, dialog is still here").
  - [x] 4.5 Assert button TEXT only — NOT button TYPE. The UX Decision spec is "Continuer" / "Revenir" verbatim; if a future story redesigns to FilledButton, the text is the contract, not the widget class.

- [x] Task 5: Client — extend `scenario_list_screen_test.dart` for the gate path (AC: 9)
  - [x] 5.1 In `client/test/features/scenarios/views/scenario_list_screen_test.dart`, widen the `_build` helper:
    ```dart
    Scenario _build({
      required String id,
      required String title,
      String tagline = 'Tagline',
      int? bestScore,
      int attempts = 0,
      String? contentWarning,           // NEW — defaults to null (existing behaviour)
    }) {
      return Scenario(
        id: id,
        title: title,
        difficulty: 'easy',
        isFree: true,
        riveCharacter: 'waiter',
        languageFocus: const <String>[],
        contentWarning: contentWarning,
        bestScore: bestScore,
        attempts: attempts,
        tagline: tagline,
      );
    }
    ```
  - [x] 5.2 Add the 4 new tests from AC9 — each one must:
    - Call `await tester.binding.setSurfaceSize(const Size(390, 844));` + `addTearDown(...)` (client/CLAUDE.md §7) — phone-sized so the `ListView` layouts as it does on real devices (no overflow, phone icon hittable).
    - Stub the bloc with `whenListen(... initialState: ScenariosLoaded([scenario]))` — same pattern as the existing `Loaded` test (line 117).
    - Use `await tester.pumpAndSettle()` after the icon tap — AlertDialog enter animation is terminating, so this is safe.
    - For tests #2 and #3 (Continuer / Revenir), tap `find.text('Continuer')` / `find.text('Revenir')` after the dialog opens.
  - [x] 5.3 If Story 5.3 has landed BEFORE this one: the existing `whenListen(..., initialState: ScenariosLoaded(scenarios))` calls become `ScenariosLoaded(scenarios, _kFreshUsage)` (5.3's widened ctor). Add the `const _kFreshUsage = CallUsage(tier: 'free', callsRemaining: 3, callsPerPeriod: 3, period: 'lifetime');` helper at the top of the file (Story 5.3 Task 13.5 establishes this exact helper name — adopt it for cross-story consistency). If Story 5.3 has NOT yet landed: leave the ctor at `ScenariosLoaded(scenarios)` and merge the widening when 5.3 ships. Either order is implementable; this story is independent.
  - [x] 5.4 The existing `'tapping the error area dispatches LoadScenariosEvent'` and the `'Loaded with 5 cards has no overflow at 320×480'` tests (lines 153, 202) MUST stay byte-for-byte identical (other than the `_kFreshUsage` widening from §5.3 if 5.3 has landed).
  - [x] 5.5 DO NOT add a `MockNavigatorObserver` or stub GoRouter further — the existing `/call` GoRoute (line 51-55) renders `Text('CALL_STUB')`. Asserting `find.text('CALL_STUB').findsNothing` (cancel) vs `findsOneWidget` (confirm) is sufficient to prove navigation correctness.

- [x] Task 6: Pre-commit validation gates (AC: 10)
  - [x] 6.1 `cd client && flutter analyze` → "No issues found!" — verify especially:
    - `Text('Continuer')` and `Text('Revenir')` MUST be `const Text(...)` (lint: `prefer_const_constructors` — client/CLAUDE.md §9)
    - `_onCallTap` returns `Future<void>` and any `_` private locals (e.g. `final _proceed = await ...`) drop the leading underscore (lint: `no_leading_underscores_for_local_identifiers` — client/CLAUDE.md §9)
    - The `if (!context.mounted) return;` guard between `await` and `context.go` (lint: `use_build_context_synchronously` — client/CLAUDE.md §9)
  - [x] 6.2 `cd client && flutter test` → "All tests passed!" — count the delta:
    - +5 tests in `content_warning_dialog_test.dart` (new file)
    - +4 tests in `scenario_list_screen_test.dart` (extended)
    - = +9 net tests; ALL pre-existing tests still green
  - [x] 6.3 `cd server && python -m ruff check .` → zero issues (Windows: `python -m ruff` per memory note)
  - [x] 6.4 `cd server && python -m ruff format --check .` → zero diffs
  - [x] 6.5 `cd server && pytest` → all green (this story ships zero server changes — `test_migrations.py` snapshot replay is unaffected; no fixture refresh needed)
  - [x] 6.6 Update `_bmad-output/implementation-artifacts/sprint-status.yaml`: `5-4-build-content-warning-display-for-intense-scenarios: backlog → in-progress` AT START, `in-progress → review` AT END. Memory rule (Epic 1 Retro Lesson + Sprint-Status Discipline): non-negotiable.
  - [x] 6.7 **DO NOT commit autonomously.** Memory rule (Git Commit Rules): wait for `/commit` or "commit ça". Dev workflow stops at `review` status.
  - [x] 6.8 NO Smoke Test Gate fill-in needed — this story is Flutter-client-only (no server endpoint touched, no DB migration, no VPS deploy). The Gate is server/DB/deploy-only per Epic 4 Retro AI-B + the create-story template's scope rule, and is correctly omitted from this story file.

## Dev Notes

### Scope Boundary (What This Story Does and Does NOT Do)

| In scope (this story) | Out of scope (later stories) |
|---|---|
| Material `AlertDialog` gate before `/call` navigation when `scenario.contentWarning != null` | A "don't show again" preference (UX Decision §"Cross-cutting rules" rejected this — re-shows on every tap) |
| `showContentWarningDialog` helper + 5 widget tests | Localization of "Continuer" / "Revenir" / dialog body — strings are French-only (UX Decision §Consequences "no localization") |
| `_onCallTap` async refactor + `if (!context.mounted)` guard | Briefing-screen content warning (briefing is read-only — no gate needed) |
| 4 new integration tests on `ScenarioListScreen` | Debrief-screen content warning (debrief is post-call — user already saw the warning) |
| FR38 fulfilment | Per-scenario warning tone variants ("Prendre l'appel" vs "Continuer") — deferred per UX Decision §Consequences |
| Pre-commit gate validation (analyze + test, both client and server) | Animated dialog entry / haptic on confirm — Material defaults are sufficient |

### Why a top-level free function (not a class with a static method)

Three reasons mirror Story 5.2's `buildCardDescriptionLabel` decision:

1. **Pure I/O at a single seam** — the function takes a `(BuildContext, Scenario)` and returns a `Future<bool>`. There's no internal state worth encapsulating. Wrapping it in a `class ContentWarningDialog { static Future<bool> show(...) ... }` is idiomatic Java, not Dart.
2. **Testability** — top-level functions are import-and-call. Static methods on a class need an extra `.show(...)` qualification at every call site for no benefit.
3. **Search-ability** — `grep showContentWarningDialog` lands on the definition + the (one) call site. A class wrapper adds `.show` noise to the grep output.

### Why no analytics / breadcrumb on cancel

UX Decision §"Cross-cutting rules" point 5 is "On cancel: close dialog, return to scenario list. No state change." A "user cancelled content warning for $scenario_id" event would:
- Leak a per-user behavioural signal (what kind of intense scenarios make the user back off) — privacy creep that would need GDPR review.
- Add an analytics dependency that doesn't exist yet (no `analytics_service.dart` in `lib/core/`). YAGNI per Walid's MVP iteration strategy.

If a future story (Epic 8 monetisation funnel?) needs cancel telemetry, that's the moment to introduce it.

### Why coerce `null → false` (not `null → true`) on `showDialog<bool>` result

`showDialog<bool>` resolves to `null` when:
1. The user presses the system back-button on Android (the only way out when `barrierDismissible: false`).
2. (Theoretical) The route is popped programmatically without a value.

Both outcomes are "user did NOT explicitly choose to proceed". The safety-conscious default is to treat them as cancel — `null → false`. The opposite (`null → true`) would mean "Android back-press auto-confirms an intense scenario" which is a UX disaster AND a data-protection concern (user might back-press by reflex without reading the body).

This is consistent with the rule: **the only path to `true` is an explicit tap on Continuer**.

### Why no theme override on the dialog itself

Material 3's `AlertDialog` reads its surface, divider, and shape tokens from `ThemeData.dialogTheme` — which is `null` on `AppTheme.dark()` (verified at `client/lib/core/theme/app_theme.dart:47-65`). The framework default falls back to `ColorScheme.surface` / `surfaceContainerHigh` derivations. The dialog renders dark on the dark scaffold, with the body and buttons inheriting from `TextTheme` and the `ColorScheme.primary` accent.

If a future UX iteration wants a specific dialog tint, the right move is to add a `dialogTheme: DialogTheme(backgroundColor: ..., titleTextStyle: ...)` block in `AppTheme.dark()` — NOT to override per-dialog. That refactor is out of scope here; the framework default is the UX Decision's stated baseline ("Material Dialog inherits from `ThemeData.dialogTheme` which is already wired").

### Tech Debt (must-track for `deferred-work.md`)

1. **No localisation** — strings "Continuer" and "Revenir" are hardcoded French. Acceptable today (project-wide policy: communication_language = French, document_output_language = English). When the app ships English copy, the dialog gets `AppLocalizations.of(context).contentWarningContinue` etc. UX Decision §Consequences explicitly accepts this debt.

2. **Generic confirm verb** — UX Decision §Consequences notes "«Continuer» is slightly generic — a future UX pass (post-MVP) may want a more scenario-specific verb per warning category (e.g. «Prendre l'appel»)." Defer to validate-fast-iterate-on-render strategy.

3. **No haptic on confirm** — Material default is silent. If user-test feedback shows the dialog is too easy to tap-through, add `HapticFeedback.heavyImpact()` on the Continuer onPressed. NOT a debt item today (no signal yet).

### What NOT to Do

1. **Do NOT add a `title:` argument to `AlertDialog`.** UX Decision §"Copy spec" line 23 is "no title". Adding "Avertissement" or "Contenu sensible" violates the spec.
2. **Do NOT add a "don't show again" checkbox or `SharedPreferences`-backed dismiss flag.** UX Decision §"Cross-cutting rules" point 3 is "No 'don't show again' option. The warning re-appears every time the user taps the card, even after successful calls."
3. **Do NOT use `barrierDismissible: true` (or omit the parameter — default is `true`).** UX Decision §"Cross-cutting rules" point 1 is `barrierDismissible: false`.
4. **Do NOT swap button order.** Secondary on the LEFT (Revenir), primary on the RIGHT (Continuer). Material convention. Reversing it would confuse muscle memory.
5. **Do NOT put the dialog logic inside the bloc.** The bloc is a pure data layer (Story 5.2 contract). The dialog is a screen-level concern — `ScenarioListScreen._onCallTap` is the right seam.
6. **Do NOT gate `_onCardTap` (briefing) or `_onReportTap` (debrief).** Briefing is pre-call read-only; debrief is post-call. The gate exists exclusively at the LiveKit-session threshold.
7. **Do NOT animate the dialog's appearance with a custom transition.** Material defaults are the spec.
8. **Do NOT log "user cancelled content warning" or any per-scenario behavioural event.** No analytics in scope.
9. **Do NOT add a Snackbar / Toast on cancel ("Call cancelled" / "Vous êtes revenu en arrière").** UX Decision §"Cross-cutting rules" point 5 — no state change on cancel.
10. **Do NOT hardcode any colour, padding, or text style** in `content_warning_dialog.dart`. Inherit from `Theme.of(context)` exclusively. `theme_tokens_test.dart` will fail the build otherwise (client/CLAUDE.md §6).
11. **Do NOT modify `Scenario` model or `ScenariosRepository`.** The `content_warning` field has been parsed and round-tripped since Story 5.1 — verified at `client/lib/features/scenarios/models/scenario.dart:37`. This story is purely additive view-layer code.
12. **Do NOT introduce a new dependency.** Material `AlertDialog` ships with `package:flutter/material.dart`. No `flutter_dialogs`, no `awesome_dialogs`, no `flutter_modal_actions`. `pubspec.yaml` stays untouched.
13. **Do NOT promote `showContentWarningDialog` to `lib/core/widgets/`.** It's scenarios-feature-specific. If Epic 7's debrief replay or Epic 8's paywall wants a similar gating dialog, refactor THEN. YAGNI now (matches Story 5.3 Task DO-NOT-#9).
14. **Do NOT add a `MockNavigatorObserver` or other navigation test harness.** Story 5.2's existing `/call` GoRoute stub (`scenario_list_screen_test.dart:51-55` rendering `Text('CALL_STUB')`) is the canonical pattern — assert on `find.text('CALL_STUB')` presence/absence.
15. **Do NOT skip `if (!context.mounted) return;`** between `await showContentWarningDialog` and `context.go(...)`. `flutter analyze` will flag `use_build_context_synchronously` and CI will fail (client/CLAUDE.md §9).
16. **Do NOT forget to update `sprint-status.yaml`** at start AND before review (Epic 1 Retro Lesson + Sprint-Status Discipline memory).
17. **Do NOT commit autonomously** — wait for `/commit` or "commit ça" (project memory: Git Commit Rules).
18. **Do NOT include a Smoke Test Gate in this story's review-handoff.** This story is Flutter-client-only. The Gate is server/DB/deploy-only per Epic 4 Retro AI-B + the template scope rule. Including it for this story would be a process-mistake; omitting it is the correct path.

### Library & Version Requirements

**No new server dependencies.** Server is unchanged.

**No new Flutter dependencies.** Everything is already in `pubspec.yaml`:
- `flutter` (Material 3 — `AlertDialog`, `showDialog`, `TextButton`, `ElevatedButton`)
- `flutter_bloc ^9.1.1` (existing — `BlocBuilder` / `BlocProvider` already in `ScenarioListScreen`)
- `go_router ^17.2.1` (existing — `context.go(AppRoutes.call, extra: scenario)`)
- `flutter_test` + `flutter_secure_storage ^10.0.0` (existing — test harness boilerplate)
- `bloc_test ^10.0.0` + `mocktail ^1.0.5` (existing — bloc test patterns from Story 5.2)

### Key Imports (exact — Epic 1 Retro Lesson: #1 velocity multiplier)

```dart
// client/lib/features/scenarios/views/widgets/content_warning_dialog.dart
import 'package:flutter/material.dart';

import '../../models/scenario.dart';
```

```dart
// client/lib/features/scenarios/views/scenario_list_screen.dart (additions)
import 'widgets/content_warning_dialog.dart';
```

```dart
// client/test/features/scenarios/views/widgets/content_warning_dialog_test.dart
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/views/widgets/content_warning_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
```

```dart
// client/test/features/scenarios/views/scenario_list_screen_test.dart (no new imports — _build helper widening only)
```

### Previous Story Intelligence

**From Story 5.2 (Scenario List Screen + ScenarioCard):**
- `ScenarioCard` exposes `onCallTap: VoidCallback` — the screen owns the tap routing. This story plugs the dialog gate INTO the screen's `_onCallTap`, not into the card. Card stays untouched.
- `ScenarioListScreen._List` uses `context.go(AppRoutes.call, extra: scenario)` (line 84) — preserve this exact navigation in the confirm branch.
- Test harness pattern: `MockBloc<ScenariosEvent, ScenariosState>` + `whenListen(... initialState: ScenariosLoaded(...))` + a tiny `GoRouter` with `/call` `/debrief/:id` `/briefing/:id` stubs (lines 40-78). The stub for `/call` renders `Text('CALL_STUB')` — assert on that text for navigation correctness in Task 5.
- The `_build()` helper at lines 19-38 hardcodes `contentWarning: null`. Widen it (Task 5.1) so individual tests can opt in to a content-warning scenario without breaking the existing 6 tests.
- 156 Flutter tests are green at Story 5.2 close — this story aims for ~165 with the +9 delta. ALL existing tests must stay green.
- `theme_tokens_test.dart` is the static enforcement test; running `flutter test test/core/theme/` after each new file proves AC6.
- `client/CLAUDE.md` §6: any new hex colour goes into `AppColors` or a parallel theme class — NEVER inline. The dialog inherits theme tokens, so this story adds ZERO new colours.

**From Story 5.3 (BottomOverlayCard + daily call limit) — AT THE TIME OF THIS WRITING IS `ready-for-dev`:**
- If 5.3 lands BEFORE this one (sprint order intent), `ScenariosLoaded` becomes `ScenariosLoaded(List<Scenario>, CallUsage)`. This story's tests on the screen pass `_kFreshUsage` to keep ctor calls compiling — Story 5.3 Task 13.5 establishes this exact helper name.
- If 5.4 lands BEFORE 5.3 (out-of-order, e.g. 5.3 hits a blocker): keep the ctor at `ScenariosLoaded(scenarios)` and merge the widening when 5.3 lands. Both orders are mechanically possible — the gate is functionally independent of the BOC.
- The post-review decision pattern from 5.2 (review notes carry forward in code comments — e.g. line 78 `// Navigation strategy (AC5, post-review decision 4 — 2026-04-27)`) is the convention for documenting deviations. Use `// AC1 — content_warning gate` style comments in `_onCallTap` if anything subtle slips in during review.

**From Story 5.1 (Scenarios API + DB):**
- `content_warning` is a nullable TEXT column on the `scenarios` table (migration `001_init.sql`, ADR 001). Already populated for 4 of 5 launch scenarios:
  - The Mugger: "This scenario simulates a threatening phone call. ..."
  - The Cop: "This scenario involves a police traffic stop. ..."
  - The Landlord: "This scenario involves a heated housing dispute. ..."
  - The Girlfriend: "This scenario involves an emotionally intense argument with a ..."
  - The Waiter: `null` (calibrated for near-guaranteed success — no warning needed)
- `ScenarioListItem.content_warning: str | None = None` is the Pydantic schema (`server/models/schemas.py:87`); `routes_scenarios.list_scenarios` round-trips it (`routes_scenarios.py:80`). NO server-side change needed for this story.
- `seed_scenarios.py:62-65` strips empty strings to `None` before insert — so the client never receives `""` masquerading as a non-null warning. The simple `scenario.contentWarning != null` guard is sufficient (no need for `!= null && trim().isNotEmpty`).

**From Story 4.5 (First-Call Incoming Call):**
- Async navigation with `if (!context.mounted) return;` guard pattern is established (likely in `incoming_call_screen.dart` or `incoming_call_bloc.dart` for the post-Accept transition). Mirror that exact pattern in `_onCallTap`.
- `flutter_secure_storage.setMockInitialValues({})` is in EVERY widget test — even when the test doesn't directly touch storage, the transitive dependencies (TokenStorage / ConsentStorage) crash without it (client/CLAUDE.md §1).

**From Epic 4 Retro (2026-04-23):**
- AI-E flagged "Story 5.4 has no UX spec for the dialog frame". RESOLVED on 2026-04-24 by `_bmad-output/planning-artifacts/ux-decisions/content-warning-dialog.md`. This story consumes that decision verbatim — zero open UX questions at kickoff.
- AI-A: client/CLAUDE.md gotchas are non-negotiable. §1 (FlutterSecureStorage), §3 (pumpAndSettle vs pump), §6 (no hex literals), §7 (setSurfaceSize), §9 (lints) all apply here.
- Walid's MVP iteration strategy (`feedback_mvp_iteration_strategy.md`): build the straight-line story, iterate on render. The dialog's exact micro-copy is locked by UX Decision; render decisions (button shape, padding, animation) defer to Walid's review iteration after dev-story lands.

**From Epic 5 ADRs (2026-04-23):**
- ADR 001 — Scenarios Schema: `content_warning` is `TEXT NULL` on the `scenarios` table; Pydantic boundary enforces `str | None`.
- ADR 002 — Tier Naming (`'paid'` canonical): orthogonal to this story (the gate fires for `tier='free'` AND `tier='paid'` — content warnings are content-driven, not tier-driven).

### Git Intelligence

Recent commit pattern to follow:
```
00abe11 feat: Story 5.2 scenarios list screen + post-review fixes
05295fb feat: 5.1-migration-guardrail harden snapshot sanitisation + self-checks
8c9b9a9 fix: 5.1-CI-deploy harden setup-vps pubkey path + bridge .env strip
7534818 feat: Story 5.1 scenarios API + 5.1-CI-deploy pipeline
4ac116a feat: 5.1-CI-deploy: point pipecat.service at atomic release symlink
```

Expected commit title when Walid says "commit ça":
```
feat: build content warning dialog for intense scenarios (Story 5.4)
```

Expected commit body (per CLAUDE.md format rules — bulleted list, verb-first, no Co-Authored-By):
```
- Add showContentWarningDialog helper with Continuer/Revenir buttons
- Wire AlertDialog gate into ScenarioListScreen._onCallTap
- Add 5 widget tests for the dialog (4 branches + barrier-dismiss)
- Add 4 list-screen tests for warning vs no-warning navigation paths
- Update sprint-status.yaml: 5-4 → review (n total Flutter tests passing)
```

**Files to read before starting (patterns, not modify beyond tasks):**
- `client/CLAUDE.md` — Flutter Gotchas §1-10. READ FIRST. §1, §3, §6, §7, §9 are the directly relevant gates.
- `_bmad-output/planning-artifacts/ux-decisions/content-warning-dialog.md` — THE canonical UX spec for this story. Every copy / behavior decision is here.
- `_bmad-output/planning-artifacts/epics.md:977-999` — Story 5.4 BDD source.
- `_bmad-output/implementation-artifacts/5-2-build-scenario-list-screen-with-scenariocard-component.md` — `ScenarioListScreen` shape, `_onCallTap` definition, GoRouter test stub pattern (THIS STORY MODIFIES files Story 5.2 creates — read both).
- `_bmad-output/implementation-artifacts/5-1-build-scenarios-api-and-database.md` — `content_warning` round-trip on `GET /scenarios`, `seed_scenarios.py` empty-string normalisation.
- `_bmad-output/planning-artifacts/architecture.md` line 247 — `scenarios.content_warning` column spec; line 1010 — FR38 traceability.
- `_bmad-output/planning-artifacts/adr/001-scenarios-schema.md` — `content_warning` nullable rationale.
- `client/lib/features/scenarios/models/scenario.dart` — `Scenario.contentWarning` field (already there).
- `client/lib/features/scenarios/views/scenario_list_screen.dart` — `_onCallTap` to gate (line 83).
- `client/lib/features/scenarios/views/widgets/scenario_card.dart` — `onCallTap` callback signature (line 50, 64-92).
- `client/lib/core/theme/app_theme.dart` — `AppTheme.dark()` provides every token the dialog inherits (line 41-65).
- `client/test/features/scenarios/views/scenario_list_screen_test.dart` — `_build` helper to widen (line 19-38), GoRouter test stubs (line 40-78).

### Testing Requirements

**Server target:** ZERO new Python tests. The `/scenarios` endpoint already round-trips `content_warning` (Story 5.1 covers it).

**Client target:** +9 new Dart tests + +0 net edits to existing tests (only the `_build` helper signature widens — pure additive, default value preserves existing behavior).

| File | Count | Scope |
|---|---|---|
| `content_warning_dialog_test.dart` (NEW) | 5 | body verbatim + no title slot + Continuer→true + Revenir→false + barrier-dismiss-blocked |
| `scenario_list_screen_test.dart` (additions) | 4 | dialog shows for warning-present + Continuer→/call + Revenir→list + no-warning bypasses dialog |

**Mock strategy:**
- **Bloc mocking** in `scenario_list_screen_test.dart`: `MockBloc<ScenariosEvent, ScenariosState>` + `whenListen(... initialState: ScenariosLoaded(...))` — same pattern as Story 5.2 lines 16-17, 99-104.
- **No mocks needed** in `content_warning_dialog_test.dart` — pure widget test of a stateless function. The harness wraps the function in a `Builder` so a real `BuildContext` is passed.
- **GoRouter test stub** for `/call` already exists in `scenario_list_screen_test.dart` lines 51-55 (`Text('CALL_STUB')`). REUSE — no new stub needed.
- **NO `MockNavigatorObserver`** — assertion on `find.text('CALL_STUB')` presence/absence is the navigation contract.

**Harness helpers:**
- The `_pumpHarness` record-returning helper in `content_warning_dialog_test.dart` (Task 4.1 sketch) keeps each `testWidgets` body short. Returns a `({bool? Function() get, Future<void> Function() trigger})` record so tests do `final h = await _pumpHarness(tester, scenario: ...); await h.trigger(); expect(h.get(), isTrue);`.

### Project Structure Notes

**New files (create):**
```
client/lib/features/scenarios/views/widgets/
└── content_warning_dialog.dart                    # showContentWarningDialog helper

client/test/features/scenarios/views/widgets/
└── content_warning_dialog_test.dart               # 5 widget tests
```

**Files to modify (client only):**
- `client/lib/features/scenarios/views/scenario_list_screen.dart` — `_onCallTap` async refactor + dialog gate + import
- `client/test/features/scenarios/views/scenario_list_screen_test.dart` — `_build` helper widening + 4 new tests

**Files to verify but DO NOT modify:**
- `client/lib/features/scenarios/models/scenario.dart` — `Scenario.contentWarning` already present (line 10)
- `client/lib/features/scenarios/repositories/scenarios_repository.dart` — already round-trips `content_warning` via `Scenario.fromJson`
- `client/lib/features/scenarios/bloc/scenarios_state.dart` — bloc/state/event layer is unaware of the dialog
- `client/lib/features/scenarios/views/widgets/scenario_card.dart` — `onCallTap` callback signature unchanged
- `client/lib/core/theme/app_colors.dart` — NO new colour token; dialog inherits theme
- `client/lib/core/theme/app_theme.dart` — NO new `dialogTheme` block; framework defaults are spec-compliant
- `client/lib/app/router.dart` — NO new route; `/call` already exists
- `client/pubspec.yaml` — NO new dependency
- `server/**` — entire backend untouched
- `_bmad-output/planning-artifacts/architecture.md` — unchanged
- `server/db/migrations/*.sql` — IMMUTABLE (no new migration)
- `server/tests/test_migrations.py` + `tests/fixtures/prod_snapshot.sqlite` — replay-against-snapshot still passes (no schema change shipped)

### References

- [Source: `_bmad-output/planning-artifacts/epics.md:977-999`] — Story 5.4 BDD acceptance criteria
- [Source: `_bmad-output/planning-artifacts/epics.md#FR38`] (line 277) — content warnings before threat/confrontation scenarios
- [Source: `_bmad-output/planning-artifacts/ux-decisions/content-warning-dialog.md`] — THE canonical UX frame: title=none, body=`scenario.content_warning`, primary=Continuer, secondary=Revenir, `barrierDismissible: false`, no don't-show-again, button order
- [Source: `_bmad-output/planning-artifacts/architecture.md:247`] — `scenarios` table: `content_warning` nullable TEXT, populated from YAML at deploy
- [Source: `_bmad-output/planning-artifacts/architecture.md:1010`] — FR38 traceability ("`content_warning` field added to scenarios")
- [Source: `_bmad-output/planning-artifacts/adr/001-scenarios-schema.md`] — `content_warning` column nullability and stored format
- [Source: `_bmad-output/implementation-artifacts/5-1-build-scenarios-api-and-database.md`] — `content_warning` round-trip on `GET /scenarios`, server-side normalisation in `seed_scenarios.py`
- [Source: `_bmad-output/implementation-artifacts/5-2-build-scenario-list-screen-with-scenariocard-component.md`] — `ScenarioListScreen._onCallTap` gateway, `_build()` test helper pattern (this story extends both)
- [Source: `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-23.md#AI-E`] — flagged Story 5.4 needed UX-side resolution; resolved 2026-04-24 by the UX Decision doc above
- [Source: `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-23.md#AI-A`] — `client/CLAUDE.md` Flutter gotchas
- [Source: `client/CLAUDE.md`] — 10 Flutter gotchas (especially §1, §3, §6, §7, §9)
- [Source: `client/lib/features/scenarios/models/scenario.dart:10`] — `Scenario.contentWarning` field
- [Source: `client/lib/features/scenarios/views/scenario_list_screen.dart:83-85`] — `_onCallTap` pre-modification
- [Source: `client/lib/core/theme/app_theme.dart:41-65`] — `AppTheme.dark()` token wiring (the dialog inherits from here)
- [Source: `server/models/schemas.py:87`] — `ScenarioListItem.content_warning: str | None = None`
- [Source: `server/api/routes_scenarios.py:80`] — `content_warning` round-trip in list endpoint
- [Source: `server/db/seed_scenarios.py:62-65`] — empty-string-to-None normalisation at seed time
- [Source: `CLAUDE.md`] — pre-commit gates + commit message format (bulleted list, no Co-Authored-By)
- [Source: project memory `feedback_mvp_iteration_strategy.md`] — straight-line story, iterate on render
- [Source: project memory (Git Commit Rules)] — NEVER autonomous commit, no Co-Authored-By, sprint-status discipline

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (Claude Code, bmad-dev-story workflow)

### Debug Log References

- `flutter analyze` → No issues found! (16.8s after Figma redesign pass)
- `flutter test` → All tests passed! (187 total — +10 net delta after the redesign: +6 sheet widget + +4 list-screen integration)
- `python -m ruff check .` → All checks passed!
- `python -m ruff format --check .` → 45 files already formatted
- `python -m pytest` → 145 passed (server unchanged, snapshot replay green)

### Completion Notes List

- `showContentWarningDialog` shipped as a top-level free function in `content_warning_dialog.dart`. Asserts non-null `contentWarning` at entry; coerces `null → false` so swipe-down, scrim tap, and Android back-press cannot auto-confirm.
- **Visual frame pivoted from `AlertDialog` to `showModalBottomSheet`** matching the Figma "iPhone 16 - 7" mock (`C:\Users\gueta\Documents\figma-export\.figma\iphone-16-7\reference.png`): drag handle, "HEADS UP" pill, static title "Buckle up", per-scenario body (`scenario.contentWarning`), italic disclaimer "You can hang up anytime", and the two-button row (Not now / Pick up). This is a spec deviation from the original AC2 ("no title slot") + the UX Decision doc — the new design supersedes both. AC2/AC5/AC8/AC9 wording in this file is left as-historical-record; the implementation matches the Figma mock and is the new canonical visual.
- 2 new color tokens promoted into `AppColors`: `headsUpBg = #F5FFAD` (pale yellow), `headsUpAccent = #8F8621` (dark olive). `theme_tokens_test.dart` updated from 10 → 12 tokens. Zero hex literals outside `lib/core/theme/`.
- Bottom sheet behavior: `isDismissible: true` (tap on scrim → null → coerced to false) + `enableDrag: true` (swipe down → null → false). Both spelled out explicitly so the dismiss contract is the API.
- `ScenarioListScreen._onCallTap` is now `Future<void>`; gates only when `scenario.contentWarning != null`, with the mandatory `if (!context.mounted) return;` guard between `await` and `context.go`. Briefing (`_onCardTap`) and debrief (`_onReportTap`) are NOT gated, per AC1.
- Action row uses `Wrap` (not `Row`) so the buttons gracefully fall to a second line when tests run with the fallback font (Inter not loaded in widget tests, fallback metrics are wider). On a real device with Inter loaded, buttons sit on a single line.
- Test deltas after redesign: 6 widget tests (body verbatim + static frame, shield+phone icons, Pick up→true, Not now→false, scrim tap→false, swipe down→false) + 4 list-screen tests (sheet shows for warning, Pick up→/call, Not now→list, no-warning bypass).
- Pre-commit gates all green. NOT auto-committed per project memory rule — awaiting `/commit` or "commit ça" from Walid.

### ⚠️ Spec deviations the reviewer must consciously accept or reject

The implementation departs from the originally-accepted spec in four places. Each was a deliberate, Walid-driven design call after the AC freeze; they are listed here so the reviewer evaluates the *current* code against the *current* design intent (the Figma mock + Walid's verbal direction), not against the now-stale text.

1. **AC2 — "no title slot"** is contradicted: the sheet now carries a static **"Buckle up"** title (24/Bold) above the per-scenario body. The body is still rendered verbatim from `scenario.contentWarning`.
2. **AC2 — "secondary on the LEFT (Revenir), primary on the RIGHT (Continuer)"** copy is replaced by **"Not now"** / **"Pick up"** (per the Figma mock). Order preserved: secondary left, primary right.
3. **AC2 — `barrierDismissible: false`** is replaced by `showModalBottomSheet` with `isDismissible: true` + `enableDrag: true`. Walid explicitly requested swipe-down + tap-outside both behave as cancel (returning `false`). Safety property is preserved: only an explicit "Pick up" tap ever resolves to `true`.
4. **AC8/AC9 wording (Continuer/Revenir, AlertDialog assertions)**: the corresponding tests now assert against "Pick up" / "Not now" / "Buckle up" and the bottom-sheet widget tree. Test count grew from the +9 planned to +10 net (the extra test covers the new swipe-down dismiss behavior).
5. **AC10 — "ZERO server changes"** is contradicted: 4 scenario YAML files (`server/pipeline/scenarios/the-cop.yaml`, `the-girlfriend.yaml`, `the-landlord.yaml`, `the-mugger.yaml`) had their `content_warning` copy tightened by Walid in a manual pass for the new sheet's tighter visual budget. The change drops some safety-explicit phrasing (e.g. "No abusive language is used" → "No insults — just a real argument."). Code-review accepted (option **a** on 2026-04-29) — softened copy is the new canonical. Next deploy will overwrite the live `content_warning` rows for these 4 scenarios via `seed_scenarios.py`. No DB schema change, no migration, no snapshot refresh needed.

The **UX Decision doc** (`_bmad-output/planning-artifacts/ux-decisions/content-warning-dialog.md`, accepted 2026-04-24) is now stale on points 1, 2, 3 above. The reviewer should either bless the new mock as canonical and either delete or supersede that doc, OR push back on the redesign. Recommended path: accept (Walid drove the change with a concrete Figma extract + verbal alignment); update the doc as a follow-up housekeeping commit.

### File List

**Created:**
- `client/lib/features/scenarios/views/widgets/content_warning_dialog.dart`
- `client/test/features/scenarios/views/widgets/content_warning_dialog_test.dart`

**Modified:**
- `client/lib/core/theme/app_colors.dart` — added `headsUpBg` + `headsUpAccent`; `values` list grew 10 → 12
- `client/lib/features/scenarios/views/scenario_list_screen.dart` — `_onCallTap` async refactor + sheet gate + `widgets/content_warning_dialog.dart` import
- `client/test/core/theme/theme_tokens_test.dart` — updated count assertion + 2 new hex assertions
- `client/test/features/scenarios/views/scenario_list_screen_test.dart` — `_build` helper widened with `String? contentWarning`; +4 integration tests for the gate
- `server/pipeline/scenarios/the-mugger.yaml`, `the-cop.yaml`, `the-landlord.yaml`, `the-girlfriend.yaml` — `content_warning` copy tightened (Walid manual pass) for the new sheet's tighter visual budget
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `5-4` flipped to `in-progress` at start, `review` at end; `last_updated` bumped

### Change Log

| Date | Story | Author | Notes |
|---|---|---|---|
| 2026-04-28 | 5.4 | walid (dev-story) | Initial implementation: AlertDialog gate + 5 widget tests + 4 integration tests. Status → review. |
| 2026-04-28 | 5.4 | walid (dev-story, redesign pass) | Pivoted to `showModalBottomSheet` matching the Figma "iPhone 16 - 7" mock. New chrome: drag handle, "HEADS UP" pill, "Buckle up" title, italic "You can hang up anytime" disclaimer, Not now / Pick up buttons. Added `headsUpBg` + `headsUpAccent` color tokens. +1 test (swipe-down). All gates green: flutter analyze + flutter test 187/187 + ruff + pytest 145/145. |
| 2026-04-28 | 5.4 | walid (dev-story, layout polish) | Right-aligned the action row (`SizedBox(width: double.infinity)` + `WrapAlignment.end`); bumped pre-action gap 15 → 31px; tightened HEADS UP icon↔label gap 10 → 6px. |
| 2026-04-28 | 5.4 | walid (dev-story, color swap) | HEADS UP palette swapped from red (#FFD8D8 / #C03A3A) to pale yellow + dark olive (#F5FFAD / #8F8621) per Walid's call. `theme_tokens_test.dart` synced. |

### Review Findings

- [x] [Review][Decision] Server YAML scope leak + safety phrasing weakened — resolved 2026-04-29 option (a): keep softened copy, declare as deviation #5 in the spec deviations section above. No code change.
- [x] [Review][Decision] Spec deviation #3 side-effect (scrim-tap auto-cancel) — resolved 2026-04-29 option (a): accept the eased behavior. Walid drove the change; safety property (`null → false`) preserved. No code change.
- [x] [Review][Decision] Stale "dialog" naming — resolved 2026-04-29 option (a): rename cascade applied. `content_warning_dialog.dart` → `content_warning_sheet.dart`, `showContentWarningDialog` → `showContentWarningSheet`, comment in `_onCallTap` updated, UX doc marked Superseded.

- [x] [Review][Patch] AC7 contradiction — `tapTargetSize: shrinkWrap` + `minimumSize: Size.zero` removed from both TextButton and ElevatedButton style blocks. [client/lib/features/scenarios/views/widgets/content_warning_sheet.dart]
- [x] [Review][Patch] Release-build crash potential — assert + `!` replaced with early-return `if (cw == null) return false;`; `_ContentWarningSheet` now takes a non-nullable `String contentWarning` instead of the full `Scenario`. [client/lib/features/scenarios/views/widgets/content_warning_sheet.dart:17-43]
- [x] [Review][Patch] AC7 not covered by any test — added widget test "sheet wraps without overflow at 320x480 + textScaler 1.5". The test surfaced a real overflow bug (390 px vertical overflow at the spec-mandated bound); fixed by wrapping the inner `Column` in `SingleChildScrollView`. [client/test/features/scenarios/views/widgets/content_warning_sheet_test.dart + content_warning_sheet.dart]
- [x] [Review][Patch] No scrim-dismiss test at the screen-integration level — added "tapping the scrim outside the sheet returns to the list with no navigation". [client/test/features/scenarios/views/scenario_list_screen_test.dart]

- [x] [Review][Defer] Hardcoded layout literals bypass AppSpacing/AppTypography tokens — fontSize 24/14/12, height ratios 29/24, padding 36/24/15/31, radii 42/18/999 are inlined throughout `content_warning_dialog.dart`. AC6 hex-only test stays green, but Story 5.3 established `AppSpacing` for exactly this reason. Cross-cutting design-token pass. [content_warning_dialog.dart] — deferred, design system follow-up
- [x] [Review][Defer] Rapid double-tap on phone icon → two sheets queued — `_onCallTap` is now async with no re-entry guard. Realistic risk: low (Flutter's modal route generally swallows taps during transition), but no debounce. Fix has design implications (StatefulWidget + busy flag, or disable the icon while gate is in-flight). [scenario_list_screen.dart:138-148] — deferred, concurrency edge
- [x] [Review][Defer] Daily call limit mid-dialog bypass — if the daily-call counter (Story 5.3 BOC gate) exhausts while the sheet is open, "Pick up" still navigates to /call. Theoretical (only completing a call exhausts the counter, which dismounts this screen). [scenario_list_screen.dart:138-148] — deferred, theoretical concurrency with Story 5.3
- [x] [Review][Defer] RTL locale — `WrapAlignment.end` aligns to left edge under Arabic/Hebrew. No-op today (project is French-only per memory + Dev Notes "no localization"). Track when localisation lands. [content_warning_dialog.dart:208] — deferred, no localization in MVP
- [x] [Review][Defer] Android back-press / drag-down dismissal path untested — `?? false` coercion at line 42 handles the null-result case, but no test pumps a back-press or full-distance drag to verify the resolved value is `false`. [content_warning_dialog_test.dart] — deferred, handled by coercion but unverified
- [x] [Review][Defer] AA contrast claim unverified by test — `app_colors.dart` comment claims `headsUpAccent on headsUpBg ≈ 4.6:1`. `#8F8621` on `#F5FFAD` actually computes around 4.0-4.5:1 depending on tool — borderline AA-large. No automated test guards the ratio. [client/lib/core/theme/app_colors.dart:43] — deferred, contrast claim drift target
