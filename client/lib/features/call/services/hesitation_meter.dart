// Story 7.5 (D3-c) — device-local, noise-robust hesitation onset meter.
//
// Measures the "hesitation" gap ON the phone: the felt pause between the
// character's audio finishing (the Story 6.3b viseme stack's
// `onSilenceConfirmed`, which ARMS this meter) and the user's speech ONSET at
// the mic. Onset is detected from a stream of short-window mic RMS frames
// (emitted by the native record-side tap, `AudioCaptureChannel`) using an
// adaptive noise FLOOR + an SNR margin + a sustained-duration debounce.
//
// WHY this defeats the product-owner failure mode ("background noise sits above
// a fixed threshold, so the device thinks the user is always speaking and NO
// blank is ever detected"): the floor is SEEDED from the known-silent arm
// window (the character just went silent and the user has not spoken yet — a
// clean per-gap ambient estimate) and FROZEN; onset triggers on SNR ABOVE that
// floor, never on absolute level. A steady noisy room sits at ~0 dB over its own
// floor and can NEVER read as permanent speech.
//
// The character's audio bleeding into the mic is rejected by ARCHITECTURE, not
// echo-cancellation: the meter is DISARMED while the character speaks, so it
// only listens during the post-character silence window. An echo-tail guard (no
// onset during seeding) folds a residual TTS reverb into the floor.
//
// Mandatory guards (Story 7.5 mic-onset noise-robustness spike — see the story
// Debug Log addendum): seed-then-freeze the floor, a floor CEILING (quiet-
// speaker protection; there is no AGC in this capture path), and a MAX-GAP
// timeout that emits a CENSORED sentinel (never 0, never infinity) so a missed
// quiet-speaker onset degrades to the server fallback instead of garbage.
//
// Honest limit (deferred): NON-stationary noise (a TV, a second talker) is
// speech-like and defeats energy+floor by construction — that case relies on
// the server `EnvironmentMonitor`/`env_warning` path + a future on-device VAD
// upgrade. Final accuracy (±0.5 s, noise rejection) is proven on the Pixel 9.
//
// Pure Dart + an injected monotonic clock → fully unit-testable on canned RMS
// sequences (no live call, no native).

import 'dart:math' as math;

/// A closed hesitation measurement, published up the data channel to the bot.
class HesitationOnset {
  /// Felt gap, ms — onset time minus the (offset-compensated) character-silence
  /// time. Both boundaries are on-device, so no network term enters the gap.
  final int gapMs;

  /// True when the onset could NOT be measured (max-gap timeout / quiet-speaker
  /// miss): the server falls back to its own observer for this turn. A censored
  /// onset still carries the elapsed budget as `gapMs` — never 0, never
  /// infinity.
  final bool censored;

  const HesitationOnset({required this.gapMs, required this.censored});

  @override
  String toString() => 'HesitationOnset(gapMs: $gapMs, censored: $censored)';
}

enum _MeterState { idle, seeding, listening }

/// Default monotonic clock (ms). Wiring injects a `Stopwatch`-backed source;
/// this fallback is only used if none is provided.
double _defaultClockMs() => DateTime.now().microsecondsSinceEpoch / 1000.0;

class HesitationMeter {
  HesitationMeter({
    required this.onHesitation,
    double snrThreshold = 2.5, // ~8 dB over the adaptive floor
    double minFloor = 1.0, // avoids div-by-zero / silence over-sensitivity
    double floorCeiling = 4000.0, // quiet-speaker protection (no AGC here)
    Duration seedWindow = const Duration(milliseconds: 250),
    Duration debounce = const Duration(milliseconds: 200),
    // Story 7.6 — aligned to 4 s to match the bot-side `DeviceHesitationCollector`
    // / `HesitationObserver` threshold (4.0 s). A 3-4 s gap emitted under the old
    // 3 s floor was recorded then DROPPED server-side; emitting at 4 s removes
    // that wasted uplink and the silent server drop. (The collector drops
    // duration <= 4.0 while this emits gap >= 4.0 — the exact-4000 ms boundary is
    // a sub-ms non-issue at real freeze durations.)
    Duration minGap = const Duration(seconds: 4),
    Duration maxGap = const Duration(seconds: 10),
    // The viseme stack confirms silence ~600 ms AFTER the audio actually ended
    // (the REST-viseme confirmation window — the SAME window that drives
    // `playback_idle`). Subtract it from the gap start so the measured gap
    // reflects the FELT pause (from when the user's EAR heard silence), not the
    // confirmation lag. Story 7.6: the value is COUPLED to that window; the
    // gap-≥-0 clamp below makes any future offset arithmetic safe, and the exact
    // value is reconciled against the ±0.5 s accuracy target on the Pixel 9.
    Duration confirmationOffset = const Duration(milliseconds: 600),
    double Function()? clockMs,
  }) : _snrThreshold = snrThreshold,
       _minFloor = minFloor,
       _floorCeiling = floorCeiling,
       _seedWindowMs = seedWindow.inMilliseconds.toDouble(),
       _debounceMs = debounce.inMilliseconds.toDouble(),
       _minGapMs = minGap.inMilliseconds.toDouble(),
       _maxGapMs = maxGap.inMilliseconds.toDouble(),
       _confirmationOffsetMs = confirmationOffset.inMilliseconds.toDouble(),
       _clock = clockMs ?? _defaultClockMs;

