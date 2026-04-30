import 'package:client/core/api/api_client.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockApiClient extends Mock implements ApiClient {}

void main() {
  late MockApiClient mockApiClient;
  late CallRepository repository;

  setUp(() {
    mockApiClient = MockApiClient();
    repository = CallRepository(mockApiClient);
  });

  Response<Map<String, dynamic>> envelope(Map<String, dynamic> data) {
    return Response<Map<String, dynamic>>(
      requestOptions: RequestOptions(path: '/calls/initiate'),
      statusCode: 200,
      data: <String, dynamic>{
        'data': data,
        'meta': const {'timestamp': '2026-04-29T10:00:00Z'},
      },
    );
  }

  group('CallRepository.initiateCall', () {
    test('posts {"scenario_id": ...} body to /calls/initiate', () async {
      Map<String, dynamic>? capturedBody;
      when(
        () => mockApiClient.post<Map<String, dynamic>>(
          '/calls/initiate',
          data: any(named: 'data'),
        ),
      ).thenAnswer((invocation) async {
        capturedBody =
            invocation.namedArguments[#data] as Map<String, dynamic>?;
        return envelope(const {
          'call_id': 7,
          'room_name': 'call-xyz',
          'token': 'user-token',
          'livekit_url': 'wss://livekit.example.com',
        });
      });

      await repository.initiateCall(scenarioId: 'waiter_easy_01');

      expect(capturedBody, equals({'scenario_id': 'waiter_easy_01'}));
    });

    test('parses the envelope and returns a CallSession', () async {
      when(
        () => mockApiClient.post<Map<String, dynamic>>(
          '/calls/initiate',
          data: any(named: 'data'),
        ),
      ).thenAnswer(
        (_) async => envelope(const {
          'call_id': 7,
          'room_name': 'call-xyz',
          'token': 'user-token',
          'livekit_url': 'wss://livekit.example.com',
        }),
      );

      final session = await repository.initiateCall(
        scenarioId: 'waiter_easy_01',
      );

      expect(session.callId, 7);
      expect(session.roomName, 'call-xyz');
      expect(session.token, 'user-token');
      expect(session.livekitUrl, 'wss://livekit.example.com');
    });

    test('propagates ApiException from ApiClient', () async {
      when(
        () => mockApiClient.post<Map<String, dynamic>>(
          '/calls/initiate',
          data: any(named: 'data'),
        ),
      ).thenThrow(
        const ApiException(code: 'NETWORK_ERROR', message: 'No connection.'),
      );

      expect(
        () => repository.initiateCall(scenarioId: 'waiter_easy_01'),
        throwsA(
          isA<ApiException>().having((e) => e.code, 'code', 'NETWORK_ERROR'),
        ),
      );
    });

    test('throws TypeError when response data shape is malformed', () async {
      when(
        () => mockApiClient.post<Map<String, dynamic>>(
          '/calls/initiate',
          data: any(named: 'data'),
        ),
      ).thenAnswer(
        (_) async => Response<Map<String, dynamic>>(
          requestOptions: RequestOptions(path: '/calls/initiate'),
          statusCode: 200,
          data: const {'unexpected': 'shape'},
        ),
      );

      expect(
        () => repository.initiateCall(scenarioId: 'waiter_easy_01'),
        throwsA(isA<TypeError>()),
      );
    });
  });
}
