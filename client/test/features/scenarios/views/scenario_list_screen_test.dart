import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/scenarios/bloc/scenarios_bloc.dart';
import 'package:client/features/scenarios/bloc/scenarios_event.dart';
import 'package:client/features/scenarios/bloc/scenarios_state.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/views/scenario_list_screen.dart';
import 'package:client/features/scenarios/views/widgets/scenario_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mocktail/mocktail.dart';

class MockScenariosBloc extends MockBloc<ScenariosEvent, ScenariosState>
    implements ScenariosBloc {}

Scenario _build({
  required String id,
  required String title,
  String tagline = 'Tagline',
  int? bestScore,
  int attempts = 0,
}) {
  return Scenario(
    id: id,
    title: title,
    difficulty: 'easy',
    isFree: true,
    riveCharacter: 'waiter',
    languageFocus: const <String>[],
    contentWarning: null,
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
    when(() => mockBloc.state).thenReturn(ScenariosLoaded(scenarios));
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: ScenariosLoaded(scenarios),
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
    when(() => mockBloc.state).thenReturn(ScenariosLoaded(scenarios));
    whenListen(
      mockBloc,
      const Stream<ScenariosState>.empty(),
      initialState: ScenariosLoaded(scenarios),
    );

    await tester.pumpWidget(_harness(mockBloc));
    await tester.pump();

    expect(tester.takeException(), isNull);
  });
}
