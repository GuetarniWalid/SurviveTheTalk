class AuthResult {
  final String token;
  final int userId;
  final String email;

  const AuthResult({
    required this.token,
    required this.userId,
    required this.email,
  });

  factory AuthResult.fromJson(Map<String, dynamic> json) {
    return AuthResult(
      token: json['token'] as String,
      userId: json['user_id'] as int,
      email: json['email'] as String,
    );
  }
}
