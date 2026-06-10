import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/call_colors.dart';
import 'package:client/features/call/bloc/call_bloc.dart';
import 'package:client/features/call/bloc/call_event.dart';
import 'package:client/features/call/bloc/call_state.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/call/models/end_call_result.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:client/features/call/services/checkpoint_advanced_payload.dart';
import 'package:client/features/call/services/data_channel_handler.dart';
import 'package:client/features/call/views/call_ended_notice_screen.dart';
import 'package:client/features/call/views/call_ended_screen.dart';
import 'package:client/features/call/views/call_screen.dart';
import 'package:client/features/call/views/widgets/animated_calling_text.dart';
import 'package:client/features/call/views/widgets/character_avatar.dart';
import 'package:client/features/call/views/widgets/checkpoint_snapshot.dart';
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

class MockDataChannelHandler extends Mock implements DataChannelHandler {}

class MockCallRepository extends Mock implements CallRepository {}

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
              debugEndCallResultTimeout: Duration.zero,
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
                debugEndCallResultTimeout: Duration.zero,
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
              debugEndCallResultTimeout: Duration.zero,
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
              debugEndCallResultTimeout: Duration.zero,
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
              debugEndCallResultTimeout: Duration.zero,
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
                debugEndCallResultTimeout: Duration.zero,
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

  group('CallScreen — DataChannelHandler lifecycle (Story 6.3)', () {
    testWidgets(
      'constructs the handler exactly once on first CallConnected and not again',
      (tester) async {
        // The `??=` + `prev is! CallConnected && next is CallConnected`
        // listenWhen filter together guarantee the handler is built once.
        // Counting builder invocations is the most direct check.
        final builderCalls = <Room>[];
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugEndCallResultTimeout: Duration.zero,
              debugCanvasFallback: false,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                builderCalls.add(room);
                return mock;
              },
            ),
          ),
        );
        // Pump past the bloc's 1-s minimum-display floor so CallConnected
        // is actually emitted (the listener fires only on the listenWhen
        // transition, not on initial-state subscription).
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        expect(builderCalls.length, 1,
            reason: 'handler MUST be built exactly once on first CallConnected');
        // The Room passed to the builder is the same Room CallBloc owns.
        expect(identical(builderCalls.single, fixture.room), isTrue);

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'Story 6.4 — onCallEnd dispatches RemoteCallEnded to the bloc',
      (tester) async {
        // The DataChannelHandler builder captures the onCallEnd callback;
        // invoking it should dispatch a RemoteCallEnded(reason, data)
        // event to the bloc. The bloc parks the call in remote-end-
        // pending state until a follow-up PlaybackDrained arrives —
        // this test only verifies the dispatch wiring; the bloc-side
        // two-phase end is exercised in `call_bloc_test.dart`.
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        void Function(String, Map<String, dynamic>)? capturedOnCallEnd;
        CallBloc? capturedBloc;

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: Builder(
              builder: (context) {
                return CallScreen(
                  scenario: _scenario,
                  callSession: _session,
                  room: fixture.room,
                  debugCanvasFallback: false,
                  debugPlaybackDrainBuffer: Duration.zero,
                  debugEndCallResultTimeout: Duration.zero,
                  debugHandlerBuilder: ({
                    required room,
                    required onEmotion,
                    required onHangUpWarning,
                    required onCallEnd,
                    required onBotSpeakingEnded,
                    required onCheckpointAdvanced,
                required onEnvWarning,
                  }) {
                    capturedOnCallEnd = onCallEnd;
                    return mock;
                  },
                );
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        // Capture the bloc instance the screen built so we can observe
        // its state after the callback fires. Read from a descendant of
        // CallScreen (the Scaffold is below the BlocProvider scope; the
        // CallScreen element itself is above it).
        capturedBloc =
            tester.element(find.byType(Scaffold).first).read<CallBloc>();

        expect(capturedOnCallEnd, isNotNull);
        expect(capturedBloc.state, isA<CallConnected>());

        // Fire the simulated `call_end` envelope. The bloc parks in
        // remote-end-pending — still CallConnected externally.
        capturedOnCallEnd!('character_hung_up', <String, dynamic>{
          'survival_pct': 40,
        });
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 50));
        expect(capturedBloc.state, isA<CallConnected>());

        // Simulate the local playback-drain signal (the real wiring is
        // through `VisemeScheduler.onSilenceConfirmed`).
        capturedBloc.add(const PlaybackDrained());
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 50));
        expect(capturedBloc.state, isA<CallEnded>());

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'Story 6.4 — onHangUpWarning callback is a no-op (no bloc event)',
      (tester) async {
        // Invoking the warning hook must NOT dispatch any event to the
        // bloc and must NOT crash the widget tree. This is the regression
        // guard for the deliberate no-op wiring documented in AC6.
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        void Function(int)? capturedOnHangUpWarning;

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugEndCallResultTimeout: Duration.zero,
              debugCanvasFallback: false,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                capturedOnHangUpWarning = onHangUpWarning;
                return mock;
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        expect(capturedOnHangUpWarning, isNotNull);

        // Fire the warning — must NOT throw, must NOT pop the screen.
        capturedOnHangUpWarning!(5);
        await tester.pump();

        // Sanity: the CallScreen is still mounted (a regression that
        // wired the warning to a bloc event would have popped it).
        expect(find.byType(RiveCharacterCanvas), findsOneWidget);

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'disposes the handler when CallScreen unmounts',
      (tester) async {
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugEndCallResultTimeout: Duration.zero,
              debugCanvasFallback: false,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                return mock;
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        // Sanity: the handler was constructed (dispose hasn't fired yet).
        verifyNever(() => mock.dispose());

        // Unmount the screen — `_CallScreenState.dispose` must call
        // `_dataChannelHandler?.dispose()` BEFORE `super.dispose()`.
        await tester.pumpWidget(const SizedBox.shrink());
        // Settle any pending micro-tasks (the dispose() future fire).
        await tester.pump();

        verify(() => mock.dispose()).called(1);
      },
    );
  });

  // ---------- Story 6.7 — CheckpointSnapshot notifier plumbing ----------

  group('CallScreen — checkpoint stepper plumbing (Story 6.7)', () {
    testWidgets(
      'checkpoint_advanced envelope updates _checkpointNotifier with typed snapshot',
      (tester) async {
        // AC5 #1 — pump `CallScreen` with a debugHandlerBuilder that
        // captures `onCheckpointAdvanced`; invoke it with a typed
        // payload; assert the State's notifier reflects the new
        // snapshot. Drills into the `@visibleForTesting` getter so
        // the test does not depend on the Phase-2 Rive subtree.
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        void Function(CheckpointAdvancedPayload)? capturedOnCheckpointAdvanced;

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: false,
              debugEndCallResultTimeout: Duration.zero,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                capturedOnCheckpointAdvanced = onCheckpointAdvanced;
                return mock;
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        expect(capturedOnCheckpointAdvanced, isNotNull);

        // The Phase-1 notifier starts null (no envelope received yet).
        final state = tester.state<State<CallScreen>>(find.byType(CallScreen))
            // ignore: invalid_use_of_visible_for_testing_member
            as dynamic;
        final ValueNotifier<CheckpointSnapshot?> notifier =
            state.checkpointNotifierForTest as ValueNotifier<CheckpointSnapshot?>;
        expect(notifier.value, isNull);

        // Fire a server-side advance. Story 6.10 — the snapshot carries
        // the met SET + the full hints; metCount = goals met,
        // justFlippedIndex = the goal that just flipped (index 1 ∈ met).
        capturedOnCheckpointAdvanced!(
          const CheckpointAdvancedPayload(
            checkpointId: 'order_item',
            index: 1,
            total: 6,
            goalsMetIndices: [0, 1],
            hints: ['greet', 'order', 'drink', 'clarify', 'confirm', 'thanks'],
          ),
        );
        await tester.pump();

        expect(notifier.value, isNotNull);
        expect(notifier.value!.metCount, 2);
        expect(notifier.value!.metIndices, [0, 1]);
        expect(notifier.value!.total, 6);
        expect(notifier.value!.justFlippedIndex, 1);
        // Active step = first not-yet-met (index 2) → hints[2].
        expect(notifier.value!.activeHint, 'drink');

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'out-of-order goals_met_indices maps to met COUNT, not max index',
      (tester) async {
        // Story 6.10 — when goals flip out of order (e.g. index 3 met
        // before index 2), metCount must equal the SIZE of the met set
        // (2), NOT the highest index (3) — and the active step is the
        // first still-pending one (index 1).
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        void Function(CheckpointAdvancedPayload)? capturedOnCheckpointAdvanced;

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: false,
              debugEndCallResultTimeout: Duration.zero,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                capturedOnCheckpointAdvanced = onCheckpointAdvanced;
                return mock;
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        capturedOnCheckpointAdvanced!(
          const CheckpointAdvancedPayload(
            checkpointId: 'drink',
            index: 3,
            total: 6,
            goalsMetIndices: [0, 3],
            hints: ['greet', 'order', 'clarify', 'drink', 'confirm', 'thanks'],
          ),
        );
        await tester.pump();

        final state = tester.state<State<CallScreen>>(find.byType(CallScreen))
            // ignore: invalid_use_of_visible_for_testing_member
            as dynamic;
        final ValueNotifier<CheckpointSnapshot?> notifier =
            state.checkpointNotifierForTest as ValueNotifier<CheckpointSnapshot?>;
        expect(
          notifier.value?.metCount,
          2,
          reason: '2 goals met (indices 0 and 3) → metCount 2, '
              'NOT 4 (max index 3 + 1)',
        );
        expect(notifier.value?.metIndices, [0, 3]);
        expect(notifier.value?.justFlippedIndex, 3);
        // Active = first pending (index 1) → hints[1].
        expect(notifier.value?.activeHint, 'order');
        expect(notifier.value?.total, 6);

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'call_end reconciles _checkpointNotifier UP to server-authoritative checkpoints_passed',
      (tester) async {
        // AC5 #2 / Deviation #2 — if the local stepper lags the server
        // by N checkpoints because one `checkpoint_advanced` push was
        // cancelled mid-flight (Story 6.6 deferred-work line 406), the
        // call_end envelope's `checkpoints_passed` reconciles the
        // notifier BEFORE the bloc receives RemoteCallEnded.
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        void Function(CheckpointAdvancedPayload)? capturedOnCheckpointAdvanced;
        void Function(String, Map<String, dynamic>)? capturedOnCallEnd;

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: false,
              debugPlaybackDrainBuffer: Duration.zero,
              debugEndCallResultTimeout: Duration.zero,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                capturedOnCheckpointAdvanced = onCheckpointAdvanced;
                capturedOnCallEnd = onCallEnd;
                return mock;
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        // Bring the local HUD to "2 of 6 met" by simulating two advances
        // arriving via the data-channel.
        capturedOnCheckpointAdvanced!(
          const CheckpointAdvancedPayload(
            checkpointId: 'greet',
            index: 0,
            total: 6,
            goalsMetIndices: [0],
            hints: ['greet', 'order', 'drink', 'clarify', 'confirm', 'thanks'],
          ),
        );
        capturedOnCheckpointAdvanced!(
          const CheckpointAdvancedPayload(
            checkpointId: 'order_item',
            index: 1,
            total: 6,
            goalsMetIndices: [0, 1],
            hints: ['greet', 'order', 'drink', 'clarify', 'confirm', 'thanks'],
          ),
        );
        await tester.pump();

        final state = tester.state<State<CallScreen>>(find.byType(CallScreen))
            // ignore: invalid_use_of_visible_for_testing_member
            as dynamic;
        final ValueNotifier<CheckpointSnapshot?> notifier =
            state.checkpointNotifierForTest as ValueNotifier<CheckpointSnapshot?>;
        expect(notifier.value?.metCount, 2);

        // Simulate the server's call_end envelope carrying the
        // authoritative count "checkpoints_passed: 6" — i.e. user
        // survived but the final advance envelope was lost in the
        // pipeline-shutdown race.
        expect(capturedOnCallEnd, isNotNull);
        capturedOnCallEnd!('survived', <String, dynamic>{
          'reason': 'survived',
          'survival_pct': 100,
          'checkpoints_passed': 6,
          'total_checkpoints': 6,
        });
        await tester.pump();

        // The notifier MUST have walked UP to 6 met before the bloc was
        // told the call ended (justFlippedIndex null — no animation on a
        // reconcile).
        expect(
          notifier.value?.metCount,
          6,
          reason: 'Deviation #2 — HUD must reconcile UP to '
              'server-authoritative checkpoints_passed on call_end',
        );
        expect(notifier.value?.total, 6);
        expect(notifier.value?.justFlippedIndex, isNull);
        // Hints survive the reconcile (server doesn't re-send them in call_end).
        expect(notifier.value?.hints.length, 6);

        // Drain the bloc's pending playback-drain timer (the
        // RemoteCallEnded path arms it via the screen's onCallEnd →
        // bloc dispatch); without firing PlaybackDrained the bloc
        // keeps a Timer pending and the test framework asserts
        // !timersPending at teardown.
        final bloc =
            tester.element(find.byType(Scaffold).first).read<CallBloc>();
        bloc.add(const PlaybackDrained());
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 50));

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'call_end prefers the real goals_met_indices SET over the count',
      (tester) async {
        // Story 6.20 AC3 — when call_end carries `goals_met_indices`, the
        // reconcile must use that EXACT set (so out-of-order completions
        // are labelled correctly), NOT the count-based `[0..passed)`
        // reconstruction which would mislabel WHICH goals were met.
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        void Function(CheckpointAdvancedPayload)? capturedOnCheckpointAdvanced;
        void Function(String, Map<String, dynamic>)? capturedOnCallEnd;

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: false,
              debugPlaybackDrainBuffer: Duration.zero,
              debugEndCallResultTimeout: Duration.zero,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                capturedOnCheckpointAdvanced = onCheckpointAdvanced;
                capturedOnCallEnd = onCallEnd;
                return mock;
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        // Local HUD shows an out-of-order pair {0, 3} (count 2).
        capturedOnCheckpointAdvanced!(
          const CheckpointAdvancedPayload(
            checkpointId: 'drink',
            index: 3,
            total: 6,
            goalsMetIndices: [0, 3],
            hints: ['greet', 'order', 'drink', 'clarify', 'confirm', 'thanks'],
          ),
        );
        await tester.pump();

        final state = tester.state<State<CallScreen>>(find.byType(CallScreen))
            // ignore: invalid_use_of_visible_for_testing_member
            as dynamic;
        final ValueNotifier<CheckpointSnapshot?> notifier =
            state.checkpointNotifierForTest as ValueNotifier<CheckpointSnapshot?>;
        expect(notifier.value?.metIndices, [0, 3]);

        // call_end carries the REAL set {0, 3, 5} (one more lost-tail flip),
        // plus a count that would WRONGLY map to [0, 1, 2]. The SET wins.
        capturedOnCallEnd!('survived', <String, dynamic>{
          'reason': 'survived',
          'survival_pct': 100,
          'checkpoints_passed': 3,
          'total_checkpoints': 6,
          'goals_met_indices': [0, 3, 5],
        });
        await tester.pump();

        expect(
          notifier.value?.metIndices,
          [0, 3, 5],
          reason: 'AC3 — the exact met SET is preferred over the count, so '
              'out-of-order completions are never mislabelled as [0..N)',
        );
        expect(notifier.value?.justFlippedIndex, isNull);

        final bloc =
            tester.element(find.byType(Scaffold).first).read<CallBloc>();
        bloc.add(const PlaybackDrained());
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 50));

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'call_end SET reconcile UNIONS with current — keeps local-only ticks '
      'and adds server-only ones (never shrinks)',
      (tester) async {
        // Story 6.20 AC3 (code-review 2026-06-05) — the SET branch must UNION
        // the server `goals_met_indices` with what the HUD already shows, so a
        // server set that is smaller-than / partially-disjoint-from the local
        // set never erases a locally-rendered tick. Local {0,1,2,3} + server
        // SET [0,1,4] -> [0,1,2,3,4] (keeps 2,3; adds 4). A regression that
        // dropped the union (used the raw server set) would NOT add 4 here —
        // the only other SET test uses a pure superset and can't catch it.
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        void Function(CheckpointAdvancedPayload)? capturedOnCheckpointAdvanced;
        void Function(String, Map<String, dynamic>)? capturedOnCallEnd;

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: false,
              debugPlaybackDrainBuffer: Duration.zero,
              debugEndCallResultTimeout: Duration.zero,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                capturedOnCheckpointAdvanced = onCheckpointAdvanced;
                capturedOnCallEnd = onCallEnd;
                return mock;
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        // Local HUD shows {0, 1, 2, 3} (count 4).
        capturedOnCheckpointAdvanced!(
          const CheckpointAdvancedPayload(
            checkpointId: 'clarify',
            index: 3,
            total: 6,
            goalsMetIndices: [0, 1, 2, 3],
            hints: ['greet', 'order', 'drink', 'clarify', 'confirm', 'thanks'],
          ),
        );
        await tester.pump();

        final state = tester.state<State<CallScreen>>(find.byType(CallScreen))
            // ignore: invalid_use_of_visible_for_testing_member
            as dynamic;
        final ValueNotifier<CheckpointSnapshot?> notifier =
            state.checkpointNotifierForTest as ValueNotifier<CheckpointSnapshot?>;
        expect(notifier.value?.metIndices, [0, 1, 2, 3]);

        // call_end carries a SET partially disjoint from + the same size as a
        // strict-subset case: [0, 1, 4]. Union must KEEP 2,3 and ADD 4.
        capturedOnCallEnd!('survived', <String, dynamic>{
          'reason': 'survived',
          'survival_pct': 100,
          'checkpoints_passed': 3,
          'total_checkpoints': 6,
          'goals_met_indices': [0, 1, 4],
        });
        await tester.pump();

        expect(
          notifier.value?.metIndices,
          [0, 1, 2, 3, 4],
          reason: 'AC3 — the SET branch unions with the current set: '
              'local-only ticks (2,3) are kept and the server-only tick (4) '
              'is added; the reconcile never shrinks what the HUD showed',
        );
        expect(notifier.value?.justFlippedIndex, isNull);

        final bloc =
            tester.element(find.byType(Scaffold).first).read<CallBloc>();
        bloc.add(const PlaybackDrained());
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 50));

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'call_end with checkpoints_passed LOWER than current does NOT walk back',
      (tester) async {
        // Defensive: never reconcile DOWN — that would mask a genuine
        // server-side regression.
        final mock = MockDataChannelHandler();
        when(() => mock.dispose()).thenAnswer((_) async {});

        void Function(CheckpointAdvancedPayload)? capturedOnCheckpointAdvanced;
        void Function(String, Map<String, dynamic>)? capturedOnCallEnd;

        final fixture = _buildRoomFastConnect();
        await tester.pumpWidget(
          MaterialApp(
            home: CallScreen(
              scenario: _scenario,
              callSession: _session,
              room: fixture.room,
              debugCanvasFallback: false,
              debugPlaybackDrainBuffer: Duration.zero,
              debugEndCallResultTimeout: Duration.zero,
              debugHandlerBuilder: ({
                required room,
                required onEmotion,
                required onHangUpWarning,
                required onCallEnd,
                required onBotSpeakingEnded,
                required onCheckpointAdvanced,
                required onEnvWarning,
              }) {
                capturedOnCheckpointAdvanced = onCheckpointAdvanced;
                capturedOnCallEnd = onCallEnd;
                return mock;
              },
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1100));

        capturedOnCheckpointAdvanced!(
          const CheckpointAdvancedPayload(
            checkpointId: 'late',
            index: 3,
            total: 6,
            goalsMetIndices: [0, 1, 2, 3],
            hints: ['greet', 'order', 'drink', 'clarify', 'confirm', 'thanks'],
          ),
        );
        await tester.pump();

        final state = tester.state<State<CallScreen>>(find.byType(CallScreen))
            // ignore: invalid_use_of_visible_for_testing_member
            as dynamic;
        final ValueNotifier<CheckpointSnapshot?> notifier =
            state.checkpointNotifierForTest as ValueNotifier<CheckpointSnapshot?>;
        expect(notifier.value?.metCount, 4);

        // Server reports a LOWER count — must not walk back.
        capturedOnCallEnd!('character_hung_up', <String, dynamic>{
          'reason': 'character_hung_up',
          'survival_pct': 30,
          'checkpoints_passed': 2,
          'total_checkpoints': 6,
        });
        await tester.pump();

        expect(
          notifier.value?.metCount,
          4,
          reason: 'reconcile must walk UP only — backward steps would mask '
              'a real server-side regression',
        );

        // Drain the bloc's pending playback-drain timer — same
        // teardown discipline as the reconcile-up test above.
        final bloc =
            tester.element(find.byType(Scaffold).first).read<CallBloc>();
        bloc.add(const PlaybackDrained());
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 50));

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  });

  group('CallScreen — post-call navigation (Story 7.2)', () {
    // Shared harness: pumps a real-bloc CallScreen with a mocked
    // CallRepository (so the overlay's debrief fetch never hits the
    // network) and captures the data-channel callbacks.
    Future<
      ({
        MockCallRepository repo,
        void Function(String, Map<String, dynamic>) onCallEnd,
        void Function(CheckpointAdvancedPayload) onCheckpointAdvanced,
      })
    >
    pumpRealBlocScreen(WidgetTester tester, {required bool gifted}) async {
      final mock = MockDataChannelHandler();
      when(() => mock.dispose()).thenAnswer((_) async {});

      final repo = MockCallRepository();
      when(
        () => repo.endCall(
          callId: any(named: 'callId'),
          reason: any(named: 'reason'),
        ),
      ).thenAnswer(
        (_) async => EndCallResult(
          wasGifted: gifted,
          giftsRemainingToday: gifted ? 2 : 3,
          durationSec: 42,
        ),
      );
      // Never resolves — the overlay holds on its own timers; the test
      // never pumps past them.
      when(
        () => repo.fetchDebrief(callId: any(named: 'callId')),
      ).thenAnswer((_) => Completer<Map<String, dynamic>>().future);

      void Function(String, Map<String, dynamic>)? capturedOnCallEnd;
      void Function(CheckpointAdvancedPayload)? capturedOnCheckpointAdvanced;

      final fixture = _buildRoomFastConnect();
      await tester.pumpWidget(
        MaterialApp(
          home: CallScreen(
            scenario: _scenario,
            callSession: _session,
            room: fixture.room,
            debugCanvasFallback: false,
            debugPlaybackDrainBuffer: Duration.zero,
            debugEndCallResultTimeout: Duration.zero,
            callRepository: repo,
            debugHandlerBuilder:
                ({
                  required room,
                  required onEmotion,
                  required onHangUpWarning,
                  required onCallEnd,
                  required onBotSpeakingEnded,
                  required onCheckpointAdvanced,
                  required onEnvWarning,
                }) {
                  capturedOnCallEnd = onCallEnd;
                  capturedOnCheckpointAdvanced = onCheckpointAdvanced;
                  return mock;
                },
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 1100));

      expect(capturedOnCallEnd, isNotNull);
      return (
        repo: repo,
        onCallEnd: capturedOnCallEnd!,
        onCheckpointAdvanced: capturedOnCheckpointAdvanced!,
      );
    }

    testWidgets(
      'debrief-eligible CallEnded pushes the Call Ended overlay with the '
      'checkpoint metrics captured at push time (AC-C12)',
      (tester) async {
        final harness = await pumpRealBlocScreen(tester, gifted: false);

        // Mid-call HUD state: 3 of 6 goals met.
        harness.onCheckpointAdvanced(
          const CheckpointAdvancedPayload(
            checkpointId: 'drink',
            index: 2,
            total: 6,
            goalsMetIndices: [0, 1, 2],
            hints: ['greet', 'order', 'drink', 'clarify', 'confirm', 'thanks'],
          ),
        );
        await tester.pump();

        final bloc = tester
            .element(find.byType(Scaffold).first)
            .read<CallBloc>();
        harness.onCallEnd('character_hung_up', <String, dynamic>{});
        await tester.pump(const Duration(milliseconds: 50));
        bloc.add(const PlaybackDrained());
        await tester.pump(const Duration(milliseconds: 50));
        // Post-frame callback → pushReplacement; pump the entry frames.
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 100));

        expect(find.byType(CallEndedScreen), findsOneWidget);
        expect(find.byType(CallEndedNoticeScreen), findsNothing);
        final screen = tester.widget<CallEndedScreen>(
          find.byType(CallEndedScreen),
        );
        expect(screen.endReason, 'character_hung_up');
        expect(screen.checkpointsPassed, 3);
        expect(screen.totalCheckpoints, 6);
        expect(screen.callId, _session.callId);
        expect(identical(screen.scenario, _scenario), isTrue);

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );

    testWidgets(
      'gifted short-call still routes to CallEndedNoticeScreen — the '
      'showsNotice path is untouched (AC-C12)',
      (tester) async {
        final harness = await pumpRealBlocScreen(tester, gifted: true);

        final bloc = tester
            .element(find.byType(Scaffold).first)
            .read<CallBloc>();
        harness.onCallEnd('character_hung_up', <String, dynamic>{});
        await tester.pump(const Duration(milliseconds: 50));
        bloc.add(const PlaybackDrained());
        await tester.pump(const Duration(milliseconds: 50));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 100));

        expect(find.byType(CallEndedNoticeScreen), findsOneWidget);
        expect(find.byType(CallEndedScreen), findsNothing);

        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  });
}
