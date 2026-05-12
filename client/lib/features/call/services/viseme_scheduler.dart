import 'dart:async';
import 'dart:developer' as dev;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Story 6.3b — bridges platform-generated visemes onto the Rive canvas.
///
/// **Why this exists**: the previous design shipped visemes over the
/// WebRTC data channel from the server. That channel suffered 2-3 s
/// SCTP slow-start latency on cellular, desyncing the mouth from the
/// audio. The current approach analyses the exact PCM bytes about to
/// hit the speaker (in `AudioClockChannel.kt` via
/// `PlaybackSamplesReadyCallback`), classifies each chunk into one of
/// the 12 Rive viseme cases, and emits the result on a Flutter
/// `EventChannel`. Sync is then a property of the architecture: the
/// viseme stream lives on the same audio thread as playback, so it
/// cannot drift.
///
/// This scheduler is a thin subscriber — it owns the EventChannel
/// subscription and forwards each int id to [applyViseme]. No
/// queueing, no audio-clock polling, no per-utterance bookkeeping.
///
/// **Lifecycle**: one instance per call. Constructed by
/// `_CallScreenState` on the first transition into `CallConnected`
/// (alongside `DataChannelHandler`) and disposed before
/// `super.dispose()`.
///
/// **Tests** inject an explicit `Stream<int>` via the optional
/// [eventStream] constructor parameter; production wires the real
/// EventChannel.
class VisemeScheduler {
  VisemeScheduler({
    required void Function(int visemeId) applyViseme,
    Stream<int>? eventStream,
  }) : _applyViseme = applyViseme {
    // Defensive cast: a non-int payload (future protocol drift, ME
    // upgrade to a richer envelope) would throw inside `map` and
    // propagate as a stream error — broadcast streams may stop
    // delivering after that, freezing the mouth for the rest of the
    // call. `.where(is int).cast<int>()` silently drops anything that
    // is not an int and keeps the stream alive.
    final stream =
        eventStream ??
        const EventChannel(
          'com.surviveTheTalk.client/viseme_events',
        ).receiveBroadcastStream().where((dynamic e) => e is int).cast<int>();
    _subscription = stream.listen(
      _onNativeViseme,
      onError: (Object e, StackTrace st) {
        dev.log(
          'VisemeScheduler: event stream error: $e',
          name: 'call.viseme',
          level: 700,
          error: e,
          stackTrace: st,
        );
      },
    );
  }

  final void Function(int visemeId) _applyViseme;
  // The analyzer can't see through the explicit `await sub.cancel()` in
  // [dispose], so the lint is a false positive — silence with rationale.
  // ignore: cancel_subscriptions
  StreamSubscription<int>? _subscription;
  bool _disposed = false;

  void _onNativeViseme(int visemeId) {
    if (_disposed) return;
    _applyViseme(visemeId);
  }

  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    final sub = _subscription;
    _subscription = null;
    if (sub != null) {
      try {
        await sub.cancel();
      } catch (e) {
        // EventChannel cancel can throw if the platform side has gone
        // away (engine detach). Best-effort.
        dev.log(
          'VisemeScheduler: cancel failed: $e',
          name: 'call.viseme',
          level: 700,
        );
      }
    }
  }

  @visibleForTesting
  bool get debugAttached => _subscription != null && !_disposed;
}
