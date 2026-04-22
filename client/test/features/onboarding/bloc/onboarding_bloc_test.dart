import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/onboarding/consent_storage.dart';
import 'package:client/core/onboarding/permission_service.dart';
import 'package:client/features/onboarding/bloc/onboarding_bloc.dart';
import 'package:client/features/onboarding/bloc/onboarding_event.dart';
import 'package:client/features/onboarding/bloc/onboarding_state.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:permission_handler/permission_handler.dart';

class MockConsentStorage extends Mock implements ConsentStorage {}

class MockPermissionService extends Mock implements PermissionService {}

void main() {
  late MockConsentStorage mockConsentStorage;
  late MockPermissionService mockPermissionService;

  setUp(() {
    mockConsentStorage = MockConsentStorage();
    mockPermissionService = MockPermissionService();
  });

  OnboardingBloc buildBloc() => OnboardingBloc(
        consentStorage: mockConsentStorage,
        permissionService: mockPermissionService,
      );

  group('CheckOnboardingStatusEvent', () {
    blocTest<OnboardingBloc, OnboardingState>(
      'emits [ConsentRequired] when no consent exists',
      build: () {
        when(() => mockConsentStorage.hasConsent())
            .thenAnswer((_) async => false);
        return buildBloc();
      },
      act: (bloc) => bloc.add(const CheckOnboardingStatusEvent()),
      expect: () => [isA<ConsentRequired>()],
    );

    blocTest<OnboardingBloc, OnboardingState>(
      'emits [OnboardingComplete] when consent + mic granted',
      build: () {
        when(() => mockConsentStorage.hasConsent())
            .thenAnswer((_) async => true);
        when(() => mockPermissionService.checkMicPermission())
            .thenAnswer((_) async => PermissionStatus.granted);
        when(() => mockConsentStorage.saveMicPermission(true))
            .thenAnswer((_) async {});
        return buildBloc();
      },
      act: (bloc) => bloc.add(const CheckOnboardingStatusEvent()),
      expect: () => [isA<OnboardingComplete>()],
    );

    blocTest<OnboardingBloc, OnboardingState>(
      'emits [MicRequired] when consent exists but mic denied',
      build: () {
        when(() => mockConsentStorage.hasConsent())
            .thenAnswer((_) async => true);
        when(() => mockPermissionService.checkMicPermission())
            .thenAnswer((_) async => PermissionStatus.denied);
        when(() => mockConsentStorage.saveMicPermission(false))
            .thenAnswer((_) async {});
        return buildBloc();
      },
      act: (bloc) => bloc.add(const CheckOnboardingStatusEvent()),
      expect: () => [isA<MicRequired>()],
    );
  });

  group('AcceptConsentEvent', () {
    blocTest<OnboardingBloc, OnboardingState>(
      'emits [ConsentAccepting, ConsentAccepted] on happy path',
      build: () {
        when(() => mockConsentStorage.saveConsent())
            .thenAnswer((_) async {});
        return buildBloc();
      },
      act: (bloc) => bloc.add(const AcceptConsentEvent()),
      expect: () => [
        isA<ConsentAccepting>(),
        isA<ConsentAccepted>(),
      ],
    );

    blocTest<OnboardingBloc, OnboardingState>(
      'emits [ConsentAccepting, OnboardingError] when saveConsent throws',
      build: () {
        when(() => mockConsentStorage.saveConsent())
            .thenThrow(Exception('write failed'));
        return buildBloc();
      },
      act: (bloc) => bloc.add(const AcceptConsentEvent()),
      expect: () => [
        isA<ConsentAccepting>(),
        isA<OnboardingError>(),
      ],
    );
  });

  group('RequestMicPermissionEvent', () {
    blocTest<OnboardingBloc, OnboardingState>(
      'emits [MicPermissionRequested, MicGranted] when already granted',
      build: () {
        when(() => mockPermissionService.checkMicPermission())
            .thenAnswer((_) async => PermissionStatus.granted);
        when(() => mockConsentStorage.saveMicPermission(true))
            .thenAnswer((_) async {});
        return buildBloc();
      },
      act: (bloc) => bloc.add(const RequestMicPermissionEvent()),
      expect: () => [
        isA<MicPermissionRequested>(),
        isA<MicGranted>(),
      ],
    );

    blocTest<OnboardingBloc, OnboardingState>(
      'emits [MicPermissionRequested, MicDenied] when permanently denied',
      build: () {
        when(() => mockPermissionService.checkMicPermission())
            .thenAnswer((_) async => PermissionStatus.permanentlyDenied);
        return buildBloc();
      },
      act: (bloc) => bloc.add(const RequestMicPermissionEvent()),
      expect: () => [
        isA<MicPermissionRequested>(),
        isA<MicDenied>(),
      ],
    );
  });

  group('OpenAppSettingsEvent', () {
    blocTest<OnboardingBloc, OnboardingState>(
      'calls openSettings on permission service',
      build: () {
        when(() => mockPermissionService.openSettings())
            .thenAnswer((_) async => true);
        return buildBloc();
      },
      act: (bloc) => bloc.add(const OpenAppSettingsEvent()),
      expect: () => <OnboardingState>[],
      verify: (_) {
        verify(() => mockPermissionService.openSettings()).called(1);
      },
    );
  });

  group('RecheckMicPermissionEvent', () {
    blocTest<OnboardingBloc, OnboardingState>(
      'emits [MicGranted] when permission now granted',
      build: () {
        when(() => mockPermissionService.checkMicPermission())
            .thenAnswer((_) async => PermissionStatus.granted);
        when(() => mockConsentStorage.saveMicPermission(true))
            .thenAnswer((_) async {});
        return buildBloc();
      },
      act: (bloc) => bloc.add(const RecheckMicPermissionEvent()),
      expect: () => [isA<MicPermissionRequested>(), isA<MicGranted>()],
    );

    blocTest<OnboardingBloc, OnboardingState>(
      'emits [MicPermissionRequested, MicDenied] when still denied',
      build: () {
        when(() => mockPermissionService.checkMicPermission())
            .thenAnswer((_) async => PermissionStatus.denied);
        return buildBloc();
      },
      act: (bloc) => bloc.add(const RecheckMicPermissionEvent()),
      expect: () => [isA<MicPermissionRequested>(), isA<MicDenied>()],
    );
  });
}
