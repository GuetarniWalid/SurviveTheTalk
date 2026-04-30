import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/features/call/bloc/call_bloc.dart';
import 'package:client/features/call/bloc/call_event.dart';
import 'package:client/features/call/bloc/call_state.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:livekit_client/livekit_client.dart';
import 'package:mocktail/mocktail.dart';

class MockRoom extends Mock implements Room {}

class MockLocalParticipant extends Mock implements LocalParticipant {}

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

({MockRoom room, EventsEmitter<RoomEvent> emitter, MockLocalParticipant participant}) _buildRoom({
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
    when(
      () => room.connect(any(), any()),
    ).thenAnswer((_) async => room);
  }

  return (room: room, emitter: emitter, participant: participant);
}

void main() {
  setUpAll(() {
    registerFallbackValue(const CallStarted());
    registerFallbackValue(const HangUpPressed());
  });

  group('_onCallStarted', () {
    test('happy path enables the mic AFTER the 1-s minimum hold', () async {
      final fixture = _buildRoom(connectDelay: const Duration(milliseconds: 50));
      final bloc = CallBloc(
        session: _session,
        scenario: _scenario,
        room: fixture.room,
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
      );

      bloc.add(const CallStarted());
      await Future<void>.delayed(const Duration(milliseconds: 1100));
      bloc.add(const HangUpPressed());
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await bloc.close();

      verify(() => fixture.room.disconnect()).called(1);
    });
  });
}
