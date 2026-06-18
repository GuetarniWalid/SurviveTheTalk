import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:client/features/call/views/no_network_screen.dart';
import 'package:client/features/paywall/views/paywall_sheet.dart';
import 'package:client/features/scenarios/bloc/scenarios_bloc.dart';
import 'package:client/features/scenarios/bloc/scenarios_event.dart';
import 'package:client/features/scenarios/bloc/scenarios_state.dart';
import 'package:client/features/scenarios/models/call_usage.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/views/scenario_list_screen.dart';
import 'package:client/features/scenarios/views/widgets/bottom_overlay_card.dart';
import 'package:client/features/scenarios/views/widgets/scenario_card.dart';
import 'package:client/features/subscription/bloc/user_profile_cubit.dart';
import 'package:client/features/subscription/models/user_profile.dart';
import 'package:client/features/subscription/views/manage_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mocktail/mocktail.dart';

const _kFreshUsage = CallUsage(
  tier: 'free',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'lifetime',
);

const _kFreeExhausted = CallUsage(
  tier: 'free',
  callsRemaining: 0,
  callsPerPeriod: 3,
  period: 'lifetime',
);

// Story 8.2 (FR29) — a free user on their LAST free call (callsRemaining == 1
// at call-init → 0 after). The debrief paywall must auto-present for this user.
const _kFreeLastCall = CallUsage(
  tier: 'free',
  callsRemaining: 1,
  callsPerPeriod: 3,
  period: 'lifetime',
);

const _kPaidWithCalls = CallUsage(
  tier: 'paid',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'day',
);

const _kPaidExhausted = CallUsage(
  tier: 'paid',
  callsRemaining: 0,
  callsPerPeriod: 3,
  period: 'day',
);

class MockScenariosBloc extends MockBloc<ScenariosEvent, ScenariosState>
    implements ScenariosBloc {}

class MockCallRepository extends Mock implements CallRepository {}

/// Drives the Manage drawer (opened from the paid `Account` hub line) without
/// touching the real `GET /user/profile`.
class MockUserProfileCubit extends MockCubit<UserProfileState>
    implements UserProfileCubit {}

const _kPaidProfile = UserProfile(
  tier: 'paid',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'day',
  subscriptionExpiresAt: '2026-07-18T12:00:00Z',
);

/// Test stub that stands in for `CallScreen` so the production push goes
/// through real `Navigator.push` machinery without constructing a real
/// LiveKit `Room` (whose background timers leak across test boundaries).
///
/// Carries a stable Key so the test can assert "the call surface mounted"
/// via `find.byKey(_kCallStubKey)` instead of relying on the textual
/// "CALL_STUB" body finder, which would brittle-couple the assertion to
/// the placeholder copy.
const Key _kCallStubKey = ValueKey('call_screen_stub');

Widget _stubCallScreen(
  Scenario scenario,
  CallSession session,
  bool presentPaywallOnDebrief,
) {
  return const Scaffold(
    key: _kCallStubKey,
    body: Center(child: Text('CALL_STUB')),
  );
}

const _kFakeSession = CallSession(
  callId: 1,
  roomName: 'call-stub',
  token: 'tok',
  livekitUrl: 'wss://stub',
);

Scenario _build({
  required String id,
  required String title,
  String tagline = 'Tagline',
  int? bestScore,
  int attempts = 0,
  String? contentWarning,
  Map<String, String>? briefing,
  bool isFree = true,
}) {
  return Scenario(
    id: id,
    title: title,
    isFree: isFree,
    riveCharacter: 'waiter',
    languageFocus: const <String>[],
    contentWarning: contentWarning,
    bestScore: bestScore,
    attempts: attempts,
    tagline: tagline,
    briefing: briefing,
  );
}

GoRouter _router(Widget screen, MockScenariosBloc bloc) {
  return GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) => BlocProvider<ScenariosBloc>.value(
          value: bloc,
          child: screen,
        ),
      ),
      // Story 6.1: `/call` is no longer a GoRouter route — the call screen
      // is pushed via the *root* Navigator (ADR 003 §Tier 1). Tests that
      // verified navigation to a `/call` GoRoute now look for the actual
      // `CallScreen` widget instance in the tree.
      GoRoute(
        path: '/debrief/:scenarioId',
        builder: (context, state) => Scaffold(
          body: Center(
            child: Text(
              'DEBRIEF_STUB:${state.pathParameters['scenarioId']}',
            ),
          ),
        ),
      ),
      // Story 7.4 — the stub mirrors the real BriefingScreen's pop-a-bool
      // contract so the hub's gate logic is exercised end-to-end; the real
      // screen's render is covered by briefing_screen_test.dart. The
      // EXTRA line surfaces whether the hub pushed the full Scenario
      // (the production route's redirect bounces to root without it).
      GoRoute(
        path: '/briefing/:scenarioId',
        builder: (context, state) => Scaffold(
          body: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                'BRIEFING_STUB:${state.pathParameters['scenarioId']}',
              ),
              Text('BRIEFING_EXTRA_IS_SCENARIO:${state.extra is Scenario}'),
              TextButton(
                onPressed: () => context.pop(true),
                child: const Text('BRIEFING_CONFIRM'),
              ),
              TextButton(
                onPressed: () => context.pop(false),
                child: const Text('BRIEFING_DISMISS'),
              ),
            ],
          ),
        ),
      ),
    ],
  );
}

