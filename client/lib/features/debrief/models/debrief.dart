// Story 7.3 — debrief wire models for `GET /debriefs/{call_id}` (server
// `DebriefOut`, server/models/schemas.py). Manual fromJson per the house
// pattern (CallSession / EndCallResult) — no codegen.
//
// Parsing contract (story Task 1.2):
//   - The four hero scalars (`survival_pct`, `character_name`,
//     `scenario_title`, `attempt_number`) are REQUIRED and strictly
//     typed — any missing/mistyped one fails the WHOLE parse
//     (`Debrief.tryParse` → null → the screen's "unavailable" state).
//     A silently-defaulted "0%" would lie to the user about their score.
//   - Arrays default to empty when absent/malformed; malformed ITEMS are
//     skipped defensively (render whatever survives).
//   - `previous_best`, `inappropriate_behavior`, `encouraging_framing`
//     (+ its `improvement`) are nullable — an absent key reads the same
//     as a null value; dependent UI hides either way.

/// One deduplicated language error (FR10). `count` >= 1; the UI shows
/// the "(×N)" badge only when count >= 2.
class DebriefError {
  final String userSaid;
  final String correction;
  final String context;
  final int count;

  const DebriefError({
    required this.userSaid,
    required this.correction,
    required this.context,
    required this.count,
  });

  static DebriefError? tryParse(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    final userSaid = _asString(raw['user_said']);
    final correction = _asString(raw['correction']);
    final context = _asString(raw['context']);
    if (userSaid == null || correction == null || context == null) return null;
    // A missing/mistyped count never kills the card — default to 1 and
    // floor at 1 (the server contract guarantees >= 1).
    final count = _asInt(raw['count']) ?? 1;
    return DebriefError(
      userSaid: userSaid,
      correction: correction,
      context: context,
      count: count < 1 ? 1 : count,
    );
  }
}

/// A >3 s hesitation (FR12) — backend-measured duration + LLM context.
class DebriefHesitation {
  final double durationSec;
  final String context;

  const DebriefHesitation({required this.durationSec, required this.context});

  static DebriefHesitation? tryParse(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    // The wire type is float, but a whole-second value arrives as a JSON
    // int — accept any num.
    final durationSec = raw['duration_sec'];
    final context = _asString(raw['context']);
    if (durationSec is! num || context == null) return null;
    return DebriefHesitation(
      durationSec: durationSec.toDouble(),
      context: context,
    );
  }
}

/// An idiom/slang expression the character used (FR13).
class DebriefIdiom {
  final String expression;
  final String meaning;
  final String context;

  const DebriefIdiom({
    required this.expression,
    required this.meaning,
    required this.context,
  });

  static DebriefIdiom? tryParse(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    final expression = _asString(raw['expression']);
    final meaning = _asString(raw['meaning']);
    final context = _asString(raw['context']);
    if (expression == null || meaning == null || context == null) return null;
    return DebriefIdiom(
      expression: expression,
      meaning: meaning,
      context: context,
    );
  }
}

/// FR15b data-driven framing — the server OMITS the key entirely when
/// survival <= 40 (absent and null read identically here). Copy is
/// composed server-side; render verbatim.
class EncouragingFraming {
  final String proximity;
  final String? improvement;

  const EncouragingFraming({required this.proximity, this.improvement});

  static EncouragingFraming? tryParse(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    final proximity = _asString(raw['proximity']);
    if (proximity == null) return null;
    return EncouragingFraming(
      proximity: proximity,
      improvement: _asString(raw['improvement']),
    );
  }
}

/// The assembled debrief (`DebriefOut`).
class Debrief {
  final int survivalPct;
  final String characterName;
  final String scenarioTitle;
  final int attemptNumber;
  final int? previousBest;
  final List<DebriefError> errors;

  /// Sorted longest-first at parse time (design: longest first — don't
  /// trust wire order).
  final List<DebriefHesitation> hesitations;
  final List<DebriefIdiom> idioms;
  final List<String> areasToWorkOn;
  final String? inappropriateBehavior;
  final EncouragingFraming? encouragingFraming;

  const Debrief({
    required this.survivalPct,
    required this.characterName,
    required this.scenarioTitle,
    required this.attemptNumber,
    required this.previousBest,
    required this.errors,
    required this.hesitations,
    required this.idioms,
    required this.areasToWorkOn,
    required this.inappropriateBehavior,
    required this.encouragingFraming,
  });

  static Debrief? tryParse(Map<String, dynamic>? json) {
    if (json == null) return null;
    final survivalPct = json['survival_pct'];
    final characterName = json['character_name'];
    final scenarioTitle = json['scenario_title'];
    final attemptNumber = json['attempt_number'];
    if (survivalPct is! int ||
        characterName is! String ||
        scenarioTitle is! String ||
        attemptNumber is! int) {
      return null;
    }
    final hesitations = _parseItems(
      json['hesitations'],
      DebriefHesitation.tryParse,
    )..sort((a, b) => b.durationSec.compareTo(a.durationSec));
    return Debrief(
      survivalPct: survivalPct,
      characterName: characterName,
      scenarioTitle: scenarioTitle,
      attemptNumber: attemptNumber,
      previousBest: _asInt(json['previous_best']),
      errors: _parseItems(json['errors'], DebriefError.tryParse),
      hesitations: hesitations,
      idioms: _parseItems(json['idioms'], DebriefIdiom.tryParse),
      areasToWorkOn: _parseItems(json['areas_to_work_on'], _asString),
      inappropriateBehavior: _asString(json['inappropriate_behavior']),
      encouragingFraming: EncouragingFraming.tryParse(
        json['encouraging_framing'],
      ),
    );
  }
}

int? _asInt(Object? value) => value is int ? value : null;

String? _asString(Object? value) => value is String ? value : null;

/// Parses a JSON array defensively: a non-list (absent/malformed) yields
/// an empty list; items that fail to parse are skipped.
List<T> _parseItems<T extends Object>(
  Object? raw,
  T? Function(Object?) parseItem,
) {
  if (raw is! List) return <T>[];
  final items = <T>[];
  for (final entry in raw) {
    final parsed = parseItem(entry);
    if (parsed != null) items.add(parsed);
  }
  return items;
}
