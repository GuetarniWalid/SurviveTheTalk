import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/views/widgets/scenario_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

Scenario _build({
  String id = 'waiter_easy_01',
  String title = 'Tina',
  String tagline = 'Order before she loses it',
  String riveCharacter = 'waiter',
  int? bestScore,
  int attempts = 0,
}) {
  return Scenario(
    id: id,
    title: title,
    difficulty: 'easy',
    isFree: true,
    riveCharacter: riveCharacter,
    languageFocus: const <String>[],
    contentWarning: null,
    bestScore: bestScore,
    attempts: attempts,
    tagline: tagline,
  );
}

Widget _harness(Widget child) => MaterialApp(
  theme: AppTheme.dark(),
  home: Scaffold(body: SafeArea(child: child)),
);

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  testWidgets(
    'not-attempted hides report icon and shows phone icon',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 480));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await tester.pumpWidget(
        _harness(
          ScenarioCard(
            scenario: _build(),
            onCallTap: () {},
            onCardTap: () {},
            // onReportTap omitted (null) → report icon must be hidden.
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Tina'), findsOneWidget);
      expect(find.text('Order before she loses it'), findsOneWidget);
      expect(find.byIcon(Icons.phone_outlined), findsOneWidget);
      expect(find.byIcon(Icons.assignment_outlined), findsNothing);
      expect(find.textContaining('Best:'), findsNothing);
    },
  );

  testWidgets(
    'in-progress renders stats with the middle-dot separator and statusInProgress color',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 480));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await tester.pumpWidget(
        _harness(
          ScenarioCard(
            scenario: _build(bestScore: 73, attempts: 3),
            onCallTap: () {},
            onCardTap: () {},
            onReportTap: () {},
          ),
        ),
      );
      await tester.pump();

      expect(find.byIcon(Icons.phone_outlined), findsOneWidget);
      expect(find.byIcon(Icons.assignment_outlined), findsOneWidget);

      final statsFinder = find.byWidgetPredicate((w) {
        if (w is! Text) return false;
        final span = w.textSpan;
        if (span is! TextSpan) return false;
        final children = span.children;
        if (children == null || children.length != 2) return false;
        final tail = children[1];
        if (tail is! TextSpan) return false;
        return tail.text == '73% · 3 attempts' &&
            tail.style?.color == AppColors.statusInProgress;
      });
      expect(statsFinder, findsOneWidget);
    },
  );

  testWidgets('completed renders stats in statusCompleted color', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      _harness(
        ScenarioCard(
          scenario: _build(bestScore: 100, attempts: 2),
          onCallTap: () {},
          onCardTap: () {},
          onReportTap: () {},
        ),
      ),
    );
    await tester.pump();

    expect(find.byIcon(Icons.assignment_outlined), findsOneWidget);

    final statsFinder = find.byWidgetPredicate((w) {
      if (w is! Text) return false;
      final span = w.textSpan;
      if (span is! TextSpan) return false;
      final children = span.children;
      if (children == null || children.length != 2) return false;
      final tail = children[1];
      if (tail is! TextSpan) return false;
      return tail.text == '100% · 2 attempts' &&
          tail.style?.color == AppColors.statusCompleted;
    });
    expect(statsFinder, findsOneWidget);
  });

  testWidgets(
    'tapping the phone icon fires onCallTap exactly once and never onCardTap',
    (tester) async {
      var callTaps = 0;
      var cardTaps = 0;
      await tester.pumpWidget(
        _harness(
          ScenarioCard(
            scenario: _build(),
            onCallTap: () => callTaps += 1,
            onCardTap: () => cardTaps += 1,
          ),
        ),
      );
      await tester.pump();

      await tester.tap(find.byIcon(Icons.phone_outlined));
      await tester.pump();

      expect(callTaps, 1);
      expect(cardTaps, 0);
    },
  );

  testWidgets(
    'tapping the report icon fires onReportTap exactly once and never onCardTap',
    (tester) async {
      var callTaps = 0;
      var cardTaps = 0;
      var reportTaps = 0;
      await tester.pumpWidget(
        _harness(
          ScenarioCard(
            scenario: _build(bestScore: 73, attempts: 3),
            onCallTap: () => callTaps += 1,
            onCardTap: () => cardTaps += 1,
            onReportTap: () => reportTaps += 1,
          ),
        ),
      );
      await tester.pump();

      await tester.tap(find.byIcon(Icons.assignment_outlined));
      await tester.pump();

      expect(reportTaps, 1);
      expect(callTaps, 0);
      expect(cardTaps, 0);
    },
  );

  testWidgets(
    'tapping the card body (avatar/text area) fires onCardTap exactly once',
    (tester) async {
      var callTaps = 0;
      var cardTaps = 0;
      var reportTaps = 0;
      await tester.pumpWidget(
        _harness(
          ScenarioCard(
            scenario: _build(bestScore: 73, attempts: 3),
            onCallTap: () => callTaps += 1,
            onCardTap: () => cardTaps += 1,
            onReportTap: () => reportTaps += 1,
          ),
        ),
      );
      await tester.pump();

      // Tap on the title text — outside any icon hit zone.
      await tester.tap(find.text('Tina'));
      await tester.pump();

      expect(cardTaps, 1);
      expect(callTaps, 0);
      expect(reportTaps, 0);
    },
  );

  testWidgets('singular "1 attempt" rendered when attempts == 1', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      _harness(
        ScenarioCard(
          scenario: _build(bestScore: 50, attempts: 1),
          onCallTap: () {},
          onCardTap: () {},
          onReportTap: () {},
        ),
      ),
    );
    await tester.pump();

    final statsFinder = find.byWidgetPredicate((w) {
      if (w is! Text) return false;
      final span = w.textSpan;
      if (span is! TextSpan) return false;
      final children = span.children;
      if (children == null || children.length != 2) return false;
      final tail = children[1];
      if (tail is! TextSpan) return false;
      // Singular "attempt" — must NOT be "attempts" when count is 1.
      return tail.text == '50% · 1 attempt';
    });
    expect(statsFinder, findsOneWidget);
  });

  testWidgets(
    'semantics tree exposes 3 distinct button nodes — icons are NOT swallowed by description container',
    (tester) async {
      final semanticsHandle = tester.ensureSemantics();

      await tester.pumpWidget(
        _harness(
          ScenarioCard(
            scenario: _build(bestScore: 73, attempts: 3),
            onCallTap: () {},
            onCardTap: () {},
            onReportTap: () {},
          ),
        ),
      );
      await tester.pump();

      // The decision-3 question: do the two icon-button Semantics nodes stay
      // addressable as distinct screen-reader targets, or does the parent
      // description container swallow them? If find.bySemanticsLabel returns
      // a hit for each, they are NOT swallowed.
      expect(find.bySemanticsLabel('Call Tina'), findsOneWidget);
      expect(find.bySemanticsLabel('View debrief'), findsOneWidget);

      // Description focal node — labelled with the scenario state plus
      // (after MergeSemantics) the underlying Text widgets. We use a
      // RegExp substring match to avoid pinning the exact merged-label
      // format which depends on Flutter's internals.
      expect(
        find.bySemanticsLabel(
          RegExp(r'Tina\. Order before she loses it\.'),
        ),
        findsOneWidget,
      );

      semanticsHandle.dispose();
    },
  );

  testWidgets(
    'semantics tree on not-attempted state — phone button addressable, report button absent',
    (tester) async {
      final semanticsHandle = tester.ensureSemantics();

      await tester.pumpWidget(
        _harness(
          ScenarioCard(
            scenario: _build(),
            onCallTap: () {},
            onCardTap: () {},
            // onReportTap omitted → report icon hidden, no Semantics for it.
          ),
        ),
      );
      await tester.pump();

      expect(find.bySemanticsLabel('Call Tina'), findsOneWidget);
      expect(find.bySemanticsLabel('View debrief'), findsNothing);
      // Description still findable via regex (state phrase varies).
      expect(
        find.bySemanticsLabel(RegExp(r'Not attempted')),
        findsOneWidget,
      );

      semanticsHandle.dispose();
    },
  );

  testWidgets('does not overflow at 320×480 with textScaler 1.5', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.dark(),
        home: MediaQuery(
          data: const MediaQueryData(textScaler: TextScaler.linear(1.5)),
          child: Scaffold(
            body: SafeArea(
              child: ScenarioCard(
                scenario: _build(bestScore: 73, attempts: 3),
                onCallTap: () {},
                onCardTap: () {},
                onReportTap: () {},
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(tester.takeException(), isNull);
  });
}
