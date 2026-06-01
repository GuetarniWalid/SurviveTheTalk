import 'dart:developer' as dev;

import 'package:flutter/foundation.dart';
import 'package:livekit_client/livekit_client.dart';

/// Story 6.14 AC1 — dev-only inbound-audio jitter diagnostic flag.
///
/// When true, the receiver-side WebRTC inbound-audio stats are logged
/// roughly every 2 s during a call (the LiveKit SDK's built-in stats
/// monitor cadence). It lets us MEASURE the receiver-side time-stretch
/// (the recurring "voix rallongée") before and after the Story 6.14
/// jitter-buffer fix instead of diagnosing by elimination.
///
/// The signal to watch is `concealedSamples` climbing turn-over-turn:
/// NetEq inserts concealment/stretch samples to fill jitter gaps, so a
/// rising per-window delta == audio being stretched. After the
/// `min_playout_delay` jitter buffer lands (server-side, see
/// `pipeline/livekit_tokens.py`), that delta should drop.
///
/// Flip to `false` to silence once the fix is validated (it is a low-rate
/// structured log, harmless in prod, but off-by-default keeps journals
/// clean post-launch).
const bool kLogInboundAudioStats = true;

/// Subscribes to every subscribed REMOTE audio track on [Room] and logs
/// its inbound-audio receiver stats. A non-lifecycle subscriber (does not
/// own the Room): construct after `CallConnected`, `dispose()` on
/// tear-down — same contract as `DataChannelHandler` and `VisemeScheduler`.
///
/// Inert when [kLogInboundAudioStats] is false (or `enabled: false` is
/// injected in tests): `start()` subscribes to nothing and `dispose()` is
/// a no-op, so the diagnostic adds zero overhead when off.
class InboundAudioStatsLogger {
  InboundAudioStatsLogger(this._room, {bool? enabled})
    : _enabled = enabled ?? kLogInboundAudioStats;

  final Room _room;
  final bool _enabled;

  /// Cancels the room-level `TrackSubscribedEvent` listener.
  CancelListenFunc? _roomCancel;

  /// One cancel per attached remote audio track (keyed by track sid), so
  /// re-subscription of the same track is idempotent and `dispose()` can
  /// tear every listener down.
  final Map<String, CancelListenFunc> _trackCancels = {};

  /// Previous cumulative `concealedSamples` per track, for the
  /// per-window delta (the stretch signal).
  final Map<String, int> _prevConcealed = {};

  /// Begin logging. Attaches to remote audio tracks already subscribed
  /// AND to any subscribed later via `TrackSubscribedEvent`.
  ///
  /// Wrapped in try/catch: a dev diagnostic must NEVER break a call, so
  /// any SDK surprise (or a non-fully-stubbed Room in a widget test) is
  /// swallowed and logged rather than propagated to the call screen.
  void start() {
    if (!_enabled) return;

    try {
      _roomCancel = _room.events.on<TrackSubscribedEvent>((event) {
        final track = event.track;
        if (track is RemoteAudioTrack) {
          _attach(track);
        }
      });

      // Belt-and-braces: the agent's audio track may already be subscribed
      // by the time we wire up (e.g. a fast connect), in which case no
      // future TrackSubscribedEvent fires for it.
      for (final participant in _room.remoteParticipants.values) {
        for (final publication in participant.audioTrackPublications) {
          final track = publication.track;
          if (track is RemoteAudioTrack) {
            _attach(track);
          }
        }
      }
    } catch (e) {
      dev.log(
        'InboundAudioStatsLogger.start skipped: $e',
        name: 'call.audioStats',
      );
    }
  }

  void _attach(RemoteAudioTrack track) {
    final sid = track.sid ?? identityHashCode(track).toString();
    if (_trackCancels.containsKey(sid)) return;
    _trackCancels[sid] = track.events.on<AudioReceiverStatsEvent>((event) {
      try {
        final stats = event.stats;
        final concealed = stats.concealedSamples?.toInt();
        final line = formatStatsLine(
          jitter: stats.jitter?.toDouble(),
          jitterBufferDelay: stats.jitterBufferDelay?.toDouble(),
          packetsLost: stats.packetsLost?.toInt(),
          concealedSamples: concealed,
          prevConcealedSamples: _prevConcealed[sid],
          concealmentEvents: stats.concealmentEvents?.toInt(),
        );
        if (concealed != null) _prevConcealed[sid] = concealed;
        dev.log(line, name: 'call.audioStats');
      } catch (_) {
        // Never let a stats-logging hiccup bubble into the SDK event loop.
      }
    });
  }

  /// Builds the structured log line. Pure (no side effects) so the
  /// delta + formatting logic is unit-testable without a live WebRTC
  /// peer (the underlying `AudioReceiverStats` type is not publicly
  /// constructible).
  ///
  /// `jitter` and `jitterBufferDelay` are raw WebRTC seconds; jitter is
  /// surfaced in ms for readability. `concealedSamples` is cumulative —
  /// the `(+delta)` is the per-window increase, the stretch signal.
  @visibleForTesting
  static String formatStatsLine({
    double? jitter,
    double? jitterBufferDelay,
    int? packetsLost,
    int? concealedSamples,
    int? prevConcealedSamples,
    int? concealmentEvents,
  }) {
    final jitterMs = jitter == null ? '?' : (jitter * 1000).toStringAsFixed(1);
    final jbDelay = jitterBufferDelay == null
        ? '?'
        : jitterBufferDelay.toStringAsFixed(2);
    final delta =
        (concealedSamples != null && prevConcealedSamples != null)
        ? concealedSamples - prevConcealedSamples
        : null;
    final concealedStr = concealedSamples == null
        ? '?'
        : (delta == null ? '$concealedSamples' : '$concealedSamples (+$delta)');
    return 'inbound-audio jitter=${jitterMs}ms '
        'jitterBufferDelay=${jbDelay}s '
        'packetsLost=${packetsLost ?? '?'} '
        'concealedSamples=$concealedStr '
        'concealmentEvents=${concealmentEvents ?? '?'}';
  }

  /// Cancel all listeners. Safe to call when `start()` never ran (no-op).
  Future<void> dispose() async {
    final roomCancel = _roomCancel;
    _roomCancel = null;
    if (roomCancel != null) await roomCancel();
    for (final cancel in _trackCancels.values) {
      await cancel();
    }
    _trackCancels.clear();
    _prevConcealed.clear();
  }
}
