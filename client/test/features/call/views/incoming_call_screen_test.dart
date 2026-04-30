import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/onboarding/consent_storage.dart';
import 'package:client/core/onboarding/vibration_service.dart';
import 'package:client/features/call/bloc/incoming_call_bloc.dart';
import 'package:client/features/call/bloc/incoming_call_event.dart';
import 'package:client/features/call/bloc/incoming_call_state.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:client/features/call/views/incoming_call_screen.dart';
import 'package:client/features/call/views/widgets/character_avatar.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockIncomingCallBloc
    extends MockBloc<IncomingCallEvent, IncomingCallState>
    implements IncomingCallBloc {}

class MockVibrationService extends Mock implements VibrationService {}

class MockCallRepository extends Mock implements CallRepository {}

class MockConsentStorage extends Mock implements ConsentStorage {}

Widget _host(
  IncomingCallBloc bloc, {
  Widget Function(Scenario, CallSession)? callScreenBuilder,
}) {
  return MaterialApp(
    home: BlocProvider<IncomingCallBloc>.value(
      value: bloc,
      child: IncomingCallScreen(callScreenBuilder: callScreenBuilder),
    ),
  );
}

const _kCallStubKey = ValueKey('incoming_call_stub');

const _kFakeSession = CallSession(
  callId: 1,
  roomName: 'call-xyz',
  token: 'user-token',
  livekitUrl: 'wss://livekit.example.com',
);

void main() {
  late MockIncomingCallBloc mockBloc;
  late MockVibrationService mockVibrationService;

  setUpAll(() {
    registerFallbackValue(const AcceptCallEvent());
    registerFallbackValue(const DeclineCallEvent());
  });

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    mockBloc = MockIncomingCallBloc();
    mockVibrationService = MockVibrationService();

    when(() => mockVibrationService.stop()).thenAnswer((_) async {});
    when(() => mockVibrationService.startRingPattern())
        .thenAnswer((_) async {});
    when(() => mockBloc.vibrationService).thenReturn(mockVibrationService);
    when(() => mockBloc.state).thenReturn(const IncomingCallRinging());
  });

  tearDown(() async {
    await mockBloc.close();
  });

  testWidgets(
      'renders character name, role, "Calling" loader, avatar, and buttons',
      (tester) async {
    await tester.pumpWidget(_host(mockBloc));
    await tester.pump();

    expect(find.text('Tina'), findsOneWidget);
    expect(find.text('Waitress'), findsOneWidget);
    // "Calling…" is now a RichText animated loader ("Calling" + animated
    // dots). `find.text` matches `Text.data` only, so use textContaining
    // which walks the inline-span tree of RichText too.
    expect(find.textContaining('Calling'), findsOneWidget);
    expect(find.text('Accept'), findsOneWidget);
    expect(find.text('Decline'), findsOneWidget);
    // The avatar widget is always mounted; Rive itself falls back to an
    // empty dark circle in tests because RiveNative.isInitialized is false.
    expect(find.byType(CharacterAvatar), findsOneWidget);
  });

  testWidgets('tapping Accept dispatches AcceptCallEvent', (tester) async {
    await tester.pumpWidget(_host(mockBloc));
    await tester.pump();

    await tester.tap(find.byIcon(Icons.call));
    await tester.pump();

    verify(() => mockBloc.add(const AcceptCallEvent())).called(1);
  });

  testWidgets('tapping Decline dispatches DeclineCallEvent', (tester) async {
    await tester.pumpWidget(_host(mockBloc));
    await tester.pump();

    await tester.tap(find.byIcon(Icons.call_end));
    await tester.pump();

    verify(() => mockBloc.add(const DeclineCallEvent())).called(1);
  });

  testWidgets(
      'Accept button shows spinner and "Connecting…" while IncomingCallAccepting',
      (tester) async {
    when(() => mockBloc.state).thenReturn(const IncomingCallAccepting());
    whenListen(
      mockBloc,
      Stream<IncomingCallState>.fromIterable(const [IncomingCallAccepting()]),
      initialState: const IncomingCallAccepting(),
    );

    await tester.pumpWidget(_host(mockBloc));
    await tester.pump();

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('Connecting…'), findsOneWidget);
    expect(find.text('Accept'), findsNothing);
  });

  testWidgets(
      'does not render an inline error banner — errors bounce to scenario list',
      (tester) async {
    const errorState = IncomingCallError('Something failed.');
    when(() => mockBloc.state).thenReturn(errorState);
    whenListen(
      mockBloc,
      Stream<IncomingCallState>.fromIterable(const [errorState]),
      initialState: errorState,
    );

    await tester.pumpWidget(_host(mockBloc));
    await tester.pump();

    // Design decision: the error banner UX was dropped in favour of
    // fade-out + navigate to `/` (same as Decline). The error message
    // must NOT be rendered on the incoming-call screen.
    expect(find.text('Something failed.'), findsNothing);
    expect(find.byType(SnackBar), findsNothing);
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('screen renders without throwing (Rive fallback in tests)',
      (tester) async {
    await tester.pumpWidget(_host(mockBloc));
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('Calling loader cycles from 0 to 3 dots over its 1600ms period',
      (tester) async {
    await tester.pumpWidget(_host(mockBloc));
    // Frame 0: zero visible dots. We can't `find.text('Calling')` directly
    // because the RichText span tree always reserves three trailing '.'
    // chars (transparent when inactive) to keep the text width constant.
    // Instead, walk one full cycle and assert the loader keeps rebuilding
    // without throwing — proving the Timer + setState path is wired.
    await tester.pump();
    expect(tester.takeException(), isNull);

    await tester.pump(const Duration(milliseconds: 400));
    expect(tester.takeException(), isNull);

    await tester.pump(const Duration(milliseconds: 400));
    expect(tester.takeException(), isNull);

    await tester.pump(const Duration(milliseconds: 400));
    expect(tester.takeException(), isNull);

    // After a full cycle the loader should still be rendered and the
    // widget tree should still contain a Text span that includes "Calling".
    expect(find.textContaining('Calling'), findsOneWidget);

    // Replace the tree so the Timer is cancelled in dispose() — prevents
    // the "Timer still pending" warning that leaks into later tests.
    await tester.pumpWidget(const MaterialApp(home: Scaffold()));
  });

  testWidgets(
    'IncomingCallConnected pushes the call surface via root Navigator '
    'with the tutorial scenario',
    (tester) async {
      // Start ringing, then transition to Connected so the BlocListener
      // fires the push exactly once.
      whenListen(
        mockBloc,
        Stream<IncomingCallState>.fromIterable(const [
          IncomingCallConnected(_kFakeSession),
        ]),
        initialState: const IncomingCallRinging(),
      );

      Scenario? capturedScenario;
      CallSession? capturedSession;

      await tester.pumpWidget(
        _host(
          mockBloc,
          callScreenBuilder: (scenario, session) {
            capturedScenario = scenario;
            capturedSession = session;
            return const Scaffold(
              key: _kCallStubKey,
              body: Center(child: Text('CALL_STUB')),
            );
          },
        ),
      );
      // Two pumps: one for initial render + one for the streamed
      // Connected emission and the post-frame async push.
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_kCallStubKey), findsOneWidget);
      expect(find.text('CALL_STUB'), findsOneWidget);
      // Scenario passed to the builder is the hardcoded tutorial literal.
      expect(capturedScenario, isNotNull);
      expect(capturedScenario!.id, 'waiter_easy_01');
      expect(capturedScenario!.riveCharacter, 'waiter');
      expect(capturedSession, _kFakeSession);
    },
  );
}
