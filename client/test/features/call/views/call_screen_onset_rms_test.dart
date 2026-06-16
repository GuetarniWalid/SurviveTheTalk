// Story 7.6 (AC8/AC9) — the `onset_rms` EventChannel parse seam.
//
// A non-`num` event (a future native AudioCaptureChannel contract change) must
// NOT be silently dropped — the call-screen listener logs it. This pins the
// pure parse decision that GATES that log: num → double (fed to the meter),
// non-num → null (logged, dropped). The dev.log side-effect itself is not
// capturable in `flutter test`; the testable seam is this classifier.

import 'package:client/features/call/views/call_screen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('onsetRmsFromEvent', () {
    test('a num event parses to its double value', () {
      expect(onsetRmsFromEvent(42), 42.0);
      expect(onsetRmsFromEvent(3.5), 3.5);
      expect(onsetRmsFromEvent(0), 0.0);
    });

    test('a non-num event returns null (the logged contract-break path)', () {
      expect(onsetRmsFromEvent('loud'), isNull);
      expect(onsetRmsFromEvent(null), isNull);
      expect(onsetRmsFromEvent(<String, Object>{'rms': 1}), isNull);
      expect(onsetRmsFromEvent(const [1, 2, 3]), isNull);
      expect(onsetRmsFromEvent(true), isNull);
    });
  });
}
