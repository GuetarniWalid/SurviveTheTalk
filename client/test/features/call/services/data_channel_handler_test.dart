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
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
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
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
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
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
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
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
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

  test('viseme envelope is silently dropped (server no longer emits it)',
      () async {
    // Story 6.3b moved viseme generation to the client side. If a future
    // server regression starts emitting `type=viseme` again, the handler
    // must drop it without routing or throwing — AND must keep
    // processing subsequent envelopes on the same subscription. A throw
    // in the viseme branch would silently kill the LiveKit stream and
    // make future emotion envelopes vanish; the second emit below is
    // the trip-wire that catches that regression.
    final fixture = _buildRoom();
    var emotionCalls = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'viseme',
        'data': {'viseme_id': 4, 'timestamp_ms': 1500},
      }),
    );
    await _flush();
    expect(emotionCalls, 0, reason: 'viseme must not route to emotion');

    // Trip-wire: prove the subscription is still alive after the drop.
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
      reason: 'handler must still process emotion after dropping viseme — '
          'a throw in the viseme branch would have killed the stream',
    );
  });

  test('unknown envelope type is silently dropped', () async {
    final fixture = _buildRoom();
    var emotionCalls = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'checkpoint_advanced',
        'data': {'checkpoint_id': 1},
      }),
    );
    await _flush();

    expect(emotionCalls, 0);
  });

  test('malformed JSON does not crash and does not call back', () async {
    final fixture = _buildRoom();
    var emotionCalls = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
    );

    fixture.emitter.emit(_rawEnvelope(utf8.encode('not-json')));
    await _flush();

    expect(emotionCalls, 0);
  });

  test('missing inner field is silently dropped', () async {
    final fixture = _buildRoom();
    var emotionCalls = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) => emotionCalls++,
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
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
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
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

  // ----- Story 6.4 — hang_up_warning + call_end routing -----

  test('hang_up_warning envelope routes seconds_remaining to onHangUpWarning',
      () async {
    final fixture = _buildRoom();
    final warnings = <int>[];
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) {},
      onHangUpWarning: warnings.add,
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'hang_up_warning',
        'data': {'seconds_remaining': 5},
      }),
    );
    await _flush();

    expect(warnings, [5]);
  });

  test('hang_up_warning missing data field does not invoke callback',
      () async {
    final fixture = _buildRoom();
    var warnings = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) {},
      onHangUpWarning: (_) => warnings++,
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () {},
    );

    // Missing top-level `data` field: the outer guard rejects the
    // envelope before reaching the switch, so the callback is never
    // invoked. The trip-wire emit afterwards proves the subscription
    // is still alive.
    fixture.emitter.emit(_envelope({'type': 'hang_up_warning'}));
    await _flush();
    expect(warnings, 0);

    fixture.emitter.emit(
      _envelope({
        'type': 'hang_up_warning',
        'data': {'seconds_remaining': 3},
      }),
    );
    await _flush();
    expect(warnings, 1, reason: 'subscription must still be alive after drop');
  });

  test('call_end envelope routes reason + full data map to onCallEnd',
      () async {
    final fixture = _buildRoom();
    final received = <(String, Map<String, dynamic>)>[];
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) {},
      onHangUpWarning: (_) {},
      onCallEnd: (r, d) => received.add((r, d)),
      onBotSpeakingEnded: () {},
    );

    fixture.emitter.emit(
      _envelope({
        'type': 'call_end',
        'data': {
          'reason': 'character_hung_up',
          'survival_pct': 40,
          'checkpoints_passed': 2,
          'total_checkpoints': 5,
        },
      }),
    );
    await _flush();

    expect(received, hasLength(1));
    expect(received.first.$1, 'character_hung_up');
    expect(received.first.$2['survival_pct'], 40);
    expect(received.first.$2['checkpoints_passed'], 2);
    expect(received.first.$2['total_checkpoints'], 5);
  });

  test('call_end missing reason falls back to "unknown"', () async {
    final fixture = _buildRoom();
    final received = <(String, Map<String, dynamic>)>[];
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) {},
      onHangUpWarning: (_) {},
      onCallEnd: (r, d) => received.add((r, d)),
      onBotSpeakingEnded: () {},
    );

    fixture.emitter.emit(_envelope({'type': 'call_end', 'data': <String, dynamic>{}}));
    await _flush();

    expect(received, hasLength(1));
    expect(received.first.$1, 'unknown');
    expect(received.first.$2, <String, dynamic>{});
  });

  test('bot_speaking_ended envelope invokes onBotSpeakingEnded', () async {
    final fixture = _buildRoom();
    var endedCount = 0;
    DataChannelHandler(
      room: fixture.room,
      onEmotion: (_, _) {},
      onHangUpWarning: (_) {},
      onCallEnd: (_, _) {},
      onBotSpeakingEnded: () => endedCount++,
    );

    fixture.emitter.emit(
      _envelope({'type': 'bot_speaking_ended', 'data': <String, dynamic>{}}),
    );
    await _flush();

    expect(endedCount, 1);
  });
}
