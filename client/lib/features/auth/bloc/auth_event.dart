sealed class AuthEvent {}

final class CheckAuthStatusEvent extends AuthEvent {}

final class SubmitEmailEvent extends AuthEvent {
  final String email;
  SubmitEmailEvent(this.email);
}

final class ResetAuthEvent extends AuthEvent {}

/// Story 10.1 — explicit, user-initiated sign-out (deletes the stored JWT, then
/// emits `AuthInitial`). Used after a successful account deletion so the de-auth
/// is immediate and deterministic instead of waiting for the next request's 401.
/// Routes through the SAME `AuthInitial` transition the 401 / expiry paths use,
/// so the Story 9.1 offline-cache wipe + the GoRouter redirect fire unchanged.
final class SignOutEvent extends AuthEvent {}

final class SubmitCodeEvent extends AuthEvent {
  final String email;
  final String code;
  SubmitCodeEvent({required this.email, required this.code});
}
