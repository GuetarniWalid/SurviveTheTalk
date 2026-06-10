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

  /// Story 7.2 — server-authored theatrical phrases for the Call Ended
  /// overlay, keyed by variant (`hung_up` / `voluntary` / `survived`).
  /// Null when the server omits the field (legacy payloads) — the overlay
  /// hides the phrase element entirely (design P-7).
  final Map<String, String>? endPhrases;

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
    this.endPhrases,
  });

  factory Scenario.fromJson(Map<String, dynamic> json) {
    final id = json['id'] as String;
    // Story 7.2 — defensive parse: keep only string-valued entries so a
    // malformed server variant can never crash the whole scenario-list
    // parse (the overlay treats a missing variant as "hide the phrase").
    final rawPhrases = json['end_phrases'];
    Map<String, String>? endPhrases;
    if (rawPhrases is Map) {
      endPhrases = <String, String>{
        for (final entry in rawPhrases.entries)
          if (entry.key is String && entry.value is String)
            entry.key as String: entry.value as String,
      };
    }
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
      endPhrases: endPhrases,
    );
  }

  bool get isCompleted => bestScore == 100;
  bool get isNotAttempted => attempts == 0;
}
