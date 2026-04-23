import 'package:vibration/vibration.dart';

/// Thin wrapper around the `vibration` package so the incoming-call screen
/// and bloc can be unit-tested without hitting the platform channel (the
/// real `Vibration` API throws on headless test runners).
///
/// iOS note: the underlying package falls back to repeated
/// `HapticFeedback.mediumImpact()` on iOS because iOS does not expose a
/// true custom-pattern vibration API. This is acceptable per the design
/// doc — the visual ring animation carries most of the "incoming call"
/// affordance, vibration is a secondary cue.
class VibrationService {
  /// Ring cadence: [pause, vibrate, pause, vibrate, pause] (ms).
  static const List<int> _kRingPattern = <int>[0, 800, 400, 800, 1600];

  /// Start a continuously-looping ring vibration. No-op on devices without
  /// a vibrator (tablets, some emulators).
  Future<void> startRingPattern() async {
    final bool hasVibrator = await Vibration.hasVibrator();
    if (!hasVibrator) return;
    await Vibration.vibrate(pattern: _kRingPattern, repeat: 0);
  }

  /// Stop any active vibration immediately. Safe to call even if no
  /// vibration is running.
  Future<void> stop() async {
    await Vibration.cancel();
  }
}
