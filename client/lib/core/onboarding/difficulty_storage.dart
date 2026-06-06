import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Story 6.19 — the learner's GLOBAL difficulty preference (easy / medium /
/// hard), set once on the hub and applied to every call.
///
/// Mirrors [ConsentStorage]: secure-storage backed, `preload()`-ed once at
/// bootstrap, and read synchronously (`getSync`) so the hub line can render the
/// current value on the first frame without an async flash (client/CLAUDE.md
/// gotcha #5). The chosen value is sent on `POST /calls/initiate`; the server
/// treats it as optional (older clients / the legacy `/connect` path omit it).
class DifficultyStorage {
  static const String _difficultyKey = 'difficulty_level';

  /// The default before the learner ever picks one. Gentle onboarding for a
  /// learning app (Story 6.19 Decision 7); adjustable here in one place.
  static const String defaultDifficulty = 'easy';

  /// The valid levels, in display order. Single source of truth for the UI.
  static const List<String> levels = <String>['easy', 'medium', 'hard'];

  final FlutterSecureStorage _storage;

  String _cached = defaultDifficulty;

  DifficultyStorage([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  /// Loads the persisted choice into memory. Call once during bootstrap (in
  /// parallel with the other preloads) so [getSync] is correct on the first
  /// frame.
  Future<void> preload() async {
    _cached = await getDifficulty();
  }

  /// The current choice, read synchronously from the in-memory cache. Returns
  /// [defaultDifficulty] until [preload] (or [set]) has run.
  String getSync() => _cached;

  /// Reads the persisted choice; falls back to [defaultDifficulty] when nothing
  /// is stored or a stale/unknown value is found.
  Future<String> getDifficulty() async {
    final value = await _storage.read(key: _difficultyKey);
    if (value != null && levels.contains(value)) return value;
    return defaultDifficulty;
  }

  /// Persists [level] and updates the sync cache. Throws [ArgumentError] on an
  /// unknown level (the UI only ever passes a valid one).
  Future<void> set(String level) async {
    if (!levels.contains(level)) {
      throw ArgumentError.value(level, 'level', 'must be one of $levels');
    }
    await _storage.write(key: _difficultyKey, value: level);
    _cached = level;
  }
}
