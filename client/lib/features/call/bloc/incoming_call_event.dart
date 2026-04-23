sealed class IncomingCallEvent {
  const IncomingCallEvent();
}

final class AcceptCallEvent extends IncomingCallEvent {
  const AcceptCallEvent();
}

final class DeclineCallEvent extends IncomingCallEvent {
  const DeclineCallEvent();
}
