sealed class AuthEvent {}

final class CheckAuthStatusEvent extends AuthEvent {}

final class SubmitEmailEvent extends AuthEvent {
  final String email;
  SubmitEmailEvent(this.email);
}

final class ResetAuthEvent extends AuthEvent {}

final class SubmitCodeEvent extends AuthEvent {
  final String email;
  final String code;
  SubmitCodeEvent({required this.email, required this.code});
}
