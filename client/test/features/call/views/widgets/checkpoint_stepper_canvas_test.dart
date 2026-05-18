import 'package:client/features/call/views/widgets/checkpoint_snapshot.dart';
import 'package:client/features/call/views/widgets/checkpoint_stepper_canvas.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rive/rive.dart' as rive;

/// Story 6.7 — widget tests for [CheckpointStepperCanvas].
///
/// Per `memory/rive-flutter-rules.md` §6 + AC8 rationale: Rive does
/// NOT load in widget tests, so every test below runs against the
/// fallback path (`RiveNative.isInitialized` is false). The substance
/// of the widget's correctness — writing 1-based step values to the
/// `stepsCount` / `lastCheckIndex` / `hintText` ViewModel inputs — is
/// validated on-device via the Smoke Test Gate, not here. These
/// widget tests are the "no crash on Rive-less environment" guard:
/// the parent `_CallScreenState.build` pumps `CheckpointStepperCanvas`
/// on every CallConnected frame, so any incidental test that mounts
/// the call screen also exercises this widget. A regression that
/// throws in fallback mode would cascade into dozens of unrelated
/// failures.

Widget _host({required CheckpointSnapshot? snapshot}) {
  return MaterialApp(
    home: Scaffold(
      body: CheckpointStepperCanvas(snapshot: snapshot),
    ),
  );
}

void main() {
  test('Rive native is NOT initialized in the widget-test env', () {
    // Sanity precondition for the fallback-path tests below. If Rive
    // ever gains a widget-test runtime in a future package upgrade,
    // these tests would need to be re-thought (or split into a
    // "Rive loaded" path with a real .riv fixture).
    expect(rive.RiveNative.isInitialized, isFalse);
  });

  testWidgets(
    'renders SizedBox.shrink() when snapshot is null',
    (tester) async {
      await tester.pumpWidget(_host(snapshot: null));
      await tester.pump();

      // The canvas itself is in the tree, but its build() short-circuits
      // to SizedBox.shrink() (no RiveWidgetBuilder rendered).
      expect(find.byType(CheckpointStepperCanvas), findsOneWidget);
      expect(find.byType(rive.RiveWidgetBuilder), findsNothing);

      // Concretely the build() returned a SizedBox.shrink — confirm by
      // measuring the rendered size (snap-null branch == zero size).
      final size = tester.getSize(find.byType(CheckpointStepperCanvas));
      expect(size, Size.zero);
    },
  );

  testWidgets(
    'renders SizedBox.shrink() in fallback when RiveNative is uninitialized',
    (tester) async {
      // Non-null snapshot, but RiveNative.isInitialized is false in
      // the widget-test env → the widget MUST silently render
      // SizedBox.shrink() instead of crashing. Without this guard,
      // every parent test that incidentally pumps the call screen
      // would crash here.
      await tester.pumpWidget(
        _host(
          snapshot: const CheckpointSnapshot(
            currentIndex: 2,
            total: 6,
            hintText: 'Tell the waiter what you want.',
          ),
        ),
      );
      // First pump lays out initState; second pump drains the
      // post-frame callback that flips `_riveFallback`.
      await tester.pump();
      await tester.pump();

      expect(find.byType(CheckpointStepperCanvas), findsOneWidget);
      expect(find.byType(rive.RiveWidgetBuilder), findsNothing);
      final size = tester.getSize(find.byType(CheckpointStepperCanvas));
      expect(size, Size.zero);
    },
  );

  testWidgets(
    'snapshot changes do NOT throw while in fallback mode',
    (tester) async {
      // The didUpdateWidget path runs `_applySnapshot`, which writes
      // to cached ViewModel handles via `?.value =`. In fallback mode
      // those handles are null — the null-safe writes must be a
      // no-op rather than throw.
      await tester.pumpWidget(
        _host(
          snapshot: const CheckpointSnapshot(
            currentIndex: 1,
            total: 6,
            hintText: 'A',
          ),
        ),
      );
      await tester.pump();
      await tester.pump();

      // Swap the snapshot — would throw if `_applySnapshot` did not
      // handle the null-handles case.
      await tester.pumpWidget(
        _host(
          snapshot: const CheckpointSnapshot(
            currentIndex: 3,
            total: 6,
            hintText: 'B',
          ),
        ),
      );
      await tester.pump();
      await tester.pump();

      expect(find.byType(CheckpointStepperCanvas), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