Widget _harness(
  MockScenariosBloc bloc, {
  CallRepository? callRepository,
  CallScreenBuilder? callScreenBuilder,
}) => MaterialApp.router(
  theme: AppTheme.dark(),
  routerConfig: _router(
    ScenarioListScreen(
      callRepository: callRepository,
      callScreenBuilder: callScreenBuilder ?? _stubCallScreen,
    ),
    bloc,
  ),
);

void main() {
  late MockScenariosBloc mockBloc;

  setUpAll(() {
    registerFallbackValue(const LoadScenariosEvent());
  });

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    mockBloc = MockScenariosBloc();
  });

  testWidgets('Loading shows no spinner and no ScenarioCard instances',
      (tester) async {
    when(() => mockBloc.state).thenReturn(ScenariosLoading());
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: ScenariosLoading(),
    );

    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();

    expect(find.byType(ScenarioCard), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.byType(Scaffold), findsOneWidget);
  });

  testWidgets('Loaded renders cards in the order returned by the bloc',
      (tester) async {
    final scenarios = [
      _build(id: 'a', title: 'Alpha'),
      _build(id: 'b', title: 'Beta'),
    ];
    when(() => mockBloc.state)
        .thenReturn(ScenariosLoaded(scenarios: scenarios, usage: _kFreshUsage));
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: ScenariosLoaded(scenarios: scenarios, usage: _kFreshUsage),
    );

    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();

    expect(find.byType(ScenarioCard), findsNWidgets(2));
    final alphaTop = tester.getTopLeft(find.text('Alpha')).dy;
    final betaTop = tester.getTopLeft(find.text('Beta')).dy;
    expect(alphaTop, lessThan(betaTop));
  });

  // ---------- Story 5.5 — Empathetic error view ----------

  // Code → (title, body, repeat-body, icon) tuples used by the parametrised
  // first/repeat-failure tests. Keep in lock-step with `_titleFor` /
  // `_bodyFor` / `_iconFor` in `core/widgets/empathetic_error_screen.dart`
  // (extracted from scenario_list_screen.dart in Story 6.5 Deviation #12).
  const errorCases = <Map<String, Object>>[
    {
      'code': 'NETWORK_ERROR',
      'title': "You're offline.",
      'firstBody':
          'We need a connection to load your scenarios. Check your Wi-Fi or mobile data, then try again.',
      'repeatBody':
          'Still no signal. Move somewhere with better reception, then try again.',
      'icon': Icons.cloud_off_outlined,
    },
    {
      'code': 'SERVER_ERROR',
      'title': 'Our servers are catching their breath.',
      'firstBody': 'This is on us, not you. Try again in a moment.',
      'repeatBody':
          'Still struggling on our side. Give it a minute and try again, or restart the app if it persists.',
      'icon': Icons.hourglass_empty_outlined,
    },
    {
      'code': 'MALFORMED_RESPONSE',
      'title': "Something didn't load right.",
      'firstBody':
          "We've logged the issue. Try again — it usually works on the second try.",
      'repeatBody': 'Still stuck. Restart the app to clear the slate.',
      'icon': Icons.help_outline,
    },
    {
      'code': 'UNKNOWN_ERROR',
      'title': 'Something went wrong.',
      'firstBody': "We're not sure what happened. Try again in a moment.",
      'repeatBody': 'Still failing. Restart the app if this keeps happening.',
      'icon': Icons.error_outline,
    },
  ];

  Future<void> pumpErrorState(
    WidgetTester tester, {
    required String code,
    required int retryCount,
  }) async {
    // 390×844 = iPhone 14 viewport (matches Figma `iPhone 16 - 8` reference
    // class). The Story 5.5 redesign is calibrated for this size; smaller
    // phones get an explicit overflow-sanity test below.
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final state = ScenariosError(code: code, retryCount: retryCount);
    when(() => mockBloc.state).thenReturn(state);
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: state,
    );

    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();
  }

  for (final c in errorCases) {
    testWidgets(
      '${c['code']}: first failure renders title + first-body + icon + Try again',
      (tester) async {
        await pumpErrorState(
          tester,
          code: c['code'] as String,
          retryCount: 0,
        );

        expect(find.text(c['title'] as String), findsOneWidget);
        expect(find.text(c['firstBody'] as String), findsOneWidget);
        expect(find.byIcon(c['icon'] as IconData), findsOneWidget);
        expect(find.text('Try again'), findsOneWidget);
      },
    );

    testWidgets(
      '${c['code']}: retryCount=1 swaps first-body for repeat-body (title sticky)',
      (tester) async {
        await pumpErrorState(
          tester,
          code: c['code'] as String,
          retryCount: 1,
        );

        expect(find.text(c['title'] as String), findsOneWidget);
        expect(find.text(c['repeatBody'] as String), findsOneWidget);
        expect(find.text(c['firstBody'] as String), findsNothing);
      },
    );
  }

  testWidgets(
    'retryCount=5 still shows the repeat (retryCount>=1) variant — no third tier',
    (tester) async {
      await pumpErrorState(
        tester,
        code: 'NETWORK_ERROR',
        retryCount: 5,
      );

      expect(
        find.text(
          'Still no signal. Move somewhere with better reception, then try again.',
        ),
        findsOneWidget,
      );
      expect(
        find.text(
          'We need a connection to load your scenarios. Check your Wi-Fi or mobile data, then try again.',
        ),
        findsNothing,
      );
    },
  );

  testWidgets(
    'tapping the "Try again" button dispatches LoadScenariosEvent',
    (tester) async {
      await pumpErrorState(
        tester,
        code: 'UNKNOWN_ERROR',
        retryCount: 0,
      );

      await tester.tap(find.text('Try again'));
      await tester.pump();

      verify(() => mockBloc.add(any<LoadScenariosEvent>())).called(1);
    },
  );

  testWidgets(
    'tapping the empty space outside the button does NOT dispatch LoadScenariosEvent',
    (tester) async {
      // Story 5.5 post-Figma decision (2026-04-29): retry is button-only.
      // The previous full-area GestureDetector (Story 5.2 post-review
      // decision 6) was removed because it could fire on accidental
      // scroll-to-end gestures and the discoverable accent-green CTA at
      // the bottom is unambiguous. (10, 10) lands at the top-left corner
      // (gutter); (50, 100) lands above the icon. Neither should retry.
      await pumpErrorState(
        tester,
        code: 'UNKNOWN_ERROR',
        retryCount: 0,
      );

      await tester.tapAt(const Offset(10, 10));
      await tester.pump();
      await tester.tapAt(const Offset(50, 100));
      await tester.pump();

      verifyNever(() => mockBloc.add(any<LoadScenariosEvent>()));
    },
  );

  testWidgets(
    'title color is AppColors.textPrimary, NOT AppColors.destructive',
    (tester) async {
      // Regression guard: the red title from Story 5.2 is reclaimed for
      // irreversible actions only — the error screen now reads as a pause.
      await pumpErrorState(
        tester,
        code: 'NETWORK_ERROR',
        retryCount: 0,
      );

      final titleWidget =
          tester.widget<Text>(find.text("You're offline."));
      expect(titleWidget.style?.color, AppColors.textPrimary);
      expect(titleWidget.style?.color, isNot(AppColors.destructive));
    },
  );

  testWidgets(
    'BottomOverlayCard stays hidden during ScenariosError (AC7 regression)',
    (tester) async {
      // _OverlayHost returns SizedBox.shrink for any non-Loaded state —
      // no half-truth like "Free tier" without the count during an error.
      await pumpErrorState(
        tester,
        code: 'NETWORK_ERROR',
        retryCount: 0,
      );

      expect(find.byType(BottomOverlayCard), findsNothing);
      // Sanity: none of the BOC's three copy variants leak through.
      expect(find.text('Unlock all scenarios'), findsNothing);
      expect(find.text('Subscribe to keep calling'), findsNothing);
      expect(find.text('No more calls today'), findsNothing);
    },
  );

  // ---------- Story 5.5 — Figma iphone-16-8 redesign ----------

  testWidgets(
    'every error code renders the common HOLD ON title + HEADS UP badge',
    (tester) async {
      // HOLD ON is the universal hero across all four codes (Figma redesign
      // 2026-04-29). HEADS UP is the accent-green badge above it.
      for (final c in errorCases) {
        await pumpErrorState(
          tester,
          code: c['code'] as String,
          retryCount: 0,
        );
        expect(
          find.text('HOLD ON'),
          findsOneWidget,
          reason: 'HOLD ON missing for code ${c['code']}',
        );
        expect(
          find.text('HEADS UP'),
          findsOneWidget,
          reason: 'HEADS UP missing for code ${c['code']}',
        );
      }
    },
  );

  testWidgets(
    'Try again button surfaces the retry icon (Figma stash:arrow-retry → Icons.refresh)',
    (tester) async {
      await pumpErrorState(
        tester,
        code: 'NETWORK_ERROR',
        retryCount: 0,
      );

      // The button is a FilledButton with a manual Row(Icon(Icons.refresh),
      // Text('Try again')) inside a FittedBox(scaleDown). find.byIcon scopes
      // globally; the only Icons.refresh in the tree comes from this button.
      expect(find.byIcon(Icons.refresh), findsOneWidget);
    },
  );

  testWidgets(
    'error layout does not overflow at 320×480 with textScaler 1.5',
    (tester) async {
      // Belt-and-braces: the Figma reference targets 390+ but Walid's PRD
      // does not exclude older devices. With longer body copy + repeat
      // variant + 1.5× scale, the content column would be tall enough to
      // collide with the bottom button — `Expanded(child: SingleChildScrollView)`
      // wraps the upper content so it scrolls while the Try again button
      // stays pinned at the bottom (button is a sibling outside the scroll
      // view, so it never gets absorbed).
      await tester.binding.setSurfaceSize(const Size(320, 480));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      // Capture any FlutterError raised during layout — RenderFlex overflow
      // surfaces here (not as a sync exception), so `takeException()` alone
      // misses it. `SingleChildScrollView` SHOULD absorb the overflow today,
      // but if a future change drops the wrap, the layout error must fail.
      final layoutErrors = <FlutterErrorDetails>[];
      final originalOnError = FlutterError.onError;
      FlutterError.onError = layoutErrors.add;
      addTearDown(() => FlutterError.onError = originalOnError);

      const state = ScenariosError(
        code: 'NETWORK_ERROR',
        retryCount: 0,
      );
      when(() => mockBloc.state).thenReturn(state);
      whenListen(
        mockBloc,
        const Stream<ScenariosState>.empty(),
        initialState: state,
      );

      await tester.pumpWidget(
        MediaQuery(
          data: const MediaQueryData(
            textScaler: TextScaler.linear(1.5),
          ),
          child: _harness(mockBloc),
        ),
      );
      await tester.pump();

      expect(tester.takeException(), isNull);
      expect(
        layoutErrors,
        isEmpty,
        reason:
            'RenderFlex / overflow errors must not surface — if this fails, '
            'check that the upper content remains wrapped in '
            'Expanded + SingleChildScrollView.',
      );
      // Sanity-check the button is still in the tree (i.e., not pushed off
      // screen by an expanded scroll view that ate the whole viewport).
      expect(find.text('Try again'), findsOneWidget);
    },
  );

  testWidgets('Loaded with 5 cards has no overflow at 320×480',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final scenarios = List<Scenario>.generate(
      5,
      (i) => _build(
        id: 's_$i',
        title: 'Char $i',
        tagline: 'Some tagline $i',
        bestScore: i.isEven ? null : 50 + i,
        attempts: i.isEven ? 0 : 2,
      ),
    );
    when(() => mockBloc.state)
        .thenReturn(ScenariosLoaded(scenarios: scenarios, usage: _kFreshUsage));
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: ScenariosLoaded(scenarios: scenarios, usage: _kFreshUsage),
    );

    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();

    expect(tester.takeException(), isNull);
  });

  // ---------- Story 5.3 — BottomOverlayCard wiring per state ----------

  Future<void> pumpWithUsage(WidgetTester tester, CallUsage usage) async {
    final scenarios = [_build(id: 'a', title: 'Alpha')];
    when(() => mockBloc.state).thenReturn(ScenariosLoaded(scenarios: scenarios, usage: usage));
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: ScenariosLoaded(scenarios: scenarios, usage: usage),
    );
    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();
  }

  testWidgets('BOC visible (free, with calls) — title is "Unlock all scenarios"',
      (tester) async {
    await pumpWithUsage(tester, _kFreshUsage);

    expect(find.byType(BottomOverlayCard), findsOneWidget);
    expect(find.text('Unlock all scenarios'), findsOneWidget);
  });

  testWidgets('BOC says "Subscribe to keep calling" when free + 0 calls',
      (tester) async {
    await pumpWithUsage(tester, _kFreeExhausted);

    expect(find.byType(BottomOverlayCard), findsOneWidget);
    expect(find.text('Subscribe to keep calling'), findsOneWidget);
  });

  testWidgets('BOC absent (no diamond / no copy) when paid + calls > 0',
      (tester) async {
    await pumpWithUsage(tester, _kPaidWithCalls);

    // The widget is in the tree but renders SizedBox.shrink — none of the
    // overlay copy is on-screen.
    expect(find.text('Unlock all scenarios'), findsNothing);
    expect(find.text('Subscribe to keep calling'), findsNothing);
    expect(find.text('No more calls today'), findsNothing);
    // No diamond image slot rendered inside the BOC (the BOC short-circuits
    // to SizedBox.shrink for paid users with calls remaining). Scoped to
    // the BOC subtree because ScenarioCard avatars are also `Image` widgets.
    expect(
      find.descendant(
        of: find.byType(BottomOverlayCard),
        matching: find.byType(Image),
      ),
      findsNothing,
    );
  });

  testWidgets('BOC says "No more calls today" when paid + 0 calls',
      (tester) async {
    await pumpWithUsage(tester, _kPaidExhausted);

    expect(find.byType(BottomOverlayCard), findsOneWidget);
    expect(find.text('No more calls today'), findsOneWidget);
    expect(find.text('Come back tomorrow'), findsOneWidget);
  });

  // ---------- Story 5.4 — Content warning dialog gate ----------

  Future<void> pumpListWithScenario(
    WidgetTester tester,
    Scenario scenario, {
    CallRepository? callRepository,
    CallScreenBuilder? callScreenBuilder,
    CallUsage usage = _kFreshUsage,
  }) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    when(() => mockBloc.state).thenReturn(
      ScenariosLoaded(scenarios: [scenario], usage: usage),
    );
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: ScenariosLoaded(scenarios: [scenario], usage: usage),
    );
    await tester.pumpWidget(
      _harness(
        mockBloc,
        callRepository: callRepository,
        callScreenBuilder: callScreenBuilder,
      ),
    );
    await tester.pump();
  }

  // ---------- Story 6.19 — global difficulty hub line ----------

  testWidgets(
    'hub shows the difficulty line; tapping it opens the sheet and updates it',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter');
      await pumpListWithScenario(tester, scenario);

      // Default preference renders on the hub.
      expect(find.text('Difficulty: Easy'), findsOneWidget);

      // Tapping the line opens the difficulty sheet.
      await tester.tap(find.text('Difficulty: Easy'));
      await tester.pumpAndSettle();
      expect(find.text('Done'), findsOneWidget);

      // Choosing Hard + Done persists and updates the hub line in place.
      await tester.tap(find.text('Hard'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Done'));
      await tester.pumpAndSettle();

      expect(find.text('Difficulty: Hard'), findsOneWidget);
    },
  );

  // ---------- Story 8.3 (2026-06-18 pivot) — Account hub line ----------

  testWidgets('paid user: Account leads, difficulty trails on the same row',
      (tester) async {
    await pumpWithUsage(tester, _kPaidWithCalls);

    expect(find.text('Account'), findsOneWidget);
    expect(find.text('Difficulty: Easy'), findsOneWidget);
    // Account is leading (left of difficulty) — the shared one-row layout.
    final accountX = tester.getTopLeft(find.text('Account')).dx;
    final difficultyX = tester.getTopLeft(find.text('Difficulty: Easy')).dx;
    expect(accountX, lessThan(difficultyX));
  });

  testWidgets('free user: NO Account line; difficulty still present', (
    tester,
  ) async {
    await pumpWithUsage(tester, _kFreshUsage);

    expect(find.text('Account'), findsNothing);
    expect(find.text('Difficulty: Easy'), findsOneWidget);
  });

  testWidgets('paid user: tapping Account opens the Manage drawer', (
    tester,
  ) async {
    final manageCubit = MockUserProfileCubit();
    whenListen(
      manageCubit,
      const Stream<UserProfileState>.empty(),
      initialState: const UserProfileLoaded(_kPaidProfile),
    );
    ManageSheet.debugCubitBuilder = () => manageCubit;
    addTearDown(() => ManageSheet.debugCubitBuilder = null);

    await pumpWithUsage(tester, _kPaidWithCalls);
    await tester.tap(find.text('Account'));
    await tester.pumpAndSettle();

    // The drawer mounted: its "Premium" header + value block are on-screen.
    expect(find.text('Premium'), findsOneWidget);
    expect(find.text('What your membership gives you'), findsOneWidget);
  });

  testWidgets('paid hub row does not overflow at 320x480, textScaler 1.5', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final scenarios = [_build(id: 'a', title: 'Alpha')];
    final state = ScenariosLoaded(scenarios: scenarios, usage: _kPaidWithCalls);
    when(() => mockBloc.state).thenReturn(state);
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: state,
    );
    await tester.pumpWidget(
      MaterialApp.router(
        theme: AppTheme.dark(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: const TextScaler.linear(1.5),
          ),
          child: child!,
        ),
        routerConfig: _router(
          const ScenarioListScreen(callScreenBuilder: _stubCallScreen),
          mockBloc,
        ),
      ),
    );
    await tester.pump();

    // The Expanded + ellipsis on the difficulty label absorbs the large text
    // scale; the shared Account+difficulty row must not RenderFlex-overflow.
    expect(tester.takeException(), isNull);
    expect(find.text('Account'), findsOneWidget);
  });

  testWidgets(
    'tapping phone icon on a scenario WITH content_warning shows the sheet',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Mugger',
        contentWarning: 'CW body 12345',
      );
      final mockRepo = MockCallRepository();
      when(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      ).thenAnswer((_) async => _kFakeSession);
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.text('Buckle up'), findsOneWidget);
      expect(find.text('CW body 12345'), findsOneWidget);
      // Still on the list — navigation has NOT happened yet.
      expect(find.byKey(_kCallStubKey), findsNothing);
      // POST not fired — gated by the content-warning sheet.
      verifyNever(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      );
    },
  );

  testWidgets(
    'tapping Pick up POSTs scenario_id and pushes CallScreen via root Navigator',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Mugger',
        contentWarning: 'CW body 12345',
      );
      final mockRepo = MockCallRepository();
      when(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      ).thenAnswer((_) async => _kFakeSession);
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pick up'));
      await tester.pumpAndSettle();

      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
      expect(find.text('Buckle up'), findsNothing);
    },
  );

  testWidgets(
    'tapping Not now in the sheet returns to the list without navigating',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Mugger',
        contentWarning: 'CW body 12345',
      );
      final mockRepo = MockCallRepository();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();

      expect(find.byKey(_kCallStubKey), findsNothing);
      expect(find.text('Buckle up'), findsNothing);
      expect(find.byType(ScenarioCard), findsOneWidget);
      verifyNever(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      );
    },
  );

  testWidgets(
    'tapping phone icon on a scenario WITHOUT content_warning POSTs and pushes directly',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Waiter',
        contentWarning: null,
      );
      final mockRepo = MockCallRepository();
      when(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      ).thenAnswer((_) async => _kFakeSession);
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);
      expect(find.text('Buckle up'), findsNothing);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
    },
  );

  // ---------- Story 6.1 — failure routing & tap debounce ----------

  testWidgets(
    'NETWORK_ERROR pushes the NoNetworkScreen via root Navigator',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter');
      final mockRepo = MockCallRepository();
      when(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      ).thenThrow(
        const ApiException(code: 'NETWORK_ERROR', message: 'No connection.'),
      );
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.byType(NoNetworkScreen), findsOneWidget);
      expect(find.byKey(_kCallStubKey), findsNothing);
    },
  );

  testWidgets(
    'CALL_LIMIT_REACHED shows the PaywallSheet (not the CallScreen)',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter');
      final mockRepo = MockCallRepository();
      when(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      ).thenThrow(
        const ApiException(
          code: 'CALL_LIMIT_REACHED',
          message: "You've used all your calls.",
        ),
      );
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.byKey(_kCallStubKey), findsNothing);
      // PaywallSheet is a modal bottom sheet — its content (any text) sits
      // above the scenario list. We assert by widget type instead of text
      // because the copy is owned by PaywallSheet not this test.
      expect(find.byType(BottomSheet), findsOneWidget);
    },
  );

  testWidgets(
    'generic 5xx (BOT_SPAWN_FAILED) shows the red AppToast with the in-persona copy',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter');
      final mockRepo = MockCallRepository();
      when(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      ).thenThrow(
        const ApiException(code: 'BOT_SPAWN_FAILED', message: 'Server error'),
      );
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pump();
      // Toast is inserted via Overlay after a 600ms delay (see
      // _ToastOverlayState.initState). Pump enough wall-time to clear that
      // delay and let the slide-in animation settle.
      await tester.pump(const Duration(milliseconds: 700));
      await tester.pump(const Duration(milliseconds: 500));

      // The exact wording is the contractual user-visible promise — if it
      // changes, the assertion will surface the change.
      expect(
        find.text(
          "This scenario hit a snag. Try a different one — we're on it.",
        ),
        findsOneWidget,
      );
      // The user is still on the list (no NoNetworkScreen, no PaywallSheet).
      expect(find.byType(NoNetworkScreen), findsNothing);
      expect(find.byKey(_kCallStubKey), findsNothing);
      // Drain the 10s auto-dismiss timer so the binding's teardown invariant
      // doesn't fire `!timersPending`.
      await tester.pump(const Duration(seconds: 11));
      await tester.pump(const Duration(milliseconds: 400));
    },
  );

  testWidgets(
    'tap debounce: a second tap during in-flight POST does NOT fire a second request',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter');
      final mockRepo = MockCallRepository();
      // Hold the request open by returning a never-resolving Future.
      final completer = Completer<CallSession>();
      when(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      ).thenAnswer((_) => completer.future);
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pump();
      // While the POST is in flight, tap again.
      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pump();

      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);

      // Cleanup: complete the future so addTearDown doesn't leak a pending
      // microtask into the next test.
      completer.complete(_kFakeSession);
      await tester.pumpAndSettle();
    },
  );

  // Spec deviation #3 (accepted 2026-04-29): scrim-tap is a valid cancel
  // path. The screen-integration coverage exercises it end-to-end so a
  // regression that re-blocked the scrim (or worse, navigated on dismiss)
  // would fail here.
  testWidgets(
    'tapping the scrim outside the sheet returns to the list with no navigation',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Mugger',
        contentWarning: 'CW body 12345',
      );
      await pumpListWithScenario(tester, scenario);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      // (20, 20) on a 390x844 surface lands in the top-left scrim region
      // — well above the bottom-anchored sheet.
      await tester.tapAt(const Offset(20, 20));
      await tester.pumpAndSettle();

      expect(find.text('CALL_STUB'), findsNothing);
      expect(find.text('Buckle up'), findsNothing);
      expect(find.byType(ScenarioCard), findsOneWidget);
    },
  );

  // ---------- Story 7.4 — first-attempt briefing gate ----------

  const briefingContent = <String, String>{
    'vocabulary': '"I\'d like..."',
    'context': 'You are ordering food.',
    'expect': 'The waitress is impatient.',
  };

  MockCallRepository happyRepo() {
    final mockRepo = MockCallRepository();
    when(
      () => mockRepo.initiateCall(
        scenarioId: any(named: 'scenarioId'),
        difficulty: any(named: 'difficulty'),
      ),
    ).thenAnswer((_) async => _kFakeSession);
    return mockRepo;
  }

  void verifyNoPost(MockCallRepository mockRepo) {
    verifyNever(
      () => mockRepo.initiateCall(
        scenarioId: any(named: 'scenarioId'),
        difficulty: any(named: 'difficulty'),
      ),
    );
  }

  testWidgets(
    'first-attempt call tap pushes the briefing (with the Scenario extra) — no POST before confirm',
    (tester) async {
      final scenario =
          _build(id: 's1', title: 'Waiter', briefing: briefingContent);
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.text('BRIEFING_STUB:s1'), findsOneWidget);
      expect(find.text('BRIEFING_EXTRA_IS_SCENARIO:true'), findsOneWidget);
      expect(find.byKey(_kCallStubKey), findsNothing);
      verifyNoPost(mockRepo);
    },
  );

  testWidgets(
    'briefing confirm → POST + CallScreen (unwarned scenario)',
    (tester) async {
      final scenario =
          _build(id: 's1', title: 'Waiter', briefing: briefingContent);
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('BRIEFING_CONFIRM'));
      await tester.pumpAndSettle();

      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
    },
  );

  testWidgets(
    'warned scenario: briefing confirm shows the content-warning sheet BEFORE any POST (Decision D order)',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Mugger',
        contentWarning: 'CW body 12345',
        briefing: briefingContent,
      );
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      // Briefing first…
      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      expect(find.text('BRIEFING_STUB:s1'), findsOneWidget);
      expect(find.text('Buckle up'), findsNothing);

      // …then the warning sheet after confirm, still no POST…
      await tester.tap(find.text('BRIEFING_CONFIRM'));
      await tester.pumpAndSettle();
      expect(find.text('Buckle up'), findsOneWidget);
      verifyNoPost(mockRepo);

      // …and the second "Pick up" finally fires the chain.
      await tester.tap(find.text('Pick up'));
      await tester.pumpAndSettle();
      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
    },
  );

  testWidgets(
    'briefing decline returns to the hub with zero network calls',
    (tester) async {
      final scenario =
          _build(id: 's1', title: 'Waiter', briefing: briefingContent);
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('BRIEFING_DISMISS'));
      await tester.pumpAndSettle();

      expect(find.byType(ScenarioCard), findsOneWidget);
      expect(find.byKey(_kCallStubKey), findsNothing);
      verifyNoPost(mockRepo);
    },
  );

  testWidgets(
    'attempts > 0 skips the briefing — direct chain (byte-identical to pre-7.4)',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Waiter',
        attempts: 3,
        bestScore: 50,
        briefing: briefingContent,
      );
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.textContaining('BRIEFING_STUB'), findsNothing);
      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
    },
  );

  for (final (label, briefing) in [
    ('null briefing', null),
    (
      'all-empty briefing',
      const <String, String>{'vocabulary': '', 'context': '', 'expect': ''}
    ),
  ]) {
    testWidgets(
      '$label skips the gate — call tap runs the chain directly',
      (tester) async {
        final scenario = _build(id: 's1', title: 'Waiter', briefing: briefing);
        final mockRepo = happyRepo();
        await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

        await tester.tap(find.byIcon(Icons.phone_outlined));
        await tester.pumpAndSettle();

        expect(find.textContaining('BRIEFING_STUB'), findsNothing);
        verify(() => mockRepo.initiateCall(
            scenarioId: 's1',
            difficulty: any(named: 'difficulty'),
          )).called(1);
        expect(find.byKey(_kCallStubKey), findsOneWidget);
      },
    );
  }

  testWidgets(
    'session mark: after a successful initiate, the next call tap skips the briefing despite stale attempts == 0',
    (tester) async {
      final scenario =
          _build(id: 's1', title: 'Waiter', briefing: briefingContent);
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      // First call: gated, confirmed, POST fires, CallScreen mounts.
      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('BRIEFING_CONFIRM'));
      await tester.pumpAndSettle();
      expect(find.byKey(_kCallStubKey), findsOneWidget);

      // End the call (pop the root-navigator route) — the hub list does
      // NOT refetch, so scenario.attempts still reads 0.
      Navigator.of(tester.element(find.byKey(_kCallStubKey))).pop();
      await tester.pumpAndSettle();

      // Second call tap: the in-session mark covers the stale attempts.
      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.textContaining('BRIEFING_STUB'), findsNothing);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(2);
    },
  );

  testWidgets(
    'failed POST (CALL_LIMIT_REACHED) does NOT set the session mark — the briefing re-shows on the next tap',
    (tester) async {
      final scenario =
          _build(id: 's1', title: 'Waiter', briefing: briefingContent);
      final mockRepo = MockCallRepository();
      when(
        () => mockRepo.initiateCall(
          scenarioId: any(named: 'scenarioId'),
          difficulty: any(named: 'difficulty'),
        ),
      ).thenThrow(
        const ApiException(
          code: 'CALL_LIMIT_REACHED',
          message: "You've used all your calls.",
        ),
      );
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      // First attempt: briefing → confirm → POST fails → PaywallSheet.
      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('BRIEFING_CONFIRM'));
      await tester.pumpAndSettle();
      expect(find.byType(BottomSheet), findsOneWidget);
      expect(find.byKey(_kCallStubKey), findsNothing);

      // Dismiss the paywall sheet (scrim tap).
      await tester.tapAt(const Offset(20, 20));
      await tester.pumpAndSettle();

      // No call ever started → the gate must re-show the briefing.
      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      expect(find.text('BRIEFING_STUB:s1'), findsOneWidget);
    },
  );

  testWidgets(
    'card tap opens the briefing in browse mode — confirm starts the call chain too',
    (tester) async {
      final scenario =
          _build(id: 's1', title: 'Waiter', briefing: briefingContent);
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      // Tap the description block (title text), not the phone icon.
      await tester.tap(find.text('Waiter'));
      await tester.pumpAndSettle();
      expect(find.text('BRIEFING_STUB:s1'), findsOneWidget);
      verifyNoPost(mockRepo);

      await tester.tap(find.text('BRIEFING_CONFIRM'));
      await tester.pumpAndSettle();

      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
    },
  );

  // Review patch (7.4) — AC-C7's double-PUSH half: the widened
  // `_initiating` span must swallow the second tap before the route push,
  // on BOTH entries. A double-push would stack two briefing routes, so one
  // dismiss must land straight back on the hub.
  for (final (label, target) in [
    ('call icon', () => find.byIcon(Icons.phone_outlined)),
    ('card', () => find.text('Waiter')),
  ]) {
    testWidgets(
      '$label double-tap never double-pushes the briefing route',
      (tester) async {
        final scenario =
            _build(id: 's1', title: 'Waiter', briefing: briefingContent);
        final mockRepo = happyRepo();
        await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

        await tester.tap(target());
        await tester.tap(target(), warnIfMissed: false);
        await tester.pumpAndSettle();

        expect(find.text('BRIEFING_STUB:s1'), findsOneWidget);
        verifyNoPost(mockRepo);

        // One dismiss returns to the hub — a second stacked briefing
        // route would still be showing the stub here.
        await tester.tap(find.text('BRIEFING_DISMISS'));
        await tester.pumpAndSettle();
        expect(find.textContaining('BRIEFING_STUB'), findsNothing);
        expect(find.byType(ScenarioCard), findsOneWidget);
        verifyNoPost(mockRepo);
      },
    );
  }

  // ---------- Story 8.2 — AC1 paid-scenario call gate (UX-DR16) ----------

  tearDown(() {
    // The gate opens the real PaywallSheet (no debugBlocBuilder here, mirroring
    // the existing CALL_LIMIT_REACHED coverage) — keep the seam clean.
    PaywallSheet.debugBlocBuilder = null;
  });

  testWidgets(
    'free user + PAID scenario: call icon shows the paywall, NO initiateCall',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Premium', isFree: false);
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      // Paywall sheet shown instead of a call.
      expect(find.byType(BottomSheet), findsOneWidget);
      expect(find.byKey(_kCallStubKey), findsNothing);
      verifyNoPost(mockRepo);
    },
  );

  testWidgets(
    'free user + FREE scenario: call icon runs the normal chain (no paywall)',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter'); // isFree default true
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.byType(BottomSheet), findsNothing);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);
    },
  );

  testWidgets(
    'PAID user + paid scenario: never gated — the call runs',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Premium', isFree: false);
      final mockRepo = happyRepo();
      await pumpListWithScenario(
        tester,
        scenario,
        callRepository: mockRepo,
        usage: _kPaidWithCalls,
      );

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.byType(BottomSheet), findsNothing);
      expect(find.byKey(_kCallStubKey), findsOneWidget);
      verify(() => mockRepo.initiateCall(
          scenarioId: 's1',
          difficulty: any(named: 'difficulty'),
        )).called(1);
    },
  );

  testWidgets(
    'browse path: paid scenario briefing is free, but "Pick up" hits the paywall',
    (tester) async {
      const briefing = <String, String>{
        'context': 'You are negotiating.',
        'expect': 'They push back hard.',
        'vocabulary': '"Let me think..."',
      };
      final scenario =
          _build(id: 's1', title: 'Premium', isFree: false, briefing: briefing);
      final mockRepo = happyRepo();
      await pumpListWithScenario(tester, scenario, callRepository: mockRepo);

      // Card tap opens the briefing (browsing a paid scenario stays free).
      await tester.tap(find.text('Premium'));
      await tester.pumpAndSettle();
      expect(find.text('BRIEFING_STUB:s1'), findsOneWidget);
      verifyNoPost(mockRepo);

      // Confirming (the call action) converges on _startCall → the paywall.
      await tester.tap(find.text('BRIEFING_CONFIRM'));
      await tester.pumpAndSettle();
      expect(find.byType(BottomSheet), findsOneWidget);
      expect(find.byKey(_kCallStubKey), findsNothing);
      verifyNoPost(mockRepo);
    },
  );

  // ---------- Story 8.3 — AC3 call-icon disablement at 0 calls ----------
  //
  // At 0 calls the call icon is INERT (never initiates a call, no server
  // round-trip): a free user is routed to the paywall (the way forward), a
  // paid user at their daily cap is a no-op (the BOC says "come back tomorrow").

  testWidgets(
    'free user + 0 calls: call icon is inert — shows the paywall, NO call',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter'); // free scenario
      final mockRepo = happyRepo();
      await pumpListWithScenario(
        tester,
        scenario,
        callRepository: mockRepo,
        usage: _kFreeExhausted,
      );

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.byType(BottomSheet), findsOneWidget); // paywall, not a call
      expect(find.byKey(_kCallStubKey), findsNothing);
      verifyNoPost(mockRepo);
    },
  );

  testWidgets(
    'paid user + 0 daily calls: call icon is inert — no call, no paywall',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter');
      final mockRepo = happyRepo();
      await pumpListWithScenario(
        tester,
        scenario,
        callRepository: mockRepo,
        usage: _kPaidExhausted,
      );

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.byType(BottomSheet), findsNothing);
      expect(find.byKey(_kCallStubKey), findsNothing);
      verifyNoPost(mockRepo);
    },
  );

  // ------- Story 8.2 — FR29 debrief-paywall trigger (D1 + P2, code-review) -------
  //
  // `isFinalFreeScenario = usage.isFree && callsRemaining <= 1` is computed in
  // `_startCall` and threaded to the call surface. Pre-fix the stub builder
  // discarded it (B6: untested); the builder now carries it so we can assert it.
  // D1: the hub silently refreshes `/scenarios` on call-return so the snapshot
  // is fresh for the NEXT call's trigger (reverses the 7.4 no-refetch).

  MockCallRepository happyCallRepo() {
    final repo = MockCallRepository();
    when(
      () => repo.initiateCall(
        scenarioId: any(named: 'scenarioId'),
        difficulty: any(named: 'difficulty'),
      ),
    ).thenAnswer((_) async => _kFakeSession);
    return repo;
  }

  // P2 — the FR29 flag reaches the call surface, computed per `<= 1` && isFree.
  // (The remaining-0 cases moved to the AC3 section below: under Story 8.3 the
  // call icon is INERT at 0 calls, so a call never starts to carry the flag.
  // The paid case uses a paid-WITH-calls usage so the call actually runs.)
  for (final (label, usage, expected) in <(String, CallUsage, bool)>[
    ('free, last call (remaining 1)', _kFreeLastCall, true),
    ('free, not last (remaining 3)', _kFreshUsage, false),
    ('paid (never qualifies)', _kPaidWithCalls, false),
  ]) {
    testWidgets(
      'FR29 flag → presentPaywallOnDebrief=$expected for $label',
      (tester) async {
        final scenario = _build(id: 's1', title: 'Waiter'); // free, no CW/brief
        bool? captured;
        await pumpListWithScenario(
          tester,
          scenario,
          callRepository: happyCallRepo(),
          usage: usage,
          callScreenBuilder: (s, sess, flag) {
            captured = flag;
            return const Scaffold(key: _kCallStubKey, body: SizedBox());
          },
        );

        await tester.tap(find.byIcon(Icons.phone_outlined));
        await tester.pumpAndSettle();

        expect(find.byKey(_kCallStubKey), findsOneWidget);
        expect(captured, expected);
      },
    );
  }

  // D1 — returning from a call dispatches a silent RefreshScenariosEvent.
  testWidgets(
    'D1: returning from a call silently refreshes /scenarios',
    (tester) async {
      final scenario = _build(id: 's1', title: 'Waiter');
      await pumpListWithScenario(
        tester,
        scenario,
        callRepository: happyCallRepo(),
        callScreenBuilder: (s, sess, flag) => Scaffold(
          key: _kCallStubKey,
          body: Builder(
            builder: (ctx) => Center(
              child: ElevatedButton(
                onPressed: () => Navigator.of(ctx).pop(),
                child: const Text('END_CALL'),
              ),
            ),
          ),
        ),
      );

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      expect(find.byKey(_kCallStubKey), findsOneWidget);
      // No refresh yet — only on RETURN.
      verifyNever(() => mockBloc.add(const RefreshScenariosEvent()));

      // Call ends → the pushed route pops → `_startCall`'s await resolves.
      await tester.tap(find.text('END_CALL'));
      await tester.pumpAndSettle();

      verify(() => mockBloc.add(const RefreshScenariosEvent())).called(1);
    },
  );
}
