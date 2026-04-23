import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class ConsentStorage {
  static const String _consentKey = 'consent_timestamp';
  static const String _micPermissionKey = 'mic_permission_granted';
  static const String _firstCallShownKey = 'first_call_shown';

  final FlutterSecureStorage _storage;

  bool _cachedConsent = false;
  bool _cachedMicPermission = false;
  bool _cachedFirstCallShown = false;

  ConsentStorage([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  /// Loads consent, mic, and first-call status from secure storage into memory.
  /// Call once during app initialization.
  Future<void> preload() async {
    _cachedConsent = await hasConsent();
    _cachedMicPermission = await hasMicPermission();
    _cachedFirstCallShown = await hasSeenFirstCall();
  }

  bool get hasConsentSync => _cachedConsent;
  bool get hasMicPermissionSync => _cachedMicPermission;
  bool get hasSeenFirstCallSync => _cachedFirstCallShown;

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
    _cachedFirstCallShown = false;
    await _storage.delete(key: _consentKey);
    await _storage.delete(key: _micPermissionKey);
    await _storage.delete(key: _firstCallShownKey);
  }

  Future<void> saveMicPermission(bool granted) async {
    await _storage.write(key: _micPermissionKey, value: granted.toString());
    _cachedMicPermission = granted;
  }

  Future<bool> hasMicPermission() async {
    final value = await _storage.read(key: _micPermissionKey);
    return value == 'true';
  }

  /// Marks the first-call onboarding screen as seen (regardless of Accept or
  /// Decline). Once set, the router routes straight past `/incoming-call` on
  /// every subsequent launch (Story 4.5 AC5 — one-time gate).
  Future<void> saveFirstCallShown() async {
    await _storage.write(key: _firstCallShownKey, value: 'true');
    _cachedFirstCallShown = true;
  }

  Future<bool> hasSeenFirstCall() async {
    final value = await _storage.read(key: _firstCallShownKey);
    return value == 'true';
  }
}
