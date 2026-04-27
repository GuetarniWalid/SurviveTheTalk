import 'scenario_taglines.dart';

class Scenario {
  final String id;
  final String title;
  final String difficulty;
  final bool isFree;
  final String riveCharacter;
  final List<String> languageFocus;
  final String? contentWarning;
  final int? bestScore;
  final int attempts;
  final String tagline;

  const Scenario({
    required this.id,
    required this.title,
    required this.difficulty,
    required this.isFree,
    required this.riveCharacter,
    required this.languageFocus,
    required this.contentWarning,
    required this.bestScore,
    required this.attempts,
    required this.tagline,
  });

  factory Scenario.fromJson(Map<String, dynamic> json) {
    final id = json['id'] as String;
    return Scenario(
      id: id,
      title: json['title'] as String,
      difficulty: json['difficulty'] as String,
      isFree: json['is_free'] as bool,
      riveCharacter: json['rive_character'] as String,
      languageFocus: (json['language_focus'] as List).cast<String>(),
      contentWarning: json['content_warning'] as String?,
      bestScore: json['best_score'] as int?,
      attempts: json['attempts'] as int? ?? 0,
      tagline: kScenarioTaglines[id] ?? '',
    );
  }

  bool get isCompleted => bestScore == 100;
  bool get isNotAttempted => attempts == 0;
}
