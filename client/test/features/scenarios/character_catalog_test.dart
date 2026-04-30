import 'package:client/features/call/views/scenario_backgrounds.dart';
import 'package:client/features/scenarios/character_catalog.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('kCharacterCatalog', () {
    test('has the same key set as kScenarioBackgrounds', () {
      // Both maps are keyed by the `riveCharacter` enum value; if one drops
      // a key the in-call surface (background) and the dial surface
      // (avatar/name/role) would silently misalign for that scenario.
      expect(
        kCharacterCatalog.keys.toSet(),
        kScenarioBackgrounds.keys.toSet(),
      );
    });

    test('every entry has a non-empty name and role', () {
      for (final entry in kCharacterCatalog.entries) {
        expect(entry.value.name, isNotEmpty,
            reason: 'name missing for "${entry.key}"');
        expect(entry.value.role, isNotEmpty,
            reason: 'role missing for "${entry.key}"');
      }
    });

    // The avatar JPG bytes must resolve at runtime. Catches a renamed,
    // moved, or unregistered (in pubspec) asset. A pure string-equality
    // test against the map literal would not catch this.
    for (final entry in kCharacterCatalog.entries) {
      testWidgets('avatar JPG for "${entry.key}" loads from rootBundle',
          (tester) async {
        final bytes = await rootBundle.load(entry.value.imageAsset);
        expect(bytes.lengthInBytes, greaterThan(0),
            reason:
                '${entry.value.imageAsset} must resolve to a non-empty asset');
      });
    }
  });
}
