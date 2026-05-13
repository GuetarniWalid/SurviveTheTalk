import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/core/services/connectivity_service.dart';
import 'package:client/core/services/end_call_retry_service.dart';
import 'package:client/features/call/bloc/call_bloc.dart';
import 'package:client/features/call/bloc/call_event.dart';
import 'package:client/features/call/bloc/call_state.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/call/models/end_call_result.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:livekit_client/livekit_client.dart';
import 'package:mocktail/mocktail.dart';

class MockRoom extends Mock implements Room {}

class MockLocalParticipant extends Mock implements LocalParticipant {}

class MockCallRepository extends Mock implements CallRepository {}

class MockConnectivityService extends Mock implements ConnectivityService {}

class MockEndCallRetryService extends Mock implements EndCallRetryService {}

late MockCallRepository mockCallRepository;
late MockConnectivityService mockConnectivityService;
late MockEndCallRetryService mockEndCallRetryService;
late StreamController<bool> connectivityLostController;

/// Story 6.5 Déviation #27 — default "not gifted, full quota" envelope
/// returned by the mocked `endCall`. Tests that exercise gift outcomes
/// stub a different result locally.
const _kDefaultEndCallResult = EndCallResult(
  wasGifted: false,
  giftsRemainingToday: 3,
  durationSec: 0,
);

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

({
  MockRoom room,
  EventsEmitter<RoomEvent> emitter,
  MockLocalParticipant participant,
})
_buildRoom({
  bool throwsOnConnect = false,
  Duration? connectDelay,
  bool failsToConnect = false,
}) {
  final room = MockRoom();
  final emitter = EventsEmitter<RoomEvent>();
  final participant = MockLocalParticipant();

  when(() => room.events).thenReturn(emitter);
  when(() => room.localParticipant).thenReturn(participant);
  when(() => participant.setMicrophoneEnabled(any())).thenAnswer((_) async {
    return null;
  });
  when(() => room.disconnect()).thenAnswer((_) async {});

  if (throwsOnConnect) {
    when(() => room.connect(any(), any())).thenThrow(StateError('boom'));
  } else if (connectDelay != null) {
    when(
      () => room.connect(any(), any()),
    ).thenAnswer((_) => Future<Room>.delayed(connectDelay, () => room));
  } else if (failsToConnect) {
    // Never resolves — exercises the 5-s timeout path.
    when(
      () => room.connect(any(), any()),
    ).thenAnswer((_) => Completer<Room>().future);
  } else {
    when(() => room.connect(any(), any())).thenAnswer((_) async => room);
  }

  return (room: room, emitter: emitter, participant: participant);
}

