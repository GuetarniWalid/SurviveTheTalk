import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../../core/onboarding/consent_storage.dart';
import '../../../core/onboarding/permission_service.dart';
import 'onboarding_event.dart';
import 'onboarding_state.dart';

class OnboardingBloc extends Bloc<OnboardingEvent, OnboardingState> {
  final ConsentStorage _consentStorage;
  final PermissionService _permissionService;

  OnboardingBloc({
    required ConsentStorage consentStorage,
    required PermissionService permissionService,
  })  : _consentStorage = consentStorage,
        _permissionService = permissionService,
        super(const OnboardingInitial()) {
    on<CheckOnboardingStatusEvent>(_onCheckStatus);
    on<AcceptConsentEvent>(_onAcceptConsent);
    on<RequestMicPermissionEvent>(_onRequestMicPermission);
    on<OpenAppSettingsEvent>(_onOpenAppSettings);
    on<RecheckMicPermissionEvent>(_onRecheckMicPermission);
  }

  Future<void> _onCheckStatus(
    CheckOnboardingStatusEvent event,
    Emitter<OnboardingState> emit,
  ) async {
    try {
      final hasConsent = await _consentStorage.hasConsent();
      if (!hasConsent) {
        emit(const ConsentRequired());
        return;
      }

      // Consent exists — check mic permission
      final micStatus = await _permissionService.checkMicPermission();
      if (micStatus.isGranted) {
        await _consentStorage.saveMicPermission(true);
        emit(const OnboardingComplete());
      } else {
        await _consentStorage.saveMicPermission(false);
        emit(const MicRequired());
      }
    } catch (e) {
      emit(const OnboardingError(
          'Onboarding check failed. Please restart the app.'));
    }
  }

  Future<void> _onAcceptConsent(
    AcceptConsentEvent event,
    Emitter<OnboardingState> emit,
  ) async {
    emit(const ConsentAccepting());
    try {
      await _consentStorage.saveConsent();
      emit(const ConsentAccepted());
    } catch (e) {
      emit(const OnboardingError('Could not save consent. Please try again.'));
    }
  }

  Future<void> _onRequestMicPermission(
    RequestMicPermissionEvent event,
    Emitter<OnboardingState> emit,
  ) async {
    emit(const MicPermissionRequested());

    try {
      final status = await _permissionService.checkMicPermission();
      if (status.isGranted) {
        await _consentStorage.saveMicPermission(true);
        emit(const MicGranted());
        return;
      }
      if (status.isPermanentlyDenied) {
        emit(const MicDenied());
        return;
      }

      final result = await _permissionService.requestMicPermission();
      if (result.isGranted) {
        await _consentStorage.saveMicPermission(true);
        emit(const MicGranted());
      } else {
        emit(const MicDenied());
      }
    } catch (e) {
      emit(const MicDenied());
    }
  }

  Future<void> _onOpenAppSettings(
    OpenAppSettingsEvent event,
    Emitter<OnboardingState> emit,
  ) async {
    await _permissionService.openSettings();
  }

  Future<void> _onRecheckMicPermission(
    RecheckMicPermissionEvent event,
    Emitter<OnboardingState> emit,
  ) async {
    // Emit intermediate state so BlocListener detects the transition
    // when previous state was already MicDenied (const == const is true,
    // so MicDenied → MicDenied would be silently skipped).
    emit(const MicPermissionRequested());
    final status = await _permissionService.checkMicPermission();
    if (status.isGranted) {
      await _consentStorage.saveMicPermission(true);
      emit(const MicGranted());
    } else {
      emit(const MicDenied());
    }
  }
}
