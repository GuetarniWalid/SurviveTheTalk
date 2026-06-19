// Story 9.1 — DebriefCacheStore (Task 4 / Task 7). sqflite_common_ffi
// in-memory, no platform channels (Gotcha A/B).

import 'package:client/core/local_cache/app_database.dart';
import 'package:client/core/local_cache/debrief_cache_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  setUpAll(() {
    sqfliteFfiInit();
  });

  late AppDatabase db;
  late DebriefCacheStore store;

  setUp(() async {
    db = await AppDatabase.open(
      factory: databaseFactoryFfi,
      path: inMemoryDatabasePath,
    );
    store = DebriefCacheStore(db);
  });

  tearDown(() async {
    await db.close();
  });

  test('write + readByCallId round-trips the payload', () async {
    await store.write(
      callId: 7,
      scenarioId: 'waiter_easy_01',
      payload: <String, dynamic>{'survival_pct': 83},
    );
    expect(await store.readByCallId(7), <String, dynamic>{'survival_pct': 83});
  });

  test('readByCallId returns null for an uncached call', () async {
    expect(await store.readByCallId(999), isNull);
  });

  test(
    'readLatestForScenario returns the newest debrief AND its call_id',
    () async {
      await store.write(
        callId: 1,
        scenarioId: 'waiter_easy_01',
        payload: <String, dynamic>{'tag': 'old'},
      );
      await store.write(
        callId: 2,
        scenarioId: 'waiter_easy_01',
        payload: <String, dynamic>{'tag': 'new'},
      );
      // A different scenario must never be returned for this key.
      await store.write(
        callId: 3,
        scenarioId: 'cop_hard_01',
        payload: <String, dynamic>{'tag': 'other'},
      );

      final latest = await store.readLatestForScenario('waiter_easy_01');
      expect(latest, isNotNull);
      expect(latest!.callId, 2);
      expect(latest.payload['tag'], 'new');
    },
  );

  test(
    'readLatestForScenario returns null for a scenario with no cached debrief',
    () async {
      expect(await store.readLatestForScenario('never_called'), isNull);
    },
  );

  test('re-writing the same call_id replaces the row', () async {
    await store.write(
      callId: 5,
      scenarioId: 'waiter_easy_01',
      payload: <String, dynamic>{'v': 1},
    );
    await store.write(
      callId: 5,
      scenarioId: 'waiter_easy_01',
      payload: <String, dynamic>{'v': 2},
    );
    expect(await store.readByCallId(5), <String, dynamic>{'v': 2});
  });
}
