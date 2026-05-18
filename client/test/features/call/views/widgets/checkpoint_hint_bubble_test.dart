import 'package:client/core/theme/app_colors.dart';
import 'package:client/features/call/views/widgets/checkpoint_hint_bubble.dart';
import 'package:client/features/call/views/widgets/checkpoint_snapshot.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Story 6.7 Phase 2 retouche #11 — widget tests for the Flutter
/// hint bubble that replaced the Rive bubble after the runtime
/// Hug-Height bug was confirmed (see
/// `memory/feedback_rive_runtime_hug_height_bug.md`).

Widget _host({required CheckpointSnapshot? snapshot}) {
  return MaterialApp(
    home: Scaffold(
      body: Center(child: CheckpointHintBubble(snapshot: snapshot)),
    ),
  );
}

void main() {
  testWidgets(
    'renders SizedBox.shrink() when snapshot is null',
    (tester) async {
      await tester.pumpWidget(_host(snapshot: null));
      await tester.pump();

      expect(find.byType(CheckpointHintBubble), findsOneWidget);
      expect(find.byType(Container), findsNothing);
      expect(find.byType(Text), findsNothing);
    },
  );

  testWidgets(
    'renders SizedBox.shrink() when hintText is empty',
    (tester) async {
      await tester.pumpWidget(
        _host(
          snapshot: const CheckpointSnapshot(
            currentIndex: 0,
            total: 6,
            hintText: '',
          ),
        ),
      );
      await tester.pump();

      expect(find.byType(CheckpointHintBubble), findsOneWidget);
      expect(find.byType(Text), findsNothing);
      // Verify the empty-state child is actually a SizedBox.shrink (not
      // some other zero-size widget) — the AnimatedSwitcher keeps a
      // keyed SizedBox.shrink so non-empty → empty fades out.
      final sizedBox = tester.widget<SizedBox>(
        find.descendant(
          of: find.byType(CheckpointHintBubble),
          matching: find.byType(SizedBox),
        ),
      );
      expect(sizedBox.width, 0.0);
      expect(sizedBox.height, 0.0);
    },
  );

  testWidgets(
    'renders the hint text with the bubble fill and text colors',
    (tester) async {
      await tester.pumpWidget(
        _host(
          snapshot: const CheckpointSnapshot(
            currentIndex: 0,
            total: 6,
            hintText: 'Tell the waitress you want to order.',
          ),
        ),
      );
      await tester.pump();

      // The text is rendered.
      expect(
        find.text('Tell the waitress you want to order.'),
        findsOneWidget,
      );

      // The text color reuses AppColors.background (dark).
      final textWidget = tester.widget<Text>(
        find.text('Tell the waitress you want to order.'),
      );
      expect(textWidget.style?.color, AppColors.background);

      // The bubble container fill reuses AppColors.textPrimary
      // (off-white #F0F0F0) — chosen by Walid 2026-05-19 to match
      // existing tokens. Scope the search to descendants of the
      // CheckpointHintBubble subtree so an unrelated Container
      // somewhere else in the host scaffold can't match.
      final bubble = tester.widget<Container>(
        find.descendant(
          of: find.byType(CheckpointHintBubble),
          matching: find.byType(Container),
        ),
      );
      final dec = bubble.decoration as BoxDecoration;
      expect(dec.color, AppColors.textPrimary);
      expect(dec.borderRadius, BorderRadius.circular(12));
    },
  );

  testWidgets(
    'AnimatedSwitcher cross-fades between hint texts',
    (tester) async {
      // First snapshot.
      await tester.pumpWidget(
        _host(
          snapshot: const CheckpointSnapshot(
            currentIndex: 0,
            total: 6,
            hintText: 'First hint.',
          ),
        ),
      );
      await tester.pump();
      expect(find.text('First hint.'), findsOneWidget);

      // Swap to a new hint — both widgets coexist briefly during the
      // cross-fade transition.
      await tester.pumpWidget(
        _host(
          snapshot: const CheckpointSnapshot(
            currentIndex: 1,
            total: 6,
            hintText: 'Second hint.',
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 100));

      // The new hint is rendering.
      expect(find.text('Second hint.'), findsOneWidget);

      // Pump past the transition to settle.
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('First hint.'), findsNothing);
      expect(find.text('Second hint.'), findsOneWidget);
    },
  );

  testWidgets(
    'long hint text wraps to multiple lines and the bubble grows '
    'vertically (the whole point of this widget existing)',
    (tester) async {
      // 320x480 phone viewport to force the wrap.
      await tester.binding.setSurfaceSize(const Size(320, 480));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await tester.pumpWidget(
        _host(
          snapshot: const CheckpointSnapshot(
            currentIndex: 0,
            total: 6,
            hintText: 'This is a deliberately long hint text that should '
                'definitely wrap onto multiple lines to verify the bubble '
                'grows vertically.',
          ),
        ),
      );
      await tester.pump();

      // Find the Text widget and verify it rendered on more than 1 line.
      final textFinder = find.textContaining('deliberately long');
      expect(textFinder, findsOneWidget);

      // The bubble's RenderBox has a height > a single line of text
      // would produce. A single 18px line of Inter is roughly 22-26px
      // including line-height; the wrapped bubble should be at least
      // double that.
      final textBox = tester.renderObject<RenderBox>(textFinder);
      expect(
        textBox.size.height,
        greaterThan(45),
        reason:
            'The whole point of moving the bubble out of Rive is so it '
            'can Hug-Height naturally — a multi-line wrap MUST produce a '
            'taller bubble than a single line.',
      );
    },
  );
}
