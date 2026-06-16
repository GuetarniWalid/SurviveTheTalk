// Story 7.5 (D3-c) — HesitationMeter onset-detection tests.
//
// Pure logic on canned RMS sequences with a controllable monotonic clock — no
// live call, no native. The "money" test is `steady background noise never
// trips onset`: the product-owner failure mode, proven defeated by the adaptive
// floor + SNR margin.

import 'package:client/features/call/services/hesitation_meter.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late double now;
  late List<HesitationOnset> emitted;

  /// A meter with short, deterministic windows. `confirmationOffset: 0` keeps
  /// the gap = onset − arm in most tests (a dedicated test covers the offset).
  HesitationMeter makeMeter({
    double snrThreshold = 2.5,
    int seedMs = 200,
    int debounceMs = 100,
    int minGapMs = 4000, // Story 7.6 — aligned to the bot-side 4 s threshold
    int maxGapMs = 10000,
    int confirmationOffsetMs = 0,
    double floorCeiling = 4000.0,
  }) {
    return HesitationMeter(
      onHesitation: emitted.add,
      snrThreshold: snrThreshold,
      seedWindow: Duration(milliseconds: seedMs),
      debounce: Duration(milliseconds: debounceMs),
      minGap: Duration(milliseconds: minGapMs),
      maxGap: Duration(milliseconds: maxGapMs),
      confirmationOffset: Duration(milliseconds: confirmationOffsetMs),
      floorCeiling: floorCeiling,
      clockMs: () => now,
    );
  }

  /// Feed `count` frames of `rms`, advancing the clock `stepMs` between each.
  void feed(HesitationMeter meter, double rms, int count, {int stepMs = 10}) {
    for (var i = 0; i < count; i++) {
      meter.onMicFrame(rms);
      now += stepMs;
    }
  }

  /// Seed the floor by driving the clock STRICTLY past the seed window, so
  /// seeding completes by elapsed TIME — NOT by a frame index that happens to
  /// land on the window edge (Story 7.6 re-pin to logic). Leaves the meter in
  /// the listening state with the floor frozen at `ambient`.
  void seedFloor(HesitationMeter meter, {double ambient = 10, int seedMs = 200}) {
    meter.arm();
    final armAt = now;
    while (now <= armAt + seedMs) {
      meter.onMicFrame(ambient);
      now += 10;
    }
  }

  setUp(() {
    now = 0;
    emitted = <HesitationOnset>[];
  });

  test('measures a clean ~4 s freeze in a quiet room', () {
    final meter = makeMeter();
    seedFloor(meter, ambient: 10); // floor ≈ 10, now ≈ 250
    // Stay silent (at the floor) until ~4000 ms, then the user speaks loudly.
    now = 4000;
    feed(meter, 100, 15); // snr = 10, sustained past the 100 ms debounce

    expect(emitted, hasLength(1));
    expect(emitted.single.censored, isFalse);
    // Onset at the FIRST loud frame (4000 ms), gap measured from arm (0).
    expect(emitted.single.gapMs, 4000);
  });

  test('MONEY TEST: steady loud background noise never trips onset', () {
    final meter = makeMeter();
    // Seed the floor in a LOUD-but-steady room (e.g. a fan/traffic at 500).
    seedFloor(meter, ambient: 500); // floor ≈ 500
    // Keep feeding the SAME steady level — snr ≈ 1, never the 2.5 margin.
    feed(meter, 500, 1000); // 1000 * 10 ms = 10 s → crosses the max-gap budget

    // No false onset; the anchor closes as CENSORED (the server falls back),
    // NOT as a ~0 ms gap (the failure mode).
    expect(emitted, hasLength(1));
    expect(emitted.single.censored, isTrue);
    expect(emitted.single.gapMs, greaterThan(0));
  });

  test('a transient (single loud frame) does not confirm onset', () {
    final meter = makeMeter();
    seedFloor(meter, ambient: 10);
    now = 4000;
    meter.onMicFrame(100); // spike — snr 10, aboveSince set
    now = 4010;
    meter.onMicFrame(10); // drops back before the 100 ms debounce → reset
    now = 4020;
    meter.onMicFrame(10);
    // No onset from the transient.
    expect(emitted, isEmpty);
  });

  test('a quiet speaker just above the floor is still detected', () {
    final meter = makeMeter();
    seedFloor(meter, ambient: 10); // floor ≈ 10
    now = 5000;
    feed(meter, 30, 15); // snr = 3 (> 2.5), sustained → onset
    expect(emitted, hasLength(1));
    expect(emitted.single.censored, isFalse);
    expect(emitted.single.gapMs, 5000);
  });

  test('a sub-threshold gap (quick reply < 4 s) is NOT a hesitation', () {
    final meter = makeMeter();
    seedFloor(meter, ambient: 10);
    now = 1500; // user replies after 1.5 s
    feed(meter, 100, 15);
    expect(emitted, isEmpty);
    expect(meter.isArmed, isFalse); // anchor closed silently
  });

  test('disarm before onset emits nothing (re-speak is the server\'s job)', () {
    final meter = makeMeter();
    seedFloor(meter, ambient: 10);
    now = 4000;
    meter.disarm(); // the character started speaking again
    feed(meter, 100, 15); // frames after disarm are ignored
    expect(emitted, isEmpty);
  });

  test('arm is idempotent — a second arm without disarm is ignored', () {
    final meter = makeMeter();
    meter.arm(); // anchor at t=0
    expect(meter.isArmed, isTrue);
    now = 50;
    meter.arm(); // state != idle → ignored, the anchor must NOT move to t=50
    // Complete seeding by TIME (not a frame count), then measure a real freeze.
    while (now <= 200) {
      meter.onMicFrame(10);
      now += 10;
    }
    now = 4000;
    feed(meter, 100, 15);
    // gap measured from the FIRST arm (t=0); a took-effect second arm would
    // anchor at t=50 and yield 3950.
    expect(emitted.single.gapMs, 4000);
  });

  test('idle frames are ignored (only listens after arm)', () {
    final meter = makeMeter();
    feed(meter, 1000, 50); // loud frames while idle
    expect(emitted, isEmpty);
    expect(meter.isArmed, isFalse);
  });

  test('confirmation offset adds the calibrated playout/confirmation lag', () {
    // Story 7.6 — the production default (1700 ms, Pixel 9-calibrated)
    // compensates the playout + REST-confirmation lag so the gap reflects the
    // FELT pause, not the confirmation-lagged onset.
    final meter = makeMeter(confirmationOffsetMs: 1700);
    seedFloor(meter, ambient: 10); // arm at t=0, gapStart = -1700
    now = 5000;
    feed(meter, 100, 15); // onset at 5000
    // gap = onset(5000) − gapStart(−1700) = 6700 (the felt pause, not 5000).
    expect(emitted.single.gapMs, 6700);
  });

  test('the floor ceiling protects a quiet speaker in a moderately loud room',
      () {
    // A very loud seed would otherwise demand impossibly loud speech; the
    // ceiling caps the floor so a normal voice can still clear the SNR margin.
    final meter = makeMeter(floorCeiling: 200);
    seedFloor(meter, ambient: 1000); // raw seed 1000, clamped to 200
    now = 4000;
    feed(meter, 600, 15); // snr vs ceiling = 600/200 = 3 (> 2.5) → onset
    expect(emitted, hasLength(1));
    expect(emitted.single.censored, isFalse);
  });

  test('Story 7.6: the emitted gap is clamped to >= 0', () {
    // The measured-gap clamp is purely defensive: a negative raw gap is
    // normally rejected by the `gap >= minGap` gate (minGap >= 0). To OBSERVE
    // the clamp we open that gate with a negative minGap, then drive a negative
    // raw gap via a pathological negative confirmation offset (gapStart pushed
    // AFTER the arm). Without the clamp this would publish gapMs = −1500.
    final meter = makeMeter(confirmationOffsetMs: -2000, minGapMs: -2000);
    seedFloor(meter); // arm at t=0 → gapStart = 0 − (−2000) = +2000
    now = 500; // onset BEFORE gapStart → raw gap = 500 − 2000 = −1500
    feed(meter, 100, 15);
    expect(emitted, hasLength(1));
    expect(emitted.single.gapMs, 0); // clamped, NOT −1500
    expect(emitted.single.gapMs, greaterThanOrEqualTo(0));
  });

  test('Story 7.6: the censored sentinel gap is also clamped to >= 0', () {
    // An offset larger than the whole max-gap budget would make the censored
    // elapsed-budget gap negative without the clamp.
    final meter = makeMeter(confirmationOffsetMs: -15000, maxGapMs: 10000);
    seedFloor(meter); // arm at t=0 → gapStart = +15000
    // Never speak; ride out the 10 s max-gap budget → censored sentinel.
    feed(meter, 10, 1100); // 1100 × 10 ms = 11 s, crosses maxGap
    expect(emitted, hasLength(1));
    expect(emitted.single.censored, isTrue);
    expect(emitted.single.gapMs, greaterThanOrEqualTo(0)); // clamped, not negative
  });

  test('Story 7.6: disarm() clears the seeded floor (no stale floor on re-arm)',
      () {
    final meter = makeMeter();
    seedFloor(meter, ambient: 100); // floor seeded to ~100
    expect(meter.debugFloor, greaterThan(0));
    meter.disarm();
    expect(meter.debugFloor, 0); // reset on disarm, not left stale for re-arm
  });

  test('Story 7.6: the floor is seeded only from ambient, then frozen', () {
    final meter = makeMeter();
    seedFloor(meter, ambient: 10);
    expect(meter.debugFloor, closeTo(10, 0.0001)); // seeded from ambient frames
    now = 4000;
    // Two loud frames WITHIN the debounce window — onset is detected-but-not-yet
    // -confirmed, so it does NOT disarm (which would reset the floor). Proves the
    // floor stays frozen at the ambient seed while listening (a creeping floor
    // would suppress later onsets — an under-production cause).
    meter.onMicFrame(100);
    meter.onMicFrame(100); // same `now` → < debounce → no onset confirmed
    expect(meter.isArmed, isTrue);
    expect(meter.debugFloor, closeTo(10, 0.0001));
  });
}
