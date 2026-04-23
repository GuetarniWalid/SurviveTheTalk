import 'package:bloc_test/bloc_test.dart';
import 'package:client/app/app.dart';
import 'package:client/core/onboarding/consent_storage.dart';
import 'package:client/features/auth/bloc/auth_bloc.dart';
import 'package:client/features/auth/bloc/auth_event.dart';
import 'package:client/features/auth/bloc/auth_state.dart';
import 'package:client/features/onboarding/bloc/onboarding_bloc.dart';
import 'package:client/features/onboarding/bloc/onboarding_event.dart';
import 'package:client/features/onboarding/bloc/onboarding_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockAuthBloc extends MockBloc<AuthEvent, AuthState>
    implements AuthBloc {}

class MockOnboardingBloc extends MockBloc<OnboardingEvent, OnboardingState>
    implements OnboardingBloc {}

class MockConsentStorage extends Mock implements ConsentStorage {}

void main() {
  late MockAuthBloc mockAuthBloc;
  late MockOnboardingBloc mockOnboardingBloc;
  late MockConsentStorage mockConsentStorage;

  setUpAll(() {
    registerFallbackValue(CheckAuthStatusEvent());
    registerFallbackValue(const CheckOnboardingStatusEvent());
  });

  setUp(() {
    mockAuthBloc = MockAuthBloc();
    mockOnboardingBloc = MockOnboardingBloc();
    mockConsentStorage = MockConsentStorage();
    when(() => mockConsentStorage.preload()).thenAnswer((_) async {});
    // Default: all onboarding gates satisfied unless a test overrides them.
    // Safer than forcing each test to stub every getter — the redirect
    // logic short-circuits at the first missing gate anyway.
    when(() => mockConsentStorage.hasConsentSync).thenReturn(true);
    when(() => mockConsentStorage.hasMicPermissionSync).thenReturn(true);
    when(() => mockConsentStorage.hasSeenFirstCallSync).thenReturn(true);
  });

  testWidgets('App renders email entry screen when not authenticated',
      (tester) async {
    when(() => mockAuthBloc.state).thenReturn(AuthInitial());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthInitial()),
      initialState: AuthInitial(),
    );
    when(() => mockOnboardingBloc.state).thenReturn(const OnboardingInitial());
    whenListen(
      mockOnboardingBloc,
      const Stream<OnboardingState>.empty(),
      initialState: const OnboardingInitial(),
    );

    await tester.pumpWidget(App(
      authBloc: mockAuthBloc,
      onboardingBloc: mockOnboardingBloc,
      consentStorage: mockConsentStorage,
    ));
    await tester.pumpAndSettle();

    expect(find.byType(MaterialApp), findsOneWidget);
    // When unauthenticated, should redirect to login and show email field
    expect(find.text('Survive\nThe Talk'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'App renders scenario list when returning user is authenticated with consent + mic',
      (tester) async {
    when(() => mockAuthBloc.state).thenReturn(AuthAuthenticated());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthAuthenticated()),
      initialState: AuthAuthenticated(),
    );
    when(() => mockOnboardingBloc.state).thenReturn(const OnboardingComplete());
    whenListen(
      mockOnboardingBloc,
      const Stream<OnboardingState>.empty(),
      initialState: const OnboardingComplete(),
    );
    when(() => mockConsentStorage.hasConsentSync).thenReturn(true);
    when(() => mockConsentStorage.hasMicPermissionSync).thenReturn(true);

    await tester.pumpWidget(App(
      authBloc: mockAuthBloc,
      onboardingBloc: mockOnboardingBloc,
      consentStorage: mockConsentStorage,
    ));
    await tester.pumpAndSettle();

    expect(find.byType(MaterialApp), findsOneWidget);
    // AC6: returning user skips auth and consent, lands on root
    expect(find.text('Scenario List — Story 5.2'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'App redirects authenticated user without consent to consent screen',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1200));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    when(() => mockAuthBloc.state).thenReturn(AuthAuthenticated());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthAuthenticated()),
      initialState: AuthAuthenticated(),
    );
    when(() => mockOnboardingBloc.state).thenReturn(const ConsentRequired());
    whenListen(
      mockOnboardingBloc,
      const Stream<OnboardingState>.empty(),
      initialState: const ConsentRequired(),
    );
    when(() => mockConsentStorage.hasConsentSync).thenReturn(false);
    when(() => mockConsentStorage.hasMicPermissionSync).thenReturn(false);

    await tester.pumpWidget(App(
      authBloc: mockAuthBloc,
      onboardingBloc: mockOnboardingBloc,
      consentStorage: mockConsentStorage,
    ));
    await tester.pumpAndSettle();

    // Should show consent screen content
    expect(find.text('BRUTAL.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'App redirects authenticated user with consent but no mic to mic permission screen',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1200));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    when(() => mockAuthBloc.state).thenReturn(AuthAuthenticated());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthAuthenticated()),
      initialState: AuthAuthenticated(),
    );
    when(() => mockOnboardingBloc.state).thenReturn(const MicRequired());
    whenListen(
      mockOnboardingBloc,
      const Stream<OnboardingState>.empty(),
      initialState: const MicRequired(),
    );
    when(() => mockConsentStorage.hasConsentSync).thenReturn(true);
    when(() => mockConsentStorage.hasMicPermissionSync).thenReturn(false);

    await tester.pumpWidget(App(
      authBloc: mockAuthBloc,
      onboardingBloc: mockOnboardingBloc,
      consentStorage: mockConsentStorage,
    ));
    await tester.pumpAndSettle();

    // Should be on mic permission screen (shows design with CTA button)
    expect(find.text('Allow microphone'), findsOneWidget);
    expect(find.text('BRUTAL.'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'App redirects authenticated user who has not seen first call to /incoming-call',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1200));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    when(() => mockAuthBloc.state).thenReturn(AuthAuthenticated());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthAuthenticated()),
      initialState: AuthAuthenticated(),
    );
    when(() => mockOnboardingBloc.state).thenReturn(const OnboardingComplete());
    whenListen(
      mockOnboardingBloc,
      const Stream<OnboardingState>.empty(),
      initialState: const OnboardingComplete(),
    );
    when(() => mockConsentStorage.hasConsentSync).thenReturn(true);
    when(() => mockConsentStorage.hasMicPermissionSync).thenReturn(true);
    when(() => mockConsentStorage.hasSeenFirstCallSync).thenReturn(false);

    await tester.pumpWidget(App(
      authBloc: mockAuthBloc,
      onboardingBloc: mockOnboardingBloc,
      consentStorage: mockConsentStorage,
    ));
    // `pump()` (not pumpAndSettle) because the incoming call screen has a
    // continuously-ticking `_AnimatedCallingText` Timer (and Rive animation)
    // that never settles.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));

    // AC5: should land on the incoming call screen (Tina's name is visible).
    expect(find.text('Tina'), findsOneWidget);
    expect(find.text('Scenario List — Story 5.2'), findsNothing);
  });

  testWidgets(
      'App stays at root for authenticated user who already saw first call',
      (tester) async {
    when(() => mockAuthBloc.state).thenReturn(AuthAuthenticated());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthAuthenticated()),
      initialState: AuthAuthenticated(),
    );
    when(() => mockOnboardingBloc.state).thenReturn(const OnboardingComplete());
    whenListen(
      mockOnboardingBloc,
      const Stream<OnboardingState>.empty(),
      initialState: const OnboardingComplete(),
    );
    when(() => mockConsentStorage.hasConsentSync).thenReturn(true);
    when(() => mockConsentStorage.hasMicPermissionSync).thenReturn(true);
    when(() => mockConsentStorage.hasSeenFirstCallSync).thenReturn(true);

    await tester.pumpWidget(App(
      authBloc: mockAuthBloc,
      onboardingBloc: mockOnboardingBloc,
      consentStorage: mockConsentStorage,
    ));
    await tester.pumpAndSettle();

    expect(find.text('Scenario List — Story 5.2'), findsOneWidget);
    expect(find.text('Tina'), findsNothing);
  });

  testWidgets('App survives textScaler 1.5 (dynamic type)', (tester) async {
    when(() => mockAuthBloc.state).thenReturn(AuthInitial());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthInitial()),
      initialState: AuthInitial(),
    );
    when(() => mockOnboardingBloc.state).thenReturn(const OnboardingInitial());
    whenListen(
      mockOnboardingBloc,
      const Stream<OnboardingState>.empty(),
      initialState: const OnboardingInitial(),
    );

    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.5)),
        child: App(
          authBloc: mockAuthBloc,
          onboardingBloc: mockOnboardingBloc,
          consentStorage: mockConsentStorage,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Survive\nThe Talk'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
