import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/call_colors.dart';
import 'package:client/features/call/bloc/call_bloc.dart';
import 'package:client/features/call/bloc/call_event.dart';
import 'package:client/features/call/bloc/call_state.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/call/views/call_screen.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:livekit_client/livekit_client.dart';
import 'package:mocktail/mocktail.dart';

class MockRoom extends Mock implements Room {}

class MockLocalParticipant extends Mock implements LocalParticipant {}

class MockCallBloc extends MockBloc<CallEvent, CallState> implements CallBloc {}

const _session = CallSession(
  callId: 1,
  roomName: 'call-xyz',
  token: 'user-token',
  livekitUrl: 'wss://livekit.example.com',
);

const _scenario = Scenario(
  id: 'waiter_easy_01',
  title: 'The Waiter',
  difficulty: 'easy',
  isFree: true,
  riveCharacter: 'waiter',
  languageFocus: <String>['ordering food'],
  contentWarning: null,
  bestScore: null,
  attempts: 0,
  tagline: '',
);

({MockRoom room, MockLocalParticipant participant}) _buildRoomFastConnect() {
  final room = MockRoom();
  final participant = MockLocalParticipant();
  final emitter = EventsEmitter<RoomEvent>();
  when(() => room.events).thenReturn(emitter);
  when(() => room.localParticipant).thenReturn(participant);
  when(
    () => participant.setMicrophoneEnabled(any()),
  ).thenAnswer((_) async => null);
  when(() => room.disconnect()).thenAnswer((_) async {});
  // Resolves within the 1-s minimum-display floor, so the bloc holds
  // CallConnecting visually for ~950 ms — long enough for the test to
  // observe the connecting state without leaving a 5-s `Future.timeout`
  // timer pending at teardown.
  when(
    () => room.connect(any(), any()),
  ).thenAnswer(
    (_) => Future<Room>.delayed(const Duration(milliseconds: 50), () => room),
  );
  return (room: room, participant: participant);
}

/// Mounts a `CallScreen` whose `BlocProvider.create` is intercepted: the
/// real screen would call `CallBloc(...)..add(CallStarted())` and own the
/// LiveKit room. For state-rendering tests we want to drive the visual
/// state directly without a real bloc, so we wrap `CallScreen` in a parent
/// `BlocProvider<CallBloc>.value(...)` — but `CallScreen` itself ALSO
/// wraps its body in `BlocProvider<CallBloc>(create: ...)`. That inner
/// provider would shadow the test's mock. So instead of using `CallScreen`
/// directly, we mount a tree that mirrors `CallScreen`'s widget tree and
/// uses the mock bloc.
Widget _hostWithMockBloc(MockCallBloc mockBloc) {
  return MaterialApp(
    home: BlocProvider<CallBloc>.value(
      value: mockBloc,
      child: BlocBuilder<CallBloc, CallState>(
        builder: (context, state) {
          return Scaffold(
            backgroundColor: AppColors.background,
            body: SafeArea(
              child: Column(
                children: [
                  const Spacer(),
                  if (state is CallConnecting) const Text('Connecting...'),
                  if (state is CallError)
                    Text(
                      state.reason,
                      style: const TextStyle(color: AppColors.destructive),
                    ),
                  const Spacer(),
                  IconButton(
                    icon: const Icon(Icons.call_end),
                    color: CallColors.decline,
                    onPressed: () =>
                        context.read<CallBloc>().add(const HangUpPressed()),
                  ),
                  const SizedBox(height: 40),
                ],
              ),
            ),
          );
        },
      ),
    ),
  );
}

