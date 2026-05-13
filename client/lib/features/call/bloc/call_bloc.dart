import 'dart:async';

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:livekit_client/livekit_client.dart';

import '../../scenarios/models/scenario.dart';
import '../models/call_session.dart';
import 'call_event.dart';
import 'call_state.dart';

class CallBloc extends Bloc<CallEvent, CallState> {
  final CallSession _session;
  // ignore: unused_field
  final Scenario _scenario;
  final Room _room;

  /// Exposes the cancel function returned by `room.events.on<...>` so we can
  /// unsubscribe in `close()` and avoid leaking a listener after the bloc
  /// is gone.
  CancelListenFunc? _disconnectCancel;

  /// True once `_onHangUpPressed` started — guards against the
  /// `RoomDisconnectedEvent` callback (asynchronously emitted via the
  /// LiveKit event bus when `room.disconnect()` runs) re-entering the
  /// disconnect path and emitting CallError on top of CallEnded.
  bool _hangingUp = false;

  /// True once the LiveKit `connect()` + mic-publish completed successfully.
  /// Guards `_onRoomDisconnected` against firing for the synchronous
  /// `RoomDisconnectedEvent` that LiveKit emits internally during a *failed*
  /// connect — without this, `_onCallStarted`'s catch arm and the listener
  /// would each emit `CallError`, racing.
  bool _connected = false;

  /// True after `room.disconnect()` has been awaited at least once. Stops
  /// `close()` from issuing a redundant second disconnect (the LiveKit Room
  /// handles a double-disconnect gracefully but it surfaces as a noisy log).
  bool _roomDisconnected = false;

  /// True once a server-driven `RemoteCallEnded` has been processed. Read
  /// by `_onRoomDisconnected` + the LiveKit listener so the follow-on
  /// `RoomDisconnectedEvent` from Pipecat's safety `EndFrame` does NOT
  /// surface `CallError('Connection lost.')` over a clean character-
  /// driven hang-up (Story 6.4 AC5). Also gates `_onPlaybackDrained`
  /// so mid-call user silence doesn't tear the room down.
  bool _remoteEndPending = false;

  /// Safety bound on the "remote-end-pending" window. If
  /// `VisemeScheduler.onSilenceConfirmed` never fires after a
  /// `RemoteCallEnded` (native channel detached, analyzer crashed,
  /// PCM stream wedged), force a `PlaybackDrained` after 10 s so the
  /// room is never wedged in a half-ended state. 10 s comfortably
  /// covers any natural exit-line duration on slow cellular.
  Timer? _remoteEndDrainTimer;

  /// Story 6.4 — small delay between the client-confirmed playback
  /// drain and the actual `_room.disconnect()` call. Covers the
  /// Android `AudioTrack` hardware buffer (~50-200 ms) that the
  /// VisemeScheduler's PCM-stream silence detector can't see. Without
  /// it, the very tail of the bot's exit line gets cut when
  /// `disconnect()` tears down the audio track.
  ///
  /// Constructor-injectable so tests can pass `Duration.zero` to
  /// keep their assertions fast.
  final Duration _playbackDrainBuffer;

  /// Read-only access to the underlying LiveKit Room for non-lifecycle
  /// subscriptions (e.g. `DataChannelHandler` listening to
  /// `DataReceivedEvent`). The bloc remains the single owner of the
  /// Room's connect/disconnect lifecycle. DO NOT call `disconnect()` on
  /// this Room from outside the bloc — emit a `HangUpPressed` event
  /// instead so the lifecycle guards (`_hangingUp`, `_roomDisconnected`)
  /// stay coherent.
  Room get room => _room;

