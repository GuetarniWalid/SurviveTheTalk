import 'dart:convert';
import 'dart:developer' as dev;

import 'package:livekit_client/livekit_client.dart';

/// Decodes Pipecat-side data-channel envelopes and forwards them to typed
/// callbacks (Story 6.3).
///
/// Wire format: each envelope is a JSON object `{type, data}` where `type`
/// is a string discriminator. Pipecat's `LiveKitTransport.send_message`
/// JSON-encodes the dict produced by an `OutputTransportMessageFrame` and
/// broadcasts via `_client.send_data(message.encode())` (no `topic`,
/// no `participant_id`). The handler decodes UTF-8 bytes → JSON → switches
/// on `type`.
///
/// Visemes are NOT routed here — Story 6.3b moved viseme generation to
/// the client side (PCM-buffer analysis on the audio thread, see
/// `AudioClockChannel.kt` + `VisemeScheduler`). The server no longer
/// emits `type=viseme` envelopes; if a future server regression
/// reintroduces them they will be silently dropped via the `default`
/// branch.
///
/// One instance per active call. Constructed by `_CallScreenState` AFTER
/// the bloc enters `CallConnected` (i.e. once the LiveKit `Room` is bound)
/// and disposed in `_CallScreenState.dispose()` BEFORE `super.dispose()`.
///
/// Decode failures (malformed JSON, missing fields, unknown types) NEVER
/// surface to the UI — UX-DR6 forbids in-call error chrome. They are
/// logged at `dev.log` level FINE (700) for diagnostic value only.
class DataChannelHandler {
  DataChannelHandler({
    required Room room,
    required void Function(String emotion, double intensity) onEmotion,
  }) : _onEmotion = onEmotion {
    _cancel = room.events.on<DataReceivedEvent>(_onDataReceived);
  }

  final void Function(String emotion, double intensity) _onEmotion;
  CancelListenFunc? _cancel;

  Future<void> _onDataReceived(DataReceivedEvent event) async {
    final dynamic payload;
    try {
      final raw = utf8.decode(event.data);
      payload = jsonDecode(raw);
    } catch (e) {
      dev.log(
        'DataChannelHandler: malformed payload: $e',
        name: 'call.data',
        level: 700,
      );
      return;
    }
    if (payload is! Map<String, dynamic>) return;

    final type = payload['type'];
    final data = payload['data'];
    if (type is! String || data is! Map<String, dynamic>) return;

    switch (type) {
      case 'emotion':
        final emotion = data['emotion'];
        final intensity = data['intensity'];
        if (emotion is String && emotion.isNotEmpty) {
          final i = (intensity is num) ? intensity.toDouble() : 0.0;
          _onEmotion(emotion, i);
        }
      default:
        // Owned by Stories 6.4 (`hang_up_warning`, `call_end`) / 6.7
        // (`checkpoint_advanced`). Additive routing — silently ignore
        // unknown types so a server-side rollout can land emitters before
        // the matching client handler ships.
        dev.log(
          'DataChannelHandler: ignoring unknown type=$type',
          name: 'call.data',
          level: 700,
        );
    }
  }

  /// Cancels the LiveKit subscription. Idempotent — calling twice does
  /// not double-cancel (the second call is a no-op). Errors from the
  /// LiveKit cancel function are caught and logged at FINE so a regressed
  /// SDK throw does not surface as an unhandled future error (the caller
  /// in `_CallScreenState.dispose()` uses `unawaited(...)` because
  /// `State.dispose()` is sync).
  Future<void> dispose() async {
    final cancel = _cancel;
    _cancel = null;
    if (cancel != null) {
      try {
        await cancel();
      } catch (e, st) {
        dev.log(
          'DataChannelHandler: cancel failed: $e',
          name: 'call.data',
          level: 700,
          error: e,
          stackTrace: st,
        );
      }
    }
  }
}
