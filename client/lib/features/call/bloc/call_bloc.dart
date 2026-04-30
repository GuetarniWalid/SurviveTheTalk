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
  }) : _session = session,
       _scenario = scenario,
       _room = room,
       super(const CallConnecting()) {
    on<CallStarted>(_onCallStarted);
    on<HangUpPressed>(_onHangUpPressed);
    on<RoomDisconnected>(_onRoomDisconnected);

    _disconnectCancel = _room.events.on<RoomDisconnectedEvent>((_) {
      if (_hangingUp) return;
      // Skip the synchronous-during-connect-failure case: `_onCallStarted`'s
      // own catch arm owns the CallError emission for that path, otherwise
      // the listener would race it with a second `[CallError, CallEnded]`.
      if (!_connected) return;
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
    // TODO(Story 6.4): POST /calls/{id}/end here.
    if (emit.isDone) return;
    emit(const CallEnded());
  }

  Future<void> _onRoomDisconnected(
    RoomDisconnected event,
    Emitter<CallState> emit,
  ) async {
    if (_hangingUp) return;
    if (emit.isDone) return;
    emit(const CallError('Connection lost.'));
    _roomDisconnected = true;
    if (emit.isDone) return;
    emit(const CallEnded());
  }

  @override
  Future<void> close() async {
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
