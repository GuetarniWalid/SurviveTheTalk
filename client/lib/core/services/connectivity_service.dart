// Thin wrapper around `connectivity_plus` for mid-call connectivity
// monitoring. Story 6.5 review (post-deploy E2E found) wires this into
// `CallBloc` so a phone going into airplane mode mid-call fires
// `RoomDisconnected` proactively, without waiting for the LiveKit SDK's
// keepalive timeouts.
//
// Why this exists despite Deviation #8 ("no connectivity_plus
// dependency"): Deviation #8 was scoped to PRE-call detection (the dio
// `connectionError` path on `/calls/initiate` is sufficient for that).
// MID-call connectivity loss is a different problem. The on-device
// LiveKit client SDK does not fire `RoomDisconnectedEvent` while the
// radio is off — the OS queues TCP/UDP sends that silently fail, the
// SDK's keepalive heartbeats never time out (they were never sent),
// and the user can sit on a stalled call screen for several minutes
// until either the radio comes back OR the SDK finally gives up on
// its internal retry budget. Validated against the live VPS deploy:
// 7 m 12 s elapsed between `Participant disconnected: user-1`
// (server-side detection, ~24 s after airplane-mode toggle) and the
// client's `/end` POST landing on the server. The user was stuck on
// the call screen for the duration.
//
// The fix is to monitor connectivity at the OS level and dispatch
// `RoomDisconnected` the moment connectivity drops to `none` — the
// existing bloc handler already does the right thing from there
// (emit `CallError('Connection lost.')` + `CallEnded`, queue the
// fire-and-forget `/end` POST through dio which will retry on radio
// return).
//
// Thin-wrapper pattern matches `PermissionService` / `VibrationService`
// (Epic 4): one class, one or two methods, mockable via
// `Mock implements ConnectivityService` in tests.

import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';

class ConnectivityService {
  final Connectivity _connectivity;

  ConnectivityService({Connectivity? connectivity})
    : _connectivity = connectivity ?? Connectivity();

  /// Emits `true` whenever connectivity transitions to "no network",
  /// `false` whenever it transitions back to any usable transport.
  ///
  /// `distinct()` collapses runs of the same boolean so subscribers
  /// only see real transitions — a flapping connection that bounces
  /// `wifi → mobile → wifi` does NOT trigger spurious "lost / regained"
  /// events because the boolean stays `false` throughout.
  ///
  /// The list-of-results shape is the `connectivity_plus` ^6 API:
  /// modern devices can have multiple active transports (WiFi + 4G).
  /// We treat the device as offline only when EVERY transport is
  /// `none` — having WiFi-but-not-mobile is online, having
  /// mobile-but-not-WiFi is online, having neither is offline.
  Stream<bool> get onConnectivityLost {
    return _connectivity.onConnectivityChanged.map(_isAllNone).distinct();
  }

  /// Fires every time connectivity transitions from `none` back to any
  /// usable transport. Used by `EndCallRetryService` to drain the
  /// persistent queue of `/end` POSTs that failed while offline (Option
  /// B — "drain on radio return" UX, so the user's cap counter is
  /// freed within seconds of regaining connectivity rather than waiting
  /// up to the janitor horizon).
  ///
  /// Implementation note: a naive `onConnectivityLost.where((lost) =>
  /// !lost)` would ALSO fire on the very first event the underlying
  /// stream produces when the app starts online (because `distinct()`
  /// has no prior state to compare against, so the initial `false`
  /// gets through). We need a stateful filter that tracks whether we
  /// have actually been offline at any point — the FIRST regain event
  /// only fires AFTER a real `none` transition has been observed.
  /// A `wifi → mobile` transport hop is NOT a regain (we were never
  /// offline). Each call to this getter creates a fresh `hasBeenOffline`
  /// closure so subscriptions are independent.
  Stream<void> get onConnectivityRegained {
    var hasBeenOffline = false;
    return onConnectivityLost
        .where((lost) {
          if (lost) {
            hasBeenOffline = true;
            return false;
          }
          if (!hasBeenOffline) return false;
          hasBeenOffline = false;
          return true;
        })
        .map<void>((_) {});
  }

  bool _isAllNone(List<ConnectivityResult> results) {
    return results.isNotEmpty &&
        results.every((r) => r == ConnectivityResult.none);
  }
}
