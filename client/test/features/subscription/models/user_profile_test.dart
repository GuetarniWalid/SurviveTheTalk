import 'package:client/features/subscription/models/user_profile.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('parses a free profile', () {
    final p = UserProfile.fromJson(const {
      'tier': 'free',
      'calls_remaining': 2,
      'calls_per_period': 3,
      'period': 'lifetime',
      'subscription_expires_at': null,
    });

    expect(p.tier, 'free');
    expect(p.isFree, isTrue);
    expect(p.isPaid, isFalse);
    expect(p.callsRemaining, 2);
    expect(p.callsPerPeriod, 3);
    expect(p.isLifetimePeriod, isTrue);
    expect(p.subscriptionExpiresAt, isNull);
  });

  test('parses a paid profile with an expiry', () {
    final p = UserProfile.fromJson(const {
      'tier': 'paid',
      'calls_remaining': 3,
      'calls_per_period': 3,
      'period': 'day',
      'subscription_expires_at': '2099-07-18T00:00:00Z',
    });

    expect(p.isPaid, isTrue);
    expect(p.isLifetimePeriod, isFalse);
    expect(p.subscriptionExpiresAt, '2099-07-18T00:00:00Z');
  });

  test('clamps a negative calls_remaining to 0', () {
    final p = UserProfile.fromJson(const {
      'tier': 'free',
      'calls_remaining': -1,
      'calls_per_period': 3,
      'period': 'lifetime',
    });

    expect(p.callsRemaining, 0);
  });

  test('throws FormatException on a non-positive calls_per_period', () {
    expect(
      () => UserProfile.fromJson(const {
        'tier': 'free',
        'calls_remaining': 0,
        'calls_per_period': 0,
        'period': 'lifetime',
      }),
      throwsFormatException,
    );
  });
}
