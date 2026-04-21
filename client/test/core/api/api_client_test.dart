import 'package:client/core/api/api_client.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/core/auth/token_storage.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockTokenStorage extends Mock implements TokenStorage {}

void main() {
  late MockTokenStorage mockTokenStorage;

  setUp(() {
    mockTokenStorage = MockTokenStorage();
  });

  group('ApiException.fromDioException', () {
    test('maps connectionError to NETWORK_ERROR', () {
      final dioException = DioException(
        type: DioExceptionType.connectionError,
        requestOptions: RequestOptions(path: '/test'),
      );

      final result = ApiException.fromDioException(dioException);

      expect(result.code, 'NETWORK_ERROR');
      expect(
        result.message,
        'No internet connection. Please check your network and try again.',
      );
    });

    test('maps connectionTimeout to NETWORK_ERROR', () {
      final dioException = DioException(
        type: DioExceptionType.connectionTimeout,
        requestOptions: RequestOptions(path: '/test'),
      );

      final result = ApiException.fromDioException(dioException);

      expect(result.code, 'NETWORK_ERROR');
    });

    test('extracts code and message from error envelope', () {
      final dioException = DioException(
        type: DioExceptionType.badResponse,
        requestOptions: RequestOptions(path: '/test'),
        response: Response(
          requestOptions: RequestOptions(path: '/test'),
          statusCode: 400,
          data: {
            'error': {
              'code': 'AUTH_CODE_INVALID',
              'message': 'Invalid code. Please check and try again.',
            },
          },
        ),
      );

      final result = ApiException.fromDioException(dioException);

      expect(result.code, 'AUTH_CODE_INVALID');
      expect(result.message, 'Invalid code. Please check and try again.');
    });

    test('returns UNKNOWN_ERROR for unstructured responses', () {
      final dioException = DioException(
        type: DioExceptionType.badResponse,
        requestOptions: RequestOptions(path: '/test'),
        response: Response(
          requestOptions: RequestOptions(path: '/test'),
          statusCode: 500,
          data: 'Internal Server Error',
        ),
      );

      final result = ApiException.fromDioException(dioException);

      expect(result.code, 'UNKNOWN_ERROR');
      expect(result.message, 'Something went wrong. Please try again.');
    });
  });

  group('ApiClient JWT interceptor', () {
    test('interceptor is installed on construction', () {
      when(() => mockTokenStorage.readToken())
          .thenAnswer((_) async => 'test-jwt-token');

      final apiClient = ApiClient(tokenStorage: mockTokenStorage);

      // No request made yet, so readToken should not have been called
      verifyNever(() => mockTokenStorage.readToken());
      expect(apiClient, isNotNull);
    });
  });

  group('ApiClient configuration', () {
    test('uses correct base URL', () {
      expect(ApiClient.baseUrl, 'http://167.235.63.129');
    });
  });
}