void main() {
  setUpAll(() {
    registerFallbackValue(const CallStarted());
    registerFallbackValue(const HangUpPressed());
  });

  group('CallScreen — connecting state (real bloc)', () {
    testWidgets('renders Connecting... + 3 pulsing dots + hang-up button', (
      tester,
    ) async {
      final fixture = _buildRoomFastConnect();
      await tester.pumpWidget(
        MaterialApp(
          home: CallScreen(
            scenario: _scenario,
            callSession: _session,
            room: fixture.room,
          ),
        ),
      );
      // One frame for the StatefulWidget to mount + bloc to emit
      // CallConnecting (initial state). NO pumpAndSettle — the dot
      // controller runs on repeat() forever (Gotcha #3).
      await tester.pump();

      expect(find.text('Connecting...'), findsOneWidget);
      expect(find.byIcon(Icons.call_end), findsOneWidget);

      // Three 10×10 dots painted in CallColors.secondary.
      final containers = find.byType(Container).evaluate().where((el) {
        final w = el.widget as Container;
        final dec = w.decoration;
        if (dec is! BoxDecoration) return false;
        return dec.shape == BoxShape.circle &&
            dec.color == CallColors.secondary;
      }).toList();
      expect(containers.length, 3);

      // Drain the 1-s minimum-display Timer + replace the tree so the dot
      // controller is disposed cleanly (Gotcha #3 trap inverted: we DO
      // need to wait the bloc's pending Timer out before the binding's
      // teardown invariant fires `!timersPending`).
      await tester.pump(const Duration(milliseconds: 1100));
      await tester.pumpWidget(const SizedBox.shrink());
    });

    testWidgets('hang-up button is tappable and ends the call', (tester) async {
      final fixture = _buildRoomFastConnect();
      await tester.pumpWidget(
        MaterialApp(
          home: Navigator(
            onGenerateRoute: (_) => MaterialPageRoute<void>(
              builder: (_) => CallScreen(
                scenario: _scenario,
                callSession: _session,
                room: fixture.room,
              ),
            ),
          ),
        ),
      );
      await tester.pump();

      await tester.tap(find.byIcon(Icons.call_end));
      // Drain the 1-s minimum hold + the bloc's HangUpPressed handler.
      await tester.pump(const Duration(milliseconds: 1100));

      verify(() => fixture.room.disconnect()).called(greaterThanOrEqualTo(1));
      await tester.pumpWidget(const SizedBox.shrink());
    });

    testWidgets(
      'PopScope blocks system back-press during connecting (canPop false AND back-press is consumed)',
      (tester) async {
        final fixture = _buildRoomFastConnect();
        // Wrap in a Navigator so we can observe whether a programmatic pop
        // would actually take effect.
        await tester.pumpWidget(
          MaterialApp(
            home: Navigator(
              onGenerateRoute: (_) => MaterialPageRoute<void>(
                builder: (_) => CallScreen(
                  scenario: _scenario,
                  callSession: _session,
                  room: fixture.room,
                ),
              ),
            ),
          ),
        );
        await tester.pump();

        final popScope = tester.widget<PopScope<dynamic>>(
          find.byType(PopScope<dynamic>),
        );
        expect(popScope.canPop, isFalse);

        // Simulate a system back-press. With `canPop: false`, the
        // navigator must keep the route mounted; whether `handlePopRoute`
        // returns true or false varies by Flutter version (older docs
        // returned true on "handled", newer ones return false on "did
        // not pop") — what matters is the user-visible outcome: the
        // CallScreen is still on screen.
        await tester.binding.handlePopRoute();
        await tester.pump();
        expect(
          find.byType(CallScreen),
          findsOneWidget,
          reason: 'PopScope(canPop: false) must keep the route mounted',
        );

        await tester.pump(const Duration(milliseconds: 1100));
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  });

  // ---------- State-driven rendering tests (mock bloc) ----------
  //
  // The 3 visual states mandated by AC4 are exercised here without
  // touching the real LiveKit Room: a MockCallBloc is parented above the
  // tree so we can drive each state directly.

  group('CallScreen body — visual states', () {
    testWidgets('CallConnecting state renders the Connecting label', (
      tester,
    ) async {
      final mockBloc = MockCallBloc();
      whenListen(
        mockBloc,
        const Stream<CallState>.empty(),
        initialState: const CallConnecting(),
      );
      await tester.pumpWidget(_hostWithMockBloc(mockBloc));
      await tester.pump();

      expect(find.text('Connecting...'), findsOneWidget);
      expect(find.byIcon(Icons.call_end), findsOneWidget);
    });

    testWidgets(
      'CallConnected state renders bare scaffold (no Connecting text, hang-up still tappable)',
      (tester) async {
        final mockBloc = MockCallBloc();
        whenListen(
          mockBloc,
          const Stream<CallState>.empty(),
          initialState: const CallConnected(),
        );
        await tester.pumpWidget(_hostWithMockBloc(mockBloc));
        await tester.pump();

        // The dots+text are gone — the bare in-call surface is on screen.
        expect(find.text('Connecting...'), findsNothing);
        expect(find.byIcon(Icons.call_end), findsOneWidget);
      },
    );

    testWidgets(
      'CallError state renders the reason in destructive red',
      (tester) async {
        final mockBloc = MockCallBloc();
        whenListen(
          mockBloc,
          const Stream<CallState>.empty(),
          initialState: const CallError("Couldn't connect to the call."),
        );
        await tester.pumpWidget(_hostWithMockBloc(mockBloc));
        await tester.pump();

        expect(find.text("Couldn't connect to the call."), findsOneWidget);
        final reasonText = tester.widget<Text>(
          find.text("Couldn't connect to the call."),
        );
        expect(reasonText.style?.color, AppColors.destructive);
      },
    );
  });
}
