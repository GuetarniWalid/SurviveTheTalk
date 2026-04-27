import 'dart:convert';

import 'package:client/core/auth/token_storage.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late TokenStorage tokenStorage;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    tokenStorage = TokenStorage();
  });

  group('Token operations', () {
    test('saveToken + readToken round-trip', () async {
      await tokenStorage.saveToken('jwt-token-123');
      final result = await tokenStorage.readToken();
      expect(result, 'jwt-token-123');
    });

    test('readToken returns null when empty', () async {
      final result = await tokenStorage.readToken();
      expect(result, isNull);
    });

    test('deleteToken clears the value', () async {
      await tokenStorage.saveToken('jwt-token-123');
      await tokenStorage.deleteToken();
      final result = await tokenStorage.readToken();
      expect(result, isNull);
    });
  });

  group('UserId operations', () {
    test('saveUserId + readUserId round-trip', () async {
      await tokenStorage.saveUserId(42);
      final result = await tokenStorage.readUserId();
      expect(result, 42);
    });

    test('readUserId returns null when empty', () async {
      final result = await tokenStorage.readUserId();
      expect(result, isNull);
    });
  });

  group('isTokenExpired', () {
    String buildJwt(int exp) {
      final header = base64Url.encode(utf8.encode('{"alg":"HS256"}'));
      final payload = base64Url.encode(utf8.encode('{"exp":$exp}'));
      const signature = 'signature';
      return '$header.$payload.$signature';
    }

    test('returns false for non-expired token', () {
      final futureExp =
          DateTime.now().millisecondsSinceEpoch ~/ 1000 + 3600; // +1h
      final token = buildJwt(futureExp);
      expect(TokenStorage.isTokenExpired(token), isFalse);
    });

    test('returns true for expired token', () {
      final pastExp =
          DateTime.now().millisecondsSinceEpoch ~/ 1000 - 3600; // -1h
      final token = buildJwt(pastExp);
      expect(TokenStorage.isTokenExpired(token), isTrue);
    });

    test('returns true for malformed token', () {
      expect(TokenStorage.isTokenExpired('not-a-jwt'), isTrue);
    });

    test('returns true for token without exp claim', () {
      final header = base64Url.encode(utf8.encode('{"alg":"HS256"}'));
      final payload = base64Url.encode(utf8.encode('{"sub":"1"}'));
      final token = '$header.$payload.signature';
      expect(TokenStorage.isTokenExpired(token), isTrue);
    });
  });

  group('preload + hasValidTokenSync (anti flash-of-login)', () {
    String buildJwt(int exp) {
      final header = base64Url.encode(utf8.encode('{"alg":"HS256"}'));
      final payload = base64Url.encode(utf8.encode('{"exp":$exp}'));
      const signature = 'signature';
      return '$header.$payload.$signature';
    }

    test(
      'hasValidTokenSync returns false when preload was never called',
      () {
        // A fresh TokenStorage that was never preloaded MUST behave as
        // "not authenticated" — production bootstrap forgets to preload?
        // The user sees /login (correct fallback), not a phantom
        // /scenarios screen.
        expect(tokenStorage.hasValidTokenSync, isFalse);
      },
    );

    test(
      'preload caches true when a non-expired token is stored',
      () async {
        final futureExp =
            DateTime.now().millisecondsSinceEpoch ~/ 1000 + 3600;
        await tokenStorage.saveToken(buildJwt(futureExp));

        await tokenStorage.preload();

        expect(tokenStorage.hasValidTokenSync, isTrue);
      },
    );

    test(
      'preload caches false when token is expired',
      () async {
        final pastExp =
            DateTime.now().millisecondsSinceEpoch ~/ 1000 - 3600;
        await tokenStorage.saveToken(buildJwt(pastExp));

        await tokenStorage.preload();

        expect(tokenStorage.hasValidTokenSync, isFalse);
      },
    );

    test('preload caches false when no token is stored', () async {
      await tokenStorage.preload();

      expect(tokenStorage.hasValidTokenSync, isFalse);
    });
  });
}
