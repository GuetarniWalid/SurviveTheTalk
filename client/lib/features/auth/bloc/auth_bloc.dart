import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/auth/token_storage.dart';
import '../data/auth_repository.dart';
import 'auth_event.dart';
import 'auth_state.dart';

class AuthBloc extends Bloc<AuthEvent, AuthState> {
  final AuthRepository _authRepository;
  final TokenStorage _tokenStorage;

  AuthBloc({
    required AuthRepository authRepository,
    required TokenStorage tokenStorage,
  }) : _authRepository = authRepository,
       _tokenStorage = tokenStorage,
       super(AuthInitial()) {
    on<CheckAuthStatusEvent>(_onCheckAuthStatus);
    on<ResetAuthEvent>(_onReset);
    on<SubmitEmailEvent>(_onSubmitEmail);
    on<SubmitCodeEvent>(_onSubmitCode);
  }

  Future<void> _onCheckAuthStatus(
    CheckAuthStatusEvent event,
    Emitter<AuthState> emit,
  ) async {
    try {
      final token = await _tokenStorage.readToken();
      if (token != null && !TokenStorage.isTokenExpired(token)) {
        emit(AuthAuthenticated());
      } else {
        if (token != null) {
          await _tokenStorage.deleteToken();
        }
        emit(AuthInitial());
      }
    } catch (_) {
      emit(AuthInitial());
    }
  }

  void _onReset(ResetAuthEvent event, Emitter<AuthState> emit) {
    emit(AuthInitial());
  }

  Future<void> _onSubmitEmail(
    SubmitEmailEvent event,
    Emitter<AuthState> emit,
  ) async {
    emit(AuthLoading());
    try {
      await _authRepository.requestCode(event.email);
      emit(AuthCodeSent(event.email));
    } on ApiException catch (e) {
      emit(AuthError(e.message, previousState: state));
    }
  }

  Future<void> _onSubmitCode(
    SubmitCodeEvent event,
    Emitter<AuthState> emit,
  ) async {
    emit(AuthLoading());
    try {
      final result = await _authRepository.verifyCode(event.email, event.code);
      try {
        await _tokenStorage.saveToken(result.token);
        await _tokenStorage.saveUserId(result.userId);
      } catch (_) {
        emit(AuthError(
          'Could not save session. Please try again.',
          previousState: AuthCodeSent(event.email),
        ));
        return;
      }
      emit(AuthAuthenticated());
    } on ApiException catch (e) {
      emit(AuthError(e.message, previousState: AuthCodeSent(event.email)));
    }
  }
}
