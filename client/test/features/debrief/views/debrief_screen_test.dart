// Story 7.5 — Debrief screen v2 tests.
//
// House rules (client/CLAUDE.md): phone surface 320×568 with tearDown reset
// (§7), explicit `pump(Duration)` while poll timers may be live — NEVER
// `pumpAndSettle` with live timers (§3), mocktail repository mock (§2).

import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/core/local_cache/debrief_cache_store.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:client/features/debrief/views/debrief_screen.dart';
import 'package:client/features/paywall/views/paywall_sheet.dart';
import 'package:client/features/subscription/bloc/subscription_bloc.dart';
import 'package:client/features/subscription/bloc/subscription_event.dart';
import 'package:client/features/subscription/bloc/subscription_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockCallRepository extends Mock implements CallRepository {}

/// Story 10.7 (Bug B) — the progressive cache write happens in DebriefScreen now.
class MockDebriefCacheStore extends Mock implements DebriefCacheStore {}

/// Story 8.2 (FR29) — drives the paywall's bloc through the test seam so the
/// auto-presented sheet never touches the real store plugin.
class MockSubscriptionBloc
    extends MockBloc<SubscriptionEvent, SubscriptionState>
    implements SubscriptionBloc {}

const String kAboutText =
    'The character ended the call because the conversation included '
    'inappropriate language.';

const String kFocusPrompt =
    'You are an English coach. Drill negative sentences.';
const String kArticlesPrompt = 'You are an English coach. Drill articles.';

/// Full v2 payload — every section populated.
Map<String, dynamic> fullPayload({int survivalPct = 73}) {
  return <String, dynamic>{
    'debrief_version': 2,
    'survival_pct': survivalPct,
    'character_name': 'The Mugger',
    'scenario_title': 'Give me your wallet',
    'attempt_number': 2,
    'previous_best': 67,
    'checkpoints': [
      {'id': 'greet', 'hint': 'Greet the mugger', 'met': true},
      {'id': 'refuse', 'hint': 'Refuse to comply', 'met': false},
    ],
    'errors': [
      {
        'user_said': 'I am agree',
        'correction': 'I agree',
        'context': 'Responding to the demand',
        'count': 2,
        'explanation': "The verb 'agree' takes no 'be'; it stands alone.",
        'examples': ['I agree with you.', 'She agrees it is late.'],
      },
      {
        'user_said': 'He go away',
        'correction': 'He went away',
        'context': 'Describing the escape',
        'count': 1,
      },
    ],
    'hesitations': [
      {
        'duration_sec': 4.2,
        'context': 'After the threat escalated',
        'id': 'h1',
        'resolved': true,
        'source': 'device',
      },
      {
        'duration_sec': 7.0,
        'context': '',
        'id': 'h2',
        'resolved': false,
        'source': 'server',
      },
    ],
    'idioms': [
      {
        'expression': 'Pull the other one',
        'meaning': "I don't believe you",
        'context': 'When you claimed to have no wallet',
      },
    ],
    'better_phrasings': [
      {
        'original': 'I will not give you the wallet',
        'suggestion': "You're not getting my wallet",
        'reason': 'More natural under pressure',
      },
    ],
    'areas': [
      {
        'title': 'Negative sentence structure',
        'evidence': 'You said "I am not want"',
        'practice_prompt': kFocusPrompt,
        'is_focus': true,
      },
      {
        'title': 'Articles',
        'evidence': 'You dropped "a" before "wallet"',
        'practice_prompt': kArticlesPrompt,
        'is_focus': false,
      },
    ],
    'areas_to_work_on': ['Negative sentence structure', 'Articles'],
    'inappropriate_behavior': kAboutText,
    'encouraging_framing': {
      'proximity': '27% away from surviving The Mugger',
      'improvement': '+6% since last attempt',
    },
  };
}

/// A stored v1 payload — no debrief_version, no v2 lists (back-compat AC2).
Map<String, dynamic> v1Payload({int survivalPct = 30}) {
  return <String, dynamic>{
    'survival_pct': survivalPct,
    'character_name': 'The Waiter',
    'scenario_title': 'Order your dinner',
    'attempt_number': 1,
    'previous_best': null,
    'errors': <Object?>[],
    'hesitations': <Object?>[],
    'idioms': <Object?>[],
    'areas_to_work_on': ['Articles (a/an/the)'],
    'inappropriate_behavior': null,
  };
}

