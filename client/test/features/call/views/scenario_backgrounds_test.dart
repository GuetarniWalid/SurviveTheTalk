import 'package:client/features/call/views/scenario_backgrounds.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('kScenarioBackgrounds', () {
    test('has exactly the 5 expected riveCharacter entries', () {
      expect(kScenarioBackgrounds.keys.toSet(), <String>{
        'mugger',
        'waiter',
        'girlfriend',
        'cop',
        'landlord',
      });
    });

    // Asset bytes are loadable at runtime — proves every JPG path resolves
    // through the Flutter asset bundle (renamed/missing assets would throw).
    // A pure equality check against the same map literal is tautological;
    // this loop is the regression guard.
    for (final entry in kScenarioBackgrounds.entries) {
      testWidgets('asset for "${entry.key}" loads from rootBundle',
          (tester) async {
        final bytes = await rootBundle.load(entry.value);
        expect(bytes.lengthInBytes, greaterThan(0),
            reason: '${entry.value} must resolve to a non-empty asset');
      });
    }
  });
}
