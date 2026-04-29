import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/features/scenarios/bloc/scenarios_bloc.dart';
import 'package:client/features/scenarios/bloc/scenarios_event.dart';
import 'package:client/features/scenarios/bloc/scenarios_state.dart';
import 'package:client/features/scenarios/models/call_usage.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/repositories/scenarios_fetch_result.dart';
import 'package:client/features/scenarios/repositories/scenarios_repository.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockScenariosRepository extends Mock implements ScenariosRepository {}

const _waiter = Scenario(
  id: 'waiter_easy_01',
  title: 'Tina',
  difficulty: 'easy',
  isFree: true,
  riveCharacter: 'waiter',
  languageFocus: <String>['assertiveness'],
  contentWarning: null,
  bestScore: null,
  attempts: 0,
  tagline: 'Order before she loses it',
);

const _mugger = Scenario(
  id: 'mugger_medium_01',
  title: 'Mugger',
  difficulty: 'medium',
  isFree: true,
  riveCharacter: 'mugger',
  languageFocus: <String>['de-escalation'],
  contentWarning: 'violence',
  bestScore: 80,
  attempts: 3,
  tagline: 'Give me your wallet',
);

final _fiveScenarios = <Scenario>[_waiter, _mugger, _waiter, _mugger, _waiter];

const _kFreshUsage = CallUsage(
  tier: 'free',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'lifetime',
);

ScenariosFetchResult _result(
  List<Scenario> scenarios, {
  CallUsage usage = _kFreshUsage,
}) =>
    ScenariosFetchResult(scenarios: scenarios, usage: usage);

