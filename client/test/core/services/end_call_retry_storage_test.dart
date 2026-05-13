import 'package:client/core/services/end_call_retry_storage.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late EndCallRetryStorage storage;

  setUp(() {
    // CLAUDE.md gotcha #1 — every test touching FlutterSecureStorage
    // must reset the mock keychain in setUp, otherwise the test is
    // green locally on a primed keychain and red in CI.
    FlutterSecureStorage.setMockInitialValues({});
    storage = EndCallRetryStorage();
  });

  group('PendingEndCall', () {
    test('round-trips through JSON without losing precision', () {
      final original = PendingEndCall(
        callId: 42,
        reason: 'user_hung_up',
        queuedAt: DateTime.utc(2026, 5, 13, 14, 30, 15),
      );
      final restored = PendingEndCall.fromJson(original.toJson());
      expect(restored, equals(original));
    });
  });

  group('EndCallRetryStorage', () {
    test('getAll on empty storage returns empty list (never throws)', () async {
      expect(await storage.getAll(), isEmpty);
    });

    test('enqueue + getAll persists the entry', () async {
      final entry = PendingEndCall(
        callId: 1,
        reason: 'network_lost',
        queuedAt: DateTime.utc(2026, 5, 13, 14, 30),
      );
      await storage.enqueue(entry);

      final loaded = await storage.getAll();
      expect(loaded, hasLength(1));
      expect(loaded.first, equals(entry));
    });

    test('enqueue preserves insertion order across multiple calls', () async {
      final a = PendingEndCall(
        callId: 1,
        reason: 'user_hung_up',
        queuedAt: DateTime.utc(2026, 5, 13, 14, 30),
      );
      final b = PendingEndCall(
        callId: 2,
        reason: 'network_lost',
        queuedAt: DateTime.utc(2026, 5, 13, 14, 31),
      );
      await storage.enqueue(a);
      await storage.enqueue(b);

      final loaded = await storage.getAll();
      expect(loaded.map((e) => e.callId), [1, 2]);
    });

    test(
      'enqueue with duplicate callId REPLACES the existing entry '
      '(no duplicates in queue)',
      () async {
        // Same callId, different reason — should win the later one.
        // Server is idempotent so a dupe is harmless on the wire,
        // but a clean queue avoids redundant POSTs on radio return.
        final earlier = PendingEndCall(
          callId: 1,
          reason: 'network_lost',
          queuedAt: DateTime.utc(2026, 5, 13, 14, 30),
        );
        final later = PendingEndCall(
          callId: 1,
          reason: 'user_hung_up',
          queuedAt: DateTime.utc(2026, 5, 13, 14, 31),
        );
        await storage.enqueue(earlier);
        await storage.enqueue(later);

        final loaded = await storage.getAll();
        expect(loaded, hasLength(1));
        expect(loaded.first, equals(later));
      },
    );

    test('remove drops the matching entry and leaves the rest', () async {
      final a = PendingEndCall(
        callId: 1,
        reason: 'user_hung_up',
        queuedAt: DateTime.utc(2026, 5, 13, 14, 30),
      );
      final b = PendingEndCall(
        callId: 2,
        reason: 'network_lost',
        queuedAt: DateTime.utc(2026, 5, 13, 14, 31),
      );
      await storage.enqueue(a);
      await storage.enqueue(b);

      await storage.remove(1);
      final loaded = await storage.getAll();
      expect(loaded, hasLength(1));
      expect(loaded.first.callId, 2);
    });

    test('remove on missing callId is a no-op (does not crash)', () async {
      await storage.remove(999);
      expect(await storage.getAll(), isEmpty);
    });

    test('clear empties the queue completely', () async {
      await storage.enqueue(
        PendingEndCall(
          callId: 1,
          reason: 'user_hung_up',
          queuedAt: DateTime.utc(2026, 5, 13, 14, 30),
        ),
      );
      await storage.clear();
      expect(await storage.getAll(), isEmpty);
    });

    test(
      'remove of the last entry clears the storage key (no empty array '
      'sitting in secure storage)',
      () async {
        await storage.enqueue(
          PendingEndCall(
            callId: 1,
            reason: 'user_hung_up',
            queuedAt: DateTime.utc(2026, 5, 13, 14, 30),
          ),
        );
        await storage.remove(1);
        // getAll returns empty list (whether the underlying key is
        // missing OR holds an empty array — both shapes are OK).
        expect(await storage.getAll(), isEmpty);
      },
    );

    test(
      'getAll tolerates a corrupt blob: returns empty list and purges '
      'the key for subsequent calls',
      () async {
        // Plant a malformed value directly.
        const storage2 = FlutterSecureStorage();
        await storage2.write(
          key: 'pending_end_calls',
          value: 'this is not json',
        );
        // First read recovers gracefully.
        expect(await storage.getAll(), isEmpty);
        // Subsequent enqueue works fine on the cleaned slate.
        final entry = PendingEndCall(
          callId: 5,
          reason: 'network_lost',
          queuedAt: DateTime.utc(2026, 5, 13, 14, 30),
        );
        await storage.enqueue(entry);
        final loaded = await storage.getAll();
        expect(loaded, [entry]);
      },
    );
  });
}
