sealed class CallEvent {
  const CallEvent();
}

/// Fires once on `initState` to start the LiveKit `Room.connect` flow.
final class CallStarted extends CallEvent {
  const CallStarted();
}

/// User tapped the hang-up button (visible during both connecting and
/// connected states).
final class HangUpPressed extends CallEvent {
  const HangUpPressed();
}

/// LiveKit emitted `RoomDisconnectedEvent` (network drop / server kick /
/// remote close). Carries no payload — the bloc treats every disconnect
/// not initiated by `HangUpPressed` as a connection-loss error.
final class RoomDisconnected extends CallEvent {
  const RoomDisconnected();
}

/// Pipecat sent `{"type":"call_end"}` over the data channel — the
/// character ended the call. Carries the server's reason (e.g.
/// `character_hung_up`, `inappropriate_content`) plus the raw `data`
/// map (`survival_pct`, `checkpoints_passed`, `total_checkpoints`) for
/// telemetry / debrief consumers downstream.
///
/// Receiving this event does NOT immediately tear down the room —
/// the bloc parks the call in a "remote-end-pending" state and waits
/// for [PlaybackDrained] before disconnecting, so the exit line audio
/// can finish playing on the local speaker. See Story 6.4 §"WebRTC
/// playback drain" deviation note.
final class RemoteCallEnded extends CallEvent {
  final String reason;
  final Map<String, dynamic> data;
  const RemoteCallEnded(this.reason, this.data);
}

/// Story 6.4 — the local audio output has stopped playing (no PCM
/// activity for [VisemeScheduler]'s silence-confirmation window). The
/// bloc consumes this AFTER [RemoteCallEnded] to disconnect the room
/// at the moment audio actually finishes — instead of right when the
/// `call_end` envelope arrives. Replaces the server-side magic-number
/// playback buffer with a signal that rides the same PCM stream used
/// for lip-sync, so the timing is correct on any network.
///
/// Outside an end-of-call window (e.g. user pauses mid-conversation),
/// the bloc ignores this event — `_remoteEndPending` is the gate.
final class PlaybackDrained extends CallEvent {
  const PlaybackDrained();
}
