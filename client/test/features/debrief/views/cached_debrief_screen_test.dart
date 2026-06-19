// Story 9.1 (Task 5 / Task 7) — the report-icon → cached-debrief route target.
// Uses the `debugResolve` seam so the widget test never touches sqflite.

import 'package:client/features/debrief/views/cached_debrief_screen.dart';
import 'package:client/features/debrief/views/debrief_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// A payload Debrief.tryParse accepts → DebriefScreen renders the content phase.
Map<String, dynamic> _validPayload() => <String, dynamic>{
  'debrief_version': 2,
  'survival_pct': 83,
  'character_name': 'The Waiter',
  'scenario_title': 'Order your dinner',
  'attempt_number': 1,
  'checkpoints': <dynamic>[],
  'errors': <dynamic>[],
  'hesitations': <dynamic>[],
  'areas': <dynamic>[],
  'areas_to_work_on': <dynamic>[],
};

Future<void> _pump(WidgetTester tester, Widget child) async {
  await tester.binding.setSurfaceSize(const Size(390, 844));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(home: child));
  // Resolve the resolver future, then let the AnimatedSwitcher settle. Explicit
  // pumps (not pumpAndSettle) per Gotcha D.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 350));
}

void main() {
  testWidgets('cache-hit renders the real DebriefScreen', (tester) async {
    await _pump(
      tester,
      CachedDebriefScreen(
        scenarioId: 'waiter_easy_01',
        cacheStore: null,
        debugResolve: () async =>
            (callId: 7, payload: _validPayload()),
      ),
    );

    expect(find.byType(DebriefScreen), findsOneWidget);
    // The content phase rendered (not loading/unavailable): the score gauge
    // shows the survival %.
    expect(find.text('83%'), findsOneWidget);
    expect(find.text('The Waiter — Order your dinner'), findsOneWidget);
  });

  testWidgets(
    'cache-miss renders the empathetic no-saved-report state (no crash)',
    (tester) async {
      await _pump(
        tester,
        CachedDebriefScreen(
          scenarioId: 'waiter_easy_01',
          cacheStore: null,
          debugResolve: () async => null,
        ),
      );

      expect(find.byType(DebriefScreen), findsNothing);
      expect(find.text('No saved report yet.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'a null cacheStore (no DB wired) resolves to the miss state',
    (tester) async {
      await _pump(
        tester,
        const CachedDebriefScreen(scenarioId: 'waiter_easy_01', cacheStore: null),
      );

      expect(find.byType(DebriefScreen), findsNothing);
      expect(find.text('No saved report yet.'), findsOneWidget);
    },
  );
}
