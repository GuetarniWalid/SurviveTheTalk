sealed class OnboardingEvent {
  const OnboardingEvent();
}

final class CheckOnboardingStatusEvent extends OnboardingEvent {
  const CheckOnboardingStatusEvent();
}

final class AcceptConsentEvent extends OnboardingEvent {
  const AcceptConsentEvent();
}

final class RequestMicPermissionEvent extends OnboardingEvent {
  const RequestMicPermissionEvent();
}

final class OpenAppSettingsEvent extends OnboardingEvent {
  const OpenAppSettingsEvent();
}

final class RecheckMicPermissionEvent extends OnboardingEvent {
  const RecheckMicPermissionEvent();
}
