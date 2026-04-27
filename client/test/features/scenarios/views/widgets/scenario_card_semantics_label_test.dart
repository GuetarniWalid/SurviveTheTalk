import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/views/widgets/scenario_card.dart';
import 'package:flutter_test/flutter_test.dart';

Scenario _buildScenario({
  String id = 'waiter_easy_01',
  String title = 'Tina',
  String tagline = 'Order before she loses it',
  int? bestScore,
  int attempts = 0,
}) {
  return Scenario(
    id: id,
    title: title,
    difficulty: 'easy',
    isFree: true,
    riveCharacter: 'waiter',
    languageFocus: const <String>[],
    contentWarning: null,
    bestScore: bestScore,
    attempts: attempts,
    tagline: tagline,
  );
}

void main() {
  group('buildCardDescriptionLabel', () {
    test('not-attempted state announces title, tagline, and state only', () {
      final label = buildCardDescriptionLabel(_buildScenario());

      expect(
        label,
        'Tina. Order before she loses it. Not attempted.',
      );
    });

    test('in-progress state includes best score, attempts, and "in progress"',
        () {
      final label = buildCardDescriptionLabel(
        _buildScenario(bestScore: 73, attempts: 3),
      );

      expect(
        label,
        'Tina. Order before she loses it. Best 73%, 3 attempts, in progress.',
      );
    });

    test('completed state announces 100% and "completed"', () {
      final label = buildCardDescriptionLabel(
        _buildScenario(bestScore: 100, attempts: 2),
      );

      expect(
        label,
        'Tina. Order before she loses it. Best 100%, 2 attempts, completed.',
      );
    });

    test('singular "1 attempt" — not "1 attempts" — when attempts == 1', () {
      final label = buildCardDescriptionLabel(
        _buildScenario(bestScore: 50, attempts: 1),
      );

      expect(
        label,
        'Tina. Order before she loses it. Best 50%, 1 attempt, in progress.',
      );
    });
  });
}
