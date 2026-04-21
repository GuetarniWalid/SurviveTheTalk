sealed class AuthState {}

final class AuthInitial extends AuthState {}

final class AuthLoading extends AuthState {}

final class AuthCodeSent extends AuthState {
  final String email;
  AuthCodeSent(this.email);
}

final class AuthAuthenticated extends AuthState {}

final class AuthError extends AuthState {
  final String message;
  final AuthState previousState;
  AuthError(this.message, {required this.previousState});
}
