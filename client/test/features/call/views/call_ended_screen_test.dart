// Story 7.2 — Call Ended overlay tests.
//
// Timing tests shrink the canonical hold durations through the widget's
// timing seams and advance the clock with explicit `pump(Duration)` calls
// (client/CLAUDE.md §3 — never `pumpAndSettle` on a screen with pending
// timers). Layout tests force a phone surface (§7).

import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/app/router.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:client/features/call/views/call_ended_screen.dart';
import 'package:client/features/debrief/views/debrief_screen.dart';
import 'package:client/features/paywall/views/paywall_sheet.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/subscription/bloc/subscription_bloc.dart';
import 'package:client/features/subscription/bloc/subscription_event.dart';
import 'package:client/features/subscription/bloc/subscription_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockCallRepository extends Mock implements CallRepository {}

/// Story 8.2 (FR29) — drives the auto-presented paywall through the test seam.
class MockSubscriptionBloc
    extends MockBloc<SubscriptionEvent, SubscriptionState>
    implements SubscriptionBloc {}

const Map<String, String> _kPhrases = {
  'hung_up': 'The waitress kicked you out',
  'voluntary': 'You walked out',
  'survived': 'You actually got your food',
};

Scenario _scenario({Map<String, String>? endPhrases = _kPhrases}) {
  return Scenario(
    id: 'waiter_easy_01',
    title: 'The Waiter',
    isFree: true,
    riveCharacter: 'waiter',
    languageFocus: const <String>['ordering food'],
    contentWarning: null,
    bestScore: null,
    attempts: 0,
    tagline: '',
    endPhrases: endPhrases,
  );
}

