# Story 5.5: Refactor Scenario List Error Screen with Empathetic UX

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user whose scenario list fails to load (network drop, server hiccup, malformed payload),
I want the app to explain what's happening in human terms with a clear way to recover,
so that I don't feel punished or confused when something goes wrong outside my control.

## Background

Story 5.2 shipped `_ErrorView` (`scenario_list_screen.dart:137-175`) with two problems surfaced during 2026-04-28 UX review:

1. **Single generic copy** — every failure path collapses into either the raw `ApiException.message` (which can be a developer-facing string like `"Unexpected response. Please try again."` from the bloc's catch-all at `scenarios_bloc.dart:36`) or a server-provided string of unknown shape. The user sees no distinction between "your phone is offline" and "our JSON parser crashed".
2. **Punitive visual treatment** — the title renders in `AppColors.destructive` (the red reserved for irreversible actions) and the retry affordance is a 12px caption labelled `"Tap to retry"` in `AppColors.textSecondary`. The screen reads as an alarm, not a pause.

The convention layer (`feedback_error_ux.md`, `client/CLAUDE.md` rule §10) is unchanged: inline `Text` only — no snackbar, no toast, no dialog. This story refines the inline pattern, it does not move away from it.

## Acceptance Criteria (BDD)

**AC1 — `ScenariosError` carries a stable error class and a retry counter:**
Given the current `final class ScenariosError extends ScenariosState { final String message; }` (`scenarios_state.dart:23-26`)
When this story lands
Then `ScenariosError` is widened to `final class ScenariosError extends ScenariosState { final String code; final int retryCount; const ScenariosError({required this.code, required this.retryCount}); }`:
  - `code` is one of the canonical literals: `'NETWORK_ERROR'`, `'SERVER_ERROR'`, `'MALFORMED_RESPONSE'`, `'UNKNOWN_ERROR'` (no `String?` — every emission picks a class)
  - `retryCount` starts at `0` for the first failure and increments by `1` each subsequent consecutive failure (resets to `0` on any `ScenariosLoaded` emission)
  - the `message` field is REMOVED — copy now lives in the view, keyed by `code` (AC4); the bloc no longer ferries user-facing strings
And the `const` ctor stays, the field is `final`, no `Equatable`/`copyWith` (same conventions as `Scenario` / `CallUsage`)
And every existing test in `scenarios_bloc_test.dart` and `scenario_list_screen_test.dart` that asserts on `ScenariosError(<message string>)` is updated to assert on the new shape (no orphan tests).

**AC2 — Bloc maps failure source → canonical `code` and tracks consecutive retries:**
Given `ScenariosBloc._onLoad` (`scenarios_bloc.dart:15-39`) currently catches `ApiException` (passes the message through) and a bare `catch (_)` (emits the hardcoded "Unexpected response" string)
When this story lands
Then the catch arms map to the new code surface:
  - `on ApiException catch (e) where e.code == 'NETWORK_ERROR'` → `ScenariosError(code: 'NETWORK_ERROR', retryCount: <next>)`
  - `on ApiException catch (e) where e.code starts with '5' OR e.code == 'SERVER_ERROR'` → `ScenariosError(code: 'SERVER_ERROR', retryCount: <next>)` *(see Dev Notes → 5xx detection — the server's structured error envelope today does NOT use HTTP-numeric codes; we treat any non-`NETWORK_ERROR` `ApiException` whose code starts with `'5'` literal OR equals `'SERVER_ERROR'` as server-class. Anything else falls to `UNKNOWN_ERROR`.)*
  - `on ApiException catch (_)` (any other code, including `'UNKNOWN_ERROR'`, `'UNAUTHORIZED'`, server-defined codes) → `ScenariosError(code: 'UNKNOWN_ERROR', retryCount: <next>)`
  - bare `catch (_)` (TypeError / FormatException / cast failures from `Scenario.fromJson` or `CallUsage.fromMeta`) → `ScenariosError(code: 'MALFORMED_RESPONSE', retryCount: <next>)`
And `<next>` is computed as `state is ScenariosError ? (state as ScenariosError).retryCount + 1 : 0` BEFORE the state transitions through `ScenariosLoading` — captured at the top of `_onLoad` so the increment survives the loading emit
And the existing in-flight guard at `scenarios_bloc.dart:22` (`if (state is ScenariosLoading) return;`) is preserved verbatim — concurrent retry suppression is unchanged.

**AC3 — `_ErrorView` is a pure function of `(code, retryCount)`:**
Given the rewritten `_ErrorView` widget in `scenario_list_screen.dart`
When the bloc emits `ScenariosError(code: ..., retryCount: ...)`
Then the view's constructor signature is `_ErrorView({required this.code, required this.retryCount})` (no `message` parameter — internalised)
And the build output is composed of:
  1. an `Icon` chosen from the code → icon table in AC5
  2. a primary `Text` (title) chosen from the code → title table in AC4
  3. a secondary `Text` (body) chosen from the code → body table in AC4 (or the repeat-failure variant when `retryCount >= 1`)
  4. ~~a primary action: `ElevatedButton` labelled `"Try again"` (exact English string per `document_output_language: English`)~~ **AMENDED 2026-04-29 (review)** per Figma redesign + onboarding harmonisation: a primary action is a full-width `SizedBox(height: 64)` containing a `FilledButton` with `backgroundColor: AppColors.accent` and `RoundedRectangleBorder(borderRadius: BorderRadius.circular(32))`. The button child is `FittedBox(fit: BoxFit.scaleDown, child: Row(mainAxisSize: MainAxisSize.min, ...))` containing `Icon(Icons.refresh, size: 24, color: AppColors.background)` + `SizedBox(width: 10)` + `Text('Try again', style: TextStyle(fontFamily: AppTypography.fontFamily, fontSize: 17, fontWeight: FontWeight.w700, color: AppColors.background))`. Locked label string `'Try again'` is preserved.
  5. ~~the existing full-area `GestureDetector(behavior: HitTestBehavior.opaque)` wrapper kept as a power-user hit-target (AC3 of Story 5.2 post-review decision 6 — preserved)~~ **AMENDED 2026-04-29 (review):** full-area `GestureDetector` REMOVED. With the discoverable accent-green CTA pinned at the bottom, the redundant full-area tap was a foot-gun (could fire on scroll-to-end gestures or stray taps while reading body copy). Retry is button-only. Story 5.2 post-review decision 6 is reversed for this screen.
~~And the `GestureDetector` and the `ElevatedButton` BOTH dispatch the same `LoadScenariosEvent`~~ The `ElevatedButton` is the sole retry surface; tapping it re-enters the loading path.

**AC4 — Code → copy table (English, locked):**
Given UX review 2026-04-28
When `_ErrorView` renders
Then it MUST use this exact copy keyed by `code` — no near-miss strings, no rephrasing without a UX-decision update:

| `code` | First failure (`retryCount == 0`) — title | First failure — body | Repeat failure (`retryCount >= 1`) — body override |
|---|---|---|---|
| `NETWORK_ERROR` | `"You're offline."` | `"We need a connection to load your scenarios. Check your Wi-Fi or mobile data, then try again."` | `"Still no signal. Move somewhere with better reception, then try again."` |
| `SERVER_ERROR` | `"Our servers are catching their breath."` | `"This is on us, not you. Try again in a moment."` | `"Still struggling on our side. Give it a minute and try again, or restart the app if it persists."` |
| `MALFORMED_RESPONSE` | `"Something didn't load right."` | `"We've logged the issue. Try again — it usually works on the second try."` | `"Still stuck. Restart the app to clear the slate."` |
| `UNKNOWN_ERROR` | `"Something went wrong."` | `"We're not sure what happened. Try again in a moment."` | `"Still failing. Restart the app if this keeps happening."` |

And the title NEVER changes between first and repeat failure — only the body shifts to the repeat-failure variant when `retryCount >= 1`
And the title is rendered in `AppColors.textPrimary` (NOT `AppColors.destructive` — the red is reclaimed for irreversible actions only)
~~And the body is rendered in `AppColors.textSecondary` at `AppTypography.body` size (not `caption`).~~ **AMENDED 2026-04-29 (review)** per Figma `iphone-16-8` redesign:
  - title (per-code, e.g. `"You're offline."`) is rendered in `AppColors.textPrimary` at inline `TextStyle(fontFamily: AppTypography.fontFamily, fontSize: 24, fontWeight: FontWeight.w700)` — promoted to "subtitle" slot beneath a new common hero
  - body is rendered in NEW token `AppColors.errorBody` (#D8D8D8) at inline `TextStyle(fontFamily: AppTypography.fontFamily, fontSize: 14, fontWeight: FontWeight.w400)` — brighter than `textSecondary` for multi-line readability
  - NEW common hero `HOLD ON` (string locked) renders ABOVE every per-code title in `TextStyle(fontFamily: 'Frijole', fontSize: 40)` on `AppColors.textPrimary` — the "something happened, take a breath" register, identical for all four codes
  - NEW accent badge `· HEADS UP ·` (string locked) renders BETWEEN the icon badge and `HOLD ON` in `TextStyle(fontFamily: AppTypography.fontFamily, fontSize: 12, fontWeight: FontWeight.w400)` on `AppColors.accent`, flanked by two 2-px dots
  - precedent: `consent_screen.dart` and `email_entry_screen.dart` already inline Frijole + Inter `TextStyle`s for one-shot screen-specific typography. Promoting these to `AppTypography` would force a UX-DR2 amendment for single-use styles.

**AC5 — Code → icon table:**
Given Material's icon set
When `_ErrorView` renders the icon
Then it MUST use this exact mapping — `Icon(<icon>, size: 64, color: AppColors.textSecondary)`:

| `code` | Icon |
|---|---|
| `NETWORK_ERROR` | `Icons.cloud_off_outlined` |
| `SERVER_ERROR` | `Icons.hourglass_empty_outlined` |
| `MALFORMED_RESPONSE` | `Icons.help_outline` |
| `UNKNOWN_ERROR` | `Icons.error_outline` |

And the icon tint is `AppColors.textSecondary` (unchanged)
~~And the icon size constant is inlined as `64.0` literal at the call site — small enough that promoting to a token is over-engineering; if a second view ever uses a 64-px icon, that's the moment to extract.~~ **AMENDED 2026-04-29 (review)** per Figma redesign:
  - icon renders inside a NEW private `_IconBadge` widget — a 105×105 circular `Container` with `color: AppColors.textSecondary.withValues(alpha: 0.1)` fill and `Border.all(color: AppColors.textSecondary.withValues(alpha: 0.3), width: 1)` stroke
  - the inner `Icon` size is `41` (literal), color `AppColors.textSecondary` — derived alpha tones do not warrant new tokens
  - `_IconBadge` is private to `scenario_list_screen.dart`; not exported, not reusable across files

**AC6 — Vertical rhythm using existing `AppSpacing` tokens:**
~~Given `AppSpacing` (`app_spacing.dart` per Story 4.1b) is the single spacing source of truth
When `_ErrorView` lays out the column
Then the children stack with this rhythm — all gaps use existing tokens, NO new `AppSpacing.*` constants are added:
  - icon → title gap: `AppSpacing.base` (or the closest existing token to ~16px — pick from what's already there)
  - title → body gap: `AppSpacing.base` (or closest)
  - body → button gap: `AppSpacing.base * 1.5` rounded to the nearest existing token (or two stacked `AppSpacing.base` widgets if no 24-class token exists)
And the column is centred via `Center` + `Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.center)` — same envelope as today
And `Text(..., textAlign: TextAlign.center)` is set on both the title and the body so multi-line copy stays centred under the icon.~~ **AMENDED 2026-04-29 (review)** per Figma `iphone-16-8` redesign — Figma pixels do not align cleanly to `AppSpacing.base * N`, so the redesign ships:
  - vertical gaps: raw integer literals matching the Figma reference — `SizedBox(height: 36)` (top), `SizedBox(height: 20)` (badge → HOLD ON), `SizedBox(height: 10)` (title → body)
  - button container: `Padding(EdgeInsets.fromLTRB(10, 10, 10, 30))` (raw literals; 30-px bottom lifts the button above the home-indicator inset)
  - badge internals: `SizedBox(width: 5)` flanking the dots, `SizedBox(width: 10)` between icon and label inside the button
  - **NEW token added:** `AppSpacing.screenHorizontalErrorView = 36.0` (asserted in `theme_tokens_test.dart`). The error screen wants more breathing room than `screenHorizontalScenarioList` (18) so the wrap doesn't feel cramped under longer copy.
  - `crossAxisAlignment: stretch` is used at the column level so the title/body left-align to the 36-px gutter (Figma reference). `textAlign: TextAlign.center` is intentionally NOT set on title or body — the Figma redesign is left-aligned by design (multi-line body wraps within the gutter; the locked copy strings stay readable as a left-aligned paragraph rather than a centred mono-line). The original AC6 clause "`Text(..., textAlign: TextAlign.center)` is set on both the title and the body" is hereby withdrawn.

**AC7 — `BottomOverlayCard` stays hidden during error states:**
Given `_OverlayHost` (`scenario_list_screen.dart:71-87`) currently returns `SizedBox.shrink()` when `state is! ScenariosLoaded`
When this story lands
Then the behaviour is preserved verbatim — during `ScenariosError`, the BOC remains absent (no `usage` to render, no half-truth like "Free tier" without the count)
And the `_OverlayHost` widget's docstring is extended with one line that makes the rationale explicit: `// During Loading/Error/Initial we have no CallUsage to render — emitting a half-state would mislead the user about their remaining calls. The error view (full-area) is the entire screen.`
And NO change is made to the `Stack` ordering or the list's bottom padding constant `kBottomOverlayCardEstimatedHeight` — the error view sits inside the same `SafeArea`/`Padding` envelope the loaded list uses, so the layout math is unchanged.

**AC8 — Bloc tests cover the four codes + retry-count progression:**
Given `client/test/features/scenarios/bloc/scenarios_bloc_test.dart` (Story 5.2 baseline + Story 5.3 widening)
When this story extends the test file
Then it adds:
  1. `emits ScenariosError(code: NETWORK_ERROR, retryCount: 0) on first ApiException(NETWORK_ERROR)` — mock repository throws `ApiException(code: 'NETWORK_ERROR', message: '...')`, dispatch `LoadScenariosEvent`, assert state sequence `[ScenariosLoading, ScenariosError(code: 'NETWORK_ERROR', retryCount: 0)]`
  2. `emits SERVER_ERROR for any 5xx-class ApiException code` — parametrised: `'500'`, `'502'`, `'SERVER_ERROR'` all map to `code: 'SERVER_ERROR'`
  3. `emits UNKNOWN_ERROR for ApiException with non-network non-5xx codes` — parametrised: `'UNAUTHORIZED'`, `'FORBIDDEN'`, server-defined `'SCENARIO_CORRUPT'`, etc. all map to `code: 'UNKNOWN_ERROR'`
  4. `emits MALFORMED_RESPONSE on bare exception (cast / TypeError)` — mock repository throws `TypeError`, assert `code: 'MALFORMED_RESPONSE'`
  5. `retryCount increments across consecutive failures` — three failures in a row → `retryCount` sequence `0, 1, 2`
  6. `retryCount resets to 0 after a successful load` — failure → success → failure → assert final `retryCount == 0`
  7. `retryCount is preserved when error code changes between attempts` — NETWORK_ERROR (retryCount: 0) → SERVER_ERROR (retryCount: 1) → MALFORMED_RESPONSE (retryCount: 2) — counter tracks consecutive *failures*, not consecutive *codes*
  8. `in-flight guard still drops re-entrant LoadScenariosEvent during ScenariosLoading` — REGRESSION GUARD for the existing behaviour at `scenarios_bloc.dart:22`
And ALL existing Story 5.2 / 5.3 bloc tests remain green; the `ScenariosError(message)` → `ScenariosError(code, retryCount)` migration touches the assertions but not the harness shape.

**AC9 — Widget tests cover the four codes × first/repeat × retry tap:**
Given `client/test/features/scenarios/views/scenario_list_screen_test.dart` (Story 5.2 baseline + Story 5.3 widening + Story 5.4 dialog tests)
When this story extends the test file
Then it adds (each `setUp` per `client/CLAUDE.md` gotcha §1 + each `testWidgets` forces phone viewport per gotcha §7):
  1. `each code renders its first-failure title + body + icon` — parametrised over the four codes; pump screen with `ScenariosError(code: <code>, retryCount: 0)` mocked into the bloc seed; assert `find.text(<title>)` + `find.text(<body>)` + `find.byIcon(<icon>)` all `findsOneWidget`
  2. `repeat-failure body overrides first-failure body when retryCount >= 1` — parametrised over the four codes; pump with `retryCount: 1`; assert the repeat-failure body string is present AND the first-failure body string is absent
  3. `retryCount: 5 still shows the retryCount: 1 (repeat) variant` — boundary check: the repeat copy is sticky for any `retryCount >= 1`, no third variant exists
  4. `tapping the "Try again" button dispatches LoadScenariosEvent` — pump, `tester.tap(find.text('Try again'))`, assert the mock bloc received exactly one `LoadScenariosEvent`
  5. ~~`tapping the empty space outside the button still dispatches LoadScenariosEvent`~~ **AMENDED 2026-04-29 (review):** test inverted to `'tapping the empty space outside the button does NOT dispatch LoadScenariosEvent'` — locks in the new button-only retry behaviour per amended AC3 item 5. Tap at `Offset(50, 100)`, assert `verifyNever(() => mockBloc.add(any<LoadScenariosEvent>()))`.
  6. `title color is AppColors.textPrimary, NOT AppColors.destructive` — extract the `Text` widget via `tester.widget<Text>(find.text(<title>))` and assert `widget.style?.color == AppColors.textPrimary` (regression guard against accidental destructive-color reintroduction)
  7. `widget tree contains zero hex literals` — covered ambient by `theme_tokens_test.dart`; mention here as a reminder so the test list stays self-documenting (no new code in this test file)
And the existing 5.2 / 5.3 / 5.4 tests stay green — every assertion that previously read `ScenariosError('Unexpected response. Please try again.')` is updated in lock-step with AC1's state-shape change.

**AC10 — Pre-commit validation gates:**
Given pre-commit requirements from CLAUDE.md (project root) + client/CLAUDE.md
When the story is complete
Then `cd client && flutter analyze` prints "No issues found!" — every info-level lint fixed (especially `prefer_const_constructors` on the new `Text(...)` literals and `Icon(...)` calls; `unnecessary_const` flagged at the new `ScenariosError(code: '...', retryCount: 0)` call sites in the bloc)
And `cd client && flutter test` prints "All tests passed!" — bloc tests +8 (AC8), widget tests +6 (AC9 — items 1/2 are parametrised so they ship as 4 + 4 = 8 actual `testWidgets`, but the `Try again` regression and the `textPrimary` colour assertion fold into single tests; aim for +14 net), with all Story 5.1 / 5.2 / 5.3 / 5.4 tests still green
And `cd server` checks (`python -m ruff check . && python -m ruff format --check . && pytest`) STILL pass — this story ships ZERO server changes, but pre-commit runs the full suite anyway to catch cross-cutting drift
~~And `theme_tokens_test.dart` STILL passes — no new hex literal anywhere in `lib/`, the icon tint reuses `AppColors.textSecondary`, the `AppColors.values` count stays at 10.~~ **AMENDED 2026-04-29 (review)** per Figma redesign:
  - `theme_tokens_test.dart` is updated in lock-step: `AppColors.values.length == 13` (12→13 — new `errorBody` token; the spec line said "10" but the live invariant since Story 5.4 was already 12)
  - ONE new hex literal is permitted inside `lib/core/theme/app_colors.dart` (the `errorBody = #D8D8D8` declaration). The token-enforcement scan only blocks hex outside `lib/core/theme/`, which still holds.
  - the `Icon` tint inside `_IconBadge` reuses `AppColors.textSecondary` (with `withValues(alpha:)` derivations — no new color token for the alpha tones).

## Tasks / Subtasks

- [x] Task 1: State shape migration (AC: 1)
  - [x] 1.1 Edit `client/lib/features/scenarios/bloc/scenarios_state.dart` — replace `ScenariosError(message)` with `ScenariosError({required this.code, required this.retryCount})`; remove the `message` field; keep `final class` and `const` ctor.
  - [x] 1.2 Run `flutter analyze` — expect every call site of `ScenariosError(<string>)` to flag. Use the analyzer output as the migration TODO list.

- [x] Task 2: Bloc mapping logic (AC: 2)
  - [x] 2.1 Edit `client/lib/features/scenarios/bloc/scenarios_bloc.dart` — at the top of `_onLoad`, capture `final nextRetryCount = state is ScenariosError ? (state as ScenariosError).retryCount + 1 : 0;` BEFORE the `emit(ScenariosLoading())`.
  - [x] 2.2 Replace the `on ApiException catch (e)` arm with the code-mapping branches (NETWORK_ERROR / SERVER_ERROR / UNKNOWN_ERROR per AC2).
  - [x] 2.3 Replace the bare `catch (_)` arm with `ScenariosError(code: 'MALFORMED_RESPONSE', retryCount: nextRetryCount)`.
  - [x] 2.4 Remove the inline `'Unexpected response. Please try again.'` literal — copy now lives in the view (AC4).

- [x] Task 3: View rewrite (AC: 3, 4, 5, 6, 7)
  - [x] 3.1 Edit `_ErrorView` in `client/lib/features/scenarios/views/scenario_list_screen.dart` — replace the `final String message` constructor parameter with `final String code; final int retryCount;`.
  - [x] 3.2 Build a private const map (or a private switch helper) for `_titleFor(String code)`, `_bodyFor(String code, int retryCount)`, `_iconFor(String code)` — keep the lookup logic at the top of the file (or in a small private extension) so the four-row copy table is one-glance auditable.
  - [x] 3.3 Compose the new column: `Icon(_iconFor(code), size: 64, color: AppColors.textSecondary)` → gap → `Text(_titleFor(code), style: AppTypography.headline.copyWith(color: AppColors.textPrimary), textAlign: TextAlign.center)` → gap → `Text(_bodyFor(code, retryCount), style: AppTypography.body.copyWith(color: AppColors.textSecondary), textAlign: TextAlign.center)` → gap → `ElevatedButton(onPressed: () => context.read<ScenariosBloc>().add(const LoadScenariosEvent()), child: const Text('Try again'))`.
  - [x] 3.4 Keep the outer `GestureDetector(behavior: HitTestBehavior.opaque, onTap: () => context.read<ScenariosBloc>().add(const LoadScenariosEvent()))` wrapping the `Center` so the full-area hit-target survives (post-review decision 6 from Story 5.2 — explicit preservation comment to be left at the top of the build method).
  - [x] 3.5 Update `scenario_list_screen.dart:52-53` switch arm from `case ScenariosError(:final message): return _ErrorView(message: message);` to `case ScenariosError(:final code, :final retryCount): return _ErrorView(code: code, retryCount: retryCount);`.
  - [x] 3.6 Add the one-line docstring on `_OverlayHost` per AC7.

- [x] Task 4: Bloc tests (AC: 8)
  - [x] 4.1 Edit `client/test/features/scenarios/bloc/scenarios_bloc_test.dart` — migrate every existing `ScenariosError('...')` assertion to the new shape `ScenariosError(code: '...', retryCount: <int>)`.
  - [x] 4.2 Add the eight new tests per AC8 — use `bloc_test`'s `expect:` matchers; mock the repository with mocktail; recall to `registerFallbackValue(LoadScenariosEvent())` if not already present (gotcha §2).
  - [x] 4.3 Run `flutter test test/features/scenarios/bloc/scenarios_bloc_test.dart` — expect green; expect total bloc-test count delta of +8.

- [x] Task 5: Widget tests (AC: 9)
  - [x] 5.1 Edit `client/test/features/scenarios/views/scenario_list_screen_test.dart` — migrate the existing `find.text('Tap to retry')` assertion (line 186) and the `find.text('Tap to retry')` tap (line 202) to `find.text('Try again')`.
  - [x] 5.2 Migrate the existing error-message assertion (line ~187 region per `Tap to retry` neighbour) to assert the new code-keyed copy — use `code: 'UNKNOWN_ERROR', retryCount: 0` for the legacy harness so the migration is mechanical.
  - [x] 5.3 Add the new tests per AC9 — each test starts with `FlutterSecureStorage.setMockInitialValues({})` (gotcha §1) and `tester.binding.setSurfaceSize(const Size(320, 480))` + `addTearDown` (gotcha §7).
  - [x] 5.4 Run `flutter test test/features/scenarios/views/scenario_list_screen_test.dart` — expect green; expect total delta of +14 (or close — see AC10 commentary on the parametrised count).

- [x] Task 6: Pre-commit gate (AC: 10)
  - [x] 6.1 `cd client && flutter analyze` → must print "No issues found!".
  - [x] 6.2 `cd client && flutter test` → must print "All tests passed!".
  - [x] 6.3 `cd server && python -m ruff check . && python -m ruff format --check . && .venv/Scripts/python -m pytest` → all three green (no server changes expected).
  - [x] 6.4 Update `_bmad-output/implementation-artifacts/sprint-status.yaml`:
    - flip `5-5-refactor-scenario-list-error-screen-with-empathetic-ux` to `review`
    - bump `last_updated` line to today's date
  - [x] 6.5 Update this story file's frontmatter `Status:` from `ready-for-dev` to `review`.

## Dev Notes

### Why this story exists

Source UX review: 2026-04-28 conversation between Walid and Sally (UX Designer persona). Two complaints triggered the refacto:

> *"je trouve ça froid, sans sens et n'explique pas le soucis"* — the message is technical (`Unexpected response`) and doesn't distinguish causes the user can act on.
>
> *"dois on mettre un ecran entier ou juste une partie ?"* — full-area is correct here (no cache to preserve, BOC depends on usage and would mislead), but it must be **calm**, not alarming.

Reference memory: `feedback_error_ux.md` (the project-wide error UX rule) — the **"keep retry pattern for forms and long-lived screens where re-navigation would lose user-entered data"** clause applies. Scenario list is a long-lived screen, not a transitional one, so inline retry stays. This story refines the inline pattern, it does NOT migrate to the fade-nav fallback pattern used in onboarding.

### What is intentionally NOT in scope

1. **No new `AppColors` token.** The icon uses `textSecondary`; the title uses `textPrimary`. `AppColors.values` count stays at 10 — `theme_tokens_test.dart` keeps its sentinel assertion intact.
2. **No reusable `ErrorView` component.** Tempting to extract a shared widget (auth flow, debrief, briefing all have inline error patterns), but the auth flow's error states use `state.previousState` for re-navigation context and the briefing/debrief screens don't yet exist. Premature extraction. If a second screen adopts this exact code-keyed pattern, that's the right time to extract — not now.
3. **No localisation pass.** Copy ships in English (`document_output_language: English`). French copy follows when the project broadly L10Ns (post-MVP per PRD).
4. **No analytics on retry taps.** Walid's PRD doesn't enumerate this signal yet; adding instrumentation here would create a one-off metric pipeline. Capture as deferred-work if Walid wants it later.
5. **No "restart the app" deep-link.** The repeat-failure copy mentions restarting the app in plain words; we don't add a system call to relaunch (Flutter doesn't expose one cleanly cross-platform). User is trusted to act on the suggestion.

### 5xx detection — why the heuristic

The server's structured error envelope (`server/api/responses.py`) uses string codes (`SCENARIO_CORRUPT`, `CALL_LIMIT_REACHED`, etc.) and HTTP status independently. There is no canonical `'500'` literal in the code stream today. AC2's heuristic — "code starts with `'5'` OR equals literal `'SERVER_ERROR'`" — is forward-compat: if a future story adds a `5xx`-prefixed code (e.g. `'500_DB_DOWN'`), it auto-classes as server-class without a one-line touch here. If Walid later codifies a single canonical 5xx tag (e.g. `'SERVER_UNAVAILABLE'`), update AC2 + the bloc switch in lock-step.

### Files touched (exhaustive list)

**Client (lib):**
- `client/lib/features/scenarios/bloc/scenarios_state.dart` — `ScenariosError` shape
- `client/lib/features/scenarios/bloc/scenarios_bloc.dart` — error mapping + retry counter
- `client/lib/features/scenarios/views/scenario_list_screen.dart` — `_ErrorView` rewrite + `_OverlayHost` docstring

**Client (test):**
- `client/test/features/scenarios/bloc/scenarios_bloc_test.dart` — migrate existing assertions, add 8 new tests
- `client/test/features/scenarios/views/scenario_list_screen_test.dart` — migrate existing assertions, add ~14 new tests

~~**No other files are touched.** No router change, no theme change, no API change, no model change, no server change.~~ **AMENDED 2026-04-29 (review)** per Figma redesign:

**Theme (added to scope):**
- `client/lib/core/theme/app_colors.dart` — new `errorBody` token (#D8D8D8)
- `client/lib/core/theme/app_spacing.dart` — new `screenHorizontalErrorView` (36.0)
- `client/test/core/theme/theme_tokens_test.dart` — count assertion 12 → 13, plus new `screenHorizontalErrorView` assertion

**Still no other files touched.** No router change, no API change, no model change, no server change.

### Convention reminders

- **Gotcha §1**: every `setUp` calls `FlutterSecureStorage.setMockInitialValues({})` even though this story's view doesn't touch storage directly — `ScenariosBloc` transitively depends on `ApiClient` which uses `TokenStorage`. Skipping the line passes locally and crashes CI.
- **Gotcha §6**: NO new hex literal in `lib/`. The `Icon` tint reuses `AppColors.textSecondary` — adding a new `AppColors.errorIconTint` is over-engineering. If a second view ever needs a 64-px tinted icon and the colour disagrees with `textSecondary`, that's the moment to extract.
- **Gotcha §7**: every widget test forces `setSurfaceSize(Size(320, 480))` + `addTearDown(() => setSurfaceSize(null))`. The `_ErrorView` column at 320-wide must not overflow under `MediaQueryData(textScaler: TextScaler.linear(1.5))` — verify with one ad-hoc test if you want belt + braces, but the existing token system already ensures this.
- **Lint trap (§9)**: `prefer_const_constructors` will flag every new `Text(...)` and `Icon(...)` literal. Add `const` proactively.

### Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Migrating `ScenariosError(message)` → `(code, retryCount)` breaks an Epic 4 / 5.3 test that asserts on `.message` | Medium | Low (compile-time error, immediately visible) | Use `flutter analyze` as the migration TODO list — every call site flags. AC1's "no orphan tests" clause is the gate. |
| Repeat-failure copy is too dramatic for a transient retry | Low | Low | Copy reviewed 2026-04-28; if user feedback says it overcorrects, this is one string change in `_bodyFor`. |
| Adding `retryCount` to state breaks `BlocListener` dedupe (state-equality changes between identical-code emissions only when retryCount changes) | Low | Low | The non-`const` `ScenariosLoading` (lines 12-15 of state file) interrupts every error→error transition with a Loading frame, so dedupe is moot. Existing pattern. |
| Server starts emitting 5xx codes that don't start with `'5'` | Low | Medium (mis-classifies as `UNKNOWN_ERROR`) | AC2's heuristic accepts both `'5*'` prefix and literal `'SERVER_ERROR'`. Server team-of-one (Walid) controls both ends. |

### Snapshot of the new visual

```
                    [icon, 64px, textSecondary]

                  Title in textPrimary, headline
                    (e.g. "You're offline.")

         Body in textSecondary, body, line-wrapped, centred
        (e.g. "We need a connection to load your scenarios.
                Check your Wi-Fi or mobile data, then try again.")

                       [ Try again ]    ← ElevatedButton, theme defaults
```

The whole rectangle remains tappable for power users. The button is the discoverable affordance. Red is gone. The icon sets the emotional register before any words register.

## Testing

Run from `client/` after the implementation:

```bash
flutter analyze
flutter test
flutter test test/features/scenarios/bloc/scenarios_bloc_test.dart
flutter test test/features/scenarios/views/scenario_list_screen_test.dart
flutter test test/core/theme/theme_tokens_test.dart
```

Expected:
- `flutter analyze` → "No issues found!"
- `flutter test` → "All tests passed!" with delta of approximately +22 net new tests (8 bloc + 14 widget)
- `theme_tokens_test.dart` → green; `AppColors.values.length == 10` invariant preserved

Run from `server/`:

```bash
python -m ruff check .
python -m ruff format --check .
.venv/Scripts/python -m pytest
```

Expected: all green (this story ships zero server changes; the full server suite is run as a cross-cutting drift check per CLAUDE.md).

## Story Definition of Done

- [x] All ACs pass
- [x] All Tasks complete
- [x] `flutter analyze` clean
- [x] `flutter test` green (full suite, not just new tests) — 205 passing
- [x] `theme_tokens_test.dart` still asserts `AppColors.values.length == 12` (sentinel intact — story added zero new tokens; spec line said "10" but the live invariant since Story 5.4 is 12)
- [x] Server pre-commit triple green (no server diff expected) — 145 pytest passing, ruff check + format clean
- [x] `sprint-status.yaml` flipped to `review`
- [x] Story file frontmatter flipped to `review`
- [x] Awaiting reviewer (do NOT commit autonomously per CLAUDE.md — wait for Walid's `/commit`)

## Dev Agent Record

### Implementation Notes

State shape (`ScenariosError`) widened from `(message: String)` to `(code: String, retryCount: int)`. The bloc now classifies failures into four canonical codes — `NETWORK_ERROR`, `SERVER_ERROR`, `MALFORMED_RESPONSE`, `UNKNOWN_ERROR` — via a small static `_classifyApiCode` helper that reads `ApiException.code`. Bare exceptions (TypeError / FormatException from a malformed payload) fall through to `MALFORMED_RESPONSE`. The retry counter is captured as `nextRetryCount` BEFORE the `emit(ScenariosLoading())` so the increment survives the loading state; resets to `0` on any non-error prior state.

`_ErrorView` was rewritten as a pure function of `(code, retryCount)`. Three private file-level helpers (`_iconFor`, `_titleFor`, `_bodyFor`) keep the code → copy/icon table one-glance auditable. The repeat-failure body kicks in at `retryCount >= 1` and is sticky for any larger value — verified by the `retryCount=5` boundary test. The title remains in `AppColors.textPrimary` (red destructive is reclaimed for irreversible actions only); the icon tint is `AppColors.textSecondary`. The full-area `GestureDetector` wrapper survives as a power-user redundancy alongside the discoverable `ElevatedButton`.

Spacing rhythm uses `AppSpacing.base` arithmetic (no new constants): `* 2 = 16px` between icon→title and title→body; `* 3 = 24px` between body→button.

`_OverlayHost` got the explicit AC7 docstring explaining why we render `SizedBox.shrink` during error states (no `CallUsage` to surface; rendering a half-state would mislead the user about remaining calls).

### Completion Notes

- 9 new bloc tests added (NETWORK_ERROR, 3× 5xx-class, 4× UNKNOWN_ERROR fallback, MALFORMED_RESPONSE, retry increments, retry reset, retry across changing codes). Existing 6 bloc tests preserved or migrated. Total: 15.
- 9 new widget tests added (4× first-failure parametrised over codes, 4× repeat-failure parametrised, retryCount=5 boundary, "Try again" button tap, full-area tap regression, title-color regression). Plus migration of the original Story 5.2 error-rendering test absorbed into the parametrised first-failure batch. Total widget tests in scenario_list_screen_test: 23.
- `flutter analyze` clean (no infos, no warnings).
- `flutter test` green: 205 passing.
- Server: ruff check + ruff format + pytest all green (145 passing, no server diff).
- `theme_tokens_test.dart`: sentinel reads 12 (Story 5.4 baseline), unchanged here.

### Notes for Reviewer — conscious choices that warrant a decision

The following five points are deliberate calls I made during implementation that the spec either prescribes verbatim (so I followed it) or stays silent on. None blocks the review; flagging each with rationale so the reviewer can override if a different trade-off is preferred.

1. **`code` is `String`, not an enum.** AC1 / AC4 / AC5 explicitly fix the canonical literals (`'NETWORK_ERROR'`, `'SERVER_ERROR'`, `'MALFORMED_RESPONSE'`, `'UNKNOWN_ERROR'`) as `String`. I followed the spec, but a private `enum ScenarioErrorCode` would buy compile-time guarantees that bloc and view stay in lock-step (today, a typo on either side passes analyzer). If the reviewer wants an enum, the migration is mechanical: the four literals already live in three places (`scenarios_bloc.dart` switch, `_iconFor`/`_titleFor`/`_bodyFor` switches, test fixtures).

2. **Bare `catch (_)` preserved.** AC2 says "bare `catch (_)` (TypeError / FormatException / cast failures …) → MALFORMED_RESPONSE". I kept the bare catch verbatim, which means *any* non-`ApiException` throwable (including a hypothetical bug in our own bloc — say, a `StateError` from a misuse of `Emitter`) gets mapped to `MALFORMED_RESPONSE` and silently shown as "Something didn't load right." A tighter `on TypeError catch (_)` + `on FormatException catch (_)` + `on CastError catch (_)` would let genuine bugs escape to the test runner / crash reporter where they belong. Deviating from the spec wording, so I left it; reviewer can call.

3. **`_iconFor` / `_titleFor` / `_bodyFor` are file-level private functions, not `_ErrorView` static methods.** Task 3.2 says "private const map (or a private switch helper) — keep the lookup logic at the top of the file (or in a small private extension)". I picked file-level switch functions, which keeps the four-row table one-glance auditable but spreads the widget's logic across the file. Promoting them to static members of `_ErrorView` groups the logic with its only consumer at the cost of slightly more indentation. Pure stylistic.

4. ~~**No textScaler 1.5 overflow test for `_ErrorView`.** Dev Notes calls this "belt + braces" / optional.~~ **WITHDRAWN 2026-04-29 (review):** the regression test `'error layout does not overflow at 320×480 with textScaler 1.5'` ships as part of the Figma redesign (`scenario_list_screen_test.dart:~410-455`); the safety net is in place. The post-review patch additionally captured `FlutterError.onError` so RenderFlex overflows can't be silently swallowed by `SingleChildScrollView`.

5. **`code.startsWith('5')` matches more than HTTP 5xx-shaped strings.** Per Dev Notes, the heuristic is intentional ("forward-compat: if a future story adds a `5xx`-prefixed code (e.g. `'500_DB_DOWN'`), it auto-classes as server-class without a one-line touch here."). The corollary: any future server-defined code that happens to start with `'5'` for unrelated reasons (e.g. a hypothetical `'5G_DISABLED'`, `'500_RATE_LIMIT'`) will misclass as `SERVER_ERROR`. Walid controls both ends today, so the risk is theoretical — but worth flagging so the reviewer knows the heuristic isn't a strict HTTP-numeric check.

6. **Figma redesign (2026-04-29) deviates from AC4/AC5 typography hardcoding.** The original AC4 prescribed `AppTypography.headline.copyWith(color: AppColors.textPrimary)` for the title and `AppTypography.body.copyWith(color: AppColors.textSecondary)` for the body. The Figma `iphone-16-8` reference fixes specific font sizes / weights / colors that don't align with existing tokens (Inter 24 w700 for the subtitle, Inter 14 w400 on a new `errorBody` for the body, Frijole 40 for the new `HOLD ON` hero). I inlined `TextStyle(...)` directly in `_ErrorView` rather than adding 3-4 single-use entries to `AppTypography`. Rationale: `AppTypography` is presented as the UX-DR2 typography registry (10 styles asserted in `theme_tokens_test.dart`); polluting it with one-shot error-screen styles would force a UX-DR2 amendment for what is a single-screen visual decision. Same precedent as the auth screens (`email_entry_screen.dart`, `consent_screen.dart`) which inline Frijole styles. Reviewer can override and promote them to `AppTypography` if the same styles get reused on a sibling error screen later.

7. **`HOLD ON` becomes a common hero across all four codes (Figma redesign).** Before the redesign, the title shifted with the code (`You're offline.` for NETWORK_ERROR, `Our servers are catching their breath.` for SERVER_ERROR, etc.) per AC4. After the redesign there are TWO hero levels: a constant `HOLD ON` in Frijole 40 (universal "something happened, take a breath" register), then the code-specific subtitle below. AC4's title-text mapping is preserved verbatim — it's now the "subtitle" slot, not the "hero" slot. No copy was lost, only the visual hierarchy was raised.

8. **New tokens shipped: `AppColors.errorBody` and `AppSpacing.screenHorizontalErrorView`.** The Figma body color `#D8D8D8` is brighter than `textSecondary` (`#8A8A95`) — deliberate UX choice for multi-line readability under longer copy. Token count goes from 12 → 13. The 36-px horizontal padding on the error screen is wider than `screenHorizontalScenarioList` (18) — error screens want more breathing room so the wrap doesn't feel cramped. Both tokens are guarded by `theme_tokens_test.dart`.

9. **`Expanded` + `SingleChildScrollView` wraps the content above the button.** The Figma reference targets a 943-tall device. On 320×480 with textScaler 1.5 (Flutter test gotcha §7), the content column overflows by ~412 px. Wrapping in `SingleChildScrollView` lets the upper content scroll while the `Try again` pill stays pinned at the bottom (button is a sibling in the outer Column, never absorbed by the scroll view). This is the same belt-and-braces pattern Story 5.4 added to the content-warning sheet under similar viewport pressure.

10. **Full-area tap-to-retry removed (Story 5.2 post-review decision 6 reversed).** Story 5.2 carried a `GestureDetector(behavior: opaque)` that wrapped the whole scaffold body so any tap re-entered loading. The Figma redesign ships a discoverable accent-green CTA pinned at the bottom; with that affordance, the hidden full-area tap was redundant *and* a foot-gun (could fire on accidental scroll-to-end gestures or stray taps while the user was reading). Retry is now button-only. The corresponding regression test was inverted from "empty-space tap dispatches" to "empty-space tap does NOT dispatch" so the new behaviour is locked in. AC3 wording in the story spec ("the existing full-area `GestureDetector` … kept as a power-user hit-target") is therefore no longer literally honoured — flagging here so the reviewer sees the deliberate deviation.

11. **Button visual harmonised with onboarding (consent_screen + mic_permission_screen).** The Figma `iphone-16-8` button differs from onboarding's button (`Inter 12 w700` per Figma vs `Inter 17 w700` in the live onboarding code; `padding: 16/36` per Figma vs `height: 64` in onboarding). Walid asked for consistency with onboarding, so the button now uses onboarding's pattern verbatim: `SizedBox(height: 64)` + `FilledButton` + `RoundedRectangleBorder(r: 32)` + Inter 17 w700 on accent. The icon stays at 24-px (Figma value, same as onboarding's `arrow_forward_rounded`). `FittedBox(BoxFit.scaleDown)` wraps the icon+label cluster so the button content scales down rather than overflowing on narrow phones × textScaler 1.5. Reviewer can call this back to literal Figma if visual fidelity matters more than cross-screen consistency.

### File List

**Modified:**
- `client/lib/core/theme/app_colors.dart` (Figma redesign — `errorBody` token)
- `client/lib/core/theme/app_spacing.dart` (Figma redesign — `screenHorizontalErrorView`)
- `client/lib/features/scenarios/bloc/scenarios_state.dart`
- `client/lib/features/scenarios/bloc/scenarios_bloc.dart`
- `client/lib/features/scenarios/views/scenario_list_screen.dart`
- `client/test/core/theme/theme_tokens_test.dart` (count 12 → 13 + new spacing assertion)
- `client/test/features/scenarios/bloc/scenarios_bloc_test.dart`
- `client/test/features/scenarios/views/scenario_list_screen_test.dart`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

**Created / Deleted:** none.

## Change Log

- 2026-04-28 — Story 5.5 implementation: empathetic error view shipped. `ScenariosError` migrated from `(message)` to `(code, retryCount)`; `_ErrorView` rewritten as pure function of state with code-keyed icon + title + body, repeat-failure body variant at `retryCount >= 1`, `ElevatedButton` "Try again" affordance, full-area tap redundancy preserved. 18 net new tests (9 bloc, 9 widget). Pre-commit gates all green. Status → review.
- 2026-04-29 — Figma redesign applied per `iphone-16-8` reference. Visual rewrite preserves the (code, retryCount) state contract and copy tables (AC1/AC2/AC4 unchanged), but the layout now follows the Figma spec verbatim:
  - 105×105 icon badge (translucent `textSecondary` fill 10% + stroke 30%) replaces the bare 64-px icon
  - new common hero `HOLD ON` in Frijole 40 above every error code
  - new accent-green `· HEADS UP ·` badge between icon and HOLD ON
  - per-code subtitle (`You're offline.` etc.) promoted from headline-style title to Inter 24 w700 sub-hero
  - body promoted from Inter 16 textSecondary → Inter 14 on new `AppColors.errorBody` (#D8D8D8) for higher readability
  - `Try again` is now a full-width accent-green stadium pill with `Icons.refresh` glyph, pinned at the bottom
  - outer `SafeArea` + `Padding` moved INTO the BlocBuilder switch (each state owns its envelope) so the error view can use `SafeArea(top: true, bottom: true)` + `AppSpacing.screenHorizontalErrorView (36)` while the loaded list keeps `SafeArea(top: true, bottom: false)` + 18-px h-pad
  - `Expanded` + `SingleChildScrollView` wraps the content above the button so 320×480 + textScaler 1.5 doesn't overflow (verified by new regression test)
  - new tokens: `AppColors.errorBody` (#D8D8D8, count 12 → 13), `AppSpacing.screenHorizontalErrorView` (36.0). `theme_tokens_test.dart` updated.
  - 3 net new widget tests (HOLD ON+HEADS UP common, retry icon visible, 320×480 textScaler 1.5 overflow guard). Total 211 flutter tests green, analyze clean. Bloc untouched.
- 2026-04-29 (later) — UX iteration on Walid request:
  - Bottom padding on the Try again button bumped from 10 → 30 (visual lift above the home-indicator inset).
  - Button visual harmonised with the onboarding pattern (consent_screen / mic_permission_screen): `SizedBox(h:64)` + `FilledButton` + `RoundedRectangleBorder(r:32)` + Inter 17 w700 on accent, icon-then-label Row inside `FittedBox(scaleDown)`.
  - Full-area tap-to-retry **removed** — retry is now button-only. The existing "empty-space tap dispatches" regression was inverted to "empty-space tap does NOT dispatch" to lock in the new behaviour. AC3 spec wording ("full-area GestureDetector kept as power-user hit-target") is no longer literally honoured; deviation #10 captures the rationale (discoverable CTA + accidental-scroll foot-gun).
  - 211 flutter tests still green, analyze clean.

### Review Findings

Code review 2026-04-29 — three parallel adversarial layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). 58 raw findings → 7 decisions / 7 patches / 11 deferred / 33 dismissed.

**Decisions needed:**
- [x] [Review][Decision] **AC3 + AC9 reversal — full-area `GestureDetector` removed** — RESOLVED 2026-04-29: ACCEPTED. Button-only retry kept as deviation #10 (discoverable CTA + accidental-scroll foot-gun). AC3 item 5 + AC9 item 5 amended in this story file to reflect the new behaviour.
- [x] [Review][Decision] **AC4/AC5/AC8/AC10/AC11 Figma redesign en bloc** — RESOLVED 2026-04-29: ACCEPTED en bloc. Deviations #6/#7/#8/#11 codified as spec amendments — AC3 item 4 (button), AC4 (typography + new HOLD ON hero + HEADS UP badge), AC5 (icon framing), AC10 (token count + permitted hex inside `lib/core/theme/`), and the "Files touched" list updated to include the three theme files. `errorBody` token kept (single-use, name honestly encodes use-case — premature renaming would be over-engineering).
- [x] [Review][Decision] **AC6 spacing — raw integer literals + new `AppSpacing.screenHorizontalErrorView` token (UNFLAGGED)** — RESOLVED 2026-04-29: ACCEPTED en bloc. Figma pixel values don't align to `AppSpacing.base * N`; raw literals + new horizontal token preserved for visual fidelity. AC6 amended in this story file to codify the new rhythm.
- [x] [Review][Decision] **AC6 `textAlign: TextAlign.center` missing on title and body (UNFLAGGED)** — RESOLVED 2026-04-29: ACCEPTED. Figma redesign is left-aligned by design; imposing `textAlign: center` would contradict the gutter-36 + `crossAxisAlignment: stretch` rhythm codified in decisions 2 and 3. AC6 amended to withdraw the centring clause.
- [x] [Review][Decision] **`SCENARIO_CORRUPT` server code lands as `UNKNOWN_ERROR`** — RESOLVED 2026-04-29: STATUS QUO. From the client's POV, the server returned a code with no actionable meaning to the user; "unknown" is defensible. AC8 test parametrisation (`'SCENARIO_CORRUPT'` → `UNKNOWN_ERROR`) preserved.
- [x] [Review][Decision] **`SERVER_ERROR` heuristic is dead code in production** — RESOLVED 2026-04-29: ACCEPTED option A (HTTP status propagation through `ApiException`). Refactor moved to the patch list below — see `[Review][Patch] ApiException.statusCode propagation`.
- [x] [Review][Decision] **`AUTH_UNAUTHORIZED` (session expired) shows generic "try again" UNKNOWN_ERROR — ⚠️ HIGH-PRIORITY DEFERRED** — RESOLVED 2026-04-29: DEFERRED with explicit "do-not-forget before MVP launch" flag from Walid. Cross-cutting auth/401 handling deserves its own story (Dio interceptor → router redirect to `/auth`); coupling it into `ScenariosBloc` would leak the auth abstraction. Captured in `deferred-work.md` (top of file) AND project memory (`feedback_auth_401_gap.md`).

**Patches (unambiguous fixes) — all resolved 2026-04-29:**
- [x] [Review][Patch] **`ApiException.statusCode` propagation** (resolves Decision 6) — APPLIED. `ApiException` extended with optional `int? statusCode`; `fromDioException` populates from `response?.statusCode`. `_classifyApiCode(String)` → `_classifyApiException(ApiException)`; routes `statusCode in [500, 600)` → SERVER_ERROR regardless of body code. `code.startsWith('5')` heuristic dropped. `'SERVER_ERROR'` literal kept defensively. Bloc tests rewritten: 5xx parametrised over `(SCENARIO_CORRUPT, 500)`, `(LIVEKIT_TOKEN_FAILED, 500)`, `(BOT_SPAWN_FAILED, 502)`, `(UNKNOWN_ERROR, 503)`; UNKNOWN_ERROR parametrised over `(UNAUTHORIZED, 401)`, `(FORBIDDEN, 403)`, `(SCENARIO_CORRUPT, null)` (preserves decision-5 status quo when no status info), `(UNKNOWN_ERROR, null)`. Defensive `'SERVER_ERROR'` literal test added.
- [x] [Review][Patch] Stale comment "ElevatedButton.icon" — APPLIED. Comment updated to reference FilledButton + manual Row + FittedBox.
- [x] [Review][Patch] Stale comment "Spacer absorbs the overflow" — APPLIED. Comment rewritten to describe the Expanded + SingleChildScrollView layout.
- [x] [Review][Patch] ~~`_iconFor` / `_titleFor` / `_bodyFor` top-level public functions~~ — DISMISSED as false positive. The functions are already prefixed with `_` (lines 394, 408, 422); in Dart, top-level identifiers starting with `_` are library-private. Blind Hunter mis-read.
- [x] [Review][Patch] `Future.delayed(Duration.zero)` flakiness — APPLIED. All 8 occurrences in retry-progression bloc tests replaced with `pumpEventQueue()` (re-exported by `flutter_test`). Deterministic flush of the Loading→Error transition between consecutive `add()` calls.
- [x] [Review][Patch] Decorative HEADS UP/HOLD ON Semantics grouping — APPLIED. `HOLD ON` Text wrapped in `Semantics(header: true, ...)`; the two `_AccentDot` widgets wrapped in `ExcludeSemantics` so TalkBack/VoiceOver hears just "HEADS UP HOLD ON [title] [body]".
- [x] [Review][Patch] `tester.takeException()` weak overflow assertion — APPLIED. Test now also captures `FlutterError.onError` into a list and asserts the list is empty, plus a `find.text('Try again')` sanity check that the button stays in the tree.
- [x] [Review][Patch] Dev-flagged deviation #4 stale — APPLIED. Notes section updated: deviation #4 marked WITHDRAWN; the overflow regression test does ship.

**Deferred (real but not actionable now):**
- [x] [Review][Defer] retryCount increments unbounded — by design (AC1 documents no third copy tier); deferred, pre-existing
- [x] [Review][Defer] `previous = state` capture under hypothetical future co-events — moot today (single-event surface); deferred, pre-existing
- [x] [Review][Defer] `_classifyApiCode` not unit-tested in isolation — bloc-level coverage exists; deferred, low priority
- [x] [Review][Defer] Loading state after error renders blank screen for up to 15s — pre-existing from Story 5.2; deferred, pre-existing
- [x] [Review][Defer] No test asserts `BottomOverlayCard` absent during `ScenariosLoading` — pre-existing test gap; deferred, pre-existing
- [x] [Review][Defer] `SCENARIO_LOAD_FAILED` and broader server-code error mapping — Story 6+ scope; deferred, out of scope
- [x] [Review][Defer] Empty/whitespace `ApiException.code` defensive handling — hypothetical future server change; deferred, defensive
- [x] [Review][Defer] Hardcoded `Offset(50, 100)` tap coords fragile under viewport refactors [client/test/features/scenarios/views/scenario_list_screen_test.dart:~320]; deferred, currently correct
- [x] [Review][Defer] `FilledButton` no `foregroundColor` — touch ripple/highlight may use wrong overlay tint [client/lib/features/scenarios/views/scenario_list_screen.dart:~351-360]; deferred, visual polish
- [x] [Review][Defer] `FittedBox(scaleDown)` shrinks 24-px refresh icon at textScaler 3.0 [client/lib/features/scenarios/views/scenario_list_screen.dart:~285-308]; deferred, edge case beyond MVP
- [x] [Review][Defer] In-flight guard test name changed but body not visible in diff — re-verify `verify(...).called(1)` still asserts a single Loading→Error cycle [client/test/features/scenarios/bloc/scenarios_bloc_test.dart:~775]; deferred, low risk

