import 'scenario_taglines.dart';

class Scenario {
  final String id;
  final String title;
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

  /// Story 7.4 — server-authored pre-scenario briefing, keyed by section
  /// (`vocabulary` / `context` / `expect`). Null when the server omits the
  /// field (legacy payloads) — the BriefingScreen gate is skipped entirely
  /// when there is no renderable content (see [hasBriefingContent]).
  final Map<String, String>? briefing;

  const Scenario({
    required this.id,
    required this.title,
    required this.isFree,
    required this.riveCharacter,
    required this.languageFocus,
    required this.contentWarning,
    required this.bestScore,
    required this.attempts,
    required this.tagline,
    this.endPhrases,
    this.briefing,
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
    // Story 7.4 — same defensive shape as end_phrases above: a malformed
    // briefing payload degrades to "no briefing" (gate skipped), never a
    // list-parse crash.
    final rawBriefing = json['briefing'];
    Map<String, String>? briefing;
    if (rawBriefing is Map) {
      briefing = <String, String>{
        for (final entry in rawBriefing.entries)
          if (entry.key is String && entry.value is String)
            entry.key as String: entry.value as String,
      };
    }
    return Scenario(
      id: id,
      title: json['title'] as String,
      isFree: json['is_free'] as bool,
      riveCharacter: json['rive_character'] as String,
      languageFocus: (json['language_focus'] as List).cast<String>(),
      contentWarning: json['content_warning'] as String?,
      bestScore: json['best_score'] as int?,
      attempts: json['attempts'] as int? ?? 0,
      tagline: kScenarioTaglines[id] ?? '',
      endPhrases: endPhrases,
      briefing: briefing,
    );
  }

  bool get isCompleted => bestScore == 100;
  bool get isNotAttempted => attempts == 0;

  /// Story 7.4 — true iff at least one of the three canonical briefing
  /// sections (`context` / `expect` / `vocabulary` — the only keys the
  /// BriefingScreen renders) is a non-empty trimmed string. A value under
  /// any other key never counts: it would gate into a blank dossier.
  /// Drives the first-attempt call-icon gate ONLY — the browse card-tap
  /// entry pushes the screen regardless of content (AC-C7).
  bool get hasBriefingContent => const ['context', 'expect', 'vocabulary']
      .any((key) => (briefing?[key])?.trim().isNotEmpty ?? false);
}