  CallBloc({
    required CallSession session,
    required Scenario scenario,
    required Room room,
    Duration playbackDrainBuffer = const Duration(milliseconds: 500),
  }) : _session = session,
       _scenario = scenario,
       _room = room,
       _playbackDrainBuffer = playbackDrainBuffer,
       super(const CallConnecting()) {
    on<CallStarted>(_onCallStarted);
    on<HangUpPressed>(_onHangUpPressed);
    on<RoomDisconnected>(_onRoomDisconnected);
    on<RemoteCallEnded>(_onRemoteCallEnded);
    on<PlaybackDrained>(_onPlaybackDrained);

    _disconnectCancel = _room.events.on<RoomDisconnectedEvent>((_) {
      if (_hangingUp) return;
      // Skip the synchronous-during-connect-failure case: `_onCallStarted`'s
      // own catch arm owns the CallError emission for that path, otherwise
      // the listener would race it with a second `[CallError, CallEnded]`.
      if (!_connected) return;
      // Story 6.4 — the server-driven hang-up sequence ends with a
      // pipecat EndFrame → LiveKit room teardown → this listener fires.
      // The `_remoteEndPending` flag short-circuits the path so the
      // already-emitted `CallEnded` isn't overwritten by `CallError`.
      // Mirror LiveKit's internal disconnected state into our flag so a
      // follow-on `PlaybackDrained` (10 s safety timer, or the natural
      // VisemeScheduler signal) doesn't try to disconnect an already-
      // disconnected room — a wasted call that surfaces as a noisy log.
      if (_remoteEndPending) {
        _roomDisconnected = true;
        return;
      }
      add(const RoomDisconnected());
    });
  }

  Future<void> _onCallStarted(
    CallStarted event,
    Emitter<CallState> emit,
  ) async {
    final stopwatch = Stopwatch()..start();
    // `Future.sync` traps a synchronous throw from `connect()` (e.g. mocked
    // failure in tests, or an SDK precondition assertion) into an async
    // failure so the surrounding try/catch is the single failure-handling
    // surface.
    final connectFuture = Future<void>.sync(
      () => _room.connect(_session.livekitUrl, _session.token),
    );
    try {
      await connectFuture.timeout(
        const Duration(seconds: 5),
        onTimeout: () => throw TimeoutException('LiveKit connect timed out'),
      );
    } on TimeoutException {
      // Schedule a fire-and-forget disconnect for the case where the
      // underlying connect resolves AFTER the timeout — Future.timeout
      // can't cancel its target, so without this we leak a half-connected
      // Room (zombie participant on the LiveKit server).
      _scheduleZombieDisconnect(connectFuture);
      if (emit.isDone) return;
      emit(const CallError("Couldn't connect to the call."));
      emit(const CallEnded());
      return;
    } catch (_) {
      _scheduleZombieDisconnect(connectFuture);
      if (emit.isDone) return;
      emit(const CallError("Couldn't connect to the call."));
      emit(const CallEnded());
      return;
    }

    // Minimum 1-s "Connecting…" display per incoming-call-screen-design.md:409.
    // Mic publish is held until AFTER the visual hold so the user is not
    // already publishing audio while the dots are still on screen.
    final remaining = 1000 - stopwatch.elapsedMilliseconds;
    if (remaining > 0) {
      await Future<void>.delayed(Duration(milliseconds: remaining));
    }
    if (emit.isDone) return;
    try {
      await _room.localParticipant?.setMicrophoneEnabled(true);
    } catch (_) {
      if (emit.isDone) return;
      emit(const CallError("Couldn't connect to the call."));
      emit(const CallEnded());
      return;
    }
    _connected = true;
    if (emit.isDone) return;
    emit(const CallConnected());
  }

  void _scheduleZombieDisconnect(Future<void> connectFuture) {
    connectFuture
        .then((_) async {
          // Connect resolved post-timeout. Drop the orphan room.
          if (_roomDisconnected) return;
          _roomDisconnected = true;
          try {
            await _room.disconnect();
          } catch (_) {}
        })
        .catchError((_) {
          // Connect resolved post-timeout with a failure — nothing to clean
          // up. Swallow to keep the future from surfacing as an unhandled
          // zone error.
        });
  }

  Future<void> _onHangUpPressed(
    HangUpPressed event,
    Emitter<CallState> emit,
  ) async {
    _hangingUp = true;
    // User-initiated hang-up takes over from any pending remote-end:
    // clear the 10 s safety timer so it can't fire a stale
    // `PlaybackDrained` after the bloc has already emitted CallEnded
    // (which would cause a double-emit, or — worse — fire on a closed
    // bloc if the screen unmounts before the timer's deadline).
    _remoteEndDrainTimer?.cancel();
    _remoteEndDrainTimer = null;
    _remoteEndPending = false;
    if (!_roomDisconnected) {
      _roomDisconnected = true;
      try {
        await _room.disconnect();
      } catch (_) {
        // disconnect() rarely throws, but if it does the user has already
        // committed to leaving — surface CallEnded anyway rather than wedge
        // the screen.
      }
    }
    // TODO(Story 6.5): POST /calls/{id}/end here.
    if (emit.isDone) return;
    emit(const CallEnded());
  }

