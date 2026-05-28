import 'package:client/features/call/views/call_screen.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:livekit_client/livekit_client.dart';

/// Story 6.13 follow-up — unit coverage for the weak-connection decision
/// that drives the in-call "weak connection" banner. The banner UI +
/// debounce live on `_CallScreenState` (UI-only, hard to drive without a
/// full Room); the load-bearing rule (which `ConnectionQuality` values
/// warn the user) is extracted to a pure top-level function so it's
/// covered here.
void main() {
  group('isWeakConnectionQuality', () {
    test('poor and lost are degraded → warn the user', () {
      expect(isWeakConnectionQuality(ConnectionQuality.poor), isTrue);
      expect(isWeakConnectionQuality(ConnectionQuality.lost), isTrue);
    });

    test('excellent / good / unknown do NOT warn', () {
      // `unknown` is the pre-measurement state at connect — must NOT trip
      // the banner on every call start.
      expect(isWeakConnectionQuality(ConnectionQuality.excellent), isFalse);
      expect(isWeakConnectionQuality(ConnectionQuality.good), isFalse);
      expect(isWeakConnectionQuality(ConnectionQuality.unknown), isFalse);
    });
  });
}
