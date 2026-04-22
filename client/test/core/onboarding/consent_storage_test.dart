import 'package:client/core/onboarding/consent_storage.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late ConsentStorage consentStorage;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    consentStorage = ConsentStorage();
  });

  group('ConsentStorage', () {
    test('hasConsent returns false when no consent is stored', () async {
      expect(await consentStorage.hasConsent(), isFalse);
    });

    test('saveConsent + hasConsent round-trip returns true', () async {
      await consentStorage.saveConsent();
      expect(await consentStorage.hasConsent(), isTrue);
    });

    test('getConsentTimestamp returns ISO 8601 string after saveConsent',
        () async {
      await consentStorage.saveConsent();
      final timestamp = await consentStorage.getConsentTimestamp();
      expect(timestamp, isNotNull);
      // Verify it's a valid ISO 8601 string
      expect(DateTime.tryParse(timestamp!), isNotNull);
    });

    test('getConsentTimestamp returns null when no consent stored', () async {
      expect(await consentStorage.getConsentTimestamp(), isNull);
    });

    test('deleteConsent clears consent and mic permission', () async {
      await consentStorage.saveConsent();
      await consentStorage.saveMicPermission(true);
      expect(await consentStorage.hasConsent(), isTrue);
      expect(await consentStorage.hasMicPermission(), isTrue);

      await consentStorage.deleteConsent();
      expect(await consentStorage.hasConsent(), isFalse);
      expect(await consentStorage.hasMicPermission(), isFalse);
    });

    test('saveMicPermission + hasMicPermission round-trip (granted)', () async {
      await consentStorage.saveMicPermission(true);
      expect(await consentStorage.hasMicPermission(), isTrue);
    });

    test('saveMicPermission + hasMicPermission round-trip (denied)', () async {
      await consentStorage.saveMicPermission(false);
      expect(await consentStorage.hasMicPermission(), isFalse);
    });

    test('hasMicPermission returns false when nothing stored', () async {
      expect(await consentStorage.hasMicPermission(), isFalse);
    });
  });
}
