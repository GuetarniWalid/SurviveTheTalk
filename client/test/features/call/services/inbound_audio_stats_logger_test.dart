import 'dart:collection';

import 'package:client/features/call/services/inbound_audio_stats_logger.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:livekit_client/livekit_client.dart';
import 'package:mocktail/mocktail.dart';

class _MockRoom extends Mock implements Room {}

void main() {
  group('formatStatsLine', () {
    test('formats all fields with jitter in ms and a concealed-delta', () {
      final line = InboundAudioStatsLogger.formatStatsLine(
        jitter: 0.0123, // 12.3 ms
        jitterBufferDelay: 45.678,
        packetsLost: 3,
        concealedSamples: 12345,
        prevConcealedSamples: 12145, // +200 this window
        concealmentEvents: 7,
      );
      expect(line, contains('jitter=12.3ms'));
      expect(line, contains('jitterBufferDelay=45.68s'));
      expect(line, contains('packetsLost=3'));
      // The (+delta) is the stretch signal: NetEq inserting samples.
      expect(line, contains('concealedSamples=12345 (+200)'));
      expect(line, contains('concealmentEvents=7'));
    });

    test('omits the delta on the first window (no previous value)', () {
      final line = InboundAudioStatsLogger.formatStatsLine(
        jitter: 0.005,
        jitterBufferDelay: 1.0,
        packetsLost: 0,
        concealedSamples: 500,
        prevConcealedSamples: null,
        concealmentEvents: 1,
      );
      expect(line, contains('concealedSamples=500'));
      expect(line, isNot(contains('(+')));
    });

    test('renders ? for any null metric (partial stats report)', () {
      final line = InboundAudioStatsLogger.formatStatsLine(
        jitter: null,
        jitterBufferDelay: null,
        packetsLost: null,
        concealedSamples: null,
        prevConcealedSamples: null,
        concealmentEvents: null,
      );
      expect(line, contains('jitter=?ms'));
      expect(line, contains('jitterBufferDelay=?s'));
      expect(line, contains('packetsLost=?'));
      expect(line, contains('concealedSamples=?'));
      expect(line, contains('concealmentEvents=?'));
    });
  });

  group('lifecycle', () {
    test('disabled logger never subscribes and disposes cleanly', () async {
      final room = _MockRoom();
      final logger = InboundAudioStatsLogger(room, enabled: false);

      logger.start();

      // No subscription path touched when disabled.
      verifyNever(() => room.events);
      verifyNever(() => room.remoteParticipants);

      // Safe to dispose without having started anything.
      await logger.dispose();
    });

    test('enabled logger subscribes to room track events on start', () async {
      final room = _MockRoom();
      final emitter = EventsEmitter<RoomEvent>();
      when(() => room.events).thenReturn(emitter);
      when(
        () => room.remoteParticipants,
      ).thenReturn(UnmodifiableMapView(<String, RemoteParticipant>{}));

      final logger = InboundAudioStatsLogger(room, enabled: true);
      logger.start();

      // It wires the room-level TrackSubscribed listener + sweeps existing
      // participants for already-subscribed audio tracks.
      verify(() => room.events).called(1);
      verify(() => room.remoteParticipants).called(1);

      await logger.dispose();
    });
  });
}
