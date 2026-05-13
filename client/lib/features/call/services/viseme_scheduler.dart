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
/// Default sustained-silence window before [VisemeScheduler] fires its
/// `onSilenceConfirmed` callback. Tuned for TTS exit lines:
///   - Cartesia pauses between words are typically 150-300 ms.
///   - Pauses between sentences (a period followed by a new clause)
///     can reach ~400 ms in the same utterance.
///   - 600 ms is past the longest natural intra-utterance pause but
///     well under any "speech truly ended" gap.
const Duration _kDefaultSilenceConfirmation = Duration(milliseconds: 600);

/// REST is the Rive viseme id emitted by [FormantVisemeAnalyzer] when
/// the chunk's RMS falls below the silence threshold. Hardcoded here
/// (and in `FormantVisemeAnalyzer.kt`) — the two sides agree by enum
/// value, not by import.
const int _kRestVisemeId = 0;

class VisemeScheduler {
  VisemeScheduler({
    required void Function(int visemeId) applyViseme,
    void Function()? onSilenceConfirmed,
    Duration silenceConfirmation = _kDefaultSilenceConfirmation,
    Stream<int>? eventStream,
  }) : _applyViseme = applyViseme,
       _onSilenceConfirmed = onSilenceConfirmed,
       _silenceConfirmation = silenceConfirmation {
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

  /// Story 6.4 — fires whenever the viseme stream has stayed at REST
  /// for [_silenceConfirmation] without any non-REST event in between.
  /// Used by `CallBloc` to know when the local speaker has actually
  /// finished playing the server's hang-up exit line, so the room
  /// disconnect can be scheduled without cutting audio mid-sentence.
  ///
  /// Fires once per silence window. Re-fires on subsequent silence
  /// windows if speech resumes (e.g. between user turns). Consumers
  /// MUST gate on their own "is this end-of-call?" state — the
  /// callback is naive about call lifecycle.
  final void Function()? _onSilenceConfirmed;

  final Duration _silenceConfirmation;
  Timer? _silenceTimer;

  /// Tracks the previously-emitted viseme id so we can defensively
  /// dedupe at the Dart layer. The native analyzer is supposed to
  /// emit each viseme only on transition, but a future native build
  /// or sample-rate change could regress to per-chunk emit — in
  /// which case every REST chunk would re-cancel + re-arm the
  /// silence timer, and `_onSilenceConfirmed` would NEVER fire (the
  /// timer is reset 50× a second). Dart-side dedup is a cheap
  /// belt-and-braces: only changes in viseme id reset the timer.
  /// `null` sentinel = no prior event observed.
  int? _lastVisemeId;

  // The analyzer can't see through the explicit `await sub.cancel()` in
  // [dispose], so the lint is a false positive — silence with rationale.
  // ignore: cancel_subscriptions
  StreamSubscription<int>? _subscription;
  bool _disposed = false;

  void _onNativeViseme(int visemeId) {
    if (_disposed) return;
    _applyViseme(visemeId);

    // Defensive Dart-side dedup: if the native side regresses and
    // emits the same viseme id on consecutive chunks, ignore the
    // duplicate so the silence timer below isn't continually
    // re-armed and never fires. Identity-of-transition is preserved
    // regardless of native-side behavior.
    if (_lastVisemeId == visemeId) return;
    _lastVisemeId = visemeId;

    // Silence tracking: REST starts/restarts the silence timer; any
    // non-REST event cancels it. The native analyzer emits each
    // viseme only on transition (it dedupes consecutive same-value
    // chunks), so receiving REST means "the stream just transitioned
    // into silence". If no further events arrive within
    // [_silenceConfirmation], the speaker has been silent the whole
    // window → fire the callback.
    _silenceTimer?.cancel();
    if (visemeId == _kRestVisemeId) {
      _silenceTimer = Timer(_silenceConfirmation, () {
        if (_disposed) return;
        _onSilenceConfirmed?.call();
      });
    } else {
      _silenceTimer = null;
    }
  }

  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _silenceTimer?.cancel();
    _silenceTimer = null;
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
