import 'package:client/features/scenarios/models/call_usage.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('CallUsage.fromMeta', () {
    test('parses the canonical 4-key meta block', () {
      final meta = <String, dynamic>{
        // Extra keys (count, timestamp) coexist with the usage keys — the
        // factory must ignore them rather than fail.
        'count': 5,
        'timestamp': '2026-04-28T12:00:00Z',
        'tier': 'paid',
        'calls_remaining': 1,
        'calls_per_period': 3,
        'period': 'day',
      };

      final usage = CallUsage.fromMeta(meta);

      expect(usage.tier, 'paid');
      expect(usage.callsRemaining, 1);
      expect(usage.callsPerPeriod, 3);
      expect(usage.period, 'day');
    });

    test('throws TypeError when a required key is missing', () {
      // The repository contract is: `meta` MUST carry the four keys. A
      // missing key is a server bug — surface it as the same blast radius
      // as a malformed scenarios list (TypeError, then ApiException-equiv
      // upstream).
      final meta = <String, dynamic>{
        'tier': 'free',
        'calls_remaining': 3,
        // 'calls_per_period' missing
        'period': 'lifetime',
      };

      expect(() => CallUsage.fromMeta(meta), throwsA(isA<TypeError>()));
    });
  });

  group('accessor flags', () {
    test('isFree / hasCallsRemaining / isLifetimePeriod for free user', () {
      const usage = CallUsage(
        tier: 'free',
        callsRemaining: 2,
        callsPerPeriod: 3,
        period: 'lifetime',
      );

      expect(usage.isFree, isTrue);
      expect(usage.hasCallsRemaining, isTrue);
      expect(usage.isLifetimePeriod, isTrue);
    });

    test('hasCallsRemaining is false when callsRemaining == 0', () {
      const usage = CallUsage(
        tier: 'paid',
        callsRemaining: 0,
        callsPerPeriod: 3,
        period: 'day',
      );

      expect(usage.isFree, isFalse);
      expect(usage.hasCallsRemaining, isFalse);
      expect(usage.isLifetimePeriod, isFalse);
    });
  });
}
