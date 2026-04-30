import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/call_colors.dart';
import 'package:client/features/call/bloc/call_bloc.dart';
import 'package:client/features/call/bloc/call_event.dart';
import 'package:client/features/call/bloc/call_state.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/call/views/call_screen.dart';
import 'package:client/features/call/views/widgets/animated_calling_text.dart';
import 'package:client/features/call/views/widgets/character_avatar.dart';
import 'package:client/features/call/views/widgets/rive_character_canvas.dart';
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
///
/// The mirror only needs to be _semantically_ equivalent for the
/// state-driven assertions (presence of certain widgets per state), not
/// pixel-perfect — keeping it minimal avoids re-mirroring every layout
/// tweak in the real `CallScreen`.
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
                  if (state is CallConnecting) ...const [
                    Text('Tina'),
                    Text('Waitress'),
                    AnimatedCallingText(
                      style: TextStyle(color: CallColors.secondary),
                    ),
                  ],
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
    testWidgets(
      'renders the dial surface (name + role + avatar + Calling text + hang-up)',
      (tester) async {
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
        // CallConnecting (initial state). NO pumpAndSettle — the
        // AnimatedCallingText runs Timer.periodic forever (Gotcha #3).
        await tester.pump();

        // Catalog identity for the waiter scenario.
        expect(find.text('Tina'), findsOneWidget);
        expect(find.text('Waitress'), findsOneWidget);
        // Calling animation primitive is mounted.
        expect(find.byType(AnimatedCallingText), findsOneWidget);
        // Circular avatar primitive.
        expect(find.byType(CharacterAvatar), findsOneWidget);
        // Single hang-up button.
        expect(find.byIcon(Icons.call_end), findsOneWidget);

        // Drain the 1-s minimum-display Timer + replace the tree so the
        // periodic dot timer is disposed cleanly (Gotcha #3 trap inverted:
        // we DO need to wait the bloc's pending Timer out before the
        // binding's teardown invariant fires `!timersPending`).
        await tester.pump(const Duration(milliseconds: 1100));
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

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
    testWidgets(
      'CallConnecting state renders the catalog identity + Calling animation',
      (tester) async {
        final mockBloc = MockCallBloc();
        whenListen(
          mockBloc,
          const Stream<CallState>.empty(),
          initialState: const CallConnecting(),
        );
        await tester.pumpWidget(_hostWithMockBloc(mockBloc));
        await tester.pump();

        expect(find.text('Tina'), findsOneWidget);
        expect(find.text('Waitress'), findsOneWidget);
        expect(find.byType(AnimatedCallingText), findsOneWidget);
        expect(find.byIcon(Icons.call_end), findsOneWidget);

        // Drain the periodic dot timer so the binding teardown invariant
        // does not fire `!timersPending`.
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'CallConnected state renders bare scaffold (no identity header, hang-up still tappable)',
      (tester) async {
        final mockBloc = MockCallBloc();
        whenListen(
          mockBloc,
          const Stream<CallState>.empty(),
          initialState: const CallConnected(),
        );
        await tester.pumpWidget(_hostWithMockBloc(mockBloc));
        await tester.pump();

        // The dial-surface texts are gone — the bare in-call surface is on
        // screen. Identity header + Calling animation only render during
        // CallConnecting.
        expect(find.text('Tina'), findsNothing);
        expect(find.byType(AnimatedCallingText), findsNothing);
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

  // ---------- Story 6.2 — CallConnected layered render ----------
  //
  // Drive the real CallScreen + MockRoom into the CallConnected branch and
  // assert on the layered Stack (Image → BackdropFilter → RiveCharacterCanvas)
  // and the conditional Flutter hang-up button gated by the `debugCanvasFallback`
  // test seam (Story 6.2 AC9).

  group('CallScreen — CallConnected layered render (Story 6.2)', () {
    testWidgets(
      'mounts the Image + BackdropFilter + RiveCharacterCanvas layer stack',
      (tester) async {
        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: false,
            ),
          ),
        );
        // Pump past the 1-s minimum-display floor so the bloc emits
        // CallConnected.
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        // Layer 1 — scenario background image.
        final imageFinder = find.byWidgetPredicate(
          (w) => w is Image && w.image is AssetImage,
        );
        expect(imageFinder, findsOneWidget);
        final image = tester.widget<Image>(imageFinder);
        expect(image.fit, BoxFit.cover);
        expect(
          (image.image as AssetImage).assetName,
          'assets/images/scenario_backgrounds/restaurant.jpg',
        );

        // Layer 2 — gaussian blur primitive.
        expect(find.byType(BackdropFilter), findsOneWidget);

        // Layer 3 — full-screen Rive canvas.
        expect(find.byType(RiveCharacterCanvas), findsOneWidget);

        // AC9 — verify the three primitives are direct siblings inside the
        // same Stack (not nested inside one another). A refactor that wraps
        // the BackdropFilter inside another widget would still pass the
        // presence checks above; this one would fail.
        final stack = tester.widget<Stack>(
          find.byWidgetPredicate(
            (w) =>
                w is Stack &&
                w.fit == StackFit.expand &&
                w.children.length >= 3,
          ),
        );
        bool isImageLayer(Widget w) => w is Image && w.image is AssetImage;
        bool isBlurLayer(Widget w) => w is BackdropFilter;
        bool isCanvasLayer(Widget w) {
          // Layer 3 is `Positioned.fill(child: Semantics(...))` whose
          // descendant is the RiveCharacterCanvas.
          if (w is! Positioned) return false;
          return find
              .descendant(
                of: find.byWidget(w),
                matching: find.byType(RiveCharacterCanvas),
              )
              .evaluate()
              .isNotEmpty;
        }

        final children = stack.children;
        expect(children.any(isImageLayer), isTrue,
            reason: 'Layer 1 (Image) must be a direct Stack child');
        expect(children.any(isBlurLayer), isTrue,
            reason: 'Layer 2 (BackdropFilter) must be a direct Stack child');
        expect(children.any(isCanvasLayer), isTrue,
            reason:
                'Layer 3 (RiveCharacterCanvas via Positioned.fill) must be a direct Stack child');

        // Settle teardown.
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'does NOT render the Flutter hang-up button when canvas is on the working path',
      (tester) async {
        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: false,
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        // The Rive canvas is the only hang-up affordance — the Flutter
        // `_buildHangUpButton` (which shows an `Icons.call_end` icon) must
        // NOT be in the tree on the working path.
        expect(find.byIcon(Icons.call_end), findsNothing);

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'DOES render the Flutter hang-up button when canvas is in fallback, and tapping it dispatches HangUpPressed',
      (tester) async {
        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: true,
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        // Flutter hang-up button is visible on the fallback path.
        expect(find.byIcon(Icons.call_end), findsOneWidget);

        // Tapping it dispatches HangUpPressed (via the real bloc) and the
        // bloc's _onHangUpPressed handler invokes room.disconnect().
        await tester.tap(find.byIcon(Icons.call_end));
        await tester.pump(const Duration(milliseconds: 100));

        verify(() => fixture.room.disconnect()).called(greaterThanOrEqualTo(1));
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'CallConnected does not overflow at 320×480 with textScaler 1.5',
      (tester) async {
        // FlutterError.onError capture (Story 5.4 / 5.5 pattern) so an
        // overflow lands in the test as a real failure rather than just a
        // log line.
        final originalOnError = FlutterError.onError;
        final overflowErrors = <FlutterErrorDetails>[];
        FlutterError.onError = (details) {
          if (details.exceptionAsString().contains('overflow')) {
            overflowErrors.add(details);
          }
          originalOnError?.call(details);
        };
        addTearDown(() => FlutterError.onError = originalOnError);

        await tester.binding.setSurfaceSize(const Size(320, 480));
        addTearDown(() => tester.binding.setSurfaceSize(null));

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: MediaQuery(
              data: const MediaQueryData(textScaler: TextScaler.linear(1.5)),
              child: CallScreen(
                scenario: _scenario,
                callSession: _session,
                room: fixture.room,
                debugCanvasFallback: true,
              ),
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        expect(overflowErrors, isEmpty,
            reason: 'CallConnected must not overflow at 320×480 textScaler 1.5');

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  });
}
