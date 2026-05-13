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
///
/// Story 6.5 Déviation #27 — `endReason`, `wasGifted`, `giftsRemainingToday`
/// drive the post-call notice screen. The fields are populated as
/// follows:
///   - `endReason` is the canonical reason string from
///     `call-ended-screen-design.md` (always set when the call ends
///     through the bloc's normal exit paths). The `network_lost` value
///     always triggers a notice screen client-side regardless of the
///     server response (the user must understand "your connection
///     dropped").
///   - `wasGifted` reflects the server response. `null` when the POST
///     hasn't resolved yet (queued for retry, or response timed out).
///     The notice screen falls back to hedged copy in that case
///     ("we'll confirm next time you open the app").
///   - `giftsRemainingToday` is the server-authoritative count after
///     this call. `null` when `wasGifted` is null.
final class CallEnded extends CallState {
  final String? endReason;
  final bool? wasGifted;
  final int? giftsRemainingToday;

  const CallEnded({
    this.endReason,
    this.wasGifted,
    this.giftsRemainingToday,
  });
}
