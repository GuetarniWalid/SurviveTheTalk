import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import 'app_database.dart';

/// Story 9.1 — local store for past debrief reports (Decision 3: cache-only).
///
/// A debrief is written ONCE, at the call-end fetch choke point
/// (`CallEndedScreen`), keyed by its owning `scenario_id` + `call_id`. The
/// report icon on a scenario card then resolves the most recent debrief for
/// that scenario offline. There is no server backfill.
class DebriefCacheStore {
  DebriefCacheStore(this._database);

  final AppDatabase _database;

  static const String _table = 'cached_debriefs';

  /// Persists (or replaces, on a re-fetch of the same `callId`) one debrief.
  Future<void> write({
    required int callId,
    required String scenarioId,
    required Map<String, dynamic> payload,
  }) async {
    await _database.db.insert(
      _table,
      <String, Object?>{
        'call_id': callId,
        'scenario_id': scenarioId,
        'debrief_json': jsonEncode(payload),
        'created_at': DateTime.now().millisecondsSinceEpoch,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// The most recent debrief for [scenarioId] (newest `created_at`, `call_id`
  /// as a deterministic tiebreak), returning BOTH the `call_id` and the payload
  /// — the report-icon route (Task 5) needs the id to construct `DebriefScreen`.
  /// Null when no debrief for that scenario was ever cached.
  Future<({int callId, Map<String, dynamic> payload})?> readLatestForScenario(
    String scenarioId,
  ) async {
    final rows = await _database.db.query(
      _table,
      where: 'scenario_id = ?',
      whereArgs: [scenarioId],
      orderBy: 'created_at DESC, call_id DESC',
      limit: 1,
    );
    if (rows.isEmpty) return null;
    final row = rows.first;
    final payload =
        jsonDecode(row['debrief_json'] as String) as Map<String, dynamic>;
    return (callId: row['call_id'] as int, payload: payload);
  }

  Future<Map<String, dynamic>?> readByCallId(int callId) async {
    final rows = await _database.db.query(
      _table,
      where: 'call_id = ?',
      whereArgs: [callId],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return jsonDecode(rows.first['debrief_json'] as String)
        as Map<String, dynamic>;
  }
}