void main() {
  late MockScenariosRepository mockRepo;

  setUpAll(() {
    registerFallbackValue(const LoadScenariosEvent());
  });

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    mockRepo = MockScenariosRepository();
  });

  ScenariosBloc buildBloc() => ScenariosBloc(mockRepo);

  group('LoadScenariosEvent', () {
    blocTest<ScenariosBloc, ScenariosState>(
      'happy path emits [Loading, Loaded] with the repo list',
      setUp: () {
        when(() => mockRepo.fetchScenarios())
            .thenAnswer((_) async => _result(_fiveScenarios));
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosLoaded>().having(
          (s) => s.scenarios.length,
          'scenarios.length',
          5,
        ),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'NETWORK_ERROR ApiException maps to ScenariosError(code: NETWORK_ERROR, retryCount: 0)',
      setUp: () {
        when(() => mockRepo.fetchScenarios()).thenThrow(
          const ApiException(
            code: 'NETWORK_ERROR',
            message:
                'No internet connection. Please check your network and try again.',
          ),
        );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'NETWORK_ERROR')
            .having((s) => s.retryCount, 'retryCount', 0),
      ],
    );

    // 5xx HTTP status routes to SERVER_ERROR regardless of body code —
    // post-decision-6 (2026-04-29 review): the bloc consults
    // `ApiException.statusCode` (propagated from the Dio response) rather
    // than a string-prefix heuristic, so realistic backend codes like
    // `SCENARIO_CORRUPT` (HTTP 500) classify correctly.
    for (final fixture in const [
      ('SCENARIO_CORRUPT', 500),
      ('LIVEKIT_TOKEN_FAILED', 500),
      ('BOT_SPAWN_FAILED', 502),
      ('UNKNOWN_ERROR', 503),
    ]) {
      final upstreamCode = fixture.$1;
      final upstreamStatus = fixture.$2;
      blocTest<ScenariosBloc, ScenariosState>(
        '5xx HTTP status $upstreamStatus (body code "$upstreamCode") maps to SERVER_ERROR',
        setUp: () {
          when(() => mockRepo.fetchScenarios()).thenThrow(
            ApiException(
              code: upstreamCode,
              message: 'irrelevant — copy lives in the view',
              statusCode: upstreamStatus,
            ),
          );
        },
        build: buildBloc,
        act: (bloc) => bloc.add(const LoadScenariosEvent()),
        expect: () => [
          isA<ScenariosLoading>(),
          isA<ScenariosError>()
              .having((s) => s.code, 'code', 'SERVER_ERROR')
              .having((s) => s.retryCount, 'retryCount', 0),
        ],
      );
    }

    // Defensive: literal `code: 'SERVER_ERROR'` with no statusCode (e.g.,
    // a future server surface that emits the canonical string code without
    // a 5xx HTTP wrapper) still classifies correctly.
    blocTest<ScenariosBloc, ScenariosState>(
      'literal code "SERVER_ERROR" with no statusCode still maps to SERVER_ERROR',
      setUp: () {
        when(() => mockRepo.fetchScenarios()).thenThrow(
          const ApiException(
            code: 'SERVER_ERROR',
            message: 'irrelevant',
          ),
        );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'SERVER_ERROR')
            .having((s) => s.retryCount, 'retryCount', 0),
      ],
    );

    // UNKNOWN_ERROR fallback — non-network, non-5xx HTTP status (4xx or
    // null) regardless of body code. SCENARIO_CORRUPT *without* statusCode
    // info preserves decision-5 status quo: from a string code alone, the
    // client can't infer 5xx-class.
    for (final fixture in const [
      ('UNAUTHORIZED', 401),
      ('FORBIDDEN', 403),
      ('SCENARIO_CORRUPT', null), // no status info → unknown
      ('UNKNOWN_ERROR', null),
    ]) {
      final upstreamCode = fixture.$1;
      final upstreamStatus = fixture.$2;
      blocTest<ScenariosBloc, ScenariosState>(
        'non-network non-5xx code "$upstreamCode" (status: $upstreamStatus) maps to UNKNOWN_ERROR',
        setUp: () {
          when(() => mockRepo.fetchScenarios()).thenThrow(
            ApiException(
              code: upstreamCode,
              message: 'irrelevant',
              statusCode: upstreamStatus,
            ),
          );
        },
        build: buildBloc,
        act: (bloc) => bloc.add(const LoadScenariosEvent()),
        expect: () => [
          isA<ScenariosLoading>(),
          isA<ScenariosError>()
              .having((s) => s.code, 'code', 'UNKNOWN_ERROR')
              .having((s) => s.retryCount, 'retryCount', 0),
        ],
      );
    }

    blocTest<ScenariosBloc, ScenariosState>(
      'bare TypeError maps to MALFORMED_RESPONSE',
      setUp: () {
        when(() => mockRepo.fetchScenarios()).thenThrow(TypeError());
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'MALFORMED_RESPONSE')
            .having((s) => s.retryCount, 'retryCount', 0),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'retryCount increments across three consecutive failures (0, 1, 2)',
      setUp: () {
        when(() => mockRepo.fetchScenarios()).thenThrow(
          const ApiException(
            code: 'NETWORK_ERROR',
            message: 'No connection.',
          ),
        );
      },
      build: buildBloc,
      act: (bloc) async {
        bloc.add(const LoadScenariosEvent());
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent());
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent());
      },
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'NETWORK_ERROR')
            .having((s) => s.retryCount, 'retryCount', 0),
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'NETWORK_ERROR')
            .having((s) => s.retryCount, 'retryCount', 1),
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'NETWORK_ERROR')
            .having((s) => s.retryCount, 'retryCount', 2),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'retryCount resets to 0 after a successful load (failure → success → failure)',
      setUp: () {
        var calls = 0;
        when(() => mockRepo.fetchScenarios()).thenAnswer((_) async {
          calls += 1;
          if (calls == 1 || calls == 3) {
            throw const ApiException(
              code: 'NETWORK_ERROR',
              message: 'No connection.',
            );
          }
          return _result(_fiveScenarios);
        });
      },
      build: buildBloc,
      act: (bloc) async {
        bloc.add(const LoadScenariosEvent());
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent());
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent());
      },
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.retryCount, 'retryCount', 0),
        isA<ScenariosLoading>(),
        isA<ScenariosLoaded>(),
        isA<ScenariosLoading>(),
        // After Loaded, the next failure starts at retryCount: 0 again.
        isA<ScenariosError>()
            .having((s) => s.retryCount, 'retryCount', 0),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'retryCount tracks consecutive failures even when error code changes',
      setUp: () {
        var calls = 0;
        when(() => mockRepo.fetchScenarios()).thenAnswer((_) async {
          calls += 1;
          if (calls == 1) {
            throw const ApiException(
              code: 'NETWORK_ERROR',
              message: '',
            );
          }
          if (calls == 2) {
            throw const ApiException(
              code: 'SCENARIO_CORRUPT',
              message: '',
              statusCode: 500,
            );
          }
          throw TypeError();
        });
      },
      build: buildBloc,
      act: (bloc) async {
        bloc.add(const LoadScenariosEvent());
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent());
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent());
      },
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'NETWORK_ERROR')
            .having((s) => s.retryCount, 'retryCount', 0),
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'SERVER_ERROR')
            .having((s) => s.retryCount, 'retryCount', 1),
        isA<ScenariosLoading>(),
        isA<ScenariosError>()
            .having((s) => s.code, 'code', 'MALFORMED_RESPONSE')
            .having((s) => s.retryCount, 'retryCount', 2),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'spam-tap during Loading is dropped (regression — in-flight guard)',
      setUp: () {
        // Repo answer is delayed so the second event lands while the first
        // is still in flight. The guard must short-circuit the second event.
        when(() => mockRepo.fetchScenarios()).thenAnswer((_) async {
          await Future<void>.delayed(const Duration(milliseconds: 50));
          return _result(_fiveScenarios);
        });
      },
      build: buildBloc,
      act: (bloc) async {
        bloc.add(const LoadScenariosEvent());
        // Yield once so _onLoad starts and emits Loading before the second
        // event is dispatched.
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent());
      },
      // Hold off on assertions until after the delayed repo answer lands,
      // otherwise the test snapshots the bloc mid-flight and only sees
      // the initial ScenariosLoading emission.
      wait: const Duration(milliseconds: 200),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosLoaded>().having(
          (s) => s.scenarios.length,
          'scenarios.length',
          5,
        ),
      ],
      verify: (_) {
        // The guard must have cancelled the second fetch — the repo is hit
        // exactly once.
        verify(() => mockRepo.fetchScenarios()).called(1);
      },
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'retry after error re-enters Loading then Loaded',
      setUp: () {
        var calls = 0;
        when(() => mockRepo.fetchScenarios()).thenAnswer((_) async {
          calls += 1;
          if (calls == 1) {
            throw const ApiException(
              code: 'NETWORK_ERROR',
              message: 'No connection.',
            );
          }
          return _result(_fiveScenarios);
        });
      },
      build: buildBloc,
      act: (bloc) async {
        bloc.add(const LoadScenariosEvent());
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent());
      },
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>(),
        isA<ScenariosLoading>(),
        isA<ScenariosLoaded>().having(
          (s) => s.scenarios.length,
          'scenarios.length',
          5,
        ),
      ],
    );
  });
}
