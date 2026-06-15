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
    int minGapMs = 3000,
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

  /// Seed the floor over EXACTLY the seed window (the 21st frame lands at
  /// 200 ms and completes seeding), leaving no ambient frame in the listening
  /// state that could falsely set the onset anchor.
  void seedFloor(HesitationMeter meter, {double ambient = 10}) {
    meter.arm();
    feed(meter, ambient, 21); // frames at 0,10,…,200 ms → completes on the last
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

  test('a sub-threshold gap (quick reply < 3 s) is NOT a hesitation', () {
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
    meter.arm();
    final armed = meter.isArmed;
    now = 50;
    meter.arm(); // ignored — no re-seed
    expect(armed, isTrue);
    // Seed then measure a normal gap to prove the FIRST arm's anchor is intact.
    feed(meter, 10, 25);
    now = 4000;
    feed(meter, 100, 15);
    expect(emitted.single.gapMs, 4000); // measured from the first arm (t=0)
  });

  test('idle frames are ignored (only listens after arm)', () {
    final meter = makeMeter();
    feed(meter, 1000, 50); // loud frames while idle
    expect(emitted, isEmpty);
    expect(meter.isArmed, isFalse);
  });

  test('confirmation offset compensates the ~600 ms viseme lag', () {
    final meter = makeMeter(confirmationOffsetMs: 600);
    seedFloor(meter, ambient: 10); // arm at t=0, gapStart = -600
    now = 4000;
    feed(meter, 100, 15); // onset at 4000
    // gap = onset(4000) − gapStart(−600) = 4600 (the felt pause, not the
    // confirmation-lagged 4000).
    expect(emitted.single.gapMs, 4600);
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
}