  Future<void> _onRoomDisconnected(
    RoomDisconnected event,
    Emitter<CallState> emit,
  ) async {
    if (_hangingUp) return;
    // Story 6.4 — character-driven end: the server's safety EndFrame
    // (8 s after `call_end`) tears down the room. We may not have
    // received our local `PlaybackDrained` yet — emit CallEnded
    // directly (clean end, not Connection lost).
    if (_remoteEndPending) {
      _remoteEndDrainTimer?.cancel();
      _remoteEndDrainTimer = null;
      _roomDisconnected = true;
      if (emit.isDone) return;
      emit(const CallEnded());
      return;
    }
    if (emit.isDone) return;
    emit(const CallError('Connection lost.'));
    _roomDisconnected = true;
    if (emit.isDone) return;
    emit(const CallEnded());
  }

  Future<void> _onRemoteCallEnded(
    RemoteCallEnded event,
    Emitter<CallState> emit,
  ) async {
    if (_remoteEndPending) return;
    _remoteEndPending = true;
    // Do NOT disconnect the room here — the server's TTS exit line is
    // still streaming and the local jitter buffer / Opus decoder still
    // has up to ~1.5 s of audio to play. Disconnecting now cuts the
    // last sentence mid-word.
    //
    // The drain signal comes from `VisemeScheduler.onSilenceConfirmed`
    // (which rides the same PCM stream that drives lip-sync, via
    // `AudioClockChannel`) → `PlaybackDrained` event → disconnect.
    //
    // Safety: if the silence signal never fires (native detach, crash,
    // wedged stream), force-end after 10 s so the bloc isn't stuck
    // forever in remote-end-pending.
    _remoteEndDrainTimer?.cancel();
    _remoteEndDrainTimer = Timer(const Duration(seconds: 10), () {
      add(const PlaybackDrained());
    });
  }

  Future<void> _onPlaybackDrained(
    PlaybackDrained event,
    Emitter<CallState> emit,
  ) async {
    // Gate on `_remoteEndPending` — VisemeScheduler fires this
    // callback on every silence window, including mid-call gaps
    // between user turns. Only the post-`RemoteCallEnded` firing
    // should end the call.
    if (!_remoteEndPending) return;
    _remoteEndDrainTimer?.cancel();
    _remoteEndDrainTimer = null;

    // The VisemeScheduler's `onSilenceConfirmed` fires when the PCM
    // STREAM BEING SENT to the speaker has been silent for the
    // confirmation window. The Android AudioTrack hardware buffer
    // (~50-200 ms) is still playing the last real audio samples at
    // that moment — calling `_room.disconnect()` immediately would
    // tear down the audio track and cut the very tail of the bot's
    // exit line ("...Goodbye." → "...Goodb").
    //
    // 500 ms covers the worst-case hardware buffer + speaker latency
    // on Android without being perceptibly long.
    if (_playbackDrainBuffer > Duration.zero) {
      await Future<void>.delayed(_playbackDrainBuffer);
    }

    // Re-check emit.isDone after the await — `HangUpPressed` could
    // have raced past us during the drain delay and already emitted
    // CallEnded (the bloc serializes handlers but Bloc's framework
    // can mark emit.isDone during teardown).
    if (emit.isDone) return;

    if (!_roomDisconnected) {
      _roomDisconnected = true;
      try {
        await _room.disconnect();
      } catch (_) {
        // Same posture as `_onHangUpPressed`: the user has already
        // committed to leaving (the server hung up); surface CallEnded
        // regardless rather than wedge the screen.
      }
    }
    // TODO(Story 6.5): POST /calls/{id}/end here.
    if (emit.isDone) return;
    emit(const CallEnded());
  }

  @override
  Future<void> close() async {
    _remoteEndDrainTimer?.cancel();
    _remoteEndDrainTimer = null;
    final cancel = _disconnectCancel;
    _disconnectCancel = null;
    if (cancel != null) {
      await cancel();
    }
    if (!_roomDisconnected) {
      _roomDisconnected = true;
      try {
        await _room.disconnect();
      } catch (_) {}
    }
    return super.close();
  }
}
