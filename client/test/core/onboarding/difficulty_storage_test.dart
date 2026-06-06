import 'package:client/core/onboarding/difficulty_storage.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late DifficultyStorage storage;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    storage = DifficultyStorage();
  });

  group('DifficultyStorage', () {
    test('getDifficulty returns the default (easy) when nothing stored', () async {
      expect(await storage.getDifficulty(), 'easy');
    });

    test('getSync returns the default before preload', () {
      expect(storage.getSync(), DifficultyStorage.defaultDifficulty);
    });

    test('set + getDifficulty round-trips', () async {
      await storage.set('hard');
      expect(await storage.getDifficulty(), 'hard');
    });

    test('set updates the sync cache immediately', () async {
      await storage.set('medium');
      expect(storage.getSync(), 'medium');
    });

    test('set rejects an unknown level', () async {
      await expectLater(storage.set('extreme'), throwsArgumentError);
    });

    test('preload seeds getSync from persistent storage', () async {
      await storage.set('hard');
      final fresh = DifficultyStorage();
      expect(fresh.getSync(), 'easy', reason: 'before preload');
      await fresh.preload();
      expect(fresh.getSync(), 'hard', reason: 'after preload');
    });

    test('getDifficulty falls back to default on a stale/unknown stored value',
        () async {
      FlutterSecureStorage.setMockInitialValues({
        'difficulty_level': 'legacy_value',
      });
      final s = DifficultyStorage();
      expect(await s.getDifficulty(), 'easy');
    });

    test('levels + defaultDifficulty are the documented contract', () {
      expect(DifficultyStorage.levels, <String>['easy', 'medium', 'hard']);
      expect(DifficultyStorage.defaultDifficulty, 'easy');
    });
  });
}
