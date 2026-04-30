import 'package:client/features/call/views/tutorial_scenario.dart';
import 'package:client/features/scenarios/character_catalog.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('TutorialScenario', () {
    test('id and riveCharacter are non-empty', () {
      expect(TutorialScenario.id, isNotEmpty);
      expect(TutorialScenario.riveCharacter, isNotEmpty);
    });

    test('scenario id matches server-side waiter tutorial id', () {
      // Contract with server/pipeline/scenarios.py TUTORIAL_SCENARIO_ID.
      // Divergence here would make the Accept flow spawn the wrong bot.
      expect(TutorialScenario.id, 'waiter_easy_01');
    });

    test('rive character matches the expected enum value', () {
      // Must match one of the `character` enum values on ViewModel1 inside
      // client/assets/rive/characters.riv. Getting this wrong surfaces as
      // a blank avatar at runtime.
      expect(TutorialScenario.riveCharacter, 'waiter');
    });

    test('rive character resolves to a catalog entry', () {
      // Without this, `IncomingCallScreen` and `CallScreen.CallConnecting`
      // would render an empty name/role and a placeholder avatar.
      expect(kCharacterCatalog.containsKey(TutorialScenario.riveCharacter),
          isTrue);
    });
  });
}
