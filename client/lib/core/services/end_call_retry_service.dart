// Drains the persistent `EndCallRetryStorage` queue on app boot and on
// every connectivity-regain event. Story 6.5 Option B (post-deploy fix
// for the "metro disconnect → cap counter stuck for 1 h" UX).
//
// Lifecycle:
//   - `bootstrap()` constructs ONE instance, calls `attach()` to wire
//     the connectivity listener, then schedules a fire-and-forget
//     `replayAll()` so any leftover queue from a previous session is
//     drained at startup (covering the "user killed the app mid-metro,
//     reopens it 30 min later with WiFi back" case).
//   - `CallBloc._endCallSilently` calls `queue(callId, reason)` when
//     the live POST fails (e.g. dio NETWORK_ERROR from a still-offline
//     radio). The service holds the entry until either `replayAll()`
//     fires or the user kills the app (the entry survives in secure
//     storage either way).
//   - The connectivity listener subscription is owned for the app
//     lifetime — we never `dispose()` this service in production.
//     Tests use `dispose()` to detach.
//
// Why a separate service rather than putting retry inside the
// repository: the retry is fundamentally CROSS-CALL (one queue across
// many calls, draining triggered by connectivity events that have no
// per-call ownership). Putting this in the repository would tangle
// per-call request state with cross-call queue state.

import 'dart:async';
import 'dart:developer' as dev;

import '../../features/call/repositories/call_repository.dart';
import 'connectivity_service.dart';
import 'end_call_retry_storage.dart';

class EndCallRetryService {
  final EndCallRetryStorage _storage;
  final CallRepository _repository;

  StreamSubscription<void>? _regainSub;

  /// Guards against overlapping `replayAll()` invocations. Without
  /// this, a connectivity-regain landing while a boot-time replay is
  /// still in flight would race on `getAll()` / `remove()` and
  /// duplicate POSTs. Server idempotency would absorb the dupes but
  /// a quiet wire is better.
  bool _replayInFlight = false;

  EndCallRetryService({
    required EndCallRetryStorage storage,
    required CallRepository repository,
  }) : _storage = storage,
       _repository = repository;

  /// Subscribe to `connectivityService.onConnectivityRegained` so the
  /// queue drains the moment the radio comes back. Idempotent — safe
  /// to call twice (later calls re-subscribe, replacing the prior
  /// subscription).
  void attach(ConnectivityService connectivityService) {
    _regainSub?.cancel();
    _regainSub = connectivityService.onConnectivityRegained.listen((_) {
      dev.log(
        'connectivity_regained — draining end-call retry queue',
        name: 'EndCallRetryService',
      );
      unawaited(replayAll());
    });
  }

  /// Append a new entry to the persistent queue. Called from the bloc
  /// when the live POST fails. Tolerates storage errors (logged, never
  /// re-thrown) — the janitor sweep is the eventually-consistent
  /// backstop if the queue itself is broken.
  Future<void> queue({required int callId, required String reason}) async {
    try {
      await _storage.enqueue(
        PendingEndCall(
          callId: callId,
          reason: reason,
          queuedAt: DateTime.now().toUtc(),
        ),
      );
      dev.log(
        'queued endCall for retry callId=$callId reason=$reason',
        name: 'EndCallRetryService',
      );
    } catch (e, stack) {
      dev.log(
        'failed to queue endCall callId=$callId reason=$reason: '
        '${e.runtimeType}',
        name: 'EndCallRetryService',
        stackTrace: stack,
      );
    }
  }

  /// Try to POST every queued entry. Each entry independently
  /// succeeds (and is removed) or fails (and stays in queue for the
  /// next replay trigger). Returns the count of entries successfully
  /// drained — useful for tests and diagnostics.
  Future<int> replayAll() async {
    if (_replayInFlight) {
      dev.log(
        'replayAll skipped — already in flight',
        name: 'EndCallRetryService',
      );
      return 0;
    }
    _replayInFlight = true;
    var drained = 0;
    try {
      final entries = await _storage.getAll();
      if (entries.isEmpty) return 0;
      dev.log(
        'replayAll starting count=${entries.length}',
        name: 'EndCallRetryService',
      );
      for (final entry in entries) {
        try {
          await _repository.endCall(
            callId: entry.callId,
            reason: entry.reason,
          );
          await _storage.remove(entry.callId);
          drained += 1;
        } catch (e) {
          // Still offline / server still down / other transient
          // error. Leave the entry in the queue for the next trigger.
          dev.log(
            'replay deferred for callId=${entry.callId} '
            'type=${e.runtimeType}',
            name: 'EndCallRetryService',
          );
        }
      }
      dev.log(
        'replayAll finished drained=$drained '
        'remaining=${entries.length - drained}',
        name: 'EndCallRetryService',
      );
    } finally {
      _replayInFlight = false;
    }
    return drained;
  }

  /// Detach the connectivity listener. Production never calls this
  /// (the service lives for the app lifetime), but tests need it to
  /// keep their isolates clean.
  Future<void> dispose() async {
    await _regainSub?.cancel();
    _regainSub = null;
  }
}
