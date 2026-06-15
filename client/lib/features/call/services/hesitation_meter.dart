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
    Duration minGap = const Duration(seconds: 3),
    Duration maxGap = const Duration(seconds: 10),
    // The viseme stack confirms silence ~600 ms AFTER the audio actually ended
    // (the REST-viseme confirmation window). Subtract it from the gap start so
    // the measured gap reflects the FELT pause, not the confirmation lag. The
    // exact value is tuned on the Pixel 9.
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
  }

  /// Feed one short-window mic RMS frame (from the native record-side tap).
  /// No-op when idle (the meter only listens during the post-character window).
  void onMicFrame(double rms) {
    if (_state == _MeterState.idle) return;
    final now = _clock();

    if (_state == _MeterState.seeding) {
      _seedSum += rms;
      _seedCount++;
      // Echo-tail guard: NO onset detection during the seed window — a residual
      // TTS reverb tail decaying here is folded into the floor.
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
      onHesitation(
        HesitationOnset(gapMs: (now - _gapStartTime).round(), censored: true),
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
          onHesitation(HesitationOnset(gapMs: gap.round(), censored: false));
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
