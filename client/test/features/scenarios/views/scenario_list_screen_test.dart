import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/scenarios/bloc/scenarios_bloc.dart';
import 'package:client/features/scenarios/bloc/scenarios_event.dart';
import 'package:client/features/scenarios/bloc/scenarios_state.dart';
import 'package:client/features/scenarios/models/call_usage.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/views/scenario_list_screen.dart';
import 'package:client/features/scenarios/views/widgets/bottom_overlay_card.dart';
import 'package:client/features/scenarios/views/widgets/scenario_card.dart';
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

Scenario _build({
  required String id,
  required String title,
  String tagline = 'Tagline',
  int? bestScore,
  int attempts = 0,
  String? contentWarning,
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
      GoRoute(
        path: '/call',
        builder: (context, state) =>
            const Scaffold(body: Center(child: Text('CALL_STUB'))),
      ),
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
      GoRoute(
        path: '/briefing/:scenarioId',
        builder: (context, state) => Scaffold(
          body: Center(
            child: Text(
              'BRIEFING_STUB:${state.pathParameters['scenarioId']}',
            ),
          ),
        ),
      ),
    ],
  );
}

Widget _harness(MockScenariosBloc bloc) => MaterialApp.router(
      theme: AppTheme.dark(),
      routerConfig: _router(const ScenarioListScreen(), bloc),
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

  testWidgets('Error renders message and tap-to-retry hint', (tester) async {
    const message =
        'No internet connection. Please check your network and try again.';
    when(() => mockBloc.state).thenReturn(const ScenariosError(message));
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: const ScenariosError(message),
    );

    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();

    expect(find.text(message), findsOneWidget);
    expect(find.text('Tap to retry'), findsOneWidget);
  });

  testWidgets('tapping the error area dispatches LoadScenariosEvent',
      (tester) async {
    const message = 'Boom.';
    when(() => mockBloc.state).thenReturn(const ScenariosError(message));
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: const ScenariosError(message),
    );

    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();

    await tester.tap(find.text('Tap to retry'));
    await tester.pump();

    verify(() => mockBloc.add(any<LoadScenariosEvent>())).called(1);
  });

  testWidgets(
    'tapping anywhere on the empty scaffold area (not just on the centered text) dispatches LoadScenariosEvent',
    (tester) async {
      // AC3 (post-review decision 6 — 2026-04-27): the WHOLE scaffold body
      // is the retry hit-target, not just the small centered Column.
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      const message = 'Boom.';
      when(() => mockBloc.state).thenReturn(const ScenariosError(message));
      whenListen(
        mockBloc,
        const Stream<ScenariosState>.empty(),
        initialState: const ScenariosError(message),
      );

      await tester.pumpWidget(_harness(mockBloc));
      await tester.pump();

      // Tap near the top-left of the visible body, well above the centered
      // error text. If the hit-target is whole-screen, this still dispatches
      // a retry; if it's only the centered Column (pre-fix behaviour), it
      // would do nothing and the verify call would fail with `called(0)`.
      await tester.tapAt(const Offset(60, 120));
      await tester.pump();

      verify(() => mockBloc.add(any<LoadScenariosEvent>())).called(1);
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
    Scenario scenario,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    when(() => mockBloc.state).thenReturn(
      ScenariosLoaded(scenarios: [scenario], usage: _kFreshUsage),
    );
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState:
          ScenariosLoaded(scenarios: [scenario], usage: _kFreshUsage),
    );
    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();
  }

  testWidgets(
    'tapping phone icon on a scenario WITH content_warning shows the sheet',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Mugger',
        contentWarning: 'CW body 12345',
      );
      await pumpListWithScenario(tester, scenario);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.text('Buckle up'), findsOneWidget);
      expect(find.text('CW body 12345'), findsOneWidget);
      // Still on the list — navigation has NOT happened yet.
      expect(find.text('CALL_STUB'), findsNothing);
    },
  );

  testWidgets(
    'tapping Pick up in the sheet navigates to /call with the scenario',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Mugger',
        contentWarning: 'CW body 12345',
      );
      await pumpListWithScenario(tester, scenario);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pick up'));
      await tester.pumpAndSettle();

      expect(find.text('CALL_STUB'), findsOneWidget);
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
      await pumpListWithScenario(tester, scenario);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();

      expect(find.text('CALL_STUB'), findsNothing);
      expect(find.text('Buckle up'), findsNothing);
      expect(find.byType(ScenarioCard), findsOneWidget);
    },
  );

  testWidgets(
    'tapping phone icon on a scenario WITHOUT content_warning skips the sheet and navigates directly',
    (tester) async {
      final scenario = _build(
        id: 's1',
        title: 'Waiter',
        contentWarning: null,
      );
      await pumpListWithScenario(tester, scenario);

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pumpAndSettle();

      expect(find.text('Buckle up'), findsNothing);
      expect(find.text('CALL_STUB'), findsOneWidget);
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
}
