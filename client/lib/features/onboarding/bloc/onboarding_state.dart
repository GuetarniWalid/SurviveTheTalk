sealed class OnboardingState {
  const OnboardingState();
}

final class OnboardingInitial extends OnboardingState {
  const OnboardingInitial();
}

final class ConsentRequired extends OnboardingState {
  const ConsentRequired();
}

final class ConsentAccepting extends OnboardingState {
  const ConsentAccepting();
}

final class ConsentAccepted extends OnboardingState {
  const ConsentAccepted();
}

final class MicRequired extends OnboardingState {
  const MicRequired();
}

final class MicPermissionRequested extends OnboardingState {
  const MicPermissionRequested();
}

final class MicGranted extends OnboardingState {
  const MicGranted();
}

final class MicDenied extends OnboardingState {
  const MicDenied();
}

final class OnboardingComplete extends OnboardingState {
  const OnboardingComplete();
}

final class OnboardingError extends OnboardingState {
  final String message;
  const OnboardingError(this.message);
}