void main() {
  late MockCallRepository repository;

  setUp(() {
    repository = MockCallRepository();
    // Default: the debrief never resolves, so render-focused tests can
    // pump freely below the (shrunk) cap without triggering the exit.
    when(
      () => repository.fetchDebrief(callId: any(named: 'callId')),
    ).thenAnswer((_) => Completer<Map<String, dynamic>>().future);
  });

  /// Shrunk-timing screen: entry 0 ms, min hold 100 ms (300 ms with a
  /// screen reader), cap 500 ms, poll 50 ms.
  CallEndedScreen buildScreen({
    String endReason = 'character_hung_up',
    int? durationSec = 167,
    int? callId = 7,
    int checkpointsPassed = 3,
    int totalCheckpoints = 6,
    Map<String, String>? endPhrases = _kPhrases,
    Route<void> Function(Map<String, dynamic>? payload)? debriefRouteBuilder,
    bool presentPaywallOnDebrief = false,
  }) {
    return CallEndedScreen(
      scenario: _scenario(endPhrases: endPhrases),
      endReason: endReason,
      durationSec: durationSec,
      callId: callId,
      checkpointsPassed: checkpointsPassed,
      totalCheckpoints: totalCheckpoints,
      callRepository: repository,
      presentPaywallOnDebrief: presentPaywallOnDebrief,
      entryDuration: Duration.zero,
      minHold: const Duration(milliseconds: 100),
      minHoldAccessible: const Duration(milliseconds: 300),
      maxHold: const Duration(milliseconds: 500),
      pollInterval: const Duration(milliseconds: 50),
      debugDebriefRouteBuilder: debriefRouteBuilder,
    );
  }

  Future<void> pumpScreen(WidgetTester tester, CallEndedScreen screen) async {
    await tester.binding.setSurfaceSize(const Size(320, 568));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(home: screen));
  }

  /// Sentinel route the timing tests use to observe the exit transition +
  /// the forwarded payload without pulling go_router into the tree.
  Route<void> Function(Map<String, dynamic>?) sentinelRoute(
    List<Map<String, dynamic>?> forwarded,
  ) {
    return (payload) {
      forwarded.add(payload);
      return MaterialPageRoute<void>(
        builder: (_) => const Scaffold(body: Text('DEBRIEF_SENTINEL')),
      );
    };
  }

  group('pure helpers', () {
    test('callEndedPhraseVariant maps reason → variant (AC-C6)', () {
      expect(callEndedPhraseVariant('survived'), 'survived');
      expect(callEndedPhraseVariant('user_hung_up'), 'voluntary');
      expect(callEndedPhraseVariant('character_hung_up'), 'hung_up');
      expect(callEndedPhraseVariant('inappropriate_content'), 'hung_up');
    });

    test('computeSurvivalPct floors and clamps (AC-C4)', () {
      expect(computeSurvivalPct(passed: 5, total: 6), 83); // floor(83.33)
      expect(computeSurvivalPct(passed: 6, total: 6), 100);
      expect(computeSurvivalPct(passed: 0, total: 6), 0);
      expect(computeSurvivalPct(passed: 0, total: 0), 0); // P-8
      expect(computeSurvivalPct(passed: 9, total: 6), 100); // clamp high
      expect(computeSurvivalPct(passed: -1, total: 6), 0); // clamp low
    });

    test('formatCallDuration follows the design format rules (AC-C7)', () {
      expect(formatCallDuration(0), '00:00');
      expect(formatCallDuration(167), '02:47');
      expect(formatCallDuration(125), '02:05');
      expect(formatCallDuration(659), '10:59');
      expect(formatCallDuration(3735), '1:02:15'); // H:MM:SS over 1 h
      expect(formatCallDuration(-5), '00:00'); // defensive
    });

    test('callEndedAnnouncement drops the role cleanly on a catalog miss '
        '(review patch — degraded server-added scenario)', () {
      final announcement = callEndedAnnouncement(
        name: 'The Stranger',
        role: '',
        durationSec: 30,
        pct: 50,
        success: false,
        phrase: null,
      );
      expect(announcement, startsWith('The Stranger. Call Ended.'));
      expect(announcement.contains(', .'), isFalse);

      // Known character keeps the "Name, Role." form untouched.
      final full = callEndedAnnouncement(
        name: 'Tina',
        role: 'Waitress',
        durationSec: 167,
        pct: 50,
        success: false,
        phrase: null,
      );
      expect(
        full,
        'Tina, Waitress. Call Ended. Duration: 2 minutes 47 seconds. '
        'Achievement: 50 percent — failed.',
      );
    });
  });

  group('rendering', () {
    testWidgets('failure variant — red %, bar fill, phrase (AC-C2/C5/C6)', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(endReason: 'character_hung_up'));
      await tester.pump(const Duration(milliseconds: 10));

      // Identity zone from kCharacterCatalog (AC-C3).
      expect(find.text('Tina'), findsOneWidget);
      expect(find.text('Waitress'), findsOneWidget);
      expect(find.text('02:47'), findsOneWidget);
      expect(find.text('Call Ended'), findsOneWidget);

      // Result zone — floor(3/6*100) = 50, failure red.
      final pctText = tester.widget<Text>(find.text('50%'));
      expect(pctText.style?.color, AppColors.destructive);

      final bar = tester.widget<LinearProgressIndicator>(
        find.byType(LinearProgressIndicator),
      );
      expect(bar.value, 0.5);
      expect(bar.color, AppColors.destructive);
      expect(bar.backgroundColor, AppColors.avatarBg);

      final phrase = tester.widget<Text>(
        find.text('The waitress kicked you out'),
      );
      expect(phrase.style?.color, AppColors.destructive);
      expect(phrase.style?.fontStyle, FontStyle.italic);
    });

    testWidgets('success variant — green 100% + survived phrase (AC-C5/C6)', (
      tester,
    ) async {
      await pumpScreen(
        tester,
        buildScreen(
          endReason: 'survived',
          checkpointsPassed: 6,
          totalCheckpoints: 6,
        ),
      );
      await tester.pump(const Duration(milliseconds: 10));

      final pctText = tester.widget<Text>(find.text('100%'));
      expect(pctText.style?.color, AppColors.accent);

      final bar = tester.widget<LinearProgressIndicator>(
        find.byType(LinearProgressIndicator),
      );
      expect(bar.value, 1.0);
      expect(bar.color, AppColors.accent);

      final phrase = tester.widget<Text>(
        find.text('You actually got your food'),
      );
      expect(phrase.style?.color, AppColors.accent);
    });

    testWidgets('user_hung_up → voluntary phrase, failure red (AC-C6)', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(endReason: 'user_hung_up'));
      await tester.pump(const Duration(milliseconds: 10));

      final phrase = tester.widget<Text>(find.text('You walked out'));
      expect(phrase.style?.color, AppColors.destructive);
    });

    testWidgets('total == 0 → 0% with track-only bar (AC-C4 / P-8)', (
      tester,
    ) async {
      await pumpScreen(
        tester,
        buildScreen(checkpointsPassed: 0, totalCheckpoints: 0),
      );
      await tester.pump(const Duration(milliseconds: 10));

      expect(find.text('0%'), findsOneWidget);
      final bar = tester.widget<LinearProgressIndicator>(
        find.byType(LinearProgressIndicator),
      );
      expect(bar.value, 0.0);
    });

    testWidgets('null durationSec renders as 00:00 (AC-C7 edge)', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(durationSec: null));
      await tester.pump(const Duration(milliseconds: 10));

      expect(find.text('00:00'), findsOneWidget);
    });

    testWidgets('missing endPhrases hides the phrase element (AC-C6 / P-7)', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen(endPhrases: null));
      await tester.pump(const Duration(milliseconds: 10));

      expect(find.text('The waitress kicked you out'), findsNothing);
      expect(find.textContaining('null'), findsNothing);
      // The % + bar above stay — only the phrase element is dropped.
      expect(find.text('50%'), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
    });

    testWidgets('blocks back navigation during the hold (AC-C2 / P-4)', (
      tester,
    ) async {
      await pumpScreen(tester, buildScreen());
      await tester.pump(const Duration(milliseconds: 10));

      // `PopScope` is generic — find by predicate so the test doesn't
      // depend on the inferred type argument.
      final popScope =
          tester.widget(find.byWidgetPredicate((w) => w is PopScope))
              as PopScope;
      expect(popScope.canPop, isFalse);

      // A back attempt during the hold must not pop the overlay.
      final navigator = tester.state<NavigatorState>(find.byType(Navigator));
      await navigator.maybePop();
      await tester.pump(const Duration(milliseconds: 10));
      expect(find.text('Call Ended'), findsOneWidget);
    });

    testWidgets(
      'live region announces the outcome word for screen readers (AC-C13 / P-5)',
      (tester) async {
        final handle = tester.ensureSemantics();
        await pumpScreen(tester, buildScreen(endReason: 'character_hung_up'));
        await tester.pump(const Duration(milliseconds: 10));

        expect(
          find.bySemanticsLabel(
            RegExp(
              r'Tina, Waitress\. Call Ended\. '
              r'Duration: 2 minutes 47 seconds\. '
              r'Achievement: 50 percent — failed\.',
            ),
          ),
          findsOneWidget,
        );
        handle.dispose();
      },
    );

    testWidgets('no overflow at 320×568 with a 2-line phrase (AC-C2)', (
      tester,
    ) async {
      final overflowErrors = <FlutterErrorDetails>[];
      final prior = FlutterError.onError;
      FlutterError.onError = (details) {
        if (details.toString().contains('overflowed')) {
          overflowErrors.add(details);
          return;
        }
        prior?.call(details);
      };
      addTearDown(() => FlutterError.onError = prior);

      await pumpScreen(
        tester,
        buildScreen(
          endPhrases: const {
            // 70-char hard limit — the longest legal phrase.
            'hung_up':
                'The waitress kicked you out of the restaurant without a '
                'single word',
          },
        ),
      );
      await tester.pump(const Duration(milliseconds: 10));

      expect(overflowErrors, isEmpty);
    });

    testWidgets('no overflow at 320×480 with textScaler 1.5 — Story 5.4 scroll '
        'wrapper (review patch)', (tester) async {
      final overflowErrors = <FlutterErrorDetails>[];
      final prior = FlutterError.onError;
      FlutterError.onError = (details) {
        if (details.toString().contains('overflowed')) {
          overflowErrors.add(details);
          return;
        }
        prior?.call(details);
      };
      addTearDown(() => FlutterError.onError = prior);

      await tester.binding.setSurfaceSize(const Size(320, 480));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MediaQuery(
          data: const MediaQueryData(textScaler: TextScaler.linear(1.5)),
          child: MaterialApp(home: buildScreen()),
        ),
      );
      await tester.pump(const Duration(milliseconds: 10));

      expect(overflowErrors, isEmpty);
      // The wrapper degrades to scrolling, never clipping.
      expect(find.byType(SingleChildScrollView), findsOneWidget);
      expect(find.text('Call Ended'), findsOneWidget);
    });
  });

  group('hold + debrief fetch + transition', () {
    testWidgets(
      'exits on the LAST condition — debrief ready early, min hold gates (AC-C9)',
      (tester) async {
        when(
          () => repository.fetchDebrief(callId: 7),
        ).thenAnswer((_) async => <String, dynamic>{'survival_pct': 50});
        final forwarded = <Map<String, dynamic>?>[];

        await pumpScreen(
          tester,
          buildScreen(debriefRouteBuilder: sentinelRoute(forwarded)),
        );
        // Debrief resolves immediately, but the 100 ms min hold hasn't
        // elapsed → still holding.
        await tester.pump(const Duration(milliseconds: 50));
        expect(find.text('Call Ended'), findsOneWidget);
        expect(find.text('DEBRIEF_SENTINEL'), findsNothing);

        // Min hold elapses → exit fires, payload forwarded (AC-C11).
        await tester.pump(const Duration(milliseconds: 100));
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.text('DEBRIEF_SENTINEL'), findsOneWidget);
        expect(forwarded.single, {'survival_pct': 50});
      },
    );

    testWidgets(
      'exits on the LAST condition — min hold elapsed, debrief gates (AC-C8/C9)',
      (tester) async {
        final completer = Completer<Map<String, dynamic>>();
        when(
          () => repository.fetchDebrief(callId: 7),
        ).thenAnswer((_) => completer.future);
        final forwarded = <Map<String, dynamic>?>[];

        await pumpScreen(
          tester,
          buildScreen(debriefRouteBuilder: sentinelRoute(forwarded)),
        );
        // Min hold (100 ms) long gone, debrief still pending → holding.
        await tester.pump(const Duration(milliseconds: 200));
        expect(find.text('Call Ended'), findsOneWidget);

        completer.complete(<String, dynamic>{'ok': true});
        // Three pumps: flush the completion microtask (the exit pushes the
        // route), render the transition's first frame (ticker t0), then
        // advance past the route transition.
        await tester.pump();
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.text('DEBRIEF_SENTINEL'), findsOneWidget);
        expect(forwarded.single, {'ok': true});
      },
    );

    testWidgets('hard cap exits without the debrief, null payload (AC-C9)', (
      tester,
    ) async {
      // Default stub: fetchDebrief never resolves.
      final forwarded = <Map<String, dynamic>?>[];

      await pumpScreen(
        tester,
        buildScreen(debriefRouteBuilder: sentinelRoute(forwarded)),
      );
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Call Ended'), findsOneWidget);

      // Cap (500 ms) fires → forced exit, no payload.
      await tester.pump(const Duration(milliseconds: 200));
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('DEBRIEF_SENTINEL'), findsOneWidget);
      expect(forwarded.single, isNull);
    });

    testWidgets('polls on DEBRIEF_NOT_READY until ready (AC-C8)', (
      tester,
    ) async {
      var calls = 0;
      when(() => repository.fetchDebrief(callId: 7)).thenAnswer((_) async {
        calls += 1;
        if (calls < 3) {
          throw const ApiException(
            code: 'DEBRIEF_NOT_READY',
            message: 'Debrief is still being generated.',
            statusCode: 404,
          );
        }
        return <String, dynamic>{'ready': true};
      });
      final forwarded = <Map<String, dynamic>?>[];

      await pumpScreen(
        tester,
        buildScreen(debriefRouteBuilder: sentinelRoute(forwarded)),
      );
      // Two 50 ms poll cycles + the 100 ms min hold.
      await tester.pump(const Duration(milliseconds: 60));
      await tester.pump(const Duration(milliseconds: 60));
      await tester.pump(const Duration(milliseconds: 60));
      await tester.pump(const Duration(milliseconds: 400));

      expect(calls, 3);
      expect(find.text('DEBRIEF_SENTINEL'), findsOneWidget);
      expect(forwarded.single, {'ready': true});
    });

    testWidgets(
      'terminal fetch failure settles silently — no poll, no error chrome (AC-C8)',
      (tester) async {
        var calls = 0;
        when(() => repository.fetchDebrief(callId: 7)).thenAnswer((_) async {
          calls += 1;
          throw const ApiException(
            code: 'CALL_NOT_FOUND',
            message: 'Call not found.',
            statusCode: 404,
          );
        });
        final forwarded = <Map<String, dynamic>?>[];

        await pumpScreen(
          tester,
          buildScreen(debriefRouteBuilder: sentinelRoute(forwarded)),
        );
        await tester.pump(const Duration(milliseconds: 150));
        await tester.pump(const Duration(milliseconds: 400));

        expect(calls, 1, reason: 'a non-NOT_READY failure must not poll');
        expect(find.text('DEBRIEF_SENTINEL'), findsOneWidget);
        expect(forwarded.single, isNull);
      },
    );

    testWidgets('null callId skips the fetch, exits on min hold alone', (
      tester,
    ) async {
      final forwarded = <Map<String, dynamic>?>[];

      await pumpScreen(
        tester,
        buildScreen(
          callId: null,
          debriefRouteBuilder: sentinelRoute(forwarded),
        ),
      );
      await tester.pump(const Duration(milliseconds: 150));
      await tester.pump(const Duration(milliseconds: 400));

      verifyNever(() => repository.fetchDebrief(callId: any(named: 'callId')));
      expect(find.text('DEBRIEF_SENTINEL'), findsOneWidget);
      expect(forwarded.single, isNull);
    });

    testWidgets(
      'screen reader active → extended min hold gates the exit (AC-C9 / P-6)',
      (tester) async {
        when(
          () => repository.fetchDebrief(callId: 7),
        ).thenAnswer((_) async => <String, dynamic>{'ok': true});
        final forwarded = <Map<String, dynamic>?>[];

        await tester.binding.setSurfaceSize(const Size(320, 568));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        await tester.pumpWidget(
          MaterialApp(
            home: MediaQuery(
              data: const MediaQueryData(accessibleNavigation: true),
              child: buildScreen(debriefRouteBuilder: sentinelRoute(forwarded)),
            ),
          ),
        );

        // Past the normal 100 ms min hold but under the 300 ms accessible
        // hold — must still be holding despite the resolved debrief.
        await tester.pump(const Duration(milliseconds: 200));
        expect(find.text('Call Ended'), findsOneWidget);

        await tester.pump(const Duration(milliseconds: 150));
        await tester.pump(const Duration(milliseconds: 400));
        expect(find.text('DEBRIEF_SENTINEL'), findsOneWidget);
      },
    );
  });

  group('real debrief route (review P4)', () {
    testWidgets('production _debriefRoute hands payload/callId/repository to '
        'DebriefScreen and keeps the Decision-F arguments contract', (
      tester,
    ) async {
      final payload = <String, dynamic>{
        'survival_pct': 83,
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
      when(
        () => repository.fetchDebrief(callId: any(named: 'callId')),
      ).thenAnswer((_) async => payload);

      // No debugDebriefRouteBuilder — the REAL route is exercised.
      await pumpScreen(tester, buildScreen());

      // Min hold (100 ms) with the fetch settled → exit fires the real
      // route; then complete the 900 ms exit transition.
      await tester.pump(const Duration(milliseconds: 150));
      await tester.pump(CallEndedScreen.kExitTransition);
      await tester.pump(const Duration(milliseconds: 50));

      final debriefFinder = find.byType(DebriefScreen);
      expect(debriefFinder, findsOneWidget);
      final debrief = tester.widget<DebriefScreen>(debriefFinder);
      expect(debrief.payload, same(payload));
      expect(debrief.callId, 7);
      expect(debrief.callRepository, same(repository));

      // Decision-F: the payload also rides RouteSettings.arguments.
      final route = ModalRoute.of(tester.element(debriefFinder))!;
      expect(route.settings.name, AppRoutes.debrief);
      expect(route.settings.arguments, same(payload));
    });

    testWidgets('Story 8.2 (FR29) — presentPaywallOnDebrief threads to '
        'DebriefScreen.presentPaywallOnLoad', (tester) async {
      // Drive the auto-presented paywall through the test seam so it never
      // touches the real store plugin.
      FlutterSecureStorage.setMockInitialValues({});
      final paywallBloc = MockSubscriptionBloc();
      whenListen(
        paywallBloc,
        const Stream<SubscriptionState>.empty(),
        initialState: const SubscriptionInitial(),
      );
      PaywallSheet.debugBlocBuilder = () => paywallBloc;
      addTearDown(() => PaywallSheet.debugBlocBuilder = null);

      final payload = <String, dynamic>{
        'survival_pct': 83,
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
      when(
        () => repository.fetchDebrief(callId: any(named: 'callId')),
      ).thenAnswer((_) async => payload);

      await pumpScreen(tester, buildScreen(presentPaywallOnDebrief: true));
      await tester.pump(const Duration(milliseconds: 150));
      await tester.pump(CallEndedScreen.kExitTransition);
      await tester.pumpAndSettle();

      final debrief = tester.widget<DebriefScreen>(find.byType(DebriefScreen));
      expect(debrief.presentPaywallOnLoad, isTrue);
      // The flag actually fired the sheet on the debrief.
      expect(find.byType(BottomSheet), findsOneWidget);
    });
  });
}
