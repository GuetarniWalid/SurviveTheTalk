// Story 9.1 — ScenarioCacheStore round-trips + parse-failure tolerance (Task 3
// / Task 7). sqflite_common_ffi in-memory, no platform channels (Gotcha A/B).
//
// Scenario has NO ==/Equatable (identity equality only) and Dart Maps/Lists
// have no value == either — so round-trips assert scalar fields directly and
// collection fields via listEquals/mapEquals (Task 7 rule).

import 'package:client/core/local_cache/app_database.dart';
import 'package:client/core/local_cache/scenario_cache_store.dart';
import 'package:client/features/scenarios/models/call_usage.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/repositories/scenarios_fetch_result.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

Map<String, dynamic> _rawScenario(
  String id, {
  String title = 'Tina',
  int? bestScore,
  int attempts = 0,
}) => <String, dynamic>{
  'id': id,
  'title': title,
  'is_free': true,
  'rive_character': 'waiter',
  'language_focus': <String>['assertiveness'],
  'content_warning': null,
  'best_score': bestScore,
  'attempts': attempts,
  'end_phrases': <String, String>{'survived': 'You made it.'},
  'briefing': <String, String>{'context': 'A busy diner.'},
};

const _rawMeta = <String, dynamic>{
  'tier': 'free',
  'calls_remaining': 3,
  'calls_per_period': 3,
  'period': 'lifetime',
};

ScenariosFetchResult _resultFrom(
  List<Map<String, dynamic>> raw, {
  Map<String, dynamic> meta = _rawMeta,
}) => ScenariosFetchResult(
  scenarios: raw.map(Scenario.fromJson).toList(),
  usage: CallUsage.fromMeta(meta),
  rawScenarios: raw,
  rawMeta: meta,
);

void main() {
  setUpAll(() {
    sqfliteFfiInit();
  });

  late AppDatabase db;
  late ScenarioCacheStore store;

  setUp(() async {
    db = await AppDatabase.open(
      factory: databaseFactoryFfi,
      path: inMemoryDatabasePath,
    );
    store = ScenarioCacheStore(db);
  });

  tearDown(() async {
    await db.close();
  });

  test('readScenarios on an empty cache returns null', () async {
    expect(await store.readScenarios(), isNull);
  });

  test('round-trips the scenario list preserving server order', () async {
    final raw = <Map<String, dynamic>>[
      _rawScenario('waiter_easy_01', title: 'Tina'),
      _rawScenario('mugger_medium_01', title: 'Mugger', bestScore: 80, attempts: 3),
      _rawScenario('cop_hard_01', title: 'Officer Reed'),
    ];
    await store.writeScenarios(_resultFrom(raw));

    final result = await store.readScenarios();
    expect(result, isNotNull);
    expect(
      result!.scenarios.map((s) => s.id).toList(),
      <String>['waiter_easy_01', 'mugger_medium_01', 'cop_hard_01'],
    );

    final tina = result.scenarios.first;
    expect(tina.title, 'Tina');
    expect(tina.isFree, isTrue);
    expect(tina.riveCharacter, 'waiter');
    expect(tina.bestScore, isNull);
    expect(tina.attempts, 0);
    expect(tina.contentWarning, isNull);
    // tagline is derived client-side (not in the server JSON) — it must survive
    // the round-trip because Scenario.fromJson re-derives it from the id.
    expect(tina.tagline, isNotNull);
    expect(listEquals(tina.languageFocus, <String>['assertiveness']), isTrue);
    expect(
      mapEquals(tina.endPhrases, <String, String>{'survived': 'You made it.'}),
      isTrue,
    );
    expect(
      mapEquals(tina.briefing, <String, String>{'context': 'A busy diner.'}),
      isTrue,
    );

    final mugger = result.scenarios[1];
    expect(mugger.bestScore, 80);
    expect(mugger.attempts, 3);
  });

  test('round-trips the usage meta', () async {
    await store.writeScenarios(_resultFrom([_rawScenario('waiter_easy_01')]));
    final result = await store.readScenarios();
    expect(result!.usage.tier, 'free');
    expect(result.usage.callsRemaining, 3);
    expect(result.usage.callsPerPeriod, 3);
    expect(result.usage.period, 'lifetime');
  });

  test('writeScenarios replaces the previous list (no stale rows)', () async {
    await store.writeScenarios(
      _resultFrom([_rawScenario('a'), _rawScenario('b'), _rawScenario('c')]),
    );
    await store.writeScenarios(_resultFrom([_rawScenario('only')]));
    final result = await store.readScenarios();
    expect(result!.scenarios.map((s) => s.id).toList(), <String>['only']);
  });

  test(
    'a corrupt cached JSON row returns null (cache-miss, never throws)',
    () async {
      await store.writeScenarios(_resultFrom([_rawScenario('waiter_easy_01')]));
      // Corrupt the stored json directly — simulates a partially-written row or
      // a schema drift between app versions.
      await db.db.update('cached_scenarios', <String, Object?>{
        'json': 'NOT JSON',
      });
      expect(await store.readScenarios(), isNull);
    },
  );

  test(
    'a corrupt cached meta (calls_per_period <= 0) returns null',
    () async {
      await store.writeScenarios(_resultFrom([_rawScenario('waiter_easy_01')]));
      // Force a meta blob that CallUsage.fromMeta rejects (FormatException).
      await db.db.update(
        'cache_meta',
        <String, Object?>{
          'value':
              '{"tier":"free","calls_remaining":3,"calls_per_period":0,"period":"lifetime"}',
        },
        where: 'key = ?',
        whereArgs: ['scenarios_usage'],
      );
      expect(await store.readScenarios(), isNull);
    },
  );
}
