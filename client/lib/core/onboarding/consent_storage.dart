import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class ConsentStorage {
  static const String _consentKey = 'consent_timestamp';
  static const String _micPermissionKey = 'mic_permission_granted';

  final FlutterSecureStorage _storage;

  bool _cachedConsent = false;
  bool _cachedMicPermission = false;

  ConsentStorage([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  /// Loads consent and mic status from secure storage into memory.
  /// Call once during app initialization.
  Future<void> preload() async {
    _cachedConsent = await hasConsent();
    _cachedMicPermission = await hasMicPermission();
  }

  bool get hasConsentSync => _cachedConsent;
  bool get hasMicPermissionSync => _cachedMicPermission;

  Future<void> saveConsent() async {
    await _storage.write(
        key: _consentKey, value: DateTime.now().toIso8601String());
    _cachedConsent = true;
  }

  Future<bool> hasConsent() async {
    final value = await _storage.read(key: _consentKey);
    return value != null;
  }

  Future<String?> getConsentTimestamp() => _storage.read(key: _consentKey);

  Future<void> deleteConsent() async {
    _cachedConsent = false;
    _cachedMicPermission = false;
    await _storage.delete(key: _consentKey);
    await _storage.delete(key: _micPermissionKey);
  }

  Future<void> saveMicPermission(bool granted) async {
    await _storage.write(key: _micPermissionKey, value: granted.toString());
    _cachedMicPermission = granted;
  }

  Future<bool> hasMicPermission() async {
    final value = await _storage.read(key: _micPermissionKey);
    return value == 'true';
  }
}
