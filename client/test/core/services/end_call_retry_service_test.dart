import 'dart:async';

import 'package:client/core/api/api_exception.dart';
import 'package:client/core/services/connectivity_service.dart';
import 'package:client/core/services/end_call_retry_service.dart';
import 'package:client/core/services/end_call_retry_storage.dart';
import 'package:client/features/call/models/end_call_result.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockCallRepository extends Mock implements CallRepository {}

class MockConnectivityService extends Mock implements ConnectivityService {}

const _kDefaultEndCallResult = EndCallResult(
  wasGifted: false,
  giftsRemainingToday: 3,
  durationSec: 0,
);

void main() {
  late EndCallRetryStorage storage;
  late MockCallRepository repository;
  late EndCallRetryService service;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    storage = EndCallRetryStorage();
    repository = MockCallRepository();
    service = EndCallRetryService(storage: storage, repository: repository);
  });

  tearDown(() async {
    await service.dispose();
  });

  group('queue', () {
    test('persists a new entry to storage', () async {
      await service.queue(callId: 42, reason: 'network_lost');

      final entries = await storage.getAll();
      expect(entries, hasLength(1));
      expect(entries.first.callId, 42);
      expect(entries.first.reason, 'network_lost');
    });

    test('survives a storage failure without re-throwing (logged only)', () async {
      // Build a service backed by a storage whose `enqueue` throws.
      final brokenStorage = _ThrowingStorage();
      final brokenService = EndCallRetryService(
        storage: brokenStorage,
        repository: repository,
      );

      // Must not throw — the bloc's catch site relies on `queue`
      // never re-throwing.
      await brokenService.queue(callId: 1, reason: 'network_lost');
      addTearDown(brokenService.dispose);
    });
  });

  group('replayAll', () {
    test('drains successful entries from the queue', () async {
      when(
        () => repository.endCall(
          callId: any(named: 'callId'),
          reason: any(named: 'reason'),
        ),
      ).thenAnswer((_) async => _kDefaultEndCallResult);

      await service.queue(callId: 1, reason: 'user_hung_up');
      await service.queue(callId: 2, reason: 'network_lost');

      final drained = await service.replayAll();

      expect(drained, 2);
      expect(await storage.getAll(), isEmpty);
      verify(
        () => repository.endCall(callId: 1, reason: 'user_hung_up'),
      ).called(1);
      verify(
        () => repository.endCall(callId: 2, reason: 'network_lost'),
      ).called(1);
    });

    test('leaves failed entries in the queue for the next trigger', () async {
      when(
        () => repository.endCall(
          callId: any(named: 'callId'),
          reason: any(named: 'reason'),
        ),
      ).thenThrow(
        const ApiException(code: 'NETWORK_ERROR', message: 'Still offline.'),
      );

      await service.queue(callId: 1, reason: 'user_hung_up');

      final drained = await service.replayAll();

      expect(drained, 0);
      expect(await storage.getAll(), hasLength(1));
    });

    test(
      'partial success: drains the entries that POST OK, leaves the failing '
      'ones for retry',
      () async {
        // First call (id=1) succeeds, second (id=2) fails. The
        // first must be removed; the second must remain.
        when(
          () => repository.endCall(callId: 1, reason: any(named: 'reason')),
        ).thenAnswer((_) async => _kDefaultEndCallResult);
        when(
          () => repository.endCall(callId: 2, reason: any(named: 'reason')),
        ).thenThrow(
          const ApiException(code: 'SERVER_ERROR', message: '500 from prod.'),
        );

        await service.queue(callId: 1, reason: 'user_hung_up');
        await service.queue(callId: 2, reason: 'network_lost');

        final drained = await service.replayAll();

        expect(drained, 1);
        final remaining = await storage.getAll();
        expect(remaining, hasLength(1));
        expect(remaining.first.callId, 2);
      },
    );

    test('on empty queue returns 0 and does not call the repository', () async {
      final drained = await service.replayAll();
      expect(drained, 0);
      verifyNever(
        () => repository.endCall(
          callId: any(named: 'callId'),
          reason: any(named: 'reason'),
        ),
      );
    });

    test(
      'overlapping replayAll calls do NOT double-POST '
      '(re-entrance guard)',
      () async {
        // Stub a slow `endCall` so a second replayAll fires while the
        // first is still in flight. The guard must skip the second.
        final firstCompleter = Completer<EndCallResult>();
        when(
          () => repository.endCall(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        ).thenAnswer((_) => firstCompleter.future);

        await service.queue(callId: 1, reason: 'user_hung_up');

        // Start the first replay (doesn't complete yet).
        final firstFuture = service.replayAll();
        await Future<void>.delayed(const Duration(milliseconds: 10));

        // Concurrent replay request — must short-circuit (return 0).
        final secondDrained = await service.replayAll();
        expect(secondDrained, 0);

        // Release the first one and assert it drained 1.
        firstCompleter.complete(_kDefaultEndCallResult);
        expect(await firstFuture, 1);

        // Repository was called exactly once.
        verify(
          () => repository.endCall(callId: 1, reason: 'user_hung_up'),
        ).called(1);
      },
    );
  });

  group('attach + connectivity-regain', () {
    test(
      'triggers replayAll when the connectivity service emits a regain '
      'event',
      () async {
        final mockConnectivity = MockConnectivityService();
        final regainController = StreamController<void>.broadcast();
        when(
          () => mockConnectivity.onConnectivityRegained,
        ).thenAnswer((_) => regainController.stream);

        when(
          () => repository.endCall(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        ).thenAnswer((_) async => _kDefaultEndCallResult);

        await service.queue(callId: 42, reason: 'network_lost');
        service.attach(mockConnectivity);

        // Simulate the radio coming back.
        regainController.add(null);
        await Future<void>.delayed(const Duration(milliseconds: 50));

        verify(
          () => repository.endCall(callId: 42, reason: 'network_lost'),
        ).called(1);
        expect(await storage.getAll(), isEmpty);

        await regainController.close();
      },
    );

    test(
      'attach twice replaces the prior subscription (no double drain)',
      () async {
        final mockA = MockConnectivityService();
        final mockB = MockConnectivityService();
        final controllerA = StreamController<void>.broadcast();
        final controllerB = StreamController<void>.broadcast();
        when(
          () => mockA.onConnectivityRegained,
        ).thenAnswer((_) => controllerA.stream);
        when(
          () => mockB.onConnectivityRegained,
        ).thenAnswer((_) => controllerB.stream);
        when(
          () => repository.endCall(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        ).thenAnswer((_) async => _kDefaultEndCallResult);

        await service.queue(callId: 1, reason: 'user_hung_up');
        service.attach(mockA);
        service.attach(mockB);

        // Emit on the FIRST (now-replaced) source. Must NOT fire a drain.
        controllerA.add(null);
        await Future<void>.delayed(const Duration(milliseconds: 30));
        verifyNever(
          () => repository.endCall(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        );

        // Emit on the SECOND source. Should fire the drain.
        controllerB.add(null);
        await Future<void>.delayed(const Duration(milliseconds: 30));
        verify(
          () => repository.endCall(callId: 1, reason: 'user_hung_up'),
        ).called(1);

        await controllerA.close();
        await controllerB.close();
      },
    );
  });
}

/// A storage stub whose `enqueue` always throws, used to exercise the
/// service's "swallow + log" failure path. We can't easily make
/// `FlutterSecureStorage` itself throw via the mock channel, so a thin
/// subclass-by-composition does the trick.
class _ThrowingStorage extends EndCallRetryStorage {
  @override
  Future<void> enqueue(PendingEndCall entry) async {
    throw StateError('storage broken');
  }
}
