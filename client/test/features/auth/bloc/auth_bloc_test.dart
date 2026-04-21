import 'dart:convert';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/core/auth/token_storage.dart';
import 'package:client/features/auth/bloc/auth_bloc.dart';
import 'package:client/features/auth/bloc/auth_event.dart';
import 'package:client/features/auth/bloc/auth_state.dart';
import 'package:client/features/auth/data/auth_repository.dart';
import 'package:client/features/auth/data/auth_result.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockAuthRepository extends Mock implements AuthRepository {}

class MockTokenStorage extends Mock implements TokenStorage {}

String _buildJwt(int exp) {
  final header = base64Url.encode(utf8.encode('{"alg":"HS256"}'));
  final payload = base64Url.encode(utf8.encode('{"exp":$exp}'));
  const signature = 'signature';
  return '$header.$payload.$signature';
}

void main() {
  late MockAuthRepository mockAuthRepository;
  late MockTokenStorage mockTokenStorage;

  setUp(() {
    mockAuthRepository = MockAuthRepository();
    mockTokenStorage = MockTokenStorage();
  });

  AuthBloc buildBloc() => AuthBloc(
    authRepository: mockAuthRepository,
    tokenStorage: mockTokenStorage,
  );

  group('CheckAuthStatusEvent', () {
    blocTest<AuthBloc, AuthState>(
      'emits [AuthAuthenticated] when token exists and is not expired',
      setUp: () {
        final validToken = _buildJwt(
          DateTime.now().millisecondsSinceEpoch ~/ 1000 + 3600,
        );
        when(() => mockTokenStorage.readToken())
            .thenAnswer((_) async => validToken);
      },
      build: buildBloc,
      act: (bloc) => bloc.add(CheckAuthStatusEvent()),
      expect: () => [isA<AuthAuthenticated>()],
    );

    blocTest<AuthBloc, AuthState>(
      'emits [AuthInitial] when no token stored',
      setUp: () {
        when(() => mockTokenStorage.readToken())
            .thenAnswer((_) async => null);
      },
      build: buildBloc,
      act: (bloc) => bloc.add(CheckAuthStatusEvent()),
      expect: () => [isA<AuthInitial>()],
    );

    blocTest<AuthBloc, AuthState>(
      'emits [AuthInitial] and deletes expired token',
      setUp: () {
        final expiredToken = _buildJwt(
          DateTime.now().millisecondsSinceEpoch ~/ 1000 - 3600,
        );
        when(() => mockTokenStorage.readToken())
            .thenAnswer((_) async => expiredToken);
        when(() => mockTokenStorage.deleteToken())
            .thenAnswer((_) async {});
      },
      build: buildBloc,
      act: (bloc) => bloc.add(CheckAuthStatusEvent()),
      expect: () => [isA<AuthInitial>()],
      verify: (_) {
        verify(() => mockTokenStorage.deleteToken()).called(1);
      },
    );
  });

  group('SubmitEmailEvent', () {
    blocTest<AuthBloc, AuthState>(
      'emits [AuthLoading, AuthCodeSent] on success',
      setUp: () {
        when(() => mockAuthRepository.requestCode('test@example.com'))
            .thenAnswer((_) async {});
      },
      build: buildBloc,
      act: (bloc) => bloc.add(SubmitEmailEvent('test@example.com')),
      expect: () => [
        isA<AuthLoading>(),
        isA<AuthCodeSent>().having((s) => s.email, 'email', 'test@example.com'),
      ],
    );

    blocTest<AuthBloc, AuthState>(
      'emits [AuthLoading, AuthError] on ApiException',
      setUp: () {
        when(() => mockAuthRepository.requestCode('test@example.com'))
            .thenThrow(
              const ApiException(
                code: 'EMAIL_DELIVERY_FAILED',
                message: 'Could not send email. Please try again.',
              ),
            );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(SubmitEmailEvent('test@example.com')),
      expect: () => [
        isA<AuthLoading>(),
        isA<AuthError>().having(
          (s) => s.message,
          'message',
          'Could not send email. Please try again.',
        ),
      ],
    );
  });

  group('SubmitCodeEvent', () {
    blocTest<AuthBloc, AuthState>(
      'emits [AuthLoading, AuthAuthenticated] on success and saves token',
      setUp: () {
        when(
          () => mockAuthRepository.verifyCode('test@example.com', '123456'),
        ).thenAnswer(
          (_) async => const AuthResult(
            token: 'jwt-token',
            userId: 1,
            email: 'test@example.com',
          ),
        );
        when(() => mockTokenStorage.saveToken('jwt-token'))
            .thenAnswer((_) async {});
        when(() => mockTokenStorage.saveUserId(1))
            .thenAnswer((_) async {});
      },
      build: buildBloc,
      act: (bloc) => bloc.add(
        SubmitCodeEvent(email: 'test@example.com', code: '123456'),
      ),
      expect: () => [isA<AuthLoading>(), isA<AuthAuthenticated>()],
      verify: (_) {
        verify(() => mockTokenStorage.saveToken('jwt-token')).called(1);
        verify(() => mockTokenStorage.saveUserId(1)).called(1);
      },
    );

    blocTest<AuthBloc, AuthState>(
      'emits [AuthLoading, AuthError] on ApiException',
      setUp: () {
        when(
          () => mockAuthRepository.verifyCode('test@example.com', '999999'),
        ).thenThrow(
          const ApiException(
            code: 'AUTH_CODE_INVALID',
            message: 'Invalid code. Please check and try again.',
          ),
        );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(
        SubmitCodeEvent(email: 'test@example.com', code: '999999'),
      ),
      expect: () => [
        isA<AuthLoading>(),
        isA<AuthError>().having(
          (s) => s.message,
          'message',
          'Invalid code. Please check and try again.',
        ),
      ],
    );
  });
}
