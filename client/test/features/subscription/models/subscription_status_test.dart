import 'package:client/features/subscription/models/subscription_status.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('SubscriptionStatus', () {
    test('fromJson maps a paid envelope', () {
      final status = SubscriptionStatus.fromJson(const {
        'tier': 'paid',
        'product_id': 'stt_weekly_199',
        'expires_at': '2026-06-23T00:00:00Z',
        'status': 'valid',
      });

      expect(status.tier, 'paid');
      expect(status.productId, 'stt_weekly_199');
      expect(status.expiresAt, '2026-06-23T00:00:00Z');
      expect(status.status, 'valid');
      expect(status.isPaid, isTrue);
    });

    test('isPaid is false for a free tier', () {
      final status = SubscriptionStatus.fromJson(const {
        'tier': 'free',
        'status': 'valid',
      });
      expect(status.isPaid, isFalse);
    });

    test('tolerates absent optional fields (product_id / expires_at)', () {
      final status = SubscriptionStatus.fromJson(const {
        'tier': 'paid',
        'status': 'pending',
      });
      expect(status.productId, isNull);
      expect(status.expiresAt, isNull);
      expect(status.status, 'pending');
      expect(status.isPaid, isTrue);
    });

    test('throws on a malformed payload (missing required tier)', () {
      expect(
        () => SubscriptionStatus.fromJson(const {'status': 'valid'}),
        throwsA(isA<TypeError>()),
      );
    });
  });
}