/// Server never-blank fallback — a DEGRADED score-only debrief (`degraded:
/// true`, empty LLM analysis). The backend still threads the score +
/// checkpoints; `inappropriate_behavior` is set only on an inappropriate end.
Map<String, dynamic> degradedPayload({
  int survivalPct = 66,
  String? inappropriateBehavior,
}) {
  return <String, dynamic>{
    'debrief_version': 2,
    'survival_pct': survivalPct,
    'character_name': 'The Mugger',
    'scenario_title': 'Give me your wallet',
    'attempt_number': 2,
    'previous_best': null,
    'checkpoints': [
      {'id': 'greet', 'hint': 'Greet the mugger', 'met': true},
      {'id': 'refuse', 'hint': 'Refuse to comply', 'met': false},
    ],
    'errors': <Object?>[],
    'hesitations': <Object?>[],
    'idioms': <Object?>[],
    'better_phrasings': <Object?>[],
    'areas': <Object?>[],
    'areas_to_work_on': <Object?>[],
    'inappropriate_behavior': inappropriateBehavior,
    'degraded': true,
  };
}

/// Story 10.7 (Bug B) — the SCORE-ONLY `pending` payload the overlay hands off:
/// real survival % + checkpoints, empty analysis arrays, `pending: true`.
Map<String, dynamic> pendingPayload({int survivalPct = 73}) {
  return <String, dynamic>{
    'debrief_version': 2,
    'survival_pct': survivalPct,
    'character_name': 'The Mugger',
    'scenario_title': 'Give me your wallet',
    'attempt_number': 2,
    'previous_best': 67,
    'checkpoints': [
      {'id': 'greet', 'hint': 'Greet the mugger', 'met': true},
      {'id': 'refuse', 'hint': 'Refuse to comply', 'met': false},
    ],
    'errors': <Object?>[],
    'hesitations': <Object?>[],
    'idioms': <Object?>[],
    'better_phrasings': <Object?>[],
    'areas': <Object?>[],
    'areas_to_work_on': <Object?>[],
    'inappropriate_behavior': null,
    'pending': true,
  };
}

