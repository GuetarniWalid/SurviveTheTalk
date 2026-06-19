import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

/// Story 9.1 — single owner of the offline-cache sqflite [Database].
///
/// Opened once in `bootstrap()` and threaded down via constructor injection
/// (the project's only DI mechanism — no service locator). The two cache stores
/// ([ScenarioCacheStore], [DebriefCacheStore]) wrap this one instance.
///
/// `open()` takes an injectable [DatabaseFactory] + path so widget/unit tests
/// pass `databaseFactoryFfi` + `inMemoryDatabasePath` and never touch the
/// Android/iOS platform channels (client/CLAUDE.md sqflite Gotcha A/B). In
/// production both are omitted: the global `databaseFactory` is used and the
/// path resolves under `getApplicationDocumentsDirectory()`.
class AppDatabase {
  AppDatabase._(this._db);

  final Database _db;

  /// The underlying handle. Exposed for the cache stores only.
  Database get db => _db;

  static const String _dbFileName = 'survive_the_talk_cache.db';
  static const int _version = 1;

  /// Opens (creating on first run) the cache DB. [factory]/[path] are test
  /// seams — production passes neither.
  static Future<AppDatabase> open({
    DatabaseFactory? factory,
    String? path,
  }) async {
    final resolvedFactory = factory ?? databaseFactory;
    final resolvedPath = path ?? await _defaultPath();
    final database = await resolvedFactory.openDatabase(
      resolvedPath,
      options: OpenDatabaseOptions(
        version: _version,
        onCreate: _onCreate,
        onUpgrade: _onUpgrade,
      ),
    );
    return AppDatabase._(database);
  }

  static Future<String> _defaultPath() async {
    final dir = await getApplicationDocumentsDirectory();
    // Manual join (a forward slash is valid on Android/iOS) so we don't take a
    // direct dependency on package:path for one concatenation.
    return '${dir.path}/$_dbFileName';
  }

  static Future<void> _onCreate(Database db, int version) async {
    await db.execute('''
      CREATE TABLE cached_scenarios (
        id TEXT PRIMARY KEY,
        position INTEGER NOT NULL,
        json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE cache_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE cached_debriefs (
        call_id INTEGER PRIMARY KEY,
        scenario_id TEXT NOT NULL,
        debrief_json TEXT NOT NULL,
        created_at INTEGER NOT NULL
      )
    ''');
    await db.execute(
      'CREATE INDEX idx_debriefs_scenario ON cached_debriefs(scenario_id)',
    );
  }

  /// Empty for v1 — left as an explicit migration seam so 9.2 / future stories
  /// can add per-version steps here without reopening this file blind.
  static Future<void> _onUpgrade(
    Database db,
    int oldVersion,
    int newVersion,
  ) async {
    for (var version = oldVersion + 1; version <= newVersion; version++) {
      switch (version) {
        // case 2:  // Story 9.x
        //   await db.execute('ALTER TABLE ...');
        //   break;
        default:
          break;
      }
    }
  }

  /// Wipes every cached row in one transaction. Used on auth reset (Task 6b) so
  /// no cached data leaks to a different account on a shared device.
  Future<void> clearAll() async {
    await _db.transaction((txn) async {
      await txn.delete('cached_scenarios');
      await txn.delete('cache_meta');
      await txn.delete('cached_debriefs');
    });
  }

  Future<void> close() => _db.close();
}
