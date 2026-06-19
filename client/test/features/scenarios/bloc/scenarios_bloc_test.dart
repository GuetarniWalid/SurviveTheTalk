import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/core/local_cache/scenario_cache_store.dart';
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

// Story 9.1 — a MOCKED cache store keeps these bloc tests off sqflite (a real
// ScenarioCacheStore would hit the platform channel → MissingPluginException,
// Gotcha A). `readScenarios()` is stubbed to null (empty cache) by default so
// every pre-existing `[Loading, ...]` expectation stays valid.
class MockScenarioCacheStore extends Mock implements ScenarioCacheStore {}

const _waiter = Scenario(
  id: 'waiter_easy_01',
  title: 'Tina',
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
    ScenariosFetchResult(
      scenarios: scenarios,
      usage: usage,
      // Story 9.1 — the bloc only reads `.scenarios`/`.usage`; the raw maps are
      // consumed by the (mocked) cache store, so empties suffice here.
      rawScenarios: const <Map<String, dynamic>>[],
      rawMeta: const <String, dynamic>{},
    );

void main() {
  late MockScenariosRepository mockRepo;
  late MockScenarioCacheStore mockStore;

  setUpAll(() {
    registerFallbackValue(const LoadScenariosEvent());
    // Story 9.1 — fallback for `writeScenarios(any())`.
    registerFallbackValue(_result(const <Scenario>[]));
  });

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    mockRepo = MockScenariosRepository();
    mockStore = MockScenarioCacheStore();
    // Default: empty cache (so existing expectations that begin with Loading
    // stay valid) + a no-op write-through.
    when(() => mockStore.readScenarios()).thenAnswer((_) async => null);
    when(() => mockStore.writeScenarios(any())).thenAnswer((_) async {});
  });

  ScenariosBloc buildBloc() => ScenariosBloc(mockRepo, cacheStore: mockStore);

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

  group('RefreshScenariosEvent (Story 8.2 D1 — silent in-session refresh)', () {
    const refreshedUsage = CallUsage(
      tier: 'free',
      callsRemaining: 2, // was 3 (stale) — proves the in-place swap
      callsPerPeriod: 3,
      period: 'lifetime',
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'refreshes in place — emits ONLY Loaded, never a Loading flash',
      setUp: () {
        when(() => mockRepo.fetchScenarios()).thenAnswer(
          (_) async => _result(_fiveScenarios, usage: refreshedUsage),
        );
      },
      build: buildBloc,
      seed: () =>
          const ScenariosLoaded(scenarios: <Scenario>[], usage: _kFreshUsage),
      act: (bloc) => bloc.add(const RefreshScenariosEvent()),
      // Exactly one emission, and it is Loaded (NOT Loading → no flicker after
      // every call, and the list State is preserved across the swap).
      expect: () => [
        isA<ScenariosLoaded>().having(
          (s) => s.usage.callsRemaining,
          'usage.callsRemaining (fresh)',
          2,
        ),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'on failure keeps the current state — NO Error flip, NO emission',
      setUp: () {
        when(() => mockRepo.fetchScenarios()).thenThrow(
          const ApiException(code: 'NETWORK_ERROR', message: 'down'),
        );
      },
      build: buildBloc,
      seed: () =>
          const ScenariosLoaded(scenarios: <Scenario>[], usage: _kFreshUsage),
      act: (bloc) => bloc.add(const RefreshScenariosEvent()),
      expect: () => const <ScenariosState>[],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'is dropped while a foreground load is already in flight',
      build: buildBloc,
      seed: ScenariosLoading.new,
      act: (bloc) => bloc.add(const RefreshScenariosEvent()),
      expect: () => const <ScenariosState>[],
      verify: (_) => verifyNever(() => mockRepo.fetchScenarios()),
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'Story 9.1 — RefreshScenariosEvent writes through to the cache on success',
      setUp: () {
        when(() => mockRepo.fetchScenarios())
            .thenAnswer((_) async => _result(_fiveScenarios));
      },
      build: buildBloc,
      seed: () =>
          const ScenariosLoaded(scenarios: <Scenario>[], usage: _kFreshUsage),
      act: (bloc) => bloc.add(const RefreshScenariosEvent()),
      expect: () => [isA<ScenariosLoaded>()],
      verify: (_) => verify(() => mockStore.writeScenarios(any())).called(1),
    );
  });

  group('Story 9.1 — cache-first load', () {
    const refreshedUsage = CallUsage(
      tier: 'free',
      callsRemaining: 2, // was 3 — proves the fresh emission replaced the cache
      callsPerPeriod: 3,
      period: 'lifetime',
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'cache-hit then successful refresh emits '
      '[Loaded(fromCache:true), Loaded(fresh)] and writes through',
      setUp: () {
        when(() => mockStore.readScenarios())
            .thenAnswer((_) async => _result(_fiveScenarios));
        when(() => mockRepo.fetchScenarios()).thenAnswer(
          (_) async => _result(_fiveScenarios, usage: refreshedUsage),
        );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoaded>()
            .having((s) => s.fromCache, 'fromCache', true)
            .having((s) => s.scenarios.length, 'scenarios.length', 5),
        isA<ScenariosLoaded>()
            .having((s) => s.fromCache, 'fromCache', false)
            .having((s) => s.usage.callsRemaining, 'fresh usage', 2),
      ],
      verify: (_) {
        verify(() => mockStore.writeScenarios(any())).called(1);
      },
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'cache-hit + network failure stays SILENT — '
      'emits Loaded(fromCache) only, NO ScenariosError',
      setUp: () {
        when(() => mockStore.readScenarios())
            .thenAnswer((_) async => _result(_fiveScenarios));
        when(() => mockRepo.fetchScenarios()).thenThrow(
          const ApiException(code: 'NETWORK_ERROR', message: 'down'),
        );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoaded>().having((s) => s.fromCache, 'fromCache', true),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'no cache + network failure emits [Loading, ScenariosError] (unchanged)',
      setUp: () {
        when(() => mockStore.readScenarios()).thenAnswer((_) async => null);
        when(() => mockRepo.fetchScenarios()).thenThrow(
          const ApiException(code: 'NETWORK_ERROR', message: 'down'),
        );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>().having((s) => s.code, 'code', 'NETWORK_ERROR'),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'a cache-WRITE failure never downgrades a successful fetch',
      setUp: () {
        when(() => mockStore.readScenarios()).thenAnswer((_) async => null);
        when(() => mockRepo.fetchScenarios())
            .thenAnswer((_) async => _result(_fiveScenarios));
        when(() => mockStore.writeScenarios(any()))
            .thenThrow(Exception('disk full'));
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosLoaded>()
            .having((s) => s.scenarios.length, 'scenarios.length', 5),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'a null cacheStore is tolerated — network-only behaviour preserved',
      setUp: () {
        when(() => mockRepo.fetchScenarios())
            .thenAnswer((_) async => _result(_fiveScenarios));
      },
      build: () => ScenariosBloc(mockRepo), // no cacheStore
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosLoaded>().having((s) => s.fromCache, 'fromCache', false),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'a re-entrant load DURING the cache-hit refresh window is dropped '
      '(in-flight guard holds when the state is Loaded, not Loading)',
      setUp: () {
        // Cache hit → the bloc emits Loaded(fromCache) and stays Loaded for the
        // whole fetch window. The old `state is ScenariosLoading` guard alone
        // would NOT fire here; `_loadInFlight` must.
        when(() => mockStore.readScenarios())
            .thenAnswer((_) async => _result(_fiveScenarios));
        when(() => mockRepo.fetchScenarios()).thenAnswer((_) async {
          await Future<void>.delayed(const Duration(milliseconds: 50));
          return _result(_fiveScenarios);
        });
      },
      build: buildBloc,
      act: (bloc) async {
        bloc.add(const LoadScenariosEvent());
        // Yield so the first load emits Loaded(fromCache) and parks on the
        // (delayed) network fetch with _loadInFlight == true.
        await pumpEventQueue();
        bloc.add(const LoadScenariosEvent()); // must be dropped
      },
      wait: const Duration(milliseconds: 200),
      expect: () => [
        isA<ScenariosLoaded>().having((s) => s.fromCache, 'fromCache', true),
        isA<ScenariosLoaded>().having((s) => s.fromCache, 'fromCache', false),
      ],
      verify: (_) {
        // The guard cancelled the second load — exactly ONE network fetch
        // (no stacked parallel requests / out-of-order overwrite).
        verify(() => mockRepo.fetchScenarios()).called(1);
      },
    );
  });
}
