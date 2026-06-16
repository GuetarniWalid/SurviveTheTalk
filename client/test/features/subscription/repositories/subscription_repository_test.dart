import 'package:client/core/api/api_client.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/features/subscription/repositories/subscription_repository.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockApiClient extends Mock implements ApiClient {}

void main() {
  late MockApiClient mockApiClient;
  late SubscriptionRepository repository;

  setUp(() {
    mockApiClient = MockApiClient();
    repository = SubscriptionRepository(mockApiClient);
  });

  Response<Map<String, dynamic>> envelope(Map<String, dynamic> data) {
    return Response<Map<String, dynamic>>(
      requestOptions: RequestOptions(path: '/subscription/verify'),
      statusCode: 200,
      data: <String, dynamic>{
        'data': data,
        'meta': const {'timestamp': '2026-06-16T10:00:00Z'},
      },
    );
  }

  group('SubscriptionRepository.verifyPurchase', () {
    test('posts the platform/product/verification body', () async {
      Map<String, dynamic>? capturedBody;
      String? capturedPath;
      when(
        () => mockApiClient.post<Map<String, dynamic>>(
          any(),
          data: any(named: 'data'),
        ),
      ).thenAnswer((invocation) async {
        capturedPath = invocation.positionalArguments[0] as String?;
        capturedBody = invocation.namedArguments[#data] as Map<String, dynamic>?;
        return envelope(const {
          'tier': 'paid',
          'product_id': 'stt_weekly_199',
          'expires_at': null,
          'status': 'valid',
        });
      });

      await repository.verifyPurchase(
        platform: 'android',
        productId: 'stt_weekly_199',
        verificationData: 'token-abc',
      );

      expect(capturedPath, '/subscription/verify');
      expect(capturedBody, {
        'platform': 'android',
        'product_id': 'stt_weekly_199',
        'verification_data': 'token-abc',
      });
    });

    test('parses the {data} envelope into a paid SubscriptionStatus', () async {
      when(
        () => mockApiClient.post<Map<String, dynamic>>(
          any(),
          data: any(named: 'data'),
        ),
      ).thenAnswer(
        (_) async => envelope(const {
          'tier': 'paid',
          'product_id': 'stt_weekly_199',
          'expires_at': '2026-06-23T00:00:00Z',
          'status': 'valid',
        }),
      );

      final status = await repository.verifyPurchase(
        platform: 'ios',
        productId: 'stt_weekly_199',
        verificationData: 'jws',
      );

      expect(status.isPaid, isTrue);
      expect(status.status, 'valid');
      expect(status.expiresAt, '2026-06-23T00:00:00Z');
    });

    test('propagates ApiException (the bloc classifies it)', () async {
      when(
        () => mockApiClient.post<Map<String, dynamic>>(
          any(),
          data: any(named: 'data'),
        ),
      ).thenThrow(
        const ApiException(
          code: 'PURCHASE_INVALID',
          message: "We couldn't validate that purchase.",
          statusCode: 402,
        ),
      );

      expect(
        () => repository.verifyPurchase(
          platform: 'ios',
          productId: 'stt_weekly_199',
          verificationData: 'jws',
        ),
        throwsA(
          isA<ApiException>().having((e) => e.code, 'code', 'PURCHASE_INVALID'),
        ),
      );
    });
  });
}