  final void Function(HesitationOnset onset) onHesitation;
  final double _snrThreshold;
  final double _minFloor;
  final double _floorCeiling;
  final double _seedWindowMs;
  final double _debounceMs;
  final double _minGapMs;
  final double _maxGapMs;
  final double _confirmationOffsetMs;
  final double Function() _clock;

  _MeterState _state = _MeterState.idle;
  double _armRealTime = 0; // actual clock at arm — drives seed/debounce/max-gap
  double _gapStartTime = 0; // offset-compensated — drives the measured gap only
  double _seedSum = 0;
  int _seedCount = 0;
  double _floor = 0;
  double? _aboveSince;

  /// Visible for tests / debugging: the current state name.
  bool get isArmed => _state != _MeterState.idle;

  /// Visible for tests: the current adaptive noise floor — 0 while idle or
  /// immediately after `arm()`/`disarm()` reset it, the seeded ambient value
  /// while listening. Lets a unit test assert the floor is seeded only from
  /// ambient (and frozen, and cleared on disarm) without reaching into private
  /// state. Story 7.6 (AC7/AC9).
  double get debugFloor => _floor;

  /// Arm at the character's audio end (`onSilenceConfirmed`). Idempotent: a
  /// second arm without an intervening disarm is ignored (one anchor at a time).
  void arm() {
    if (_state != _MeterState.idle) return;
    _state = _MeterState.seeding;
    _armRealTime = _clock();
    _gapStartTime = _armRealTime - _confirmationOffsetMs;
    _seedSum = 0;
    _seedCount = 0;
    _floor = 0;
    _aboveSince = null;
  }

  /// Disarm — the character started speaking again (a re-speak freeze is the
  /// SERVER observer's job, C2), the user was muted, or the call ended. No
  /// measurement is emitted.
  void disarm() {
    _state = _MeterState.idle;
    // Story 7.6 (AC7) — clear the seed/floor accumulators on disarm so a later
    // `arm()` can NEVER inherit a stale floor (a high floor left over from a
    // prior loud window would suppress the next onset — an under-production
    // cause). `arm()` resets these too; resetting here keeps the invariant
    // local to disarm and defends a future arm() that forgets to.
    _seedSum = 0;
    _seedCount = 0;
    _floor = 0;
    _aboveSince = null;
  }

  /// Feed one short-window mic RMS frame (from the native record-side tap).
  /// No-op when idle (the meter only listens during the post-character window).
  void onMicFrame(double rms) {
    if (_state == _MeterState.idle) return;
    final now = _clock();

    if (_state == _MeterState.seeding) {
      _seedSum += rms;
      _seedCount++;
      // Story 7.6 (AC7) — the floor is seeded ONLY from genuine post-character
      // ambient: `arm()` fires at `onSilenceConfirmed`, AFTER the viseme stack
      // already confirmed the character's audio ended (the same window that
      // gates `playback_idle`), so no TTS tail is live in the seed window; and
      // an idle meter no-ops frames (above), so no PRE-arm frame can enter
      // `_seedSum`. Echo-tail guard: NO onset detection during the seed window —
      // any residual TTS reverb decaying here is folded into the floor, not read
      // as the user's onset.
      if (now - _armRealTime >= _seedWindowMs) {
        final seeded = _seedCount > 0 ? _seedSum / _seedCount : _minFloor;
        _floor = seeded.clamp(_minFloor, _floorCeiling);
        _state = _MeterState.listening;
        _aboveSince = null;
      }
      return;
    }

    // listening
    if (now - _armRealTime >= _maxGapMs) {
      // Quiet-speaker miss / the user never spoke — emit a CENSORED sentinel so
      // the server falls back to its observer for this turn (never 0/infinity).
      // Story 7.6 (AC7) — clamp ≥ 0 so the confirmation-offset arithmetic can
      // never yield a negative gap.
      onHesitation(
        HesitationOnset(
          gapMs: math.max(0.0, now - _gapStartTime).round(),
          censored: true,
        ),
      );
      disarm();
      return;
    }
    final snr = rms / _floor;
    if (snr >= _snrThreshold) {
      // The felt onset is when energy FIRST crossed; the debounce only confirms
      // it is sustained speech, not a transient — it must NOT add to the gap.
      _aboveSince ??= now;
      if (now - _aboveSince! >= _debounceMs) {
        final gap = _aboveSince! - _gapStartTime;
        if (gap >= _minGapMs) {
          // Story 7.6 (AC7) — clamp ≥ 0; a defensive guard so no future offset
          // arithmetic can publish a negative gap.
          onHesitation(
            HesitationOnset(gapMs: math.max(0.0, gap).round(), censored: false),
          );
        }
        // A sub-threshold gap (normal quick reply) is NOT a hesitation — close
        // the anchor silently.
        disarm();
      }
    } else {
      // Energy dropped before sustaining → a transient (cough, click), not
      // speech onset. Reset the debounce.
      _aboveSince = null;
    }
  }
}
