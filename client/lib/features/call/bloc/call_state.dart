sealed class CallState {
  const CallState();
}

/// Initial state — `Room.connect` is in flight (or the 1-s minimum-display
/// floor is being honored).
final class CallConnecting extends CallState {
  const CallConnecting();
}

/// `Room.connect` succeeded and the mic was published.
final class CallConnected extends CallState {
  const CallConnected();
}

/// Connect failed (timeout, exception) OR the Room dropped mid-call.
/// The reason is shown in-screen briefly before the route fades back.
final class CallError extends CallState {
  final String reason;
  const CallError(this.reason);
}

/// Terminal state — set after `room.disconnect()`. The widget treats it as
/// the cue to pop the route.
final class CallEnded extends CallState {
  const CallEnded();
}
