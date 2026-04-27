import 'package:client/features/scenarios/models/scenario.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _basePayload() => <String, dynamic>{
      'id': 'waiter_easy_01',
      'title': 'Tina',
      'difficulty': 'easy',
      'is_free': true,
      'rive_character': 'waiter',
      'language_focus': <dynamic>['assertiveness', 'directness'],
      'content_warning': null,
      'best_score': 73,
      'attempts': 2,
    };

void main() {
  group('Scenario.fromJson', () {
    test('maps every API field for a fully-populated row', () {
      final scenario = Scenario.fromJson(_basePayload());

      expect(scenario.id, 'waiter_easy_01');
      expect(scenario.title, 'Tina');
      expect(scenario.difficulty, 'easy');
      expect(scenario.isFree, isTrue);
      expect(scenario.riveCharacter, 'waiter');
      expect(scenario.languageFocus, <String>['assertiveness', 'directness']);
      expect(scenario.contentWarning, isNull);
      expect(scenario.bestScore, 73);
      expect(scenario.attempts, 2);
      expect(scenario.tagline, 'Order before she loses it');
      expect(scenario.isCompleted, isFalse);
      expect(scenario.isNotAttempted, isFalse);
    });

    test('defaults attempts to 0 when the key is missing', () {
      final payload = _basePayload()..remove('attempts');
      final scenario = Scenario.fromJson(payload);

      expect(scenario.attempts, 0);
      expect(scenario.isNotAttempted, isTrue);
    });

    test('handles best_score: null as Dart null', () {
      final payload = _basePayload()..['best_score'] = null;
      final scenario = Scenario.fromJson(payload);

      expect(scenario.bestScore, isNull);
      expect(scenario.isCompleted, isFalse);
    });

    test('hydrates tagline from kScenarioTaglines for a known id', () {
      final scenario = Scenario.fromJson(
        _basePayload()..['id'] = 'cop_hard_01',
      );

      expect(scenario.tagline, 'Step out of the vehicle');
    });

    test('hydrates tagline to empty string for an unknown id', () {
      final scenario = Scenario.fromJson(
        _basePayload()..['id'] = 'unknown_id_999',
      );

      expect(scenario.tagline, '');
    });

    test('marks the row completed when bestScore is 100', () {
      final scenario = Scenario.fromJson(
        _basePayload()
          ..['best_score'] = 100
          ..['attempts'] = 4,
      );

      expect(scenario.isCompleted, isTrue);
      expect(scenario.isNotAttempted, isFalse);
    });
  });
}
