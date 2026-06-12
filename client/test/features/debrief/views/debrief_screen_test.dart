// Story 7.3 — Debrief screen tests.
//
// House rules (client/CLAUDE.md): phone surface 320×568 with tearDown
// reset (§7), explicit `pump(Duration)` while poll timers may be live —
// NEVER `pumpAndSettle` (§3), mocktail repository mock (§2).

import 'dart:async';

import 'package:client/core/api/api_exception.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:client/features/debrief/views/debrief_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockCallRepository extends Mock implements CallRepository {}

const String kAboutText =
    'The character ended the call because the conversation included '
    'inappropriate language.';

Map<String, dynamic> fullPayload({int survivalPct = 73}) {
  return <String, dynamic>{
    'survival_pct': survivalPct,
    'character_name': 'The Mugger',
    'scenario_title': 'Give me your wallet',
    'attempt_number': 2,
    'previous_best': 67,
    'errors': [
      {
        'user_said': 'I am agree',
        'correction': 'I agree',
        'context': 'Responding to the demand',
        'count': 2,
      },
      {
        'user_said': 'He go away',
        'correction': 'He went away',
        'context': 'Describing the escape',
        'count': 1,
      },
    ],
    'hesitations': [
      {'duration_sec': 4.2, 'context': 'After the threat escalated'},
      {'duration_sec': 3.4, 'context': 'When asked for the time'},
    ],
    'idioms': [
      {
        'expression': 'Pull the other one',
        'meaning': "I don't believe you",
        'context': 'When you claimed to have no wallet',
      },
    ],
    'areas_to_work_on': [
      "Negative sentence structure (don't/doesn't)",
      'Articles (a/an/the)',
    ],
    'inappropriate_behavior': kAboutText,
    'encouraging_framing': {
      'proximity': '27% away from surviving The Mugger',
      'improvement': '+6% since last attempt',
    },
  };
}

Map<String, dynamic> minimalPayload() {
  return <String, dynamic>{
    'survival_pct': 30,
    'character_name': 'The Waiter',
    'scenario_title': 'Order your dinner',
    'attempt_number': 1,
    'previous_best': null,
    'errors': <Object?>[],
    'hesitations': <Object?>[],
    'idioms': <Object?>[],
    'areas_to_work_on': ['Articles (a/an/the)'],
    'inappropriate_behavior': null,
    // encouraging_framing key absent (server <= 40% omission).
  };
}

