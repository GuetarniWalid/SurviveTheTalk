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
