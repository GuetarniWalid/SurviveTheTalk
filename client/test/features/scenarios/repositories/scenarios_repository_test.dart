import 'package:client/core/api/api_client.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/features/scenarios/repositories/scenarios_repository.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockApiClient extends Mock implements ApiClient {}

void main() {
  late MockApiClient mockApiClient;
  late ScenariosRepository repository;

  setUp(() {
    mockApiClient = MockApiClient();
    repository = ScenariosRepository(mockApiClient);
  });

  group('ScenariosRepository.fetchScenarios', () {
    test('parses the envelope and returns 5 Scenario objects', () async {
      when(() => mockApiClient.get<Map<String, dynamic>>('/scenarios'))
          .thenAnswer(
        (_) async => Response<Map<String, dynamic>>(
          requestOptions: RequestOptions(path: '/scenarios'),
          statusCode: 200,
          data: const <String, dynamic>{
            'data': [
              {
                'id': 'waiter_easy_01',
                'title': 'Tina',
                'difficulty': 'easy',
                'is_free': true,
                'rive_character': 'waiter',
                'language_focus': ['assertiveness'],
                'content_warning': null,
                'best_score': null,
                'attempts': 0,
              },
              {
                'id': 'mugger_medium_01',
                'title': 'Mugger',
                'difficulty': 'medium',
                'is_free': true,
                'rive_character': 'mugger',
                'language_focus': ['de-escalation'],
                'content_warning': 'violence',
                'best_score': 80,
                'attempts': 3,
              },
              {
                'id': 'girlfriend_medium_01',
                'title': 'Maya',
                'difficulty': 'medium',
                'is_free': true,
                'rive_character': 'girlfriend',
                'language_focus': ['emotional-regulation'],
                'content_warning': null,
                'best_score': 100,
                'attempts': 1,
              },
              {
                'id': 'cop_hard_01',
                'title': 'Officer Reed',
                'difficulty': 'hard',
                'is_free': false,
                'rive_character': 'cop',
                'language_focus': ['compliance'],
                'content_warning': null,
                'best_score': null,
                'attempts': 0,
              },
              {
                'id': 'landlord_hard_01',
                'title': 'Mr. Dalton',
                'difficulty': 'hard',
                'is_free': false,
                'rive_character': 'landlord',
                'language_focus': ['negotiation'],
                'content_warning': null,
                'best_score': null,
                'attempts': 0,
              },
            ],
            'meta': {
              'count': 5,
              'timestamp': '2026-04-27T10:00:00Z',
              'tier': 'free',
              'calls_remaining': 3,
              'calls_per_period': 3,
              'period': 'lifetime',
            },
          },
        ),
      );

      final result = await repository.fetchScenarios();

      expect(result.scenarios, hasLength(5));
      expect(result.scenarios.first.id, 'waiter_easy_01');
      expect(result.scenarios.last.id, 'landlord_hard_01');
      expect(result.scenarios[2].isCompleted, isTrue);
      expect(result.usage.tier, 'free');
      expect(result.usage.callsRemaining, 3);
      expect(result.usage.callsPerPeriod, 3);
      expect(result.usage.period, 'lifetime');
    });

    test('propagates ApiException from ApiClient.get', () async {
      when(() => mockApiClient.get<Map<String, dynamic>>('/scenarios'))
          .thenThrow(const ApiException(
        code: 'NETWORK_ERROR',
        message:
            'No internet connection. Please check your network and try again.',
      ));

      expect(
        () => repository.fetchScenarios(),
        throwsA(isA<ApiException>()
            .having((e) => e.code, 'code', 'NETWORK_ERROR')),
      );
    });

    test('throws TypeError when response data shape is malformed', () async {
      when(() => mockApiClient.get<Map<String, dynamic>>('/scenarios'))
          .thenAnswer(
        (_) async => Response<Map<String, dynamic>>(
          requestOptions: RequestOptions(path: '/scenarios'),
          statusCode: 200,
          data: const <String, dynamic>{'unexpected': 'shape'},
        ),
      );

      expect(() => repository.fetchScenarios(), throwsA(isA<TypeError>()));
    });

    test(
      'throws TypeError when meta is missing the usage keys (AC4 contract)',
      () async {
        // Story 5.3 AC4: "missing/malformed meta keys throw TypeError (caller
        // treats it as ApiException-equivalent — same blast radius as a
        // malformed scenarios list)". This test locks the contract at the
        // repository boundary, complementing call_usage_test.dart which
        // covers the model-layer factory.
        when(() => mockApiClient.get<Map<String, dynamic>>('/scenarios'))
            .thenAnswer(
          (_) async => Response<Map<String, dynamic>>(
            requestOptions: RequestOptions(path: '/scenarios'),
            statusCode: 200,
            // `data` is well-formed but `meta` lacks tier / calls_remaining
            // / calls_per_period / period — exactly the shape returned by
            // a stale server (pre-5.3 deploy).
            data: const <String, dynamic>{
              'data': <Map<String, dynamic>>[],
              'meta': {
                'count': 0,
                'timestamp': '2026-04-28T12:00:00Z',
              },
            },
          ),
        );

        expect(() => repository.fetchScenarios(), throwsA(isA<TypeError>()));
      },
    );
  });
}
