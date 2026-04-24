# Story 5.2: Build Scenario List Screen with ScenarioCard Component

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to browse a scrollable list of scenarios showing each character's name, tagline, and my completion stats,
So that I can choose which scenario to attempt and see my progress at a glance.

## Acceptance Criteria (BDD)

**AC1 — ScenariosRepository fetches the list envelope:**
Given an authenticated user opens the app and lands at `/` (root)
When the presentation layer asks for scenarios
Then `ScenariosRepository.fetchScenarios()` calls `GET /scenarios` via the shared `ApiClient` (JWT injected by the existing interceptor)
And the `{ "data": [...], "meta": { "count": <int>, "timestamp": "..." } }` envelope from Story 5.1 is parsed into `List<Scenario>` (5 items in current seed)
And each `Scenario` maps the snake_case payload into Dart camelCase per the model (see Dev Notes → Scenario model)
And a network failure or 401 is surfaced as `ApiException` — the repository does NOT swallow it.

**AC2 — ScenariosBloc state transitions:**
Given the root route mounts a `BlocProvider<ScenariosBloc>` with `LoadScenariosEvent` dispatched on create
When the bloc handles the event
Then it emits `ScenariosLoading` immediately, then one of:
  - `ScenariosLoaded(List<Scenario> scenarios)` on success (ordered exactly as the server returned — NO client-side re-sort)
  - `ScenariosError(String message)` on any `ApiException` (message = `e.message`; the code is available for future telemetry but not rendered)
And a subsequent `LoadScenariosEvent` (user-triggered retry) goes back through `ScenariosLoading`
And the bloc uses the sealed-event / sealed-state pattern (see `AuthBloc` + `IncomingCallBloc` for the established shape).

**AC3 — ScenarioListScreen renders the three states:**
Given `/` is the authenticated-user destination (routing already in place — router.dart line 96-106 placeholder to replace)
When `ScenariosBloc` is `ScenariosLoading`
Then the screen renders a `#1E1F23` background with NO spinner and NO header/appbar (UX-DR17, UX-DR21) — a blank dark scaffold is acceptable for the brief loading window (API is local-network-fast)
And when it emits `ScenariosLoaded`, the scaffold shows a `ListView.separated` of `ScenarioCard` widgets with a 12-px `SizedBox` separator (`AppSpacing.cardGap`), 30-px vertical + 20-px horizontal padding (`screenVerticalList` + `screenHorizontal`), top `SafeArea` respected
And when it emits `ScenariosError`, the screen shows an inline `Text` in `AppColors.destructive` (per client CLAUDE.md §10: inline error, never snackbar/toast) centered, with a subtle "Tap to retry" affordance that re-dispatches `LoadScenariosEvent` on tap (whole screen is the hit target — no styled button, monochrome rule).

**AC4 — ScenarioCard anatomy + three states (UX-DR4):**
Given UX-DR4 defines the ScenarioCard layout
When a card is rendered
Then it is a `Row` with: `[Avatar 50×50 circle #414143]` + 10-px gap + `[Expanded text column]` + `[Action icons row, 20-px gap]` vertically centred
And the text column contains:
  - Line 1: character name (`title` from API) in `AppTypography.cardTitle` (Inter Bold 12px `#F0F0F0`)
  - Line 2: scenario tagline in `AppTypography.cardTagline` (Inter Italic 12px `#F0F0F0`), `maxLines: 2, overflow: TextOverflow.ellipsis` (UX line 1264)
  - Line 3: stats (conditional — see state table below)
  - 5-px gap between lines (`AppSpacing.cardTextGap`)
And the card has NO background, NO border, NO shadow, NO elevation (flat — UX-DR17 + §324)
And the three states render as:

