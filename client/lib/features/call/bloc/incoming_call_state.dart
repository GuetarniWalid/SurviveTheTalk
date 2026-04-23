import '../models/call_session.dart';

sealed class IncomingCallState {
  const IncomingCallState();
}

final class IncomingCallRinging extends IncomingCallState {
  const IncomingCallRinging();
}

final class IncomingCallAccepting extends IncomingCallState {
  const IncomingCallAccepting();
}

final class IncomingCallConnected extends IncomingCallState {
  final CallSession session;
  const IncomingCallConnected(this.session);
}

final class IncomingCallDeclined extends IncomingCallState {
  const IncomingCallDeclined();
}

final class IncomingCallError extends IncomingCallState {
  final String message;
  const IncomingCallError(this.message);
}