void main() {
  late MockCallRepository repository;

  setUp(() {
    repository = MockCallRepository();
  });

  /// Shrunk-timing screen: poll 50 ms, budget 400 ms.
  DebriefScreen buildScreen({
    required Map<String, dynamic>? payload,
    int? callId = 7,
  }) {
    return DebriefScreen(
      payload: payload,
      callId: callId,
      callRepository: repository,
      pollInterval: const Duration(milliseconds: 50),
      pollBudget: const Duration(milliseconds: 400),
    );
  }

  Future<void> pumpScreen(WidgetTester tester, DebriefScreen screen) async {
    await tester.binding.setSurfaceSize(const Size(320, 568));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(home: screen));
  }

  group('pure helpers', () {
    test('debriefAttemptLine drops the previous-best segment on null', () {
      expect(
        debriefAttemptLine(attemptNumber: 1, previousBest: null),
        'Attempt #1',
      );
      expect(
        debriefAttemptLine(attemptNumber: 3, previousBest: 67),
        'Attempt #3 · Previous best: 67%',
      );
    });

    test('count lines pluralize per the design copy', () {
      expect(errorCountLine(0), 'No errors flagged');
      expect(errorCountLine(1), '1 error flagged');
      expect(errorCountLine(3), '3 errors flagged');
      expect(hesitationCountLine(0), 'No hesitations flagged');
      expect(hesitationCountLine(1), '1 moment flagged');
      expect(hesitationCountLine(2), '2 moments flagged');
    });

    test('errorYouSaidLabel shows the ×N badge only when count >= 2', () {
      expect(errorYouSaidLabel(1), 'You said:');
      expect(errorYouSaidLabel(2), 'You said (×2):');
      expect(errorYouSaidLabel(3), 'You said (×3):');
    });
  });

  group('content render (AC1-AC6, AC8, AC9)', () {
    testWidgets('full payload renders every section', (tester) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));

      // Hero (AC1, AC8).
      expect(find.text('73%'), findsOneWidget);
      expect(find.text('Survival Rate'), findsOneWidget);
      expect(find.text('The Mugger — Give me your wallet'), findsOneWidget);
      expect(find.text('Attempt #2 · Previous best: 67%'), findsOneWidget);

      // Encouraging framing (AC5) — server strings verbatim.
      expect(find.text('27% away from surviving The Mugger'), findsOneWidget);
      expect(find.text('+6% since last attempt'), findsOneWidget);

      // Language errors (AC2) with the ×2 badge on the repeated error.
      expect(find.text('Language Errors'), findsOneWidget);
      expect(find.text('2 errors flagged'), findsOneWidget);
      expect(find.text('You said (×2):'), findsOneWidget);
      expect(find.text('You said:'), findsOneWidget);
      expect(find.text('I am agree'), findsOneWidget);
      expect(find.text('I agree'), findsOneWidget);
      expect(find.text('Correct form:'), findsNWidgets(2));

      // Hesitations (AC3) — toStringAsFixed(1) durations.
      expect(find.text('Hesitation Analysis'), findsOneWidget);
      expect(find.text('2 moments flagged'), findsOneWidget);
      expect(find.text('4.2 seconds'), findsOneWidget);
      expect(find.text('3.4 seconds'), findsOneWidget);
      expect(find.text('"After the threat escalated"'), findsOneWidget);

      // Idioms (AC4) — expression in single quotes, context in quotes.
      expect(find.text('Idioms & Slang'), findsOneWidget);
      expect(find.text("'Pull the other one'"), findsOneWidget);
      expect(find.text("I don't believe you"), findsOneWidget);

      // FR37 card (AC9).
      expect(find.text('About This Call'), findsOneWidget);
      expect(find.text(kAboutText), findsOneWidget);

      // Areas (AC6) — numbered.
      expect(find.text('Areas to Work On'), findsOneWidget);
      expect(
        find.text("1. Negative sentence structure (don't/doesn't)"),
        findsOneWidget,
      );
      expect(find.text('2. Articles (a/an/the)'), findsOneWidget);

      // Happy path made zero network calls.
      verifyNever(() => repository.fetchDebrief(callId: any(named: 'callId')));
      // No overflow at the phone surface.
      expect(tester.takeException(), isNull);
    });

    testWidgets('correction text uses the accent color (AC2)', (tester) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      final correction = tester.widget<Text>(find.text('I agree'));
      expect(correction.style?.color, AppColors.accent);
      // The user's phrase stays standard white.
      final userSaid = tester.widget<Text>(find.text('I am agree'));
      expect(userSaid.style?.color, AppColors.textPrimary);
    });

    testWidgets('hero % is destructive below 100', (tester) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      final hero = tester.widget<Text>(find.text('73%'));
      expect(hero.style?.color, AppColors.destructive);
    });

    testWidgets('hero % is statusCompleted at exactly 100', (tester) async {
      await pumpScreen(
        tester,
        buildScreen(payload: fullPayload(survivalPct: 100)),
      );
      final hero = tester.widget<Text>(find.text('100%'));
      expect(hero.style?.color, AppColors.statusCompleted);
    });

    testWidgets('FR37 card carries the 4px destructive left border (AC9)', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      final card = tester.widget<Container>(
        find.ancestor(
          of: find.text(kAboutText),
          matching: find.byType(Container),
        ),
      );
      final decoration = card.decoration! as BoxDecoration;
      final border = decoration.border! as Border;
      expect(
        border.left,
        const BorderSide(color: AppColors.destructive, width: 4),
      );
      // The stripe is left-only.
      expect(border.top, BorderSide.none);
      expect(border.right, BorderSide.none);
      expect(border.bottom, BorderSide.none);
    });
  });

  group('empty / conditional states (AC3, AC4, AC5, AC9)', () {
    testWidgets('minimal payload hides every conditional element', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: minimalPayload()));

      // First attempt — no previous-best segment.
      expect(find.text('Attempt #1'), findsOneWidget);
      expect(find.textContaining('Previous best'), findsNothing);

      // Framing key absent → section hidden.
      expect(find.textContaining('away from'), findsNothing);

      // Errors/hesitations stay visible with their empty count lines.
      expect(find.text('No errors flagged'), findsOneWidget);
      expect(find.text('No hesitations flagged'), findsOneWidget);

      // Idioms section ABSENT entirely (no header, no empty message).
      expect(find.text('Idioms & Slang'), findsNothing);
      expect(find.textContaining('No idioms'), findsNothing);

      // FR37 hidden when null.
      expect(find.text('About This Call'), findsNothing);

      expect(tester.takeException(), isNull);
    });

    testWidgets('degenerate empty areas_to_work_on hides the whole section '
        '(review P2 — no bare card under an orphan header)', (tester) async {
      final payload = minimalPayload()..['areas_to_work_on'] = <Object?>[];
      await pumpScreen(tester, buildScreen(payload: payload));

      expect(find.text('Areas to Work On'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  group('AC7 — no CTA, no praise', () {
    testWidgets('no buttons besides the back arrow, even at 100%', (
      tester,
    ) async {
      await pumpScreen(
        tester,
        buildScreen(payload: fullPayload(survivalPct: 100)),
      );
      expect(find.byType(ElevatedButton), findsNothing);
      expect(find.byType(TextButton), findsNothing);
      expect(find.byType(FilledButton), findsNothing);
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.byType(IconButton), findsOneWidget); // back arrow only
    });

    testWidgets('no praise strings in any rendered text at 100%', (
      tester,
    ) async {
      await pumpScreen(
        tester,
        buildScreen(payload: fullPayload(survivalPct: 100)),
      );
      final rendered = tester
          .widgetList<Text>(find.byType(Text))
          .map((t) => (t.data ?? '').toLowerCase())
          .toList();
      for (final praise in ['great job', 'congratulations', 'well done']) {
        expect(
          rendered.any((t) => t.contains(praise)),
          isFalse,
          reason: 'praise string "$praise" must never render',
        );
      }
    });
  });

  group('BS-7 fallback (AC10)', () {
    testWidgets('null payload + callId shows the loading text (no spinner) and '
        'fades the content in when polling resolves', (tester) async {
      var calls = 0;
      when(() => repository.fetchDebrief(callId: 7)).thenAnswer((_) async {
        calls++;
        if (calls < 3) {
          throw const ApiException(
            code: 'DEBRIEF_NOT_READY',
            message: 'still generating',
            statusCode: 404,
          );
        }
        return fullPayload();
      });

      await pumpScreen(tester, buildScreen(payload: null));
      await tester.pump(); // flush the first (NOT_READY) fetch

      expect(find.text('Analyzing your conversation...'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);

      // Two more 50 ms poll ticks — third attempt resolves.
      await tester.pump(const Duration(milliseconds: 60));
      expect(find.text('Analyzing your conversation...'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 60));
      await tester.pump(); // rebuild with the settled payload

      // Content is in the tree as the 300 ms fade starts…
      expect(find.text('73%'), findsOneWidget);
      // …and the loading text is gone once the fade completes.
      await tester.pump(const Duration(milliseconds: 310));
      expect(find.text('Analyzing your conversation...'), findsNothing);
      expect(calls, 3);
    });

    testWidgets('poll budget exhaustion lands on the quiet terminal state', (
      tester,
    ) async {
      var calls = 0;
      when(() => repository.fetchDebrief(callId: 7)).thenAnswer((_) async {
        calls++;
        throw const ApiException(
          code: 'DEBRIEF_NOT_READY',
          message: 'still generating',
          statusCode: 404,
        );
      });

      await pumpScreen(tester, buildScreen(payload: null));
      await tester.pump();
      expect(find.text('Analyzing your conversation...'), findsOneWidget);

      // Cross the 400 ms budget — polling stops, terminal state shows.
      await tester.pump(const Duration(milliseconds: 450));
      expect(find.text('Debrief unavailable for this call.'), findsOneWidget);

      // The loop is dead: no further fetches after the budget fired.
      final callsAtBudget = calls;
      await tester.pump(const Duration(milliseconds: 200));
      expect(calls, callsAtBudget);

      // Loading text fully gone after the fade; never any error chrome.
      await tester.pump(const Duration(milliseconds: 310));
      expect(find.text('Analyzing your conversation...'), findsNothing);
      expect(find.byType(SnackBar), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
      'a fetch already in flight when the budget fires still lands the '
      'content (review P1 — success is honored, not discarded)',
      (tester) async {
        final completer = Completer<Map<String, dynamic>>();
        when(
          () => repository.fetchDebrief(callId: 7),
        ).thenAnswer((_) => completer.future);

        await pumpScreen(tester, buildScreen(payload: null));
        expect(find.text('Analyzing your conversation...'), findsOneWidget);

        // The 400 ms budget exhausts while the first fetch is in flight.
        await tester.pump(const Duration(milliseconds: 450));
        expect(find.text('Debrief unavailable for this call.'), findsOneWidget);

        // The in-flight response then resolves with a valid debrief — it
        // must replace the terminal state, not be thrown away.
        completer.complete(fullPayload());
        await tester.pump(); // flush the microtask + rebuild
        expect(find.text('73%'), findsOneWidget);
        await tester.pump(const Duration(milliseconds: 310)); // fade done
        expect(find.text('Debrief unavailable for this call.'), findsNothing);
      },
    );

    testWidgets('null payload + null callId is unavailable immediately', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: null, callId: null));
      expect(find.text('Debrief unavailable for this call.'), findsOneWidget);
      verifyNever(() => repository.fetchDebrief(callId: any(named: 'callId')));
    });

    testWidgets('terminal ApiException (non-NOT_READY) → unavailable', (
      tester,
    ) async {
      when(() => repository.fetchDebrief(callId: 7)).thenAnswer(
        (_) async => throw const ApiException(
          code: 'CALL_NOT_FOUND',
          message: 'nope',
          statusCode: 404,
        ),
      );
      await pumpScreen(tester, buildScreen(payload: null));
      await tester.pump();
      expect(find.text('Debrief unavailable for this call.'), findsOneWidget);
      // Terminal — exactly one fetch, no re-poll.
      verify(() => repository.fetchDebrief(callId: 7)).called(1);
      await tester.pump(const Duration(milliseconds: 200));
      verifyNever(() => repository.fetchDebrief(callId: 7));
    });

    testWidgets('provided-but-malformed payload → unavailable, no fetch', (
      tester,
    ) async {
      await pumpScreen(
        tester,
        buildScreen(payload: <String, dynamic>{'garbage': true}),
      );
      expect(find.text('Debrief unavailable for this call.'), findsOneWidget);
      verifyNever(() => repository.fetchDebrief(callId: any(named: 'callId')));
    });

    testWidgets('fetched payload failing structural parse → unavailable', (
      tester,
    ) async {
      when(
        () => repository.fetchDebrief(callId: 7),
      ).thenAnswer((_) async => <String, dynamic>{'garbage': true});
      await pumpScreen(tester, buildScreen(payload: null));
      await tester.pump();
      expect(find.text('Debrief unavailable for this call.'), findsOneWidget);
    });
  });

  group('back navigation (AC7)', () {
    testWidgets('back arrow pops to the previous route', (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 568));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: Center(child: Text('HOME'))),
        ),
      );
      final navigator = tester.state<NavigatorState>(find.byType(Navigator));
      unawaited(
        navigator.push(
          MaterialPageRoute<void>(
            builder: (_) => buildScreen(payload: fullPayload()),
          ),
        ),
      );
      // Content state runs NO timers (payload provided → zero polling),
      // so pumpAndSettle is safe here (the CLAUDE.md §3 ban applies to
      // live poll timers) and reliably finishes the route transitions.
      await tester.pumpAndSettle();
      expect(find.text('73%'), findsOneWidget);

      await tester.tap(find.byIcon(Icons.arrow_back_ios_new));
      await tester.pumpAndSettle();
      expect(find.text('HOME'), findsOneWidget);
      expect(find.text('73%'), findsNothing);
    });

    testWidgets('loading state also offers the back arrow', (tester) async {
      when(() => repository.fetchDebrief(callId: 7)).thenAnswer(
        (_) async => throw const ApiException(
          code: 'DEBRIEF_NOT_READY',
          message: 'still generating',
          statusCode: 404,
        ),
      );
      await pumpScreen(tester, buildScreen(payload: null));
      await tester.pump();
      expect(find.byIcon(Icons.arrow_back_ios_new), findsOneWidget);
      expect(find.text('Analyzing your conversation...'), findsOneWidget);
    });
  });

  group('a11y (story Task 2.12)', () {
    testWidgets('back arrow + hero labels, headers marked', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpScreen(tester, buildScreen(payload: fullPayload()));

      expect(find.bySemanticsLabel('Back to scenarios'), findsOneWidget);
      expect(find.bySemanticsLabel('73 percent survival rate'), findsOneWidget);

      final header = tester.getSemantics(find.text('Language Errors'));
      expect(header.flagsCollection.isHeader, isTrue);

      handle.dispose();
    });

    testWidgets('back arrow keeps the 44x44 touch target', (tester) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      expect(tester.getSize(find.byType(IconButton)), const Size(44, 44));
    });
  });
}
