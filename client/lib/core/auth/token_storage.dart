import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStorage {
  static const String _tokenKey = 'auth_token';
  static const String _userIdKey = 'user_id';

  final FlutterSecureStorage _storage;

  /// Sync cache of "do we hold a non-expired JWT?". Populated by [preload]
  /// during bootstrap so `GoRouter.redirect` can decide auth status without
  /// awaiting `FlutterSecureStorage.read` on the first frame (which would
  /// otherwise cause a flash-of-login-screen for already-authenticated
  /// returning users — see client/CLAUDE.md gotcha #5).
  bool? _cachedHasValidToken;

  TokenStorage([FlutterSecureStorage? storage])
    : _storage = storage ?? const FlutterSecureStorage();

  /// Read the stored token once at bootstrap and cache whether it's a valid
  /// (non-expired) JWT. Subsequent [hasValidTokenSync] calls return the
  /// cached answer with no I/O. The async [readToken] still works the same
  /// for code paths that need the actual token string.
  Future<void> preload() async {
    final token = await readToken();
    _cachedHasValidToken = token != null && !isTokenExpired(token);
  }

  /// True iff [preload] found a stored, non-expired JWT. Returns false when
  /// [preload] was never called (so unit tests with a fresh TokenStorage
  /// behave as "not authenticated" by default — matches the production
  /// pre-preload state).
  bool get hasValidTokenSync => _cachedHasValidToken ?? false;

  Future<void> saveToken(String token) => _storage.write(key: _tokenKey, value: token);

  Future<String?> readToken() => _storage.read(key: _tokenKey);

  Future<void> deleteToken() => _storage.delete(key: _tokenKey);

  Future<void> saveUserId(int userId) =>
      _storage.write(key: _userIdKey, value: userId.toString());

  Future<int?> readUserId() async {
    final value = await _storage.read(key: _userIdKey);
    return value != null ? int.tryParse(value) : null;
  }

  static bool isTokenExpired(String token) {
    final parts = token.split('.');
    if (parts.length != 3) return true;
    try {
      final payload = utf8.decode(base64Url.decode(base64Url.normalize(parts[1])));
      final map = jsonDecode(payload) as Map<String, dynamic>;
      final exp = map['exp'] as int?;
      if (exp == null) return true;
      return DateTime.now().millisecondsSinceEpoch ~/ 1000 >= exp;
    } catch (_) {
      return true;
    }
  }
}
