// `EventsEmitter.emit(...)` is annotated `@internal` on the LiveKit Flutter
// SDK, but tests have no other way to fire `DataReceivedEvent` against a
// real emitter — the public publish path requires a live WebRTC peer. We
// silence the analyzer here only; production code never touches `emit`.
// ignore_for_file: invalid_use_of_internal_member
import 'dart:convert';

import 'package:client/features/call/services/data_channel_handler.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:livekit_client/livekit_client.dart';
import 'package:mocktail/mocktail.dart';

class _MockRoom extends Mock implements Room {}

DataReceivedEvent _envelope(Map<String, dynamic> payload) {
  return DataReceivedEvent(
    participant: null,
    data: utf8.encode(jsonEncode(payload)),
    topic: null,
  );
}

DataReceivedEvent _rawEnvelope(List<int> bytes) {
  return DataReceivedEvent(participant: null, data: bytes, topic: null);
}

({Room room, EventsEmitter<RoomEvent> emitter}) _buildRoom() {
  final room = _MockRoom();
  final emitter = EventsEmitter<RoomEvent>();
  when(() => room.events).thenReturn(emitter);
  return (room: room, emitter: emitter);
}

Future<void> _flush() async {
  // The stream-controller is async (`broadcast(sync: false)`), so we must
  // hand control to the event loop for the listener to fire.
  await Future<void>.delayed(Duration.zero);
}

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  test('constructor subscribes to DataReceivedEvent exactly once', () async {
    final fixture = _buildRoom();
    var emotionCalls = 0;

    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onViseme: (_, _) {},
    );

    // Emit ONE envelope; if the handler subscribed twice (or zero times)
    // the callback count would not equal 1.
    fixture.emitter.emit(
      _envelope({
        'type': 'emotion',
        'data': {'emotion': 'satisfaction', 'intensity': 0.5},
      }),
    );
    await _flush();

    expect(
      emotionCalls,
      1,
      reason: 'one emit must trigger exactly one callback — '
          'a count of 0 means no subscription, 2 means double-subscription',
    );
  });

  test('dispose cancels the LiveKit subscription', () async {
    final fixture = _buildRoom();
    var emotionCalls = 0;

    final handler = DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onViseme: (_, _) {},
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'emotion',
        'data': {'emotion': 'satisfaction', 'intensity': 0.7},
      }),
    );
    await _flush();
    expect(emotionCalls, 1);

    await handler.dispose();
    fixture.emitter.emit(
      _envelope({
        'type': 'emotion',
        'data': {'emotion': 'anger', 'intensity': 0.9},
      }),
    );
    await _flush();
    expect(emotionCalls, 1, reason: 'after dispose, no further callbacks');
  });

  test('dispose is idempotent', () async {
    final fixture = _buildRoom();
    final handler = DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) {},
      onViseme: (_, _) {},
    );

    await handler.dispose();
    // Second call MUST NOT throw and MUST NOT double-cancel.
    await handler.dispose();
  });

  test('emotion envelope routes to onEmotion with parsed values', () async {
    final fixture = _buildRoom();
    final received = <(String, double)>[];
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (e, i) => received.add((e, i)),
      onViseme: (_, _) {},
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'emotion',
        'data': {'emotion': 'satisfaction', 'intensity': 0.7},
      }),
    );
    await _flush();

    expect(received, [('satisfaction', 0.7)]);
  });

  test('viseme envelope routes to onViseme with int values', () async {
    final fixture = _buildRoom();
    final received = <(int, int)>[];
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) {},
      onViseme: (id, ts) => received.add((id, ts)),
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'viseme',
        'data': {'viseme_id': 4, 'timestamp_ms': 1500},
      }),
    );
    await _flush();

    expect(received, [(4, 1500)]);
  });

  test('unknown envelope type is silently dropped', () async {
    final fixture = _buildRoom();
    var emotionCalls = 0;
    var visemeCalls = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onViseme: (_, _) => visemeCalls++,
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'checkpoint_advanced',
        'data': {'checkpoint_id': 1},
      }),
    );
    await _flush();

    expect(emotionCalls, 0);
    expect(visemeCalls, 0);
  });

  test('malformed JSON does not crash and does not call back', () async {
    final fixture = _buildRoom();
    var emotionCalls = 0;
    var visemeCalls = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onViseme: (_, _) => visemeCalls++,
    );

    fixture.emitter.emit(_rawEnvelope(utf8.encode('not-json')));
    await _flush();

    expect(emotionCalls, 0);
    expect(visemeCalls, 0);
  });

  test('missing inner field is silently dropped', () async {
    final fixture = _buildRoom();
    var emotionCalls = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onViseme: (_, _) {},
    );

    fixture.emitter.emit(_envelope({'type': 'emotion', 'data': {}}));
    await _flush();

    expect(emotionCalls, 0);
  });

  test('non-numeric intensity falls back to 0.0 without crashing', () async {
    final fixture = _buildRoom();
    final received = <(String, double)>[];
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (e, i) => received.add((e, i)),
      onViseme: (_, _) {},
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'emotion',
        'data': {'emotion': 'smirk', 'intensity': 'oops'},
      }),
    );
    await _flush();

    expect(received, [('smirk', 0.0)]);
  });
}