| State | Criteria | Line 3 shown? | Stats color | Report icon |
|---|---|---|---|---|
| Not attempted | `attempts == 0` | Hidden (2 lines total) | — | Hidden |
| In progress | `attempts >= 1` AND (`bestScore == null` OR `bestScore < 100`) | `"Best: ${bestScore ?? 0}% · $attempts attempts"` | `AppColors.statusInProgress` (#FF6B6B) | Visible |
| Completed | `bestScore == 100` | `"Best: 100% · $attempts attempts"` | `AppColors.statusCompleted` (#2ECC40) | Visible |

And the "Best:" prefix stays `AppColors.textPrimary`; only the percentage + "attempts" tail takes the conditional colour (UX line 603 — use two `TextSpan`s inside a `Text.rich`).

**AC5 — Action icons — phone & report (UX-DR4):**
Given the card has two action icons sized 24×24 (`AppSpacing.iconSmall`), 20-px gap (`AppSpacing.cardIconGap`), both `AppColors.textPrimary`
When the user taps the phone icon
Then Story 5.2 navigates to `/call` via `context.go(AppRoutes.call)` passing the tapped `Scenario` object as `extra` (the existing `/call` route already has a defensive fallback — router.dart line 166-185 — so this works end-to-end for smoke testing even before Story 6.1 wires the real call screen)
And the phone icon is wrapped in a `Semantics(button: true, label: 'Call ${title}')` with a 44-px minimum touch area (`AppSpacing.minTouchTarget`)
And when the user taps the report icon (only rendered when visible)
Then Story 5.2 navigates to `/debrief/${scenarioId}` **or** no-ops if that route is not yet defined in router.dart — preferred path: route stub that logs `debugPrint('Debrief tap — scenario=$id')` and returns a placeholder `Scaffold` (same "stub until Story 7.x" pattern as `CallPlaceholderScreen`). The route name is `/debrief/:scenarioId`. Add `AppRoutes.debrief = '/debrief'` to the constants table.

**AC6 — Ordering + responsive layout (FR19 + UX-DR18):**
Given FR19 requires scenarios ordered easy → medium → hard
When the list renders
Then the items appear in the exact order returned by `GET /scenarios` (Story 5.1 ORDER BY already enforces `easy < medium < hard` with `id` as tiebreaker — the client trusts the server)
And on any supported phone width (320-430 px, UX-DR18), the `Row` renders without overflow because:
  - Avatar (50) + icons (24 + 20 + 24) + gaps (10 + 20) = 148-px fixed
  - Text column takes `Expanded(flex: 1)` — tagline wraps to 2 lines with ellipsis on narrow screens
  - Top safe-area is respected via `SafeArea(top: true)`
And a widget test at 320×480 (`tester.binding.setSurfaceSize(const Size(320, 480))`) passes `expect(tester.takeException(), isNull)` — client CLAUDE.md §7.

**AC7 — Accessibility (UX-DR12):**
Given screen readers are enabled (VoiceOver / TalkBack)
When a card is focused
Then its `Semantics` wrapper announces one composed label:
  - Not attempted: `"<title>. <tagline>. Not attempted. Tap phone to call."`
  - In progress:    `"<title>. <tagline>. Best ${bestScore}%, ${attempts} attempts, in progress. Tap phone to call, tap report to view debrief."`
  - Completed:      `"<title>. <tagline>. Best 100%, ${attempts} attempts, completed. Tap phone to call, tap report to view debrief."`
And the screen-reader string is built by a pure helper `_buildCardSemanticsLabel(scenario)` that is unit-tested for all three states (no widget-tree dependency).

**AC8 — Theme-token enforcement (UX-DR1 + client CLAUDE.md §6):**
Given `test/core/theme/theme_tokens_test.dart` scans `lib/**` for raw hex-color literals
When this story lands
Then every colour used in the scenario list + card comes from `AppColors` — no `Color(0xFF...)` in scenario files, no `Colors.red` / `Colors.white`, no ad-hoc `Color.fromARGB`
And every font size + weight comes from `AppTypography` (either via `Theme.of(context).textTheme.labelMedium` etc., or by referencing `AppTypography.cardTitle` directly — both are acceptable because `app_theme.dart:57-59` has already mapped `labelMedium → cardTitle`, `labelSmall → cardStats`, `displaySmall → cardTagline`)
And every spacing number comes from `AppSpacing.*` — no magic `12.0` or `24.0` in the new files.

**AC9 — Router integration + existing tests stay green:**
Given the root placeholder in `lib/app/router.dart:96-106` currently renders `Text('Scenario List — Story 5.2')`
When this story replaces it with the real `ScenarioListScreen` behind a `BlocProvider<ScenariosBloc>`
Then `app_test.dart` (6 tests — lines 45, 74, 105, 138, 172, 210) is updated:
  - "App renders scenario list when returning user is authenticated" (line 74) and "App stays at root for authenticated user who already saw first call" (line 210) flip their assertion from `expect(find.text('Scenario List — Story 5.2'), findsOneWidget)` to either:
    (a) `expect(find.byType(ScenarioListScreen), findsOneWidget)` — preferred, stable against copy changes
    (b) OR a specific marker the new screen renders (e.g. a `Key('scenario-list-screen')` on the top-level `Scaffold`)
  - "App redirects authenticated user who has not seen first call to /incoming-call" (line 172) already asserts `findsNothing` for the old placeholder — update to `findsNothing` for `ScenarioListScreen`
And the root `GoRoute` now supplies a `BlocProvider<ScenariosBloc>` whose `create:` dispatches `LoadScenariosEvent()` immediately — follow the same pattern the incoming-call route uses (router.dart line 153-160) for route-scoped blocs.

**AC10 — Pre-commit validation gates:**
Given pre-commit requirements from CLAUDE.md + client/CLAUDE.md
When the story is complete
Then `cd client && flutter analyze` prints "No issues found!" — every info-level lint fixed or explicitly silenced with rationale comment
And `cd client && flutter test` prints "All tests passed!" — ~18+ new widget/unit/bloc tests plus ALL pre-existing tests still green (app_test.dart, auth, onboarding, call-feature, theme_tokens_test.dart, dependencies_smoke_test.dart)
And `cd server && python -m ruff check . && python -m ruff format --check . && pytest` stay green (this story touches ZERO server code but CI gates the full matrix)
And `test/core/theme/theme_tokens_test.dart` still passes (no raw hex literals added — AC8).

## Tasks / Subtasks

- [ ] Task 1: Add `Scenario` model with tagline fallback (AC: 1, 4)
  - [ ] 1.1 Create `client/lib/features/scenarios/models/scenario.dart` with fields: `id (String)`, `title (String)`, `difficulty (String)`, `isFree (bool)`, `riveCharacter (String)`, `languageFocus (List<String>)`, `contentWarning (String?)`, `bestScore (int?)`, `attempts (int)`, `tagline (String)` — all `final`
  - [ ] 1.2 `factory Scenario.fromJson(Map<String, dynamic> json)` — map snake_case → camelCase per the table in Dev Notes → Scenario model, coerce `is_free: bool`, `language_focus: List<String>` via `(json['language_focus'] as List).cast<String>()`, `attempts: json['attempts'] as int? ?? 0`, `best_score: json['best_score'] as int?`
  - [ ] 1.3 Resolve `tagline` from the client-side `kScenarioTaglines` map (see Task 2) by keying on `id`; if the id is absent from the map, default to empty string `''` (so the card still renders 2 lines without crashing — Walid will fill in any missing tagline before launch)
  - [ ] 1.4 Add a `bool get isCompleted => bestScore == 100` and `bool get isNotAttempted => attempts == 0` — keep the card widget declarative
  - [ ] 1.5 DO NOT implement `toJson` — the client never sends a Scenario back to the server. Keep the model read-only for now.
  - [ ] 1.6 DO NOT add `Equatable` or `copyWith` — the Scenario list is rebuilt wholesale on every `ScenariosLoaded` emission; value equality isn't needed yet. Add it later if a diff optimisation proves worthwhile.

- [ ] Task 2: Add `kScenarioTaglines` map as launch content (AC: 4)
  - [ ] 2.1 Create `client/lib/features/scenarios/models/scenario_taglines.dart` with `const Map<String, String> kScenarioTaglines`
  - [ ] 2.2 Seed the 5 known scenario ids with short, punchy, italic-ready one-liners (≤ 40 chars each to avoid a 3rd wrap line on 320-px screens):
    ```dart
    const Map<String, String> kScenarioTaglines = {
      'waiter_easy_01': 'Order before she loses it',
      'mugger_medium_01': 'Give me your wallet',
      'girlfriend_medium_01': "You're cheating on me, aren't you?",
      'cop_hard_01': 'Step out of the vehicle',
      'landlord_hard_01': "Rent's overdue. Again.",
    };
    ```
  - [ ] 2.3 Add a one-line file header comment: `// Launch content. Move server-side (scenarios.tagline column) post-MVP — see tech-debt note in Story 5.2.`
  - [ ] 2.4 DO NOT wrap this in a class or add `const` constructor machinery — a top-level const Map is the lightest possible shape for content-like lookups and is consistent with `TutorialScenario` (static constants in a dedicated file).

- [ ] Task 3: Add `ScenariosRepository` (AC: 1)
  - [ ] 3.1 Create `client/lib/features/scenarios/repositories/scenarios_repository.dart` mirroring `CallRepository` (13-line file) — constructor takes `ApiClient`, single async method `Future<List<Scenario>> fetchScenarios()`
  - [ ] 3.2 Call `_apiClient.get<Map<String, dynamic>>('/scenarios')`, pull `response.data!['data'] as List<dynamic>`, map each to `Scenario.fromJson(e as Map<String, dynamic>)`, return `.toList()`
  - [ ] 3.3 Let any `ApiException` bubble up — `ApiClient` already converts `DioException` to `ApiException` in the interceptor, so the repo is a thin passthrough
  - [ ] 3.4 DO NOT call `/scenarios/{id}` here — this story only needs the list; the detail endpoint is Story 6.1's territory
  - [ ] 3.5 Unit-test parsing (see Task 8) covers: happy envelope with 5 items, empty list `{"data": []}`, malformed shape throws `TypeError`, `ApiException` passthrough

- [ ] Task 4: Build `ScenariosBloc` + events + states (AC: 2)
  - [ ] 4.1 Create `client/lib/features/scenarios/bloc/scenarios_event.dart` with sealed base + `LoadScenariosEvent` (const, no args). Follow the pattern in `auth_event.dart` — sealed class, `final class LoadScenariosEvent extends ScenariosEvent { const LoadScenariosEvent(); }`
  - [ ] 4.2 Create `client/lib/features/scenarios/bloc/scenarios_state.dart` with: `sealed class ScenariosState`, `final class ScenariosInitial extends ScenariosState { const ScenariosInitial(); }`, `ScenariosLoading`, `ScenariosLoaded(List<Scenario> scenarios)` (store as `final List<Scenario>` — accept `const` ctor on states that have no payload)
  - [ ] 4.3 Create `client/lib/features/scenarios/bloc/scenarios_bloc.dart` — constructor takes `ScenariosRepository`, super-initialises `ScenariosInitial()`, registers `on<LoadScenariosEvent>(_onLoad)`
  - [ ] 4.4 `_onLoad`: emit `ScenariosLoading()` → try `await _repo.fetchScenarios()` → emit `ScenariosLoaded(list)` → on `ApiException` emit `ScenariosError(e.message)`
  - [ ] 4.5 Beware the **same-const BlocListener skip** gotcha (client CLAUDE.md §4): if a retry might emit `const ScenariosLoading()` twice, flutter_bloc will dedupe the second. For this story the user-retry path goes `Loaded → Loading → (Loaded|Error)` so dedupe is not an issue — but keep the `Loading` state instance-not-const-tagged to be safe (see `auth_state.dart` which deliberately uses `class AuthLoading extends AuthState {}` without `const`, for the same reason). Mirror that choice here.

- [ ] Task 5: Build `ScenarioCard` widget (AC: 4, 5, 7, 8)
  - [ ] 5.1 Create `client/lib/features/scenarios/views/widgets/scenario_card.dart` — `StatelessWidget` with required `final Scenario scenario`, `final VoidCallback onCallTap`, `final VoidCallback? onReportTap`
  - [ ] 5.2 Layout: `Semantics(label: _buildCardSemanticsLabel(scenario), child: Padding(vertical: AppSpacing.cardInternalPaddingVertical, child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [_avatar, SizedBox(width: 10), Expanded(child: _textColumn), _actions])))`
  - [ ] 5.3 `_avatar` — `Container(width: 50, height: 50, decoration: BoxDecoration(shape: BoxShape.circle, color: AppColors.avatarBg))`. DO NOT attempt Rive here — avatars on the list are plain circles for MVP (UX spec line 591-592 explicitly defines #414143 flat circle — no character puppet). Epic 2 Story 2.7 deliverables provided character thumbnails but they're not in scope for MVP launch; just render the circle.
  - [ ] 5.4 `_textColumn` — `Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [title, SizedBox(height: AppSpacing.cardTextGap), tagline, if (!scenario.isNotAttempted) ...[SizedBox(height: AppSpacing.cardTextGap), stats]])`. Use `Text` with `AppTypography.cardTitle`/`cardTagline`/`cardStats` styles plus `.copyWith(color: AppColors.textPrimary)` where needed. For stats, build a `Text.rich` with 2 spans ("Best: " always textPrimary, then `"${score}% · ${attempts} attempts"` in the conditional color).
  - [ ] 5.5 `_actions` — `Row(mainAxisSize: MainAxisSize.min, children: [if (onReportTap != null) _iconButton(Icons.assignment_outlined or Icons.description_outlined, label: 'View debrief', onTap: onReportTap!, SizedBox(width: AppSpacing.cardIconGap)), _iconButton(Icons.phone_outlined, label: 'Call ${scenario.title}', onTap: onCallTap)])`. Each `_iconButton` is an `InkResponse` (circle) wrapped in `Semantics(button: true, label: ...)` with `SizedBox(width: AppSpacing.touchTargetComfortable, height: AppSpacing.touchTargetComfortable)` container (48×48 touch target, 24×24 painted icon centered). Icon color = `AppColors.textPrimary`, size = `AppSpacing.iconSmall`.
  - [ ] 5.6 Pure helper `String _buildCardSemanticsLabel(Scenario s)` that returns the composed label from AC7. Keep it at the top of the file as a free function so it's directly importable in a unit test.
  - [ ] 5.7 DO NOT make the entire card tappable — tapping the row background does nothing (UX-DR17 emphasizes phone icon as the single call trigger). Only the two icons are interactive. Tap feedback = InkResponse ripple contained to each icon's circle.
  - [ ] 5.8 DO NOT use `MaterialButton`, `ElevatedButton`, or any coloured button — monochrome rule (UX §539 + 1139).

- [ ] Task 6: Build `ScenarioListScreen` (AC: 3, 5, 9)
  - [ ] 6.1 Create `client/lib/features/scenarios/views/scenario_list_screen.dart` — `StatelessWidget` that uses `BlocBuilder<ScenariosBloc, ScenariosState>`
  - [ ] 6.2 `Scaffold(backgroundColor: AppColors.background, body: SafeArea(top: true, bottom: false, child: …))` — `bottom: false` because Story 5.3's BottomOverlayCard will extend into the bottom safe area
  - [ ] 6.3 Wrap inner body in `Padding(padding: EdgeInsets.symmetric(horizontal: AppSpacing.screenHorizontal, vertical: AppSpacing.screenVerticalList))`
  - [ ] 6.4 For `ScenariosInitial` and `ScenariosLoading` → return `const SizedBox.shrink()` (blank on dark bg — no spinner, UX §539 + client CLAUDE.md §10)
  - [ ] 6.5 For `ScenariosLoaded(scenarios)` → return `ListView.separated(itemCount: scenarios.length, separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.cardGap), itemBuilder: (context, i) => ScenarioCard(scenario: scenarios[i], onCallTap: () => _onCallTap(context, scenarios[i]), onReportTap: scenarios[i].isNotAttempted ? null : () => _onReportTap(context, scenarios[i])))`
  - [ ] 6.6 For `ScenariosError(message)` → `Center(child: GestureDetector(behavior: HitTestBehavior.opaque, onTap: () => context.read<ScenariosBloc>().add(const LoadScenariosEvent()), child: Column(mainAxisSize: MainAxisSize.min, children: [Text(message, style: AppTypography.body.copyWith(color: AppColors.destructive), textAlign: TextAlign.center), SizedBox(height: AppSpacing.base), Text('Tap to retry', style: AppTypography.caption.copyWith(color: AppColors.textSecondary))])))`
  - [ ] 6.7 `_onCallTap(context, scenario)` → `context.go(AppRoutes.call, extra: scenario)` (router.dart already defensively falls back on non-CallSession extras — line 167-180 — so this will display the placeholder "No active call" until Story 6.1 swaps the route, which is intentional for end-to-end smoke-testability)
  - [ ] 6.8 `_onReportTap(context, scenario)` → `context.go('${AppRoutes.debrief}/${scenario.id}')` (add the route — Task 7)

- [ ] Task 7: Wire the router + add debrief placeholder route (AC: 5, 9)
  - [ ] 7.1 In `lib/app/router.dart`, add `static const String debrief = '/debrief';` to `AppRoutes`
  - [ ] 7.2 Replace the `AppRoutes.root` `GoRoute` (lines 96-106) — its `pageBuilder` now returns `_fadePage(key: state.pageKey, child: BlocProvider<ScenariosBloc>(create: (_) => ScenariosBloc(ScenariosRepository(ApiClient()))..add(const LoadScenariosEvent()), child: const ScenarioListScreen()))`
  - [ ] 7.3 Add a new `GoRoute(path: '${AppRoutes.debrief}/:scenarioId', pageBuilder: (context, state) => _fadePage(key: state.pageKey, child: _DebriefPlaceholderScreen(scenarioId: state.pathParameters['scenarioId'] ?? 'unknown')))`
  - [ ] 7.4 Define `_DebriefPlaceholderScreen` as a file-private widget in `router.dart` OR in `client/lib/features/debrief/views/debrief_placeholder_screen.dart` (preferred — mirrors `CallPlaceholderScreen`). It renders a `Scaffold` with centered `Text('Debrief placeholder — scenario $scenarioId (Story 7.x)')` using `AppTypography.body.copyWith(color: AppColors.textPrimary)`. Add a back-arrow `IconButton` in the app bar (or a plain `SafeArea + Padding` + `IconButton(icon: Icons.arrow_back, onPressed: () => context.go(AppRoutes.root))`) so the user can return from the stub.
  - [ ] 7.5 Import `../features/scenarios/bloc/scenarios_bloc.dart`, `../features/scenarios/bloc/scenarios_event.dart`, `../features/scenarios/repositories/scenarios_repository.dart`, `../features/scenarios/views/scenario_list_screen.dart` at the top of router.dart. Keep imports alphabetically grouped the way they already are.
  - [ ] 7.6 DO NOT promote `ScenariosBloc` to a top-level `MultiBlocProvider` in `app.dart` — route-scoped is the right pattern here because the bloc's lifetime should equal the list screen's (matches how `IncomingCallBloc` is scoped). If Story 5.3 needs the same data on the same route it can `context.read<ScenariosBloc>()` from the nested widget tree; if it needs it on a different route, extract a shared store later.

- [ ] Task 8: Unit tests — model + repository (AC: 1, 4)
  - [ ] 8.1 Create `client/test/features/scenarios/models/scenario_test.dart` — 5 tests:
    - `fromJson` maps every API field correctly for a fully-populated row (use the `GET /scenarios` example payload from the Story 5.1 Dev Notes as fixture)
    - `fromJson` defaults `attempts` to 0 when missing (`{}` without the key)
    - `fromJson` handles `best_score: null` as Dart `null`
    - `fromJson` hydrates `tagline` from `kScenarioTaglines` for a known id (`waiter_easy_01`)
    - `fromJson` hydrates `tagline` to `''` for an unknown id
  - [ ] 8.2 Create `client/test/features/scenarios/repositories/scenarios_repository_test.dart` — mirrors `call_repository_test.dart` (3 tests):
    - parses the envelope and returns 5 `Scenario` objects when the API returns the happy list
    - propagates `ApiException` from `ApiClient.get`
    - throws `TypeError` on malformed `{ "unexpected": "shape" }` (matches the existing regression harness)
  - [ ] 8.3 Unit-test the `_buildCardSemanticsLabel(scenario)` helper at `client/test/features/scenarios/views/widgets/scenario_card_semantics_label_test.dart` — 3 tests, one per state (not-attempted / in-progress / completed). Import the helper directly from `scenario_card.dart` (make it a top-level free function, not a private method on the widget, so it's testable without pumping).

- [ ] Task 9: Bloc tests (AC: 2)
  - [ ] 9.1 Create `client/test/features/scenarios/bloc/scenarios_bloc_test.dart` — mirror `incoming_call_bloc_test.dart` skeleton (setUp + `blocTest`):
    - `setUpAll`: `registerFallbackValue(const LoadScenariosEvent())` (client CLAUDE.md §2 — sealed-class mock fallback must be a concrete event, not a `Fake extends`)
    - `setUp`: `FlutterSecureStorage.setMockInitialValues({})` (client CLAUDE.md §1 — even though this bloc doesn't touch secure storage, the transitive import chain through `ApiClient` → `TokenStorage` does; tests will crash in CI without it)
  - [ ] 9.2 Tests to write (4 minimum):
    - happy path: repo returns 5 scenarios → emits `[ScenariosLoading, ScenariosLoaded]` and the `scenarios` field length is 5
    - error path: repo throws `ApiException(code: 'NETWORK_ERROR', message: 'No internet…')` → emits `[ScenariosLoading, ScenariosError]` with `.message == 'No internet…'`
    - 401 path: repo throws `ApiException(code: 'AUTH_UNAUTHORIZED', message: '…')` → emits `[ScenariosLoading, ScenariosError]` (bloc is agnostic to the specific code — router-level logout is a future concern, not this story)
    - retry path: after `ScenariosError`, dispatching `LoadScenariosEvent` again goes `[ScenariosLoading, ScenariosLoaded]` with a fresh list
  - [ ] 9.3 DO NOT mock `ApiClient` or `Dio` — mock at the `ScenariosRepository` boundary. The repo is already thin-tested in 8.2.

- [ ] Task 10: Widget tests — ScenarioCard (AC: 4, 5, 6, 7, 8)
  - [ ] 10.1 Create `client/test/features/scenarios/views/widgets/scenario_card_test.dart`:
    - setUp: `FlutterSecureStorage.setMockInitialValues({})` + `tester.binding.setSurfaceSize(const Size(320, 480))` + `addTearDown(() => tester.binding.setSurfaceSize(null))` — client CLAUDE.md §1 + §7
    - wrap the widget in a `MaterialApp(theme: AppTheme.dark(), home: Scaffold(body: ScenarioCard(…)))` harness helper
  - [ ] 10.2 Tests (6 minimum):
    - not-attempted renders 2 text lines (title + tagline), report icon is absent, phone icon is present
    - in-progress (bestScore 73, attempts 3) renders 3 text lines, "73%" appears in the `statusInProgress` color, report icon is visible
    - completed (bestScore 100, attempts 2) renders 3 text lines, "100%" appears in the `statusCompleted` color, report icon is visible
    - tapping phone icon fires the `onCallTap` callback exactly once (use `tester.tap(find.byIcon(Icons.phone_outlined))` or `find.bySemanticsLabel(…)`)
    - tapping report icon fires `onReportTap` exactly once when provided
    - no overflow at 320×480 with text-scaler 1.5 (`MediaQuery(data: MediaQueryData(textScaler: TextScaler.linear(1.5)), child: …)`) — `expect(tester.takeException(), isNull)` + no red overflow bar
  - [ ] 10.3 Theme-tokens test (`test/core/theme/theme_tokens_test.dart`) MUST still pass — run it explicitly once while iterating: `flutter test test/core/theme/theme_tokens_test.dart`

- [ ] Task 11: Widget tests — ScenarioListScreen (AC: 3, 6, 9)
  - [ ] 11.1 Create `client/test/features/scenarios/views/scenario_list_screen_test.dart`:
    - use `MockBloc<ScenariosEvent, ScenariosState>` pattern from `app_test.dart:14-18`
    - harness wraps the screen in `BlocProvider<ScenariosBloc>.value(value: mockBloc)` inside a `MaterialApp(theme: AppTheme.dark(), home: ScenarioListScreen())`
  - [ ] 11.2 Tests (5 minimum):
    - `ScenariosLoading` → no spinner, no error, Scaffold is rendered with dark background, no `ScenarioCard` instances
    - `ScenariosLoaded([scenario1, scenario2])` → `find.byType(ScenarioCard)` returns 2, in the order given (assert `scenario1.title` appears above `scenario2.title` using `tester.getTopLeft`)
    - `ScenariosError('No internet connection. Please check your network and try again.')` → the message and "Tap to retry" both render in their respective styles
    - tapping the error area dispatches `LoadScenariosEvent` on the bloc (`verify(() => mockBloc.add(any<LoadScenariosEvent>()))`)
    - `ScenariosLoaded` with 5 items renders the entire list without overflow at 320×480 (no red overflow bar, `takeException` null)

- [ ] Task 12: Update `app_test.dart` assertions (AC: 9)
  - [ ] 12.1 Replace `find.text('Scenario List — Story 5.2')` at lines 101 and 236 with `find.byType(ScenarioListScreen)` (import the class). Use `findsOneWidget`.
  - [ ] 12.2 Replace `find.text('Scenario List — Story 5.2')` at line 207 (inside "first call redirect" test) with `find.byType(ScenarioListScreen)` + `findsNothing`. The assertion semantics stay identical.
  - [ ] 12.3 For the "returning user / already saw first call" tests to work, the `ScenarioListScreen` widget tree must not throw on pump with an unstubbed `ScenariosBloc` default. Given the route creates its own `ScenariosBloc(ScenariosRepository(ApiClient()))`, the test will hit the real `Dio` stack and fail. **Mitigation:** stub `ApiClient` HTTP calls via a wrapper, OR expose `ScenariosBloc` as a widget-tree override through `App`'s constructor (add an optional `scenariosBloc` parameter, matching the existing `authBloc`/`onboardingBloc` overrides — preferred, keeps app_test.dart self-contained).
  - [ ] 12.4 If the "inject via App param" path is taken (recommended — clean, symmetric): add `final ScenariosBloc? scenariosBloc` to `App`, promote it to the route via a `BlocProvider.value` wrapper around the root `GoRoute`'s page (or via MultiBlocProvider one level up). In `_AppState`, the `initState` block gets a third bloc-setup branch (see app.dart lines 44-60 — mirror the `authBloc`/`onboardingBloc` pattern). Remember `dispose()` must only close the bloc if the app constructed it (app.dart:69-78).
  - [ ] 12.5 Update every `app_test.dart` test that lands on root to stub `mockScenariosBloc.state = ScenariosLoaded([])` + `whenListen(mockScenariosBloc, const Stream<ScenariosState>.empty(), initialState: ScenariosLoaded([]))`. Empty list is fine — the tests just assert the screen renders, not the card contents.

- [ ] Task 13: Dependencies smoke test (AC: 10)
  - [ ] 13.1 `client/test/dependencies_smoke_test.dart` already exists — check it still passes unchanged (no new deps added, so it should)
  - [ ] 13.2 DO NOT add any new `pubspec.yaml` dependency — everything needed is already present (`flutter_bloc`, `dio`, `go_router`, `mocktail`, `bloc_test`, `flutter_secure_storage`). Any new dep is a scope-creep red flag.

- [ ] Task 14: Pre-commit validation (AC: 10)
  - [ ] 14.1 `cd client && flutter analyze` → "No issues found!" (zero errors, zero warnings, zero infos — infos block CI per project + client CLAUDE.md)
  - [ ] 14.2 `cd client && flutter test` → "All tests passed!" — run the whole suite (no selective `flutter test path/to/one_test.dart`); count that the new tests bring the total up by 18+ and no existing test regressed
  - [ ] 14.3 `cd server && python -m ruff check . && python -m ruff format --check . && pytest` stays green — this story touches no server code but CI gates it
  - [ ] 14.4 Update `sprint-status.yaml`: `ready-for-dev → in-progress` AT START, `in-progress → review` AT END (dev Phase 8.5). Memory rule: Epic 1 Retro Lesson — sprint-status discipline is non-negotiable.
  - [ ] 14.5 **DO NOT commit autonomously.** Memory rule (Git Commit Rules): Walid invokes `/commit` or says "commit ça" explicitly. Dev workflow stops at "review" status.

## Dev Notes

### Scope Boundary (What This Story Does and Does NOT Do)

| In scope (this story) | Out of scope (later stories) |
|---|---|
| `Scenario` model + `fromJson` | `toJson` — client never posts scenarios |
| `ScenariosRepository` + `fetchScenarios()` | `fetchScenarioDetail(id)` — Story 6.1 |
| `ScenariosBloc` with `LoadScenariosEvent` | Content-warning dialog — Story 5.4 |
| `ScenarioCard` widget (3 states) | BottomOverlayCard + daily call limits — Story 5.3 |
| `ScenarioListScreen` (Loading / Loaded / Error) | Rive character thumbnails on the list cards — post-MVP |
| Router root route swap (`/` → `ScenarioListScreen`) | Call-initiate call flow on phone-icon tap — Story 6.1 wires real `/call` with Rive |
| `/debrief/:scenarioId` route + placeholder screen | Real debrief screen + generation — Epic 7 |
| Client-side `kScenarioTaglines` map | Server-side `scenarios.tagline` column — tracked as post-MVP tech debt |
| Inline error UX on list load failure | Offline cache / sqflite mirror — Epic 9 (Story 9.1) |

### Tagline — Pragmatic Client-Side Map (Tech Debt Callout)

**UX-DR4 + Story 5.2 AC4 both require a "tagline" on the ScenarioCard**, but the authoring YAMLs (`_bmad-output/planning-artifacts/scenarios/*.yaml`) have no `tagline` field and ADR 001 (scenarios-schema) frozen the `scenarios` column list without one. Story 5.1 ships without a `tagline` column in the DB.

**Decision for MVP launch:** tagline lives client-side in `features/scenarios/models/scenario_taglines.dart` as a `const Map<String, String>` keyed by `scenario_id`. The Scenario model joins on this map in `fromJson`. Missing-key fallback is `''` (empty tagline → 1-line card gracefully).

**Why this is OK:**
- Launch content is fixed (5 scenarios). Adding a 6th scenario = one-line YAML edit PLUS a one-line map edit. Not invisible friction, but not much.
- The alternative (adding a `tagline` column now) is a full server-side change: ADR amendment + migration 005 + seeder field + AC test sweep + redeploy. Delays Flutter launch for a pure content decision.
- Walid is the sole content author — the client-side map IS the source of truth until scale makes it not.

**Tech debt tracking:** Add to `deferred-work.md` (or create if absent) under Epic 5: "Promote `scenarios.tagline` to server column + migration + seeder + API list/detail shape, so new scenarios can ship without a Flutter redeploy." Priority: **Post-MVP, before first non-founder scenario authoring (~Epic 10 or early post-launch)**.

### Scenario Model — JSON → Dart Mapping

The Story 5.1 LIST-ITEM shape is our contract. This table is the single source of truth for the `fromJson` factory:

| JSON key (API) | Dart field | Type | Transform |
|---|---|---|---|
| `id` | `id` | `String` | pass-through |
| `title` | `title` | `String` | pass-through |
| `difficulty` | `difficulty` | `String` | pass-through (`'easy'` / `'medium'` / `'hard'`) |
| `is_free` | `isFree` | `bool` | `json['is_free'] as bool` (server coerces `1/0` → `true/false` per Story 5.1 AC5) |
| `rive_character` | `riveCharacter` | `String` | pass-through |
| `language_focus` | `languageFocus` | `List<String>` | `(json['language_focus'] as List).cast<String>()` |
| `content_warning` | `contentWarning` | `String?` | `json['content_warning'] as String?` |
| `best_score` | `bestScore` | `int?` | `json['best_score'] as int?` |
| `attempts` | `attempts` | `int` | `json['attempts'] as int? ?? 0` |
| (client-side lookup) | `tagline` | `String` | `kScenarioTaglines[id] ?? ''` |

**NO snake_case leaks into Dart** — follow the architecture.md Naming Golden Rule (§454-470). Dart side is always camelCase.

### Router Changes — What Actually Swaps

**Before (router.dart:96-106):**
```dart
GoRoute(
  path: AppRoutes.root,
  pageBuilder: (context, state) => _fadePage(
    key: state.pageKey,
    child: const Scaffold(
      body: Center(
        child: Text('Scenario List — Story 5.2'),
      ),
    ),
  ),
),
```

**After (this story):**
```dart
GoRoute(
  path: AppRoutes.root,
  pageBuilder: (context, state) => _fadePage(
    key: state.pageKey,
    child: BlocProvider<ScenariosBloc>(
      create: (_) => ScenariosBloc(ScenariosRepository(ApiClient()))
        ..add(const LoadScenariosEvent()),
      child: const ScenarioListScreen(),
    ),
  ),
),
GoRoute(
  path: '${AppRoutes.debrief}/:scenarioId',
  pageBuilder: (context, state) => _fadePage(
    key: state.pageKey,
    child: DebriefPlaceholderScreen(
      scenarioId: state.pathParameters['scenarioId'] ?? 'unknown',
    ),
  ),
),
```

### State Machine (ASCII)

```
             dispatch LoadScenariosEvent
ScenariosInitial ───────────────────────► ScenariosLoading
                                               │
                            happy ◄────────────┼────────────► ApiException
                            fetchScenarios()   │
                                   │           │
                                   ▼           ▼
                             ScenariosLoaded   ScenariosError
                                  │                │
                                  │                ▼
                                  │        tap "Tap to retry"
                                  │                │
                                  └────────────────┘
                           dispatch LoadScenariosEvent again
```

### What NOT to Do

1. **Do NOT re-sort the list client-side.** The server orders easy→medium→hard→id (Story 5.1 AC4). Trusting the server is the contract; re-sorting duplicates logic and drifts.
2. **Do NOT render a spinner** on `ScenariosLoading`. UX §539 + §1137 + client CLAUDE.md §10. A blank dark scaffold is the design. The API is fast; humans perceive <300 ms as instant.
3. **Do NOT add a snackbar, toast, or dialog on error.** Inline `Text` + tap-to-retry on the full screen area is the established error UX pattern (Epic 4 `feedback_error_ux.md`). Toasts are for informational hints only.
4. **Do NOT filter the list by `isFree` client-side.** Epic 5's invisible-paywall rule (UX-DR16 + §231) — free and paid scenarios look identical. Story 5.3 handles the tap-on-paid-as-free-user path and the BottomOverlayCard.
5. **Do NOT hardcode any colour, size, or font weight.** `AppColors` + `AppSpacing` + `AppTypography`/`AppTheme` only. Theme-tokens test (client CLAUDE.md §6) will break the build otherwise.
6. **Do NOT write `Fake extends ScenariosEvent`** in tests. Sealed classes reject that. Use `registerFallbackValue(const LoadScenariosEvent())` — client CLAUDE.md §2.
7. **Do NOT use `pumpAndSettle` on ScenarioListScreen widget tests if any descendant is an animating widget** (the CharacterAvatar's Rive fallback path is static, but future iterations might add animation). Prefer explicit `pump(Duration(ms: ...))` — client CLAUDE.md §3.
8. **Do NOT emit the same `const ScenariosLoading()` instance twice in a row** from the bloc — `BlocListener` dedupes equality and the second state is silently dropped. The easy guard: don't mark `ScenariosLoading`/`ScenariosError` as `const` — have the bloc use `emit(ScenariosLoading())` with fresh instances. Pattern: `auth_state.dart` deliberately avoids `const` on `AuthLoading` for this exact reason. Client CLAUDE.md §4.
9. **Do NOT put a Rive character puppet on the list cards.** UX spec (line 591-592) says plain `#414143` circle for now. Rive is the call-screen payoff, not the list.
10. **Do NOT wire real Story 5.3 call-limit branching here.** The phone icon navigates to `/call` unconditionally in this story; the call-limit state + BottomOverlayCard gating is Story 5.3.
11. **Do NOT build a content-warning dialog here.** Story 5.4 owns that — the `contentWarning` field is carried on the model but NOT displayed in 5.2.
12. **Do NOT cache the list in memory across bloc rebuilds.** The bloc is route-scoped; when the user backgrounds/foregrounds the app or navigates away and back, a fresh fetch is the desired behavior (confirms progression changes from calls/debrief updates). Offline caching is Story 9.1.
13. **Do NOT add `/scenarios/{id}` fetching in this story.** That's Story 6.1's contract when call-initiate needs the full body.
14. **Do NOT introduce `Equatable` or `freezed` packages.** Pubspec stays untouched — pattern matches `CallSession`, `Scenario` is in the same lightweight style.
15. **Do NOT forget to update sprint-status.yaml** at start AND before review (Epic 1 Retro Lesson). Project rule — non-negotiable.
16. **Do NOT commit autonomously** — wait for Walid's "commit ça" or explicit `/commit` invocation (project memory: Git Commit Rules).
17. **Do NOT rename or delete the `TutorialScenario` constants** in `features/call/views/tutorial_scenario.dart`. Story 6.1 is the retirement point, not 5.2. For now the incoming-call screen still hardcodes "Tina" and the `waiter` Rive variant; the scenario list and the first-call flow are independent until Story 6.1 unifies them.

### Library & Version Requirements

**No new Flutter dependencies.** Everything needed is already in `pubspec.yaml`:
- `flutter_bloc: ^9.1.1` — BLoC base
- `dio: ^5.9.2` (via `ApiClient`) — HTTP
- `go_router: ^17.2.1` — routing
- `bloc_test: ^10.0.0` — bloc testing
- `mocktail: ^1.0.5` — mocks
- `flutter_secure_storage: ^10.0.0` (transitive via `ApiClient → TokenStorage`)

**No new Python dependencies.** Story touches zero server code.

### Key Imports (exact — Epic 1 Retro Lesson: #1 velocity multiplier)

```dart
// client/lib/features/scenarios/models/scenario.dart
import 'scenario_taglines.dart';
```

```dart
// client/lib/features/scenarios/repositories/scenarios_repository.dart
import '../../../core/api/api_client.dart';
import '../models/scenario.dart';
```

```dart
// client/lib/features/scenarios/bloc/scenarios_bloc.dart
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../core/api/api_exception.dart';
import '../models/scenario.dart';
import '../repositories/scenarios_repository.dart';
import 'scenarios_event.dart';
import 'scenarios_state.dart';
```

```dart
// client/lib/features/scenarios/views/widgets/scenario_card.dart
import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../models/scenario.dart';
```

```dart
// client/lib/features/scenarios/views/scenario_list_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../bloc/scenarios_bloc.dart';
import '../bloc/scenarios_event.dart';
import '../bloc/scenarios_state.dart';
import '../models/scenario.dart';
import 'widgets/scenario_card.dart';
```

```dart
// client/lib/app/router.dart (added imports)
import '../core/api/api_client.dart';
import '../features/debrief/views/debrief_placeholder_screen.dart';
import '../features/scenarios/bloc/scenarios_bloc.dart';
import '../features/scenarios/bloc/scenarios_event.dart';
import '../features/scenarios/repositories/scenarios_repository.dart';
import '../features/scenarios/views/scenario_list_screen.dart';
```

### Previous Story Intelligence

**From Story 5.1 (Scenarios API + DB):**
- `GET /scenarios` list-item shape is frozen: `id`, `title`, `difficulty`, `is_free`, `rive_character`, `language_focus` (array), `content_warning` (nullable), `best_score` (nullable int), `attempts` (int). NO tagline column. NO price field. Server never tier-filters (the full list always comes back).
- Envelope: `{"data": [...], "meta": {"count": N, "timestamp": "..."}}`. The client parses `data` — meta is advisory.
- Ordering: easy → medium → hard, tiebreak by `id` — server-enforced. Client trusts and does NOT re-sort.
- 5 scenarios are seeded: `waiter_easy_01`, `girlfriend_medium_01`, `mugger_medium_01`, `cop_hard_01`, `landlord_hard_01`. 3 are free (waiter, mugger, girlfriend), 2 are paid (cop, landlord).
- Error envelope: `{"error": {"code": "SCENARIO_NOT_FOUND" | "AUTH_UNAUTHORIZED" | ...}}` — already parsed by `ApiException.fromDioException` (`lib/core/api/api_exception.dart`).

**From Story 4.5 (First-call incoming UX):**
- `CharacterAvatar` pattern: Rive gated on `RiveNative.isInitialized` + `rootBundle.load()` pre-check + fallback to plain colored `ClipOval`. Do not copy it for list cards — UX spec says plain circle for MVP, no Rive.
- Route-scoped `BlocProvider` pattern: `IncomingCallBloc` is created INSIDE the GoRoute's `pageBuilder`, not promoted to `MultiBlocProvider`. Same pattern for `ScenariosBloc` in this story.
- `context.go(AppRoutes.x, extra: object)` is the navigation idiom; the `/call` route has a defensive non-CallSession fallback.
- Error on a transitional screen → `_fadeController.forward()` → `context.go(fallback)`. In this story the fallback is the screen itself (retry in place), not a fade-nav — but the principle (inline, not modal) is what carries.

**From Story 4.3 (Email auth flow):**
- Inline error `Text` with `AppColors.destructive` is the established pattern for field-level + operation errors (`feedback_error_ux.md` in project memory). No snackbar / dialog / toast.
- `serverError` boolean state held on the screen, toggled on bloc emissions via `BlocListener`. `ScenarioListScreen` does it simpler: reads the bloc state directly in `BlocBuilder` since the error is not interleaved with user input.

**From Story 4.1b (Design system):**
- `AppColors`, `AppSpacing`, `AppTypography` are the ONLY color/spacing/typography sources. `app_theme.dart` maps TextTheme slots to `AppTypography.cardTitle`/`cardTagline`/`cardStats` — you can use either `Theme.of(context).textTheme.labelMedium` or `AppTypography.cardTitle` directly; both are kosher.
- `theme_tokens_test.dart` scans for hex literals outside `lib/core/theme/` — test will fail if the new scenario files hardcode any color.

**From Story 4.1 (Monorepo restructure):**
- `features/<name>/{bloc,models,repositories,views}/` is the established subfolder shape. The `views/` folder may contain a `widgets/` subfolder for reusable widgets used only by that feature (see `features/call/views/widgets/character_avatar.dart`). Story 5.2 follows exactly: `features/scenarios/{bloc,models,repositories,views,views/widgets}/`.

**From Epic 4 Retro (2026-04-23):**
- **AI-A: `client/CLAUDE.md` gotcha doc is live.** Read it before touching any Flutter test. The ten gotchas captured in §1-10 are all relevant to this story — particularly §1 (setMockInitialValues), §2 (sealed-class mock fallback), §3 (pumpAndSettle hangs), §4 (same-const BlocListener skip), §6 (theme-tokens test), §7 (test viewport), §10 (inline error UX).
- **Post-implementation UX iteration is the feature, not a defect** (`feedback_mvp_iteration_strategy.md`). Build the straight-line story, then Walid will review and iterate via Figma-extract handoff if needed. Don't over-design for speculative copy/layout changes.
- **No Smoke Test Gate.** This story is Flutter-client-only — no server endpoint changes, no DB migration, no VPS deploy. Gate applies to server/deploy stories only (template scope rule).

### Git Intelligence

Recent commit pattern to follow:
```
b0a804e feat: close Epic 4 retro action items and create Story 5.1
c00f3af feat: resolve Epic 5 blocking ADRs and add Smoke Test Gate to story template
d97ff27 feat: run Epic 4 retrospective and prepare Epic 5 kickoff
fd117b6 feat: implement first-call incoming call experience (Story 4.5)
```

Expected commit title when Walid says "commit ça":
```
feat: build scenario list screen with ScenarioCard component (Story 5.2)
```

**Files to read before starting (patterns, not modify beyond tasks):**
- `client/CLAUDE.md` — Flutter Gotchas §1-10, Architecture patterns section. READ FIRST.
- `client/lib/app/router.dart` — pageBuilder + route-scoped BlocProvider pattern (the `/incoming-call` route line 146-162 is the cleanest template)
- `client/lib/app/app.dart` — constructor-injection pattern for test overrides
- `client/lib/features/call/repositories/call_repository.dart` — thin repo shape, envelope-unpacking idiom
- `client/lib/features/call/bloc/incoming_call_bloc.dart` — sealed-event bloc, `close()` lifecycle
- `client/lib/features/call/bloc/incoming_call_state.dart` — sealed state with payload variant
- `client/lib/features/auth/bloc/auth_bloc.dart` — repository-backed loading flow
- `client/lib/features/auth/bloc/auth_state.dart` — sealed states, deliberate non-const on `AuthLoading`
- `client/lib/core/api/api_client.dart` + `api_exception.dart` — interceptor contract + error envelope decoding
- `client/lib/core/theme/app_colors.dart` / `app_spacing.dart` / `app_typography.dart` — token tables
- `client/test/features/call/repositories/call_repository_test.dart` — repo test template
- `client/test/features/call/bloc/incoming_call_bloc_test.dart` — bloc test skeleton (setUp + blocTest)
- `client/test/app_test.dart` — MockBloc pattern, tests that assert on root route (MUST be updated — Task 12)
- `_bmad-output/implementation-artifacts/5-1-build-scenarios-api-and-database.md` — authoritative API contract
- `_bmad-output/planning-artifacts/ux-design-specification.md` §624-668 + §970-992 — ScenarioCard anatomy + states + accessibility
- `_bmad-output/planning-artifacts/epics.md:903-942` — Story 5.2 BDD source

### Testing Requirements

**Target:** ~22 new Dart tests.

| File | Count | Scope |
|---|---|---|
| `scenario_test.dart` (model) | 5 | fromJson mapping, tagline lookup, null handling |
| `scenarios_repository_test.dart` | 3 | envelope parse, ApiException passthrough, malformed shape |
| `scenario_card_semantics_label_test.dart` | 3 | 3-state semantics label builder |
| `scenarios_bloc_test.dart` | 4 | happy / network-error / 401 / retry |
| `scenario_card_test.dart` | 6 | 3 states rendering + 2 tap callbacks + responsive overflow |
| `scenario_list_screen_test.dart` | 5 | Loading blank, Loaded list, Error + retry dispatch, responsive |

**Mock strategy:**
- Mock `ScenariosRepository` in `scenarios_bloc_test.dart` — NOT `ApiClient`/`Dio`.
- Mock `ScenariosBloc` (extending `MockBloc<ScenariosEvent, ScenariosState>`) in `scenario_list_screen_test.dart` — NOT the repo. Keep tests at one-layer boundaries.
- `MockApiClient extends Mock implements ApiClient` for `scenarios_repository_test.dart` — mirror `call_repository_test.dart` line 8.

**Harness helpers worth factoring:**
- If `app_test.dart` + `scenario_list_screen_test.dart` both need a harness wrapping a screen in `MaterialApp(theme: AppTheme.dark())` plus bloc providers, consider a shared helper in `test/_helpers/widget_harness.dart`. Don't over-engineer on the first pass — extract only when duplication crosses 3 sites.

### Project Structure Notes

**New files (create):**
```
client/lib/features/scenarios/
├── bloc/
│   ├── scenarios_bloc.dart
│   ├── scenarios_event.dart
│   └── scenarios_state.dart
├── models/
│   ├── scenario.dart
│   └── scenario_taglines.dart
├── repositories/
│   └── scenarios_repository.dart
└── views/
    ├── scenario_list_screen.dart
    └── widgets/
        └── scenario_card.dart

client/lib/features/debrief/views/
└── debrief_placeholder_screen.dart

client/test/features/scenarios/
├── bloc/
│   └── scenarios_bloc_test.dart
├── models/
│   └── scenario_test.dart
├── repositories/
│   └── scenarios_repository_test.dart
└── views/
    ├── scenario_list_screen_test.dart
    └── widgets/
        ├── scenario_card_test.dart
        └── scenario_card_semantics_label_test.dart
```

**Files to modify:**
- `client/lib/app/router.dart` — root route swap + add debrief route + imports
- `client/lib/app/app.dart` — add optional `scenariosBloc` constructor param + wire into `_AppState.initState` (mirror `authBloc`/`onboardingBloc` override pattern)
- `client/test/app_test.dart` — update 3 assertions + stub `ScenariosBloc` in tests that land on `/`

**Files to verify but DO NOT modify:**
- `client/lib/core/api/api_client.dart` / `api_exception.dart` — contract; do not tweak for this story
- `client/lib/core/theme/*.dart` — design-system is Story 4.1b's contract
- `client/lib/features/call/**` — untouched by 5.2
- `client/lib/features/auth/**` — untouched
- `client/pubspec.yaml` — no new deps
- `server/**/*.py` — zero server touches

**Alignment with architecture.md §Frontend Folder (lines 798-808):** the target layout matches the planned structure exactly. No deviation.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md:903-942`] — Story 5.2 BDD acceptance criteria
- [Source: `_bmad-output/implementation-artifacts/5-1-build-scenarios-api-and-database.md`] — `GET /scenarios` authoritative contract (list-item shape + ordering + envelope)
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Screen 1: Scenario List`] (line 624-668) — scrollable list visual
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#ScenarioCard`] (line 970-992) — anatomy, three states, accessibility
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Spacing & Layout Foundation`] (line 565-620) — spacing + state color map
- [Source: `_bmad-output/planning-artifacts/epics.md#UX-DR4`] (line 207) — ScenarioCard requirements
- [Source: `_bmad-output/planning-artifacts/epics.md#UX-DR17`] (line 233) — monochrome list rule
- [Source: `_bmad-output/planning-artifacts/epics.md#UX-DR12`] (line 223) — screen reader announcements
- [Source: `_bmad-output/planning-artifacts/epics.md#UX-DR18`] — responsive 320-430 px layout
- [Source: `_bmad-output/planning-artifacts/epics.md#FR19`] — easy-to-hard ordering
- [Source: `_bmad-output/planning-artifacts/architecture.md#Frontend Architecture`] (line 325-357) — BLoC + GoRouter + Dio stack choices
- [Source: `_bmad-output/planning-artifacts/architecture.md#API Response Format`] (line 518-556) — envelope + snake_case rule
- [Source: `_bmad-output/planning-artifacts/architecture.md#Naming Patterns`] (line 454-484) — camelCase boundary
- [Source: `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-23.md#AI-A`] — `client/CLAUDE.md` Flutter gotchas doc (prereq for this story)
- [Source: `client/CLAUDE.md`] — 10 Flutter gotchas (tests, lints, error UX)
- [Source: `CLAUDE.md`] — pre-commit validation gates (flutter analyze + flutter test + ruff + pytest)
- [Source: project memory `feedback_error_ux.md`] — inline error over retry banner
- [Source: project memory `feedback_mvp_iteration_strategy.md`] — validate fast, iterate on render
- [Source: project memory (Git Commit Rules)] — NEVER commit autonomously, no Co-Authored-By, sprint-status discipline

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
