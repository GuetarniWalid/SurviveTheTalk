import 'dart:convert';
import 'dart:developer' as dev;

import 'package:livekit_client/livekit_client.dart';

import 'checkpoint_advanced_payload.dart';

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
    required void Function(int secondsRemaining) onHangUpWarning,
    required void Function(String reason, Map<String, dynamic> data) onCallEnd,
    required void Function() onBotSpeakingEnded,
    required void Function(CheckpointAdvancedPayload payload)
    onCheckpointAdvanced,
  }) : _onEmotion = onEmotion,
       _onHangUpWarning = onHangUpWarning,
       _onCallEnd = onCallEnd,
       _onBotSpeakingEnded = onBotSpeakingEnded,
       _onCheckpointAdvanced = onCheckpointAdvanced {
    _cancel = room.events.on<DataReceivedEvent>(_onDataReceived);
  }

  final void Function(String emotion, double intensity) _onEmotion;
  final void Function(int secondsRemaining) _onHangUpWarning;
  final void Function(String reason, Map<String, dynamic> data) _onCallEnd;
  final void Function() _onBotSpeakingEnded;
  final void Function(CheckpointAdvancedPayload payload) _onCheckpointAdvanced;
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
      case 'hang_up_warning':
        // Story 6.4 — server signals an imminent hang-up so the client
        // can prepare (no UI in 6.4; future stories may wire a visual
        // countdown). Defensive default of 5 s mirrors the server-side
        // emit shape (`seconds_remaining: 5`).
        final seconds = data['seconds_remaining'];
        if (seconds is! num) {
          // Defaulting silently here hid a wire-protocol regression
          // during the smoke loop: log the fall-back so a future
          // server-side envelope shape drift surfaces in the diagnostic
          // tail without the client misrendering a countdown.
          dev.log(
            'DataChannelHandler: hang_up_warning missing/invalid '
            'seconds_remaining (got ${seconds.runtimeType}); defaulting to 5',
            name: 'call.data',
            level: 700,
          );
        }
        final n = (seconds is num) ? seconds.toInt() : 5;
        _onHangUpWarning(n);
      case 'call_end':
        // Story 6.4 — character-driven end of call. Carries the reason
        // (`character_hung_up` / `inappropriate_content`) plus the
        // `survival_pct` + checkpoint counters consumers may render in
        // a future debrief screen. Missing `reason` falls back to
        // `unknown` so the bloc still treats this as a clean end.
        final reason = data['reason'];
        if (reason is! String) {
          // Same posture as `hang_up_warning`: a regressed server-side
          // emit (reason as int, null, missing entirely) defaults the
          // client to `unknown` instead of crashing — log so the
          // diagnostic tail surfaces the drift.
          dev.log(
            'DataChannelHandler: call_end missing/invalid reason '
            '(got ${reason.runtimeType}); defaulting to "unknown"',
            name: 'call.data',
            level: 700,
          );
        }
        final reasonStr = reason is String ? reason : 'unknown';
        _onCallEnd(reasonStr, data);
      case 'checkpoint_advanced':
        // Story 6.7 — server emits this on initial-state (index=0 at
        // bot startup; `bot.py::on_first_participant_joined` calls
        // `CheckpointManager.emit_initial_state()` AFTER the canned
        // greeting) AND on every checkpoint advance (index>0). Single
        // envelope shape for both; the client treats them identically.
        // Same defensive-parse posture as the other cases: validate
        // every field's type, default on missing/wrong-type, log at
        // FINE on drift, NEVER throw.
        final id = data['checkpoint_id'];
        final idx = data['index'];
        final total = data['total'];
        final hint = data['next_hint'];
        if (id is! String ||
            idx is! num ||
            total is! num ||
            hint is! String) {
          dev.log(
            'DataChannelHandler: checkpoint_advanced malformed payload: '
            'id=${id.runtimeType} idx=${idx.runtimeType} '
            'total=${total.runtimeType} hint=${hint.runtimeType}',
            name: 'call.data',
            level: 700,
          );
          return;
        }
        final idxInt = idx.toInt();
        final totalInt = total.toInt();
        // Defensive: a server-side bug or future spec drift that sends
        // index > total-1, or total <= 0, must not crash the stepper.
        if (totalInt <= 0 || idxInt < 0 || idxInt >= totalInt) {
          dev.log(
            'DataChannelHandler: checkpoint_advanced out-of-range: '
            'idx=$idxInt total=$totalInt',
            name: 'call.data',
            level: 700,
          );
          return;
        }
        _onCheckpointAdvanced(
          CheckpointAdvancedPayload(
            checkpointId: id,
            index: idxInt,
            total: totalInt,
            hintText: hint,
          ),
        );
      case 'bot_speaking_ended':
        // Story 6.4 — server signals that THIS bot turn is over (its
        // outbound audio buffer drained). The screen uses this as
        // the arming gate for the next `playback_idle` upstream
        // publish: only AFTER `bot_speaking_ended` does the next
        // confirmed silence count as "user's speaker drained".
        // Without this gate, intra-utterance Cartesia pauses (~600 ms
        // between sentences in a multi-sentence greeting) would be
        // mis-classified as "bot turn over" and trigger a premature
        // ladder start.
        _onBotSpeakingEnded();
      default:
        // Additive routing — silently ignore unknown types so a
        // server-side rollout can land emitters before the matching
        // client handler ships.
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
