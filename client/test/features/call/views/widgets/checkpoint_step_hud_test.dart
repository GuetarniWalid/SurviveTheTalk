import 'package:client/features/call/views/widgets/checkpoint_snapshot.dart';
import 'package:client/features/call/views/widgets/checkpoint_step_hud.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Story 6.10 UI refonte — widget tests for [CheckpointStepHud], the
/// Flutter-native checkpoint HUD that replaced the Rive stepper. These
/// assert the deterministic behaviours (which step text is shown, the
/// hide-when-empty contract, the completion → next-step transition, the
/// out-of-order detour back to the active step). The exact animation
/// feel is validated on-device via the Smoke Test Gate.
///
/// NOTE: the widget renders the step text TWICE — once visible, once in
/// an invisible 0-opacity "mirror" used to size the box to 2× the content
/// (so the text always lands in the solid top half of the dark gradient).
/// So a present step matches `findsWidgets` (≥1, actually 2); the
/// complementary absence checks (`findsNothing` for the wrong step) are
/// what prove the RIGHT step is shown.

Widget _host(CheckpointSnapshot? snapshot) {
  return MaterialApp(
    home: Scaffold(
      body: Align(
        alignment: Alignment.topCenter,
        child: CheckpointStepHud(snapshot: snapshot),
      ),
    ),
  );
}

const _hints = ['greet', 'order', 'drink', 'clarify', 'confirm', 'thanks'];

CheckpointSnapshot _snap({
  required List<int> met,
  int total = 6,
  int? flipped,
}) {
  return CheckpointSnapshot(
    hints: _hints,
    metIndices: met,
    total: total,
    justFlippedIndex: flipped,
  );
}

/// Pump generously so the serialized animation chain (Future.delayed +
/// AnimatedSwitcher) fully settles. Several discrete pumps ensure each
/// chained timer fires.
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 400));
  }
}

void main() {
  testWidgets('renders nothing when snapshot is null', (tester) async {
    await tester.pumpWidget(_host(null));
    await tester.pump();
    expect(find.byType(Row), findsNothing);
    expect(find.byType(Text), findsNothing);
  });

  testWidgets('renders nothing when hints are empty', (tester) async {
    await tester.pumpWidget(
      _host(
        const CheckpointSnapshot(
          hints: <String>[],
          metIndices: <int>[],
          total: 6,
        ),
      ),
    );
    await tester.pump();
    expect(find.byType(Text), findsNothing);
  });

  testWidgets('shows the active (first not-yet-met) step on initial state', (
    tester,
  ) async {
    await tester.pumpWidget(_host(_snap(met: const [])));
    await tester.pump();
    expect(find.text('greet'), findsWidgets);
  });

  testWidgets('active step skips already-met goals (author order)', (
    tester,
  ) async {
    // Goals 0 + 1 already met → the active step is index 2 ('drink').
    await tester.pumpWidget(_host(_snap(met: const [0, 1])));
    await tester.pump();
    expect(find.text('drink'), findsWidgets);
    expect(find.text('greet'), findsNothing);
  });

  testWidgets('in-order completion advances to the next step', (tester) async {
    // Start showing step 0 ('greet'), nothing met.
    await tester.pumpWidget(_host(_snap(met: const [])));
    await tester.pump();
    expect(find.text('greet'), findsWidgets);

    // Step 0 completes (in order) → after the completion animation the HUD
    // settles on the next step ('order').
    await tester.pumpWidget(_host(_snap(met: const [0], flipped: 0)));
    await _settle(tester);
    expect(find.text('order'), findsWidgets);
    expect(find.text('greet'), findsNothing);
  });

  testWidgets(
    'out-of-order completion returns to the still-pending active step',
    (tester) async {
      // Showing step 0 ('greet'); user completes step 3 ('clarify') out of
      // order. The active step is still index 0 → after the detour the HUD
      // settles back on 'greet'.
      await tester.pumpWidget(_host(_snap(met: const [])));
      await tester.pump();
      expect(find.text('greet'), findsWidgets);

      await tester.pumpWidget(_host(_snap(met: const [3], flipped: 3)));
      await _settle(tester);
      expect(find.text('greet'), findsWidgets);
    },
  );

  testWidgets(
    'two goals completing in one turn both animate, then settle on next pending',
    (tester) async {
      // Regression for the call_id=183 bug: asking for water flipped BOTH
      // greet(0) and drink-index(3) in one turn; the HUD used to animate
      // only the first and swallow the second. Now it animates each
      // newly-met goal off the full set, then settles on the next pending
      // step (index 1 = 'order').
      await tester.pumpWidget(_host(_snap(met: const [])));
      await tester.pump();
      expect(find.text('greet'), findsWidgets);

      await tester.pumpWidget(_host(_snap(met: const [0, 3], flipped: 3)));
      await _settle(tester);

      // Both met goals are no longer the active step; the HUD settled on
      // the first still-pending one (index 1 → 'order').
      expect(find.text('order'), findsWidgets);
      expect(find.text('greet'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('hides after the final objective is met', (tester) async {
    // One objective left (index 5). It completes → all met → HUD hides.
    await tester.pumpWidget(
      _host(_snap(met: const [0, 1, 2, 3, 4])),
    );
    await tester.pump();
    expect(find.text('thanks'), findsWidgets);

    await tester.pumpWidget(
      _host(_snap(met: const [0, 1, 2, 3, 4, 5], flipped: 5)),
    );
    await _settle(tester);
    expect(find.byType(Text), findsNothing);
  });

  testWidgets('no crash when disposed mid-completion-animation', (
    tester,
  ) async {
    await tester.pumpWidget(_host(_snap(met: const [])));
    await tester.pump();
    await tester.pumpWidget(_host(_snap(met: const [0], flipped: 0)));
    await tester.pump(const Duration(milliseconds: 100));
    // Tear the widget down while the chain is still running.
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(seconds: 2));
    expect(tester.takeException(), isNull);
  });
}
