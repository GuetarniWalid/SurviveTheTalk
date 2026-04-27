import 'package:client/features/scenarios/models/scenario_taglines.dart';
import 'package:flutter_test/flutter_test.dart';

/// Ids must stay in sync with `server/db/seed_scenarios.py` (Story 5.1
/// seeded 5 scenarios). Fail loudly if a new id ships server-side without
/// a matching client-side tagline — otherwise the card silently degrades
/// to a 1-line layout (only catchable by manual QA).
const _kExpectedSeededIds = <String>{
  'waiter_easy_01',
  'mugger_medium_01',
  'girlfriend_medium_01',
  'cop_hard_01',
  'landlord_hard_01',
};

void main() {
  group('kScenarioTaglines', () {
    test('covers every seeded scenario id', () {
      expect(
        kScenarioTaglines.keys.toSet(),
        equals(_kExpectedSeededIds),
        reason:
            'kScenarioTaglines must contain a tagline for every id seeded '
            'by server/db/seed_scenarios.py. If the server adds a new '
            'scenario, update this map AND _kExpectedSeededIds.',
      );
    });

    test('every tagline is non-empty', () {
      for (final entry in kScenarioTaglines.entries) {
        expect(
          entry.value,
          isNotEmpty,
          reason: 'Tagline for "${entry.key}" must not be empty.',
        );
      }
    });

    test('every tagline stays under the 40-char wrap budget', () {
      // > 40 chars wraps to a 3rd line at 320-px width and breaks the card
      // height contract from the Figma frame.
      for (final entry in kScenarioTaglines.entries) {
        expect(
          entry.value.length,
          lessThanOrEqualTo(40),
          reason:
              'Tagline for "${entry.key}" is ${entry.value.length} chars; '
              'must be <= 40 to avoid a 3rd-line wrap on 320-px screens.',
        );
      }
    });
  });
}
