import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../../features/scenarios/models/call_usage.dart';
import '../../features/scenarios/models/scenario.dart';
import '../../features/scenarios/repositories/scenarios_fetch_result.dart';
import 'app_database.dart';

/// Story 9.1 — read-through cache for the `/scenarios` payload.
///
/// Stores the RAW server JSON (Decision 1): the parsed [Scenario]/[CallUsage]
/// models have no `toJson`/`toMeta` and `tagline` is derived client-side, so
/// re-serializing them would be lossy. The raw maps ride the extended
/// [ScenariosFetchResult] from the repository to here.
class ScenarioCacheStore {
  ScenarioCacheStore(this._database);

  final AppDatabase _database;

  static const String _scenariosTable = 'cached_scenarios';
  static const String _metaTable = 'cache_meta';
  static const String _usageKey = 'scenarios_usage';
  static const String _syncedAtKey = 'scenarios_synced_at';

  /// Reads the cached scenario list + usage. Returns null on an EMPTY cache OR
  /// ANY parse/format failure of the cached rows/meta (a `TypeError` from an
  /// unchecked cast, the `FormatException` from `CallUsage.fromMeta`'s
  /// `calls_per_period <= 0` guard, or malformed JSON after a schema change
  /// between app versions). The Bloc treats null as a cache-miss and falls
  /// through to the network path — a corrupt cached row must never crash the
  /// cache-first render.
  Future<ScenariosFetchResult?> readScenarios() async {
    try {
      final db = _database.db;
      final rows = await db.query(_scenariosTable, orderBy: 'position ASC');
      if (rows.isEmpty) return null;
      final metaRows = await db.query(
        _metaTable,
        where: 'key = ?',
        whereArgs: [_usageKey],
        limit: 1,
      );
      if (metaRows.isEmpty) return null;

      final rawScenarios = <Map<String, dynamic>>[];
      final scenarios = <Scenario>[];
      for (final row in rows) {
        final raw = jsonDecode(row['json'] as String) as Map<String, dynamic>;
        rawScenarios.add(raw);
        scenarios.add(Scenario.fromJson(raw));
      }
      final rawMeta =
          jsonDecode(metaRows.first['value'] as String) as Map<String, dynamic>;
      final usage = CallUsage.fromMeta(rawMeta);

      return ScenariosFetchResult(
        scenarios: scenarios,
        usage: usage,
        rawScenarios: rawScenarios,
        rawMeta: rawMeta,
      );
      // Any failure = a cache-miss (see dartdoc above).
      // ignore: avoid_catches_without_on_clauses
    } catch (_) {
      return null;
    }
  }

  /// Transactionally replaces the cached scenario list + usage. Writes the RAW
  /// maps from [result] (keyed by id, ordered by `position`) — never a
  /// re-serialized model.
  Future<void> writeScenarios(ScenariosFetchResult result) async {
    final now = DateTime.now().millisecondsSinceEpoch;
    await _database.db.transaction((txn) async {
      await txn.delete(_scenariosTable);
      for (var i = 0; i < result.rawScenarios.length; i++) {
        final raw = result.rawScenarios[i];
        await txn.insert(
          _scenariosTable,
          <String, Object?>{
            'id': raw['id'] as String,
            'position': i,
            'json': jsonEncode(raw),
            'updated_at': now,
          },
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
      await txn.insert(
        _metaTable,
        <String, Object?>{'key': _usageKey, 'value': jsonEncode(result.rawMeta)},
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
      await txn.insert(
        _metaTable,
        <String, Object?>{'key': _syncedAtKey, 'value': now.toString()},
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    });
  }
}
