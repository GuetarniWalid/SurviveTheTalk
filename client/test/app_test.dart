import 'package:bloc_test/bloc_test.dart';
import 'package:client/app/app.dart';
import 'package:client/core/onboarding/consent_storage.dart';
import 'package:client/core/services/end_call_retry_service.dart';
import 'package:client/features/auth/bloc/auth_bloc.dart';
import 'package:client/features/auth/bloc/auth_event.dart';
import 'package:client/features/auth/bloc/auth_state.dart';
import 'package:client/features/onboarding/bloc/onboarding_bloc.dart';
import 'package:client/features/onboarding/bloc/onboarding_event.dart';
import 'package:client/features/onboarding/bloc/onboarding_state.dart';
import 'package:client/features/scenarios/bloc/scenarios_bloc.dart';
import 'package:client/features/scenarios/bloc/scenarios_event.dart';
import 'package:client/features/scenarios/bloc/scenarios_state.dart';
import 'package:client/features/scenarios/models/call_usage.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/views/scenario_list_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockAuthBloc extends MockBloc<AuthEvent, AuthState>
    implements AuthBloc {}

class MockOnboardingBloc extends MockBloc<OnboardingEvent, OnboardingState>
    implements OnboardingBloc {}

class MockScenariosBloc extends MockBloc<ScenariosEvent, ScenariosState>
    implements ScenariosBloc {}

class MockConsentStorage extends Mock implements ConsentStorage {}

class MockEndCallRetryService extends Mock implements EndCallRetryService {}

void main() {
  late MockAuthBloc mockAuthBloc;
  late MockOnboardingBloc mockOnboardingBloc;
  late MockScenariosBloc mockScenariosBloc;
  late MockConsentStorage mockConsentStorage;

  setUpAll(() {
    registerFallbackValue(CheckAuthStatusEvent());
    registerFallbackValue(const CheckOnboardingStatusEvent());
    registerFallbackValue(const LoadScenariosEvent());
  });

  setUp(() {
    mockAuthBloc = MockAuthBloc();
    mockOnboardingBloc = MockOnboardingBloc();
    mockScenariosBloc = MockScenariosBloc();
    mockConsentStorage = MockConsentStorage();
    when(() => mockConsentStorage.preload()).thenAnswer((_) async {});
    // Default: all onboarding gates satisfied unless a test overrides them.
    // Safer than forcing each test to stub every getter — the redirect
    // logic short-circuits at the first missing gate anyway.
    when(() => mockConsentStorage.hasConsentSync).thenReturn(true);
    when(() => mockConsentStorage.hasMicPermissionSync).thenReturn(true);
    when(() => mockConsentStorage.hasSeenFirstCallSync).thenReturn(true);
    // Empty list keeps the screen content trivial — these tests assert that
    // the right route renders, not the card contents.
    const emptyLoaded = ScenariosLoaded(
      scenarios: <Scenario>[],
      usage: CallUsage(
        tier: 'free',
        callsRemaining: 3,
        callsPerPeriod: 3,
        period: 'lifetime',
      ),
    );
    when(() => mockScenariosBloc.state).thenReturn(emptyLoaded);
    whenListen(
      mockScenariosBloc,
      const Stream<ScenariosState>.empty(),
      initialState: emptyLoaded,
    );
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
      scenariosBloc: mockScenariosBloc,
    ));
    await tester.pumpAndSettle();

    expect(find.byType(MaterialApp), findsOneWidget);
    // AC6: returning user skips auth and consent, lands on root
    expect(find.byType(ScenarioListScreen), findsOneWidget);
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
    expect(find.byType(ScenarioListScreen), findsNothing);
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
      scenariosBloc: mockScenariosBloc,
    ));
    await tester.pumpAndSettle();

    expect(find.byType(ScenarioListScreen), findsOneWidget);
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

  testWidgets(
    'Story 6.5 Option B (PD3) — AppLifecycleState.resumed triggers '
    'EndCallRetryService.replayAll() so a queue stuck after a missed '
    'connectivity-regain event drains the next time the user '
    'foregrounds the app',
    (tester) async {
      final mockRetryService = MockEndCallRetryService();
      when(() => mockRetryService.replayAll()).thenAnswer((_) async => 0);

      when(() => mockAuthBloc.state).thenReturn(AuthInitial());
      whenListen(
        mockAuthBloc,
        Stream<AuthState>.value(AuthInitial()),
        initialState: AuthInitial(),
      );
      when(
        () => mockOnboardingBloc.state,
      ).thenReturn(const OnboardingInitial());
      whenListen(
        mockOnboardingBloc,
        const Stream<OnboardingState>.empty(),
        initialState: const OnboardingInitial(),
      );

      await tester.pumpWidget(
        App(
          authBloc: mockAuthBloc,
          onboardingBloc: mockOnboardingBloc,
          consentStorage: mockConsentStorage,
          endCallRetryService: mockRetryService,
        ),
      );
      await tester.pumpAndSettle();

      // Initial frame — no resume event yet. Bootstrap is what would
      // normally fire the first replayAll() in production; the App
      // widget only owns the lifecycle-resume trigger.
      verifyNever(() => mockRetryService.replayAll());

      // Simulate the app coming back to foreground. The framework's
      // SystemChannels.lifecycle string is what the platform sends;
      // dispatching it to the binding mirrors a real Android resume
      // event arriving on the platform channel.
      tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.resumed,
      );
      await tester.pump();

      verify(() => mockRetryService.replayAll()).called(1);

      // Hide → resume cycle fires a second drain — every foregrounding
      // is a potential "user just left the metro" moment. Flutter
      // enforces a strict state machine (resumed → inactive → hidden
      // → paused → hidden → inactive → resumed), so we step through
      // each intermediate state.
      tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.inactive,
      );
      tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.hidden,
      );
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.inactive,
      );
      tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.resumed,
      );
      await tester.pump();

      verify(() => mockRetryService.replayAll()).called(1);
    },
  );

  testWidgets(
    'AppLifecycleState.resumed with no EndCallRetryService is a no-op '
    '(legacy widget-test path that omits the service must not crash)',
    (tester) async {
      when(() => mockAuthBloc.state).thenReturn(AuthInitial());
      whenListen(
        mockAuthBloc,
        Stream<AuthState>.value(AuthInitial()),
        initialState: AuthInitial(),
      );
      when(
        () => mockOnboardingBloc.state,
      ).thenReturn(const OnboardingInitial());
      whenListen(
        mockOnboardingBloc,
        const Stream<OnboardingState>.empty(),
        initialState: const OnboardingInitial(),
      );

      await tester.pumpWidget(
        App(
          authBloc: mockAuthBloc,
          onboardingBloc: mockOnboardingBloc,
          consentStorage: mockConsentStorage,
          // endCallRetryService deliberately omitted.
        ),
      );
      await tester.pumpAndSettle();

      tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.resumed,
      );
      await tester.pump();

      expect(tester.takeException(), isNull);
    },
  );
}
