import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/features/scenarios/bloc/scenarios_bloc.dart';
import 'package:client/features/scenarios/bloc/scenarios_event.dart';
import 'package:client/features/scenarios/bloc/scenarios_state.dart';
import 'package:client/features/scenarios/models/scenario.dart';
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
            .thenAnswer((_) async => _fiveScenarios);
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
      'network error emits [Loading, Error] with the ApiException message',
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
        isA<ScenariosError>().having(
          (s) => s.message,
          'message',
          'No internet connection. Please check your network and try again.',
        ),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      '401 surfaces through Error (bloc agnostic to error code)',
      setUp: () {
        when(() => mockRepo.fetchScenarios()).thenThrow(
          const ApiException(
            code: 'AUTH_UNAUTHORIZED',
            message: 'Session expired.',
          ),
        );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>().having(
          (s) => s.message,
          'message',
          'Session expired.',
        ),
      ],
    );

    blocTest<ScenariosBloc, ScenariosState>(
      'spam-tap during Loading is dropped (no parallel requests)',
      setUp: () {
        // Repo answer is delayed so the second event lands while the first
        // is still in flight. The guard must short-circuit the second event.
        when(() => mockRepo.fetchScenarios()).thenAnswer((_) async {
          await Future<void>.delayed(const Duration(milliseconds: 50));
          return _fiveScenarios;
        });
      },
      build: buildBloc,
      act: (bloc) async {
        bloc.add(const LoadScenariosEvent());
        // Yield once so _onLoad starts and emits Loading before the second
        // event is dispatched.
        await Future<void>.delayed(Duration.zero);
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
      'malformed-payload TypeError surfaces through Error (generic catch)',
      setUp: () {
        // Repository can throw a bare TypeError on cast failure inside
        // Scenario.fromJson — without the bloc's generic catch, this
        // would escape and leave the UI hung in ScenariosLoading.
        when(() => mockRepo.fetchScenarios()).thenThrow(TypeError());
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const LoadScenariosEvent()),
      expect: () => [
        isA<ScenariosLoading>(),
        isA<ScenariosError>().having(
          (s) => s.message,
          'message',
          'Unexpected response. Please try again.',
        ),
      ],
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
          return _fiveScenarios;
        });
      },
      build: buildBloc,
      act: (bloc) async {
        bloc.add(const LoadScenariosEvent());
        await Future<void>.delayed(Duration.zero);
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
