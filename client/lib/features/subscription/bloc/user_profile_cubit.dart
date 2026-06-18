import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../core/api/api_exception.dart';
import '../models/user_profile.dart';
import '../repositories/user_repository.dart';

/// The 4 base states the Manage subscription DRAWER drives off (Story 8.3,
/// 2026-06-18 pivot): Initial → Loading (a dim skeleton renewal bar) → Loaded
/// (the renewal line, by expiry) / Error (a compact inline "Try again" rendered
/// in the drawer's `_RenewalSlot` — NOT the full-screen EmpatheticErrorScreen,
/// which would flood the sheet). A Cubit (not a full Bloc) — the only "event"
/// is "(re)load the profile".
sealed class UserProfileState {
  const UserProfileState();
}

final class UserProfileInitial extends UserProfileState {
  const UserProfileInitial();
}

final class UserProfileLoading extends UserProfileState {
  const UserProfileLoading();
}

final class UserProfileLoaded extends UserProfileState {
  final UserProfile profile;
  const UserProfileLoaded(this.profile);
}

/// `code` is an `ApiException` code ('NETWORK_ERROR' / 'SERVER_ERROR' / …). The
/// drawer renders one compact inline "Couldn't load your details." + "Try
/// again" for every code; `retryCount` is retained (parity with other error
/// surfaces) but the drawer does not branch its copy on it.
final class UserProfileError extends UserProfileState {
  final String code;
  final int retryCount;
  const UserProfileError(this.code, {this.retryCount = 0});
}

class UserProfileCubit extends Cubit<UserProfileState> {
  final UserRepository _repository;
  int _retryCount = 0;

  UserProfileCubit(this._repository) : super(const UserProfileInitial());

  /// (Re)fetch the profile. Drives Loading → Loaded / Error. Increments the
  /// retry counter on each consecutive failure (reset on success) so the error
  /// screen can escalate its copy.
  Future<void> load() async {
    emit(const UserProfileLoading());
    try {
      final profile = await _repository.getProfile();
      _retryCount = 0;
      emit(UserProfileLoaded(profile));
    } on ApiException catch (e) {
      _retryCount++;
      emit(UserProfileError(e.code, retryCount: _retryCount));
    } catch (_) {
      _retryCount++;
      emit(UserProfileError('UNKNOWN_ERROR', retryCount: _retryCount));
    }
  }
}