void main() {
  setUpAll(() {
    registerFallbackValue(const CallStarted());
    registerFallbackValue(const HangUpPressed());
    registerFallbackValue(const RemoteCallEnded('test', <String, dynamic>{}));
    registerFallbackValue(const PlaybackDrained());
  });

  setUp(() {
    mockCallRepository = MockCallRepository();
    // Story 6.5 — default the endCall mock to a fire-and-forget success
    // returning the "not gifted, full quota" envelope. Individual tests
    // that want to assert failure-handling or gift outcomes stub it
    // again.
    when(
      () => mockCallRepository.endCall(
        callId: any(named: 'callId'),
        reason: any(named: 'reason'),
      ),
    ).thenAnswer((_) async => _kDefaultEndCallResult);

    // Story 6.5 review (post-deploy E2E) — connectivity monitor mock.
    // Default: never emits (stays connected throughout the test).
    // Tests that exercise the airplane-mode path push `true` onto
    // `connectivityLostController` to simulate the loss event.
    mockConnectivityService = MockConnectivityService();
    connectivityLostController = StreamController<bool>.broadcast();
    when(
      () => mockConnectivityService.onConnectivityLost,
    ).thenAnswer((_) => connectivityLostController.stream);

    // Story 6.5 Option B — retry service mock. Defaults to a no-op
    // `queue` so tests that don't care about the retry path stay
    // unchanged; tests that DO care use `verify(...)` against this
    // mock to assert the bloc queued the failed POST.
    mockEndCallRetryService = MockEndCallRetryService();
    when(
      () => mockEndCallRetryService.queue(
        callId: any(named: 'callId'),
        reason: any(named: 'reason'),
      ),
    ).thenAnswer((_) async {});
  });

  tearDown(() async {
    // Belt-and-braces — every test creates a fresh StreamController in
    // setUp; close any that a test forgot to drain. `close()` on an
    // already-closed controller throws StateError, so guard it.
    if (!connectivityLostController.isClosed) {
      await connectivityLostController.close();
    }
  });

  group('_onCallStarted', () {
    test('happy path enables the mic AFTER the 1-s minimum hold', () async {
      final fixture = _buildRoom(
        connectDelay: const Duration(milliseconds: 50),
      );
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());

      // Just before the 1-s minimum hold elapses: connect is done but mic
      // must NOT be enabled yet (the user is still seeing "Connecting…").
      await Future<void>.delayed(const Duration(milliseconds: 800));
      verifyNever(() => fixture.participant.setMicrophoneEnabled(true));

      // After the visual hold settles: mic enabled exactly once and the
      // bloc is in CallConnected.
      await Future<void>.delayed(const Duration(milliseconds: 400));
      verify(() => fixture.participant.setMicrophoneEnabled(true)).called(1);
      expect(bloc.state, isA<CallConnected>());

      await bloc.close();
    });

    blocTest<CallBloc, CallState>(
      'connect throws → emits [CallError, CallEnded] (so the screen pops)',
      build: () {
        final fixture = _buildRoom(throwsOnConnect: true);
        return CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
        );
      },
      act: (bloc) => bloc.add(const CallStarted()),
      expect: () => [
        isA<CallError>().having(
          (s) => s.reason,
          'reason',
          "Couldn't connect to the call.",
        ),
        isA<CallEnded>(),
      ],
    );

    blocTest<CallBloc, CallState>(
      'connect never resolves → 5-s timeout → [CallError, CallEnded]',
      build: () {
        final fixture = _buildRoom(failsToConnect: true);
        return CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
        );
      },
      act: (bloc) => bloc.add(const CallStarted()),
      wait: const Duration(seconds: 6),
      expect: () => [
        isA<CallError>().having(
          (s) => s.reason,
          'reason',
          "Couldn't connect to the call.",
        ),
        isA<CallEnded>(),
      ],
    );
  });

  group('_onHangUpPressed', () {
    test('disconnects the room exactly once and emits CallEnded', () async {
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      // Wait for connect + 1-s minimum.
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      final states = <CallState>[];
      final sub = bloc.stream.listen(states.add);
      bloc.add(const HangUpPressed());
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await sub.cancel();

      expect(states, contains(isA<CallEnded>()));
      verify(() => fixture.room.disconnect()).called(1);
      // Reset call counters before closing the bloc so the defensive
      // `verifyNever` below only sees post-close interactions.
      clearInteractions(fixture.room);
      await bloc.close();
      verifyNever(() => fixture.room.disconnect());
    });
  });

  group('Room disconnected externally', () {
    test('emits [CallError, CallEnded]', () async {
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      final states = <CallState>[];
      final sub = bloc.stream.listen(states.add);

      // Simulate server-side kick. The bloc subscribes to
      // `room.events.on<RoomDisconnectedEvent>` in its constructor and
      // re-fires its own `RoomDisconnected` event onto the bloc; we drive
      // the underlying broadcast stream directly because `emit()` is marked
      // `@internal` in the LiveKit SDK.
      fixture.emitter.streamCtrl.add(
        RoomDisconnectedEvent(reason: DisconnectReason.serverShutdown),
      );
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await sub.cancel();

      expect(states.whereType<CallError>(), isNotEmpty);
      expect(states.whereType<CallEnded>(), isNotEmpty);
      final error = states.whereType<CallError>().first;
      expect(error.reason, 'Connection lost.');
      await bloc.close();
    });
  });

  group('close()', () {
    test('disconnects the room defensively when called pre-hangup', () async {
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      await bloc.close();
      verify(() => fixture.room.disconnect()).called(1);
    });

    test('does NOT double-disconnect when hang-up already ran', () async {
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));
      bloc.add(const HangUpPressed());
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await bloc.close();

      verify(() => fixture.room.disconnect()).called(1);
    });
  });

  group('CallBloc.room (Story 6.3)', () {
    test('exposes the same Room instance passed to the constructor', () async {
      // Story 6.3 — `DataChannelHandler` needs read-only access to the
      // underlying Room so it can subscribe to DataReceivedEvent. The
      // getter MUST return the very same instance (not a copy / wrapper).
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      expect(identical(bloc.room, fixture.room), isTrue);

      await bloc.close();
    });
  });

  group('RemoteCallEnded + PlaybackDrained (Story 6.4)', () {
    test('RemoteCallEnded does NOT disconnect or emit until drain', () async {
      // The two-phase end: RemoteCallEnded just marks the flag and
      // sets the safety timer; the actual disconnect waits for
      // PlaybackDrained (= local speaker confirmed silent).
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      final states = <CallState>[];
      final sub = bloc.stream.listen(states.add);

      bloc.add(
        const RemoteCallEnded('character_hung_up', <String, dynamic>{
          'survival_pct': 40,
          'checkpoints_passed': 0,
          'total_checkpoints': 5,
        }),
      );
      await Future<void>.delayed(const Duration(milliseconds: 50));

      // No disconnect, no state change yet — bloc is parked waiting
      // for PlaybackDrained.
      verifyNever(() => fixture.room.disconnect());
      expect(states, isEmpty);

      await sub.cancel();
      await bloc.close();
    });

    test(
      'PlaybackDrained after RemoteCallEnded disconnects + emits CallEnded',
      () async {
        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        final states = <CallState>[];
        final sub = bloc.stream.listen(states.add);

        bloc.add(
          const RemoteCallEnded('character_hung_up', <String, dynamic>{}),
        );
        await Future<void>.delayed(const Duration(milliseconds: 20));
        bloc.add(const PlaybackDrained());
        await Future<void>.delayed(const Duration(milliseconds: 50));
        await sub.cancel();

        verify(() => fixture.room.disconnect()).called(1);
        expect(states.whereType<CallEnded>(), isNotEmpty);
        expect(
          states.whereType<CallError>(),
          isEmpty,
          reason: 'character-driven end MUST NOT surface CallError',
        );

        await bloc.close();
      },
    );

    test('PlaybackDrained without RemoteCallEnded is ignored', () async {
      // Mid-call user silence between turns triggers PlaybackDrained
      // naively. The bloc MUST ignore it unless an end is pending.
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      final states = <CallState>[];
      final sub = bloc.stream.listen(states.add);

      bloc.add(const PlaybackDrained());
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await sub.cancel();

      verifyNever(() => fixture.room.disconnect());
      expect(states.whereType<CallEnded>(), isEmpty);
      expect(states.whereType<CallError>(), isEmpty);

      await bloc.close();
    });

    test('safety timer is cancelled by an earlier PlaybackDrained '
        '(no double-disconnect)', () async {
      // If `VisemeScheduler.onSilenceConfirmed` fires first (normal
      // path), the bloc must cancel the 10 s safety timer so it
      // doesn't redundantly fire PlaybackDrained later. We
      // exercise that here without waiting the full 10 s.
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      bloc.add(const RemoteCallEnded('character_hung_up', <String, dynamic>{}));
      await Future<void>.delayed(const Duration(milliseconds: 30));
      // Manual drain — cancels the safety timer.
      bloc.add(const PlaybackDrained());
      await Future<void>.delayed(const Duration(milliseconds: 50));

      verify(() => fixture.room.disconnect()).called(1);

      // Wait a bit; a stale safety timer would have to fire to
      // cause a 2nd disconnect — we already verified called(1) so
      // any extra call would surface as a different count below.
      await Future<void>.delayed(const Duration(milliseconds: 200));
      verifyNever(() => fixture.room.disconnect());

      await bloc.close();
    });

    test('RoomDisconnectedEvent during remote-end-pending is ignored by the '
        'listener (safety timer drives the clean end instead)', () async {
      // Server's 8 s safety EndFrame → LiveKit teardown → listener
      // fires. The listener short-circuits on `_remoteEndPending`,
      // so the bloc does NOT add a RoomDisconnected event from
      // that path. The 10 s safety timer (inside the bloc) is what
      // eventually drives the clean end.
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      final states = <CallState>[];
      final sub = bloc.stream.listen(states.add);

      bloc.add(const RemoteCallEnded('character_hung_up', <String, dynamic>{}));
      await Future<void>.delayed(const Duration(milliseconds: 30));

      // Server's EndFrame → LiveKit teardown event.
      fixture.emitter.streamCtrl.add(
        RoomDisconnectedEvent(reason: DisconnectReason.clientInitiated),
      );
      await Future<void>.delayed(const Duration(milliseconds: 50));

      // Listener ignored the event → no state change yet.
      expect(states, isEmpty);
      expect(
        states.whereType<CallError>(),
        isEmpty,
        reason: 'remote-end-pending must NEVER surface Connection lost',
      );

      // Manually drain (would normally come from VisemeScheduler OR
      // the bloc's own safety timer). The bloc disconnects + emits
      // CallEnded — no CallError in the stream.
      bloc.add(const PlaybackDrained());
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await sub.cancel();

      expect(states.whereType<CallEnded>(), isNotEmpty);
      expect(states.whereType<CallError>(), isEmpty);

      await bloc.close();
    });

    test(
      'HangUpPressed during remote-end-pending takes over cleanly',
      () async {
        // User may tap hang-up while the exit line is still playing.
        // The bloc must disconnect (user took control) and a
        // follow-up PlaybackDrained must NOT trigger a second
        // disconnect.
        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        bloc.add(
          const RemoteCallEnded('character_hung_up', <String, dynamic>{}),
        );
        await Future<void>.delayed(const Duration(milliseconds: 30));
        bloc.add(const HangUpPressed());
        await Future<void>.delayed(const Duration(milliseconds: 50));

        // PlaybackDrained arrives late (e.g. from safety timer or a
        // delayed VisemeScheduler emission). No second disconnect.
        bloc.add(const PlaybackDrained());
        await Future<void>.delayed(const Duration(milliseconds: 30));

        verify(() => fixture.room.disconnect()).called(1);

        await bloc.close();
      },
    );

    test(
      'HangUpPressed during remote-end-pending clears the safety timer + '
      'flag so a late PlaybackDrained does not double-emit CallEnded',
      () async {
        // Regression for code-review P1 — the 10 s `_remoteEndDrainTimer`
        // and the `_remoteEndPending` flag both survived a user hang-up
        // in the original implementation, so a late PlaybackDrained
        // (from the safety timer or a delayed VisemeScheduler emit)
        // re-entered the disconnect path and emitted a duplicate
        // CallEnded — wasted work, potentially fired on a closing bloc.
        final fixture = _buildRoom();
        final emittedStates = <CallState>[];
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );
        final subscription = bloc.stream.listen(emittedStates.add);

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        bloc.add(
          const RemoteCallEnded('character_hung_up', <String, dynamic>{}),
        );
        await Future<void>.delayed(const Duration(milliseconds: 30));

        bloc.add(const HangUpPressed());
        await Future<void>.delayed(const Duration(milliseconds: 30));

        // Late PlaybackDrained simulating either the 10 s safety timer
        // firing or a delayed VisemeScheduler.onSilenceConfirmed.
        bloc.add(const PlaybackDrained());
        await Future<void>.delayed(const Duration(milliseconds: 30));

        // Exactly ONE CallEnded — the user-hangup one. The late
        // PlaybackDrained was correctly gated by `!_remoteEndPending`
        // (which HangUpPressed flipped back to false) and was a no-op.
        final endedStates = emittedStates.whereType<CallEnded>().toList();
        expect(
          endedStates,
          hasLength(1),
          reason: 'late PlaybackDrained must not re-emit CallEnded',
        );

        await subscription.cancel();
        await bloc.close();
      },
    );

    test('RoomDisconnectedEvent during remote-end-pending mirrors '
        '_roomDisconnected so a follow-up PlaybackDrained does not '
        'issue a redundant disconnect (P14)', () async {
      // Regression for code-review P14 — the LiveKit listener
      // short-circuited on `_remoteEndPending` but did NOT mirror
      // the room's now-disconnected state into our flag. A follow-up
      // PlaybackDrained (from the safety timer or the natural drain
      // signal) then attempted a second `_room.disconnect()` — a
      // wasted call wrapped in try/catch + a noisy LiveKit log.
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      bloc.add(const RemoteCallEnded('character_hung_up', <String, dynamic>{}));
      await Future<void>.delayed(const Duration(milliseconds: 30));

      // Simulate LiveKit's RoomDisconnectedEvent firing after the
      // server's safety EndFrame. Drive the underlying broadcast
      // stream directly because `emit()` is marked `@internal` in
      // the LiveKit SDK (same pattern as the existing
      // RoomDisconnected listener tests above).
      fixture.emitter.streamCtrl.add(
        RoomDisconnectedEvent(reason: DisconnectReason.serverShutdown),
      );
      await Future<void>.delayed(const Duration(milliseconds: 30));

      // Follow-up PlaybackDrained — the listener should have mirrored
      // _roomDisconnected=true so this no-ops on the disconnect path.
      bloc.add(const PlaybackDrained());
      await Future<void>.delayed(const Duration(milliseconds: 30));

      verifyNever(() => fixture.room.disconnect());

      await bloc.close();
    });

    test('event carries reason + data unchanged', () {
      // Basic constructor / accessor sanity — the bloc passes these to
      // future telemetry / debrief consumers without mutation.
      const event = RemoteCallEnded('inappropriate_content', <String, dynamic>{
        'survival_pct': 0,
        'checkpoints_passed': 1,
        'total_checkpoints': 5,
      });
      expect(event.reason, 'inappropriate_content');
      expect(event.data['survival_pct'], 0);
      expect(event.data['total_checkpoints'], 5);
    });
  });

  // Story 6.5 — fire-and-forget POST /calls/{id}/end from all 3 exit paths.
  group('endCall wiring (Story 6.5)', () {
    test('HangUpPressed → endCall(reason: "user_hung_up") once', () async {
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      bloc.add(const HangUpPressed());
      await Future<void>.delayed(const Duration(milliseconds: 50));

      verify(
        () => mockCallRepository.endCall(
          callId: _session.callId,
          reason: 'user_hung_up',
        ),
      ).called(1);

      await bloc.close();
    });

    test('RoomDisconnected (post-connect) → endCall(reason: "network_lost") + '
        'state stream is [CallError("Connection lost."), CallEnded]', () async {
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      final states = <CallState>[];
      final sub = bloc.stream.listen(states.add);

      fixture.emitter.streamCtrl.add(
        RoomDisconnectedEvent(reason: DisconnectReason.serverShutdown),
      );
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await sub.cancel();

      verify(
        () => mockCallRepository.endCall(
          callId: _session.callId,
          reason: 'network_lost',
        ),
      ).called(1);

      // POST is fire-and-forget telemetry; the state machine is unchanged.
      final errors = states.whereType<CallError>().toList();
      expect(errors, hasLength(1));
      expect(errors.first.reason, 'Connection lost.');
      expect(states.whereType<CallEnded>(), isNotEmpty);

      await bloc.close();
    });

    test(
      'RemoteCallEnded("character_hung_up") → endCall reason pass-through',
      () async {
        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        bloc.add(
          const RemoteCallEnded('character_hung_up', <String, dynamic>{}),
        );
        await Future<void>.delayed(const Duration(milliseconds: 50));

        verify(
          () => mockCallRepository.endCall(
            callId: _session.callId,
            reason: 'character_hung_up',
          ),
        ).called(1);

        await bloc.close();
      },
    );

    test(
      'RemoteCallEnded("inappropriate_content") → endCall reason pass-through',
      () async {
        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        bloc.add(
          const RemoteCallEnded('inappropriate_content', <String, dynamic>{}),
        );
        await Future<void>.delayed(const Duration(milliseconds: 50));

        verify(
          () => mockCallRepository.endCall(
            callId: _session.callId,
            reason: 'inappropriate_content',
          ),
        ).called(1);

        await bloc.close();
      },
    );

    test(
      'endCall failure does NOT escalate to the UI (fire-and-forget swallows)',
      () async {
        // Stub the repo to throw — the bloc swallows it via _endCallSilently
        // and the state stream emits CallEnded as if everything went fine.
        when(
          () => mockCallRepository.endCall(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        ).thenThrow(
          const ApiException(code: 'NETWORK_ERROR', message: 'No connection.'),
        );

        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          endCallRetryService: mockEndCallRetryService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        final states = <CallState>[];
        final sub = bloc.stream.listen(states.add);

        bloc.add(const HangUpPressed());
        await Future<void>.delayed(const Duration(milliseconds: 50));
        await sub.cancel();

        // CallEnded fired despite the POST throwing. No CallError surfaces
        // from a failed endCall (CLAUDE.md Gotcha #10 — fire-and-forget).
        expect(states.whereType<CallEnded>(), isNotEmpty);
        expect(
          states.whereType<CallError>(),
          isEmpty,
          reason: 'endCall failure must not escalate to CallError',
        );

        // Review P16: verify the repository was actually called (proves
        // the try/catch in _endCallSilently fired vs. the bloc skipping
        // the POST entirely). `untilCalled` waits for the async path so
        // the assertion is not timing-dependent.
        verify(
          () => mockCallRepository.endCall(
            callId: _session.callId,
            reason: 'user_hung_up',
          ),
        ).called(1);

        // Story 6.5 Option B — the failed POST must be queued so the
        // retry service can replay it on the next connectivity-regain.
        verify(
          () => mockEndCallRetryService.queue(
            callId: _session.callId,
            reason: 'user_hung_up',
          ),
        ).called(1);

        await bloc.close();
      },
    );

    test(
      'Option B — successful endCall does NOT queue for retry',
      () async {
        // Sanity check: queueing must happen ONLY on failure. A
        // happy-path POST should leave the retry queue untouched.
        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          endCallRetryService: mockEndCallRetryService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));
        bloc.add(const HangUpPressed());
        await Future<void>.delayed(const Duration(milliseconds: 50));

        verify(
          () => mockCallRepository.endCall(
            callId: _session.callId,
            reason: 'user_hung_up',
          ),
        ).called(1);
        verifyNever(
          () => mockEndCallRetryService.queue(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        );

        await bloc.close();
      },
    );

    test(
      'Option B — bloc without a retry service falls back to log-only '
      'on failure (legacy contract preserved)',
      () async {
        // The retry service is OPTIONAL on the bloc constructor.
        // Test environments that pump CallScreen standalone (no App
        // shell, no RepositoryProvider) get a null service. The bloc
        // must not crash on the null path — it just falls back to the
        // janitor-sweep backstop.
        when(
          () => mockCallRepository.endCall(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        ).thenThrow(
          const ApiException(code: 'NETWORK_ERROR', message: 'No connection.'),
        );

        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          // endCallRetryService: null — deliberately omitted.
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        final states = <CallState>[];
        final sub = bloc.stream.listen(states.add);

        bloc.add(const HangUpPressed());
        await Future<void>.delayed(const Duration(milliseconds: 50));
        await sub.cancel();

        // Bloc still completes the hang-up flow.
        expect(states.whereType<CallEnded>(), isNotEmpty);
        expect(states.whereType<CallError>(), isEmpty);

        // No crash on null service.
        await bloc.close();
      },
    );

    test('review P1 — connect failure (synchronous throw) POSTs '
        '"network_lost" so the orphaned pending row is cleaned up', () async {
      final fixture = _buildRoom(throwsOnConnect: true);
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 50));

      verify(
        () => mockCallRepository.endCall(
          callId: _session.callId,
          reason: 'network_lost',
        ),
      ).called(1);

      await bloc.close();
    });

    test('review P1 — connect timeout (5 s) POSTs "network_lost" so the '
        'orphaned pending row is cleaned up', () async {
      final fixture = _buildRoom(failsToConnect: true);
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      // The connect future never resolves — wait past the 5 s timeout.
      await Future<void>.delayed(const Duration(seconds: 6));

      verify(
        () => mockCallRepository.endCall(
          callId: _session.callId,
          reason: 'network_lost',
        ),
      ).called(1);

      await bloc.close();
    }, timeout: const Timeout(Duration(seconds: 10)));

    test('review P1 — mic enable failure POSTs "network_lost" (no other '
        'path will fire it, since _connected is still false)', () async {
      final fixture = _buildRoom();
      when(
        () => fixture.participant.setMicrophoneEnabled(any()),
      ).thenThrow(StateError('mic blocked'));
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      // Past the 1-s minimum hold so mic-enable runs.
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      verify(
        () => mockCallRepository.endCall(
          callId: _session.callId,
          reason: 'network_lost',
        ),
      ).called(1);

      await bloc.close();
    });

    test('review P4 — double-POST guard: HangUpPressed then RoomDisconnected '
        'only fires endCall once', () async {
      // The listener's `if (_hangingUp) return;` already short-circuits
      // the secondary path, but `_endPostFired` is the canonical guard
      // so this test pins the contract.
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      bloc.add(const HangUpPressed());
      await Future<void>.delayed(const Duration(milliseconds: 30));

      // Server-side teardown event arrives AFTER the user hang-up.
      fixture.emitter.streamCtrl.add(
        RoomDisconnectedEvent(reason: DisconnectReason.clientInitiated),
      );
      await Future<void>.delayed(const Duration(milliseconds: 50));

      // Exactly one POST — for the user_hung_up reason.
      verify(
        () => mockCallRepository.endCall(
          callId: _session.callId,
          reason: 'user_hung_up',
        ),
      ).called(1);
      verifyNever(
        () => mockCallRepository.endCall(
          callId: any(named: 'callId'),
          reason: 'network_lost',
        ),
      );

      await bloc.close();
    });

    test(
      'review P5 — RemoteCallEnded("unknown") coerces to '
      '"character_hung_up" so the server-side Literal does not 422',
      () async {
        // `DataChannelHandler` defaults a malformed `call_end` envelope's
        // reason to the literal string `'unknown'` — the bloc must
        // coerce to a canonical value before the POST or the server's
        // strict Literal will silently 422 the request.
        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        bloc.add(const RemoteCallEnded('unknown', <String, dynamic>{}));
        await Future<void>.delayed(const Duration(milliseconds: 50));

        verify(
          () => mockCallRepository.endCall(
            callId: _session.callId,
            reason: 'character_hung_up',
          ),
        ).called(1);
        verifyNever(
          () => mockCallRepository.endCall(
            callId: any(named: 'callId'),
            reason: 'unknown',
          ),
        );

        await bloc.close();
      },
    );

    test(
      'review post-deploy — connectivity loss mid-call fires '
      'RoomDisconnected proactively (does NOT wait for LiveKit SDK timeout)',
      () async {
        // Real-device repro: phone goes into airplane mode mid-call.
        // LiveKit SDK does NOT fire RoomDisconnectedEvent while the radio
        // is off (validated on prod 2026-05-13 — 7 m 12 s lag). The
        // OS-level connectivity monitor catches the loss within ~1 s and
        // dispatches our own `RoomDisconnected` event, which the bloc
        // handles via the existing network-lost path (POST /end +
        // CallError + CallEnded → screen pops).
        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        final states = <CallState>[];
        final sub = bloc.stream.listen(states.add);

        // Simulate the OS reporting total connectivity loss.
        connectivityLostController.add(true);
        await Future<void>.delayed(const Duration(milliseconds: 50));
        await sub.cancel();

        // Same outcome as a LiveKit-detected disconnect: POST fires
        // with `network_lost`, state stream goes [CallError, CallEnded],
        // screen pops back to /scenarios.
        verify(
          () => mockCallRepository.endCall(
            callId: _session.callId,
            reason: 'network_lost',
          ),
        ).called(1);
        expect(states.whereType<CallError>(), isNotEmpty);
        expect(states.whereType<CallEnded>(), isNotEmpty);
        expect(states.whereType<CallError>().first.reason, 'Connection lost.');

        await bloc.close();
      },
    );

    test(
      'review post-deploy — connectivity loss BEFORE connect is ignored '
      '(the dial-screen owns that failure path, not the call bloc)',
      () async {
        // The bloc's connectivity listener guards on `!_connected`.
        // The dial path (/calls/initiate → NoNetworkScreen) is the
        // canonical pre-call detection per Deviation #8; the listener
        // here only acts AFTER the call is established.
        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );

        // Connectivity-lost fires BEFORE CallStarted (so _connected is
        // still false).
        connectivityLostController.add(true);
        await Future<void>.delayed(const Duration(milliseconds: 30));

        verifyNever(
          () => mockCallRepository.endCall(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        );

        await bloc.close();
      },
    );

    test('review post-deploy — connectivity false events (radio came back) '
        'do NOT fire RoomDisconnected', () async {
      // Stream maps `none → true` and `wifi/mobile → false`. Only
      // the `true` transition should arm the disconnect path.
      final fixture = _buildRoom();
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
        callRepository: mockCallRepository,
        connectivityService: mockConnectivityService,
        playbackDrainBuffer: Duration.zero,
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));

      // Connectivity returns to "online" — must be a no-op.
      connectivityLostController.add(false);
      await Future<void>.delayed(const Duration(milliseconds: 50));

      verifyNever(
        () => mockCallRepository.endCall(
          callId: any(named: 'callId'),
          reason: any(named: 'reason'),
        ),
      );

      await bloc.close();
    });

    test(
      'review P3 — close() awaits in-flight endCall before tearing down',
      () async {
        // Stub the repo with a delayed resolution so we can observe the
        // ordering: close() must NOT return until the POST settles
        // (bounded by the 2 s timeout in close()).
        final completer = Completer<EndCallResult>();
        when(
          () => mockCallRepository.endCall(
            callId: any(named: 'callId'),
            reason: any(named: 'reason'),
          ),
        ).thenAnswer((_) => completer.future);

        final fixture = _buildRoom();
        final bloc = CallBloc(
          session: _session,
          scenario: _scenario,
          room: fixture.room,
          callRepository: mockCallRepository,
          connectivityService: mockConnectivityService,
          playbackDrainBuffer: Duration.zero,
        );

        bloc.add(const CallStarted());
        await Future<void>.delayed(const Duration(milliseconds: 1100));

        bloc.add(const HangUpPressed());
        await Future<void>.delayed(const Duration(milliseconds: 30));

        // Close racing the in-flight POST. close() must not resolve
        // until the POST settles OR the 2 s timeout elapses.
        final closeFuture = bloc.close();
        var closeResolved = false;
        unawaited(closeFuture.then((_) => closeResolved = true));

        // Brief yield: close() is awaiting; the POST has not settled
        // (completer is still pending), so closeFuture must NOT have
        // resolved.
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(
          closeResolved,
          isFalse,
          reason: 'close() must await the in-flight POST',
        );

        // Settle the POST → close() resolves.
        completer.complete(_kDefaultEndCallResult);
        await closeFuture;
        expect(closeResolved, isTrue);
      },
    );
  });
}