void main() {
  late MockCallRepository repository;

  setUpAll(() {
    // mocktail `any(named: 'payload')` needs a fallback for the Map type.
    registerFallbackValue(<String, dynamic>{});
  });

  setUp(() {
    repository = MockCallRepository();
  });

  DebriefScreen buildScreen({
    required Map<String, dynamic>? payload,
    int? callId = 7,
    DebriefCacheStore? cacheStore,
    String? scenarioId,
  }) {
    return DebriefScreen(
      payload: payload,
      callId: callId,
      callRepository: repository,
      debriefCacheStore: cacheStore,
      scenarioId: scenarioId,
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
      expect(checkpointCountLine(1, 2), '1 of 2 reached');
      expect(checkpointCountLine(6, 6), '6 of 6 reached');
    });

    test('errorYouSaidLabel shows the ×N badge only when count >= 2', () {
      expect(errorYouSaidLabel(1), 'You said:');
      expect(errorYouSaidLabel(2), 'You said (×2):');
    });

    test('hesitationDurationLabel rounds and prefixes ~', () {
      expect(hesitationDurationLabel(4.2), '~4s');
      expect(hesitationDurationLabel(6.6), '~7s');
      expect(hesitationDurationLabel(3.0), '~3s');
    });

    test('scoreColor: red <=40, amber 41-99, green 100', () {
      expect(scoreColor(0), AppColors.destructive);
      expect(scoreColor(40), AppColors.destructive);
      expect(scoreColor(41), AppColors.warning);
      expect(scoreColor(99), AppColors.warning);
      expect(scoreColor(100), AppColors.statusCompleted);
    });
  });

  group('v2 content render', () {
    testWidgets('full payload renders every v2 section', (tester) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));

      // Hero scorecard.
      expect(find.text('73%'), findsOneWidget);
      expect(find.text('Survival Rate'), findsOneWidget);
      expect(find.text('The Mugger — Give me your wallet'), findsOneWidget);
      expect(find.text('Attempt #2 · Previous best: 67%'), findsOneWidget);
      expect(find.text('27% away from surviving The Mugger'), findsOneWidget);

      // Checkpoint breakdown (B7) — collapsed to a tappable summary on the
      // surface (Story 7.5 review); the per-beat rows live in the sheet.
      expect(find.text('CHECKPOINTS'), findsOneWidget);
      expect(find.text('1 of 2 reached'), findsOneWidget);
      expect(find.text('Greet the mugger'), findsNothing);
      expect(find.text('Refuse to comply'), findsNothing);

      // Errors — uppercase eyebrow + ×2 badge.
      expect(find.text('LANGUAGE ERRORS'), findsOneWidget);
      expect(find.text('2 errors flagged'), findsOneWidget);
      expect(find.text('You said (×2):'), findsOneWidget);
      expect(find.text('I am agree'), findsOneWidget);
      expect(find.text('I agree'), findsOneWidget);

      // Hesitations — approximate durations + the freeze note.
      expect(find.text('HESITATIONS'), findsOneWidget);
      expect(find.text('~4s'), findsOneWidget);
      expect(find.text('~7s'), findsOneWidget);
      expect(find.text('The character had to speak first.'), findsOneWidget);

      // Idioms + better phrasings + about.
      expect(find.text('IDIOMS & SLANG'), findsOneWidget);
      expect(find.text("'Pull the other one'"), findsOneWidget);
      expect(find.text('SAID MORE NATURALLY'), findsOneWidget);
      expect(find.text("You're not getting my wallet"), findsOneWidget);
      expect(find.text('ABOUT THIS CALL'), findsOneWidget);
      expect(find.text(kAboutText), findsOneWidget);

      // Areas — focus-first eyebrow + a subtle inline copy row per card (both
      // areas carry a practice prompt); the how-to explanation stays in the
      // drawer (closed here).
      expect(find.text('AREAS TO WORK ON'), findsOneWidget);
      expect(find.text('FOCUS FIRST'), findsOneWidget);
      expect(find.text('Negative sentence structure'), findsOneWidget);
      expect(find.text('Copy the prompt'), findsNWidgets(2));
      expect(find.text('HOW TO PRACTICE'), findsNothing);

      verifyNever(() => repository.fetchDebrief(callId: any(named: 'callId')));
      expect(tester.takeException(), isNull);
    });

    testWidgets('tapping the checkpoint summary opens the sheet, done first', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));

      // Collapsed on the surface: the per-beat rows are hidden until tapped.
      expect(find.text('Greet the mugger'), findsNothing);
      expect(find.text('Refuse to comply'), findsNothing);

      await tester.tap(find.text('1 of 2 reached'));
      await tester.pumpAndSettle();

      // Both beats now render in the sheet, the DONE one ('Greet the mugger')
      // listed before the not-done one ('Refuse to comply').
      final met = tester.getTopLeft(find.text('Greet the mugger')).dy;
      final missed = tester.getTopLeft(find.text('Refuse to comply')).dy;
      expect(met, lessThan(missed));
      expect(tester.takeException(), isNull);
    });

    testWidgets('gauge % uses the 3-color rule', (tester) async {
      // Clear the tree between cases so the DebriefScreen State (which parses
      // the payload in initState only) is recreated each time.
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      expect(
        tester.widget<Text>(find.text('73%')).style?.color,
        AppColors.warning,
      );

      await tester.pumpWidget(const SizedBox());
      await pumpScreen(
        tester,
        buildScreen(payload: fullPayload(survivalPct: 100)),
      );
      expect(
        tester.widget<Text>(find.text('100%')).style?.color,
        AppColors.statusCompleted,
      );

      await tester.pumpWidget(const SizedBox());
      await pumpScreen(
        tester,
        buildScreen(payload: fullPayload(survivalPct: 30)),
      );
      expect(
        tester.widget<Text>(find.text('30%')).style?.color,
        AppColors.destructive,
      );
    });

    testWidgets('correction uses the accent color; the suggestion does not', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      expect(
        tester.widget<Text>(find.text('I agree')).style?.color,
        AppColors.accent,
      );
      // "More natural" suggestion is weight, NOT accent (two-ink discipline).
      expect(
        tester
            .widget<Text>(find.text("You're not getting my wallet"))
            .style
            ?.color,
        AppColors.textPrimary,
      );
    });

    testWidgets('chevrons mark only depth-bearing cards', (tester) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      // 1 error with depth + 2 areas with a practice prompt + the collapsed
      // checkpoint summary (Story 7.5 review) = 4 chevrons. The depthless second
      // error stays chevron-less (honest affordance).
      expect(find.byIcon(Icons.chevron_right), findsNWidgets(4));
    });

    testWidgets('FR37 card keeps the 4px destructive left border', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      final card = tester.widget<Container>(
        find.ancestor(
          of: find.text(kAboutText),
          matching: find.byType(Container),
        ),
      );
      final border = (card.decoration! as BoxDecoration).border! as Border;
      expect(
        border.left,
        const BorderSide(color: AppColors.destructive, width: 4),
      );
      expect(border.top, BorderSide.none);
    });
  });

  group('v1 payload fallback (AC2)', () {
    testWidgets('a v1 payload renders without crashing, v2 sections hidden', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: v1Payload()));

      // Gauge + identity + count lines render from v1 fields.
      expect(find.text('30%'), findsOneWidget);
      expect(find.text('The Waiter — Order your dinner'), findsOneWidget);
      expect(find.text('No errors flagged'), findsOneWidget);
      expect(find.text('No hesitations flagged'), findsOneWidget);

      // The numbered areas fallback (no rich areas in a v1 payload).
      expect(find.text('AREAS TO WORK ON'), findsOneWidget);
      expect(find.text('1. Articles (a/an/the)'), findsOneWidget);

      // v2-only sections + affordances are ABSENT.
      expect(find.text('CHECKPOINTS'), findsNothing);
      expect(find.text('SAID MORE NATURALLY'), findsNothing);
      expect(find.text('FOCUS FIRST'), findsNothing);
      expect(find.text('Copy the prompt'), findsNothing);
      expect(find.byIcon(Icons.chevron_right), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  group('degraded debrief (server never-blank fallback)', () {
    testWidgets(
      'shows score + checkpoints + honest note, hides empty analysis',
      (tester) async {
        await pumpScreen(tester, buildScreen(payload: degradedPayload()));

        // Score + checkpoints (backend-factual) still render.
        expect(find.text('66%'), findsOneWidget);
        expect(find.text('The Mugger — Give me your wallet'), findsOneWidget);
        expect(find.text('CHECKPOINTS'), findsOneWidget);
        expect(find.text('1 of 2 reached'), findsOneWidget);

        // The one honest line replaces the analysis.
        expect(
          find.text('Detailed analysis is unavailable for this call.'),
          findsOneWidget,
        );

        // The empty analysis sections are SUPPRESSED — no misleading "No errors
        // flagged" / "No hesitations flagged" implying a flawless call.
        expect(find.text('LANGUAGE ERRORS'), findsNothing);
        expect(find.text('No errors flagged'), findsNothing);
        expect(find.text('HESITATIONS'), findsNothing);
        expect(find.text('No hesitations flagged'), findsNothing);
        expect(find.text('AREAS TO WORK ON'), findsNothing);

        verifyNever(
          () => repository.fetchDebrief(callId: any(named: 'callId')),
        );
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('an inappropriate-end degraded debrief still explains why', (
      tester,
    ) async {
      await pumpScreen(
        tester,
        buildScreen(
          payload: degradedPayload(inappropriateBehavior: kAboutText),
        ),
      );

      expect(
        find.text('Detailed analysis is unavailable for this call.'),
        findsOneWidget,
      );
      // The factual "about this call" line is backend-pinned even when degraded.
      expect(find.text('ABOUT THIS CALL'), findsOneWidget);
      expect(find.text(kAboutText), findsOneWidget);
    });
  });

  group('area practice drawer (AC5, Walid 2026-06-15)', () {
    testWidgets('the inline copy row copies directly, WITHOUT opening the drawer', (
      tester,
    ) async {
      final clipboardCalls = <MethodCall>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') clipboardCalls.add(call);
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );

      await pumpScreen(tester, buildScreen(payload: fullPayload()));

      // The focus area is pinned first; its inline copy row is the first one.
      // The experienced user copies straight from the card (Walid 2026-06-15).
      final inlineCopy = find.text('Copy the prompt').first;
      await tester.ensureVisible(inlineCopy);
      await tester.pump();
      await tester.tap(inlineCopy);
      await tester.pump();

      // The focus prompt is copied VERBATIM...
      expect(clipboardCalls, hasLength(1));
      expect((clipboardCalls.single.arguments as Map)['text'], kFocusPrompt);

      // ...and the inline row's opaque tap did NOT bubble up to open the drawer.
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('HOW TO PRACTICE'), findsNothing);

      // The informational "Copied" toast appears (600 ms delay + 400 ms in).
      await tester.pump(const Duration(milliseconds: 700));
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Copied'), findsOneWidget);

      // Flush the toast's 10 s auto-dismiss + 300 ms exit so no pending timer.
      await tester.pump(const Duration(seconds: 10));
      await tester.pump(const Duration(milliseconds: 350));
    });

    testWidgets(
      'tapping the card body opens the drawer with the practice loop',
      (tester) async {
        await pumpScreen(tester, buildScreen(payload: fullPayload()));

        expect(find.text('HOW TO PRACTICE'), findsNothing);
        // Tap the area TITLE (not the inline copy row) → opens the drawer.
        final areaTitle = find.text('Articles');
        await tester.ensureVisible(areaTitle);
        await tester.pump();
        await tester.tap(areaTitle);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400)); // drawer opens

        // The loop is explained in A2/B1 steps BEFORE the copy action — so a
        // first-time user understands what the copied prompt is for.
        expect(find.text('HOW TO PRACTICE'), findsOneWidget);
        expect(
          find.text('Keep practicing this skill on your own, for free.'),
          findsOneWidget,
        );
        expect(find.text('1. Copy the prompt below.'), findsOneWidget);
        expect(
          find.text(
            '2. Paste it into any AI chat (ChatGPT, Gemini, or Claude).',
          ),
          findsOneWidget,
        );
        expect(
          find.text('3. Turn on voice mode and practice out loud.'),
          findsOneWidget,
        );
        expect(find.text('Come back here when it feels easy.'), findsOneWidget);
        // The prominent CTA is present in the drawer too — 2 inline rows on the
        // cards behind + 1 drawer CTA = 3 "Copy the prompt".
        expect(find.text('Copy the prompt'), findsNWidgets(3));
      },
    );

    testWidgets('the prominent drawer CTA copies the prompt + toast', (
      tester,
    ) async {
      final clipboardCalls = <MethodCall>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') clipboardCalls.add(call);
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );

      await pumpScreen(tester, buildScreen(payload: fullPayload()));

      // Open the focus area's drawer via its TITLE (not its inline copy row).
      final focusTitle = find.text('Negative sentence structure');
      await tester.ensureVisible(focusTitle);
      await tester.pump();
      await tester.tap(focusTitle);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400)); // drawer opens

      // The drawer CTA is the LAST "Copy the prompt" (the modal route is pushed
      // on top of the cards). Bring it up — it sits below the how-to steps.
      final cta = find.text('Copy the prompt').last;
      await tester.ensureVisible(cta);
      await tester.pump();
      await tester.tap(cta);
      await tester.pump();

      // The server practice_prompt is copied VERBATIM.
      expect(clipboardCalls, hasLength(1));
      expect((clipboardCalls.single.arguments as Map)['text'], kFocusPrompt);

      // The informational "Copied" toast appears (600 ms delay + 400 ms in).
      await tester.pump(const Duration(milliseconds: 700));
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Copied'), findsOneWidget);

      // Flush the toast's 10 s auto-dismiss + 300 ms exit so no pending timer.
      await tester.pump(const Duration(seconds: 10));
      await tester.pump(const Duration(milliseconds: 350));
    });
  });

  group('error detail sheet (AC6, D1-b)', () {
    testWidgets('tapping an error with depth opens the dark detail sheet', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));

      expect(find.text('EXAMPLES'), findsNothing);
      final depthCard = find.text('I am agree');
      await tester.ensureVisible(depthCard);
      await tester.pump();
      await tester.tap(depthCard);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400)); // sheet opens

      // The sheet reveals the rule + the EXAMPLES eyebrow + an example.
      expect(find.text('EXAMPLES'), findsOneWidget);
      expect(
        find.text("The verb 'agree' takes no 'be'; it stands alone."),
        findsOneWidget,
      );
      expect(find.text('· I agree with you.'), findsOneWidget);
    });

    testWidgets('an error WITHOUT depth has no chevron and opens nothing', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      final shallowCard = find.text('He go away');
      await tester.ensureVisible(shallowCard);
      await tester.pump();
      await tester.tap(shallowCard);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      // No sheet opened.
      expect(find.text('EXAMPLES'), findsNothing);
    });
  });

  group('AC7-v2 — learning actions only, no praise', () {
    testWidgets('no retry/nav/monetization controls, one back affordance', (
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

    testWidgets('no praise and no exclamation mark anywhere in the chrome', (
      tester,
    ) async {
      await pumpScreen(
        tester,
        buildScreen(payload: fullPayload(survivalPct: 100)),
      );
      final rendered = tester
          .widgetList<Text>(find.byType(Text))
          .map((t) => t.data ?? '')
          .toList();
      for (final text in rendered) {
        expect(text.contains('!'), isFalse, reason: 'no "!" in "$text"');
      }
      final lower = rendered.map((t) => t.toLowerCase()).toList();
      for (final praise in [
        'great job',
        'congratulations',
        'well done',
        'nice',
      ]) {
        expect(
          lower.any((t) => t.contains(praise)),
          isFalse,
          reason: 'praise string "$praise" must never render',
        );
      }
    });
  });

  group('BS-7 fallback (AC10)', () {
    testWidgets('null payload + callId shows loading text, fades content in', (
      tester,
    ) async {
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
      await tester.pump();
      expect(find.text('Analyzing your conversation...'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);

      await tester.pump(const Duration(milliseconds: 60));
      await tester.pump(const Duration(milliseconds: 60));
      await tester.pump();
      expect(find.text('73%'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 310));
      expect(find.text('Analyzing your conversation...'), findsNothing);
      expect(calls, 3);
    });

    testWidgets('poll budget exhaustion lands on the quiet terminal state', (
      tester,
    ) async {
      when(() => repository.fetchDebrief(callId: 7)).thenAnswer(
        (_) async => throw const ApiException(
          code: 'DEBRIEF_NOT_READY',
          message: 'still generating',
          statusCode: 404,
        ),
      );

      await pumpScreen(tester, buildScreen(payload: null));
      await tester.pump();
      expect(find.text('Analyzing your conversation...'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 450));
      expect(find.text('Debrief unavailable for this call.'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 310));
      expect(find.byType(SnackBar), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
      'an in-flight fetch when the budget fires still lands content',
      (tester) async {
        final completer = Completer<Map<String, dynamic>>();
        when(
          () => repository.fetchDebrief(callId: 7),
        ).thenAnswer((_) => completer.future);

        await pumpScreen(tester, buildScreen(payload: null));
        expect(find.text('Analyzing your conversation...'), findsOneWidget);
        await tester.pump(const Duration(milliseconds: 450));
        expect(find.text('Debrief unavailable for this call.'), findsOneWidget);
        completer.complete(fullPayload());
        await tester.pump();
        expect(find.text('73%'), findsOneWidget);
        await tester.pump(const Duration(milliseconds: 310));
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
      // Drain any pending budget timer; the terminal state must not crash.
      await tester.pump(const Duration(milliseconds: 450));
      expect(tester.takeException(), isNull);
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
      // Content state runs NO timers (payload provided), so pumpAndSettle is
      // safe here.
      await tester.pumpAndSettle();
      expect(find.text('73%'), findsOneWidget);

      await tester.tap(find.byIcon(Icons.arrow_back_ios_new));
      await tester.pumpAndSettle();
      expect(find.text('HOME'), findsOneWidget);
      expect(find.text('73%'), findsNothing);
    });
  });

  group('a11y', () {
    testWidgets('back arrow + gauge label, eyebrow headers marked', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await pumpScreen(tester, buildScreen(payload: fullPayload()));

      expect(find.bySemanticsLabel('Back to scenarios'), findsOneWidget);
      expect(find.bySemanticsLabel('73 percent survival rate'), findsOneWidget);

      final header = tester.getSemantics(find.text('LANGUAGE ERRORS'));
      expect(header.flagsCollection.isHeader, isTrue);
      handle.dispose();
    });

    testWidgets('back arrow keeps the 44x44 touch target', (tester) async {
      await pumpScreen(tester, buildScreen(payload: fullPayload()));
      expect(tester.getSize(find.byType(IconButton)), const Size(44, 44));
    });
  });

  group('Story 8.2 — FR29 paywall on load (AC3)', () {
    setUp(() {
      FlutterSecureStorage.setMockInitialValues({});
      final paywallBloc = MockSubscriptionBloc();
      whenListen(
        paywallBloc,
        const Stream<SubscriptionState>.empty(),
        initialState: const SubscriptionInitial(),
      );
      PaywallSheet.debugBlocBuilder = () => paywallBloc;
    });

    tearDown(() => PaywallSheet.debugBlocBuilder = null);

    testWidgets(
      'presentPaywallOnLoad: true auto-presents the paywall over the debrief',
      (tester) async {
        await pumpScreen(
          tester,
          DebriefScreen(
            payload: fullPayload(),
            callId: 7,
            callRepository: repository,
            presentPaywallOnLoad: true,
          ),
        );
        await tester.pumpAndSettle();

        // The paywall is shown…
        expect(find.byType(BottomSheet), findsOneWidget);
        expect(find.text('Speak English for real'), findsOneWidget);
        // …with the debrief still rendered behind the scrim.
        expect(find.text('Survival Rate'), findsOneWidget);
      },
    );

    testWidgets(
      'presentPaywallOnLoad: false (default) does NOT present the paywall',
      (tester) async {
        await pumpScreen(tester, buildScreen(payload: fullPayload()));
        await tester.pumpAndSettle();

        expect(find.byType(BottomSheet), findsNothing);
        expect(find.text('Speak English for real'), findsNothing);
      },
    );
  });

  // ===========================================================================
  // Story 10.7 (Bug B) — progressive debrief
  // ===========================================================================
  group('Story 10.7 — progressive debrief (Bug B)', () {
    testWidgets(
      'a pending payload shows the scorecard + analyzing placeholder, keeps polling',
      (tester) async {
        when(() => repository.fetchDebrief(callId: 7)).thenAnswer(
          (_) async => throw const ApiException(
            code: 'DEBRIEF_NOT_READY',
            message: 'still generating',
            statusCode: 404,
          ),
        );

        await pumpScreen(tester, buildScreen(payload: pendingPayload()));
        await tester.pump();

        // The scorecard + checkpoints render INSTANTLY from the pending payload.
        expect(find.text('73%'), findsOneWidget);
        expect(find.text('CHECKPOINTS'), findsOneWidget);
        expect(find.text('1 of 2 reached'), findsOneWidget);
        // The analysis is a quiet placeholder — NOT the empty "No errors
        // flagged" sections (which would falsely imply a flawless call).
        expect(find.text('ANALYSIS'), findsOneWidget);
        expect(find.text('Analyzing your conversation...'), findsOneWidget);
        expect(find.text('LANGUAGE ERRORS'), findsNothing);

        // It KEEPS polling for the analysis (the score being shown is not a
        // terminal state).
        await tester.pump(const Duration(milliseconds: 60));
        verify(
          () => repository.fetchDebrief(callId: 7),
        ).called(greaterThanOrEqualTo(1));

        // Drain the budget so no timer outlives the test.
        await tester.pump(const Duration(milliseconds: 450));
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('a ready fetch fills the analysis in and stops polling', (
      tester,
    ) async {
      var calls = 0;
      when(() => repository.fetchDebrief(callId: 7)).thenAnswer((_) async {
        calls++;
        return fullPayload();
      });

      await pumpScreen(tester, buildScreen(payload: pendingPayload()));
      await tester.pump();
      expect(find.text('Analyzing your conversation...'), findsOneWidget);
      expect(find.text('LANGUAGE ERRORS'), findsNothing);

      // The first poll returns the READY analysis → it merges in.
      await tester.pump(const Duration(milliseconds: 60));
      await tester.pump();
      expect(find.text('LANGUAGE ERRORS'), findsOneWidget);
      expect(find.text('I am agree'), findsOneWidget);
      expect(find.text('Analyzing your conversation...'), findsNothing);

      // Polling stops on a terminal (ready) payload — no further fetches.
      await tester.pump(const Duration(milliseconds: 410));
      final settledCalls = calls;
      await tester.pump(const Duration(milliseconds: 410));
      expect(calls, settledCalls);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
      'budget exhaustion while pending lands a score-only (degraded) terminal',
      (tester) async {
        when(() => repository.fetchDebrief(callId: 7)).thenAnswer(
          (_) async => throw const ApiException(
            code: 'DEBRIEF_NOT_READY',
            message: 'still generating',
            statusCode: 404,
          ),
        );

        await pumpScreen(tester, buildScreen(payload: pendingPayload()));
        await tester.pump();
        expect(find.text('73%'), findsOneWidget);
        expect(find.text('Analyzing your conversation...'), findsOneWidget);

        // The analysis never lands within the budget.
        await tester.pump(const Duration(milliseconds: 450));

        // Never blank: the score + checkpoints stay; the placeholder is replaced
        // by the honest "unavailable" line (the degraded terminal).
        expect(find.text('73%'), findsOneWidget);
        expect(find.text('CHECKPOINTS'), findsOneWidget);
        expect(find.text('Analyzing your conversation...'), findsNothing);
        expect(
          find.text('Detailed analysis is unavailable for this call.'),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'a pending payload with no callId degrades to score-only immediately',
      (tester) async {
        await pumpScreen(
          tester,
          buildScreen(payload: pendingPayload(), callId: null),
        );
        await tester.pump();
        // No id to poll with → render the score, but never spin the placeholder.
        expect(find.text('73%'), findsOneWidget);
        expect(find.text('Analyzing your conversation...'), findsNothing);
        expect(
          find.text('Detailed analysis is unavailable for this call.'),
          findsOneWidget,
        );
        verifyNever(
          () => repository.fetchDebrief(callId: any(named: 'callId')),
        );
      },
    );
  });

  group('Story 10.7 — progressive offline cache (Story 9.1)', () {
    testWidgets('a pending payload is NOT cached; the ready analysis IS', (
      tester,
    ) async {
      final store = MockDebriefCacheStore();
      final writes = <Map<String, dynamic>>[];
      when(
        () => store.write(
          callId: any(named: 'callId'),
          scenarioId: any(named: 'scenarioId'),
          payload: any(named: 'payload'),
        ),
      ).thenAnswer((inv) async {
        writes.add(inv.namedArguments[#payload] as Map<String, dynamic>);
      });

      var ready = false;
      when(() => repository.fetchDebrief(callId: 7)).thenAnswer((_) async {
        if (!ready) {
          throw const ApiException(
            code: 'DEBRIEF_NOT_READY',
            message: 'still generating',
            statusCode: 404,
          );
        }
        return fullPayload();
      });

      await pumpScreen(
        tester,
        buildScreen(
          payload: pendingPayload(),
          cacheStore: store,
          scenarioId: 'mugger_medium_01',
        ),
      );
      await tester.pump();
      // While pending, NOTHING is cached (never a pending blob as final).
      await tester.pump(const Duration(milliseconds: 60));
      expect(writes, isEmpty);

      // Once the READY analysis lands, it IS cached — and it is not pending.
      ready = true;
      await tester.pump(const Duration(milliseconds: 60));
      await tester.pump();
      expect(writes, hasLength(1));
      expect(writes.first['pending'], isNot(true));
      expect(writes.first['errors'], isNotEmpty);

      await tester.pump(const Duration(milliseconds: 410));
      expect(tester.takeException(), isNull);
    });
  });

  group('Story 10.7 — paywall deferred until the analysis merges', () {
    setUp(() {
      FlutterSecureStorage.setMockInitialValues({});
      final paywallBloc = MockSubscriptionBloc();
      whenListen(
        paywallBloc,
        const Stream<SubscriptionState>.empty(),
        initialState: const SubscriptionInitial(),
      );
      PaywallSheet.debugBlocBuilder = () => paywallBloc;
    });

    tearDown(() => PaywallSheet.debugBlocBuilder = null);

    testWidgets(
      'the paywall is NOT presented while pending, then presents at the terminal',
      (tester) async {
        when(() => repository.fetchDebrief(callId: 7)).thenAnswer(
          (_) async => throw const ApiException(
            code: 'DEBRIEF_NOT_READY',
            message: 'still generating',
            statusCode: 404,
          ),
        );

        await pumpScreen(
          tester,
          DebriefScreen(
            payload: pendingPayload(),
            callId: 7,
            callRepository: repository,
            presentPaywallOnLoad: true,
            pollInterval: const Duration(milliseconds: 50),
            pollBudget: const Duration(milliseconds: 400),
          ),
        );
        await tester.pump();
        // Deferred: the scrim must not cover the analysis-pending state.
        await tester.pump(const Duration(milliseconds: 100));
        expect(find.text('Speak English for real'), findsNothing);

        // The budget fires → the debrief reaches a terminal state → the paywall
        // is now allowed.
        await tester.pump(const Duration(milliseconds: 350));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));
        expect(find.byType(BottomSheet), findsOneWidget);
        expect(find.text('Speak English for real'), findsOneWidget);
      },
    );
  });
}
