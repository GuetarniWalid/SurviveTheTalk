// Story 7.3 — debrief wire models for `GET /debriefs/{call_id}` (server
// `DebriefOut`, server/models/schemas.py). Manual fromJson per the house
// pattern (CallSession / EndCallResult) — no codegen.
//
// Parsing contract (story 7.3 Task 1.2, extended for Story 7.5 v2):
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
//   - Story 7.5 v2 fields are ADDITIVE + defaulted: a stored v1 payload
//     (which lacks `debrief_version`, `checkpoints`, `better_phrasings`,
//     `areas`, and the per-error/per-hesitation v2 keys) parses unchanged —
//     `debriefVersion` defaults to 1, the new lists to empty, the new
//     scalars to neutral defaults. So this model renders BOTH a v1 and a v2
//     payload without crashing (Story 7.5 AC2).

/// One deduplicated language error (FR10). `count` >= 1; the UI shows
/// the "(×N)" badge only when count >= 2.
///
/// Story 7.5 v2 adds tap-sheet depth (B1): `explanation` (the underlying
/// rule, one sentence) and `examples` (extra correct sentences). Both are
/// optional — a v1 error parses with `explanation == null` + empty `examples`.
class DebriefError {
  final String userSaid;
  final String correction;
  final String context;
  final int count;
  final String? explanation;
  final List<String> examples;

  const DebriefError({
    required this.userSaid,
    required this.correction,
    required this.context,
    required this.count,
    this.explanation,
    this.examples = const [],
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
      explanation: _asString(raw['explanation']),
      examples: _parseItems(raw['examples'], _asString),
    );
  }
}

/// A >3 s hesitation (FR12) — backend-measured duration + LLM context.
///
/// Story 7.5 v2 adds `id` (pairs to the LLM context by id, not index),
/// `resolved` (false = a freeze so long the character re-spoke — the
/// invisible-freeze class C2), and `source` ("device" = measured on the phone
/// per D3-c, else "server"). All defaulted so a v1 hesitation parses unchanged.
class DebriefHesitation {
  final double durationSec;
  final String context;
  final String? id;
  final bool resolved;
  final String source;

  const DebriefHesitation({
    required this.durationSec,
    required this.context,
    this.id,
    this.resolved = true,
    this.source = 'server',
  });

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
      id: _asString(raw['id']),
      resolved: _asBool(raw['resolved']) ?? true,
      source: _asString(raw['source']) ?? 'server',
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

/// Story 7.5 v2 (B2) — a correct-but-clumsy utterance phrased more naturally.
/// All three fields required (a partial suggestion is noise) — a malformed
/// item is skipped.
class DebriefBetterPhrasing {
  final String original;
  final String suggestion;
  final String reason;

  const DebriefBetterPhrasing({
    required this.original,
    required this.suggestion,
    required this.reason,
  });

  static DebriefBetterPhrasing? tryParse(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    final original = _asString(raw['original']);
    final suggestion = _asString(raw['suggestion']);
    final reason = _asString(raw['reason']);
    if (original == null || suggestion == null || reason == null) return null;
    return DebriefBetterPhrasing(
      original: original,
      suggestion: suggestion,
      reason: reason,
    );
  }
}

/// Story 7.5 v2 (B7) — one scenario beat with its met/missed state: the
/// factual decomposition of the survival % the user saw on the HUD. An item
/// missing its `met` bool is skipped (a checkpoint with an unknown outcome is
/// meaningless).
class DebriefCheckpoint {
  final String id;
  final String hint;
  final bool met;

  const DebriefCheckpoint({
    required this.id,
    required this.hint,
    required this.met,
  });

  static DebriefCheckpoint? tryParse(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    final id = _asString(raw['id']);
    final hint = _asString(raw['hint']);
    final met = _asBool(raw['met']);
    if (id == null || hint == null || met == null) return null;
    return DebriefCheckpoint(id: id, hint: hint, met: met);
  }
}

/// Story 7.5 v2 (D-a/B5/D-c) — one prioritised, evidence-linked, actionable
/// area. `practicePrompt` is the copy-button payload (pasteable into any LLM
/// to drill this one topic); `isFocus` marks the #1 "focus first" area.
/// `title` is required (the card needs it); `evidence`/`practicePrompt`
/// default to '' defensively (an empty `practicePrompt` = no copy action).
class DebriefArea {
  final String title;
  final String evidence;
  final String practicePrompt;
  final bool isFocus;

  const DebriefArea({
    required this.title,
    this.evidence = '',
    this.practicePrompt = '',
    this.isFocus = false,
  });

  static DebriefArea? tryParse(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    final title = _asString(raw['title']);
    if (title == null) return null;
    return DebriefArea(
      title: title,
      evidence: _asString(raw['evidence']) ?? '',
      practicePrompt: _asString(raw['practice_prompt']) ?? '',
      isFocus: _asBool(raw['is_focus']) ?? false,
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

  // --- Story 7.5 v2 (additive, defaulted for v1 back-compat) ---

  /// Schema version of the stored payload. A v1 row omits the key → 1.
  final int debriefVersion;

  /// B7 — the met/missed scenario beats (empty on a v1 payload).
  final List<DebriefCheckpoint> checkpoints;

  /// B2 — ≤2 better-phrasing suggestions (empty on a v1 payload).
  final List<DebriefBetterPhrasing> betterPhrasings;

  /// D-a/B5 — the rich, actionable areas (carries the copy-button practice
  /// prompts). Rides ALONGSIDE the v1 `areasToWorkOn` titles list; a v2 screen
  /// prefers `areas` and falls back to `areasToWorkOn` when empty.
  final List<DebriefArea> areas;

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
    this.debriefVersion = 1,
    this.checkpoints = const [],
    this.betterPhrasings = const [],
    this.areas = const [],
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
      debriefVersion: _asInt(json['debrief_version']) ?? 1,
      checkpoints: _parseItems(json['checkpoints'], DebriefCheckpoint.tryParse),
      betterPhrasings: _parseItems(
        json['better_phrasings'],
        DebriefBetterPhrasing.tryParse,
      ),
      areas: _parseItems(json['areas'], DebriefArea.tryParse),
    );
  }
}

int? _asInt(Object? value) => value is int ? value : null;

String? _asString(Object? value) => value is String ? value : null;

bool? _asBool(Object? value) => value is bool ? value : null;

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
