// Story 9.1 — AppDatabase schema + clearAll (Task 2 / Task 6b). Uses
// sqflite_common_ffi + inMemoryDatabasePath so it never hits the Android/iOS
// platform channel (client/CLAUDE.md sqflite Gotcha A/B).

import 'package:client/core/local_cache/app_database.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  setUpAll(() {
    sqfliteFfiInit();
  });

  Future<AppDatabase> openDb() => AppDatabase.open(
    factory: databaseFactoryFfi,
    path: inMemoryDatabasePath,
  );

  test('open() creates the three cache tables + the debrief index', () async {
    final db = await openDb();
    addTearDown(db.close);

    final tables = await db.db.query(
      'sqlite_master',
      columns: ['name'],
      where: 'type = ?',
      whereArgs: ['table'],
    );
    final names = tables.map((r) => r['name'] as String).toSet();
    expect(
      names,
      containsAll(<String>[
        'cached_scenarios',
        'cache_meta',
        'cached_debriefs',
      ]),
    );

    final indexes = await db.db.query(
      'sqlite_master',
      columns: ['name'],
      where: 'type = ?',
      whereArgs: ['index'],
    );
    expect(
      indexes.map((r) => r['name'] as String),
      contains('idx_debriefs_scenario'),
    );
  });

  test('clearAll() empties all three tables (Task 6b privacy)', () async {
    final db = await openDb();
    addTearDown(db.close);

    await db.db.insert('cached_scenarios', <String, Object?>{
      'id': 'waiter_easy_01',
      'position': 0,
      'json': '{}',
      'updated_at': 1,
    });
    await db.db.insert('cache_meta', <String, Object?>{
      'key': 'scenarios_usage',
      'value': '{}',
    });
    await db.db.insert('cached_debriefs', <String, Object?>{
      'call_id': 7,
      'scenario_id': 'waiter_easy_01',
      'debrief_json': '{}',
      'created_at': 1,
    });

    await db.clearAll();

    expect(await db.db.query('cached_scenarios'), isEmpty);
    expect(await db.db.query('cache_meta'), isEmpty);
    expect(await db.db.query('cached_debriefs'), isEmpty);
  });
}
