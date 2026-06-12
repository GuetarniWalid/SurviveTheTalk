// Story 7.4 — BriefingScreen ("The Handler's Brief") widget tests.
//
// The screen is a pure render + confirm surface: everything here drives it
// through a tiny GoRouter (the production pop contract uses go_router's
// `context.pop(bool)`), with a launcher screen capturing the popped result
// exactly like the hub's `_onCallTap` does.

import 'dart:io';

import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/briefing/views/briefing_screen.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

// The authored waiter briefing (Dev Notes §Data contract) — quotes and
// commas inside the vocabulary string are part of the verbatim contract.
const Map<String, String> _kFullBriefing = <String, String>{
  'vocabulary': '"I\'d like...", "soup of the day", "grilled / fried"',
  'context':
      "You're ordering food at a restaurant. The waitress is not in a good mood.",
  'expect':
      "The waitress is impatient — order clearly and don't take too long deciding.",
};

const String _kStakesLine = 'They can hang up on you. So can you.';

Scenario _scenario({Map<String, String>? briefing, String title = 'The Waiter'}) {
  return Scenario(
    id: 'waiter_easy_01',
    title: title,
    isFree: true,
    riveCharacter: 'waiter',
    languageFocus: const <String>[],
    contentWarning: null,
    bestScore: null,
    attempts: 0,
    tagline: '',
    briefing: briefing,
  );
}

Widget _app(Scenario scenario, List<bool?> results) {
  return MaterialApp.router(
    theme: AppTheme.dark(),
    routerConfig: GoRouter(
      initialLocation: '/',
      routes: [
        GoRoute(
          path: '/',
          builder: (context, state) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () async {
                  final ready = await context.push<bool>(
                    '/briefing/${scenario.id}',
                    extra: scenario,
                  );
                  results.add(ready);
                },
                child: const Text('OPEN'),
              ),
            ),
          ),
        ),
        GoRoute(
          path: '/briefing/:scenarioId',
          builder: (context, state) =>
              BriefingScreen(scenario: state.extra! as Scenario),
        ),
      ],
    ),
  );
}

Future<List<bool?>> _open(
  WidgetTester tester,
  Scenario scenario, {
  Size size = const Size(390, 844),
  TextScaler textScaler = TextScaler.noScaling,
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() => tester.binding.setSurfaceSize(null));
  final results = <bool?>[];
  await tester.pumpWidget(
    MediaQuery(
      data: MediaQueryData(textScaler: textScaler),
      child: _app(scenario, results),
    ),
  );
  await tester.tap(find.text('OPEN'));
  await tester.pumpAndSettle();
  return results;
}

void main() {
  setUpAll(() async {
    // Review patch (7.4): the §Layout spec viewport contract (360×800
    // above-the-fold) is typographic — the test font's square glyphs wrap
    // ~2× wider than Inter and fail it spuriously. Load the real family
    // once for this suite (weights the screen composes: 400/500/700 +
    // italic); narrower real glyphs only relax the other layout tests.
    TestWidgetsFlutterBinding.ensureInitialized();
    final loader = FontLoader('Inter')
      ..addFont(rootBundle.load('assets/fonts/inter/Inter-Regular.ttf'))
      ..addFont(rootBundle.load('assets/fonts/inter/Inter-Italic.ttf'))
      ..addFont(rootBundle.load('assets/fonts/inter/Inter-Medium.ttf'))
      ..addFont(rootBundle.load('assets/fonts/inter/Inter-Bold.ttf'));
    await loader.load();
  });

  group('BriefingScreen — "The Handler\'s Brief" layout', () {
    testWidgets('renders the full dossier in the fixed left-rail order',
        (tester) async {
      await _open(tester, _scenario(briefing: _kFullBriefing));

      // Every lockup element present, exactly once. The 72px hero circle is
      // the screen's only ClipOval (and only pictorial element).
      expect(find.byType(ClipOval), findsOneWidget);
      expect(tester.getSize(find.byType(ClipOval)), const Size(72, 72));
      expect(find.text('INCOMING CALL'), findsOneWidget);
      expect(find.text('The Waiter'), findsOneWidget);
      expect(
        find.text('Live voice call · English only · No script'),
        findsOneWidget,
      );
      expect(find.text('THE SITUATION'), findsOneWidget);
      expect(find.text('WHAT TO EXPECT'), findsOneWidget);
      expect(find.text('SAY THIS'), findsOneWidget);

      // Fixed vertical order: hero → kicker → title → fact line → triad
      // (SAY THIS last, nearest the CTA).
      final heroY = tester.getTopLeft(find.byType(ClipOval)).dy;
      final kickerY = tester.getTopLeft(find.text('INCOMING CALL')).dy;
      expect(heroY, lessThan(kickerY));
      final titleY = tester.getTopLeft(find.text('The Waiter')).dy;
      final factY = tester
          .getTopLeft(find.text('Live voice call · English only · No script'))
          .dy;
      final situationY = tester.getTopLeft(find.text('THE SITUATION')).dy;
      final expectY = tester.getTopLeft(find.text('WHAT TO EXPECT')).dy;
      final sayThisY = tester.getTopLeft(find.text('SAY THIS')).dy;
      final stakesY = tester.getTopLeft(find.text(_kStakesLine)).dy;
      expect(kickerY, lessThan(titleY));
      expect(titleY, lessThan(factY));
      expect(factY, lessThan(situationY));
      expect(situationY, lessThan(expectY));
      expect(expectY, lessThan(sayThisY));
      expect(sayThisY, lessThan(stakesY));

      // One left rail: kicker, title, fact line, and eyebrows all share the
      // same x (nothing centered).
      final railX = tester.getTopLeft(find.text('INCOMING CALL')).dx;
      expect(tester.getTopLeft(find.text('The Waiter')).dx, railX);
      expect(tester.getTopLeft(find.text('THE SITUATION')).dx, railX);
      expect(tester.getTopLeft(find.text(_kStakesLine)).dx, railX);
    });

    testWidgets(
        'server strings render verbatim — vocabulary in exactly one Text at w500, prose at w400',
        (tester) async {
      await _open(tester, _scenario(briefing: _kFullBriefing));

      final vocabFinder = find.text(_kFullBriefing['vocabulary']!);
      expect(vocabFinder, findsOneWidget);
      expect(
        tester.widget<Text>(vocabFinder).style?.fontWeight,
        FontWeight.w500,
      );

      final contextFinder = find.text(_kFullBriefing['context']!);
      expect(contextFinder, findsOneWidget);
      expect(
        tester.widget<Text>(contextFinder).style?.fontWeight,
        FontWeight.w400,
      );

      final expectFinder = find.text(_kFullBriefing['expect']!);
      expect(expectFinder, findsOneWidget);
      expect(
        tester.widget<Text>(expectFinder).style?.fontWeight,
        FontWeight.w400,
      );
    });

    testWidgets('an empty/whitespace section is hidden entirely — no bare eyebrow',
        (tester) async {
      await _open(
        tester,
        _scenario(
          briefing: const <String, String>{
            'vocabulary': '',
            'context': 'Only the situation is authored.',
            'expect': '   ',
          },
        ),
      );

      expect(find.text('THE SITUATION'), findsOneWidget);
      expect(find.text('Only the situation is authored.'), findsOneWidget);
      expect(find.text('WHAT TO EXPECT'), findsNothing);
      expect(find.text('SAY THIS'), findsNothing);
    });

    testWidgets(
        'all-empty briefing renders no eyebrows at all (browse entry stays graceful)',
        (tester) async {
      await _open(
        tester,
        _scenario(
          briefing: const <String, String>{
            'vocabulary': '',
            'context': '',
            'expect': '',
          },
        ),
      );

      expect(find.text('THE SITUATION'), findsNothing);
      expect(find.text('WHAT TO EXPECT'), findsNothing);
      expect(find.text('SAY THIS'), findsNothing);
      // The caller-ID lockup + threshold footer still render.
      expect(find.text('INCOMING CALL'), findsOneWidget);
      expect(find.text('The Waiter'), findsOneWidget);
      expect(find.text(_kStakesLine), findsOneWidget);
      expect(find.text('Pick up'), findsOneWidget);
    });

    testWidgets(
        'null briefing (legacy payload) renders no eyebrows — browse entry stays graceful',
        (tester) async {
      // Review patch (7.4): the card-tap entry pushes regardless of content,
      // so the null map must render exactly like the all-empty one.
      await _open(tester, _scenario());

      expect(find.text('THE SITUATION'), findsNothing);
      expect(find.text('WHAT TO EXPECT'), findsNothing);
      expect(find.text('SAY THIS'), findsNothing);
      expect(find.text('INCOMING CALL'), findsOneWidget);
      expect(find.text('The Waiter'), findsOneWidget);
      expect(find.text(_kStakesLine), findsOneWidget);
      expect(find.text('Pick up'), findsOneWidget);
    });

    testWidgets('threshold footer carries the stakes line + a >=48px Pick up pill',
        (tester) async {
      await _open(tester, _scenario(briefing: _kFullBriefing));

      expect(find.text(_kStakesLine), findsOneWidget);
      // No maxLines clamp on the stakes line — the footer grows instead.
      expect(tester.widget<Text>(find.text(_kStakesLine)).maxLines, isNull);

      final pill = find.widgetWithText(ElevatedButton, 'Pick up');
      expect(pill, findsOneWidget);
      expect(tester.getSize(pill).height, greaterThanOrEqualTo(48));
      expect(find.byIcon(Icons.phone_outlined), findsOneWidget);
    });

    testWidgets(
        'viewport contract: the authored waiter briefing fits above the fold at 360×800',
        (tester) async {
      // §Layout spec baseline (BINDING, Decision E): hero + lockup + fact
      // line + full triad + stakes line above the fold at textScaler 1.0 on
      // 360×800. No hairline ⇔ nothing scrolls ⇔ everything is on screen.
      await _open(
        tester,
        _scenario(briefing: _kFullBriefing),
        size: const Size(360, 800),
      );

      expect(
        find.byKey(const ValueKey('briefing-footer-hairline')),
        findsNothing,
      );
      expect(find.text('SAY THIS'), findsOneWidget);
      expect(find.text(_kFullBriefing['vocabulary']!), findsOneWidget);
      expect(find.text(_kStakesLine), findsOneWidget);
    });
  });

  group('BriefingScreen — confirm contract', () {
    testWidgets('Pick up pops true exactly once', (tester) async {
      final results = await _open(tester, _scenario(briefing: _kFullBriefing));

      await tester.tap(find.text('Pick up'));
      await tester.pumpAndSettle();

      expect(results, [true]);
      expect(find.text('OPEN'), findsOneWidget);
    });

    testWidgets('back arrow pops false', (tester) async {
      final results = await _open(tester, _scenario(briefing: _kFullBriefing));

      await tester.tap(find.byIcon(Icons.arrow_back));
      await tester.pumpAndSettle();

      expect(results, [false]);
      expect(find.text('OPEN'), findsOneWidget);
    });

    testWidgets('CTA double-tap pops once (second pop would dismiss the hub)',
        (tester) async {
      final results = await _open(tester, _scenario(briefing: _kFullBriefing));

      await tester.tap(find.text('Pick up'));
      await tester.tap(find.text('Pick up'), warnIfMissed: false);
      await tester.pumpAndSettle();

      expect(results, [true]);
      expect(find.text('OPEN'), findsOneWidget);
    });

    testWidgets('back-arrow double-tap pops once', (tester) async {
      final results = await _open(tester, _scenario(briefing: _kFullBriefing));

      await tester.tap(find.byIcon(Icons.arrow_back));
      await tester.tap(find.byIcon(Icons.arrow_back), warnIfMissed: false);
      await tester.pumpAndSettle();

      expect(results, [false]);
      expect(find.text('OPEN'), findsOneWidget);
    });
  });

  group('BriefingScreen — conditional footer hairline', () {
    const hairlineKey = ValueKey('briefing-footer-hairline');

    testWidgets('hidden when the content fits above the footer', (tester) async {
      await _open(tester, _scenario(briefing: _kFullBriefing));

      expect(find.byKey(hairlineKey), findsNothing);
    });

    testWidgets('visible when body content scrolls beneath the footer',
        (tester) async {
      final longBriefing = <String, String>{
        'vocabulary': _kFullBriefing['vocabulary']!,
        'context': List.filled(
          12,
          'You are ordering food at a restaurant and the situation keeps going.',
        ).join(' '),
        'expect': _kFullBriefing['expect']!,
      };
      await _open(
        tester,
        _scenario(briefing: longBriefing),
        size: const Size(320, 568),
      );

      expect(find.byKey(hairlineKey), findsOneWidget);
    });

    testWidgets(
        'toggles on viewport metrics changes after first build (not a first-build latch)',
        (tester) async {
      // Review patch (7.4) — spec probe: "re-evaluate on viewport/metrics
      // changes (rotation, text-scale change), not just on first build".
      await _open(tester, _scenario(briefing: _kFullBriefing));
      expect(find.byKey(hairlineKey), findsNothing);

      // Shrink the viewport: the same content now scrolls → it appears.
      await tester.binding.setSurfaceSize(const Size(320, 400));
      await tester.pumpAndSettle();
      expect(find.byKey(hairlineKey), findsOneWidget);

      // Restore: the content fits again → it hides.
      await tester.binding.setSurfaceSize(const Size(390, 844));
      await tester.pumpAndSettle();
      expect(find.byKey(hairlineKey), findsNothing);
    });
  });

  group('BriefingScreen — a11y', () {
    testWidgets('no overflow at 320×568 with textScaler 1.5 (stakes line wraps)',
        (tester) async {
      final layoutErrors = <FlutterErrorDetails>[];
      final originalOnError = FlutterError.onError;
      FlutterError.onError = layoutErrors.add;
      addTearDown(() => FlutterError.onError = originalOnError);

      await _open(
        tester,
        _scenario(briefing: _kFullBriefing),
        size: const Size(320, 568),
        textScaler: const TextScaler.linear(1.5),
      );

      expect(tester.takeException(), isNull);
      expect(
        layoutErrors,
        isEmpty,
        reason: 'RenderFlex / overflow errors must not surface — the body '
            'scrolls under the footer; spacing is never compressed.',
      );
      // The unclamped stakes line wrapped to (at least) two lines: its
      // rendered height exceeds any single scaled 13px line.
      final stakesSize = tester.getSize(find.text(_kStakesLine));
      expect(stakesSize.height, greaterThan(30));
      // The CTA stays reachable.
      expect(find.text('Pick up'), findsOneWidget);
    });

    testWidgets('semantics: back button, avatar photo, title header, merged sections, CTA button',
        (tester) async {
      final handle = tester.ensureSemantics();
      await _open(tester, _scenario(briefing: _kFullBriefing));

      expect(find.bySemanticsLabel('Back to scenarios'), findsOneWidget);
      expect(find.bySemanticsLabel('The Waiter, photo'), findsOneWidget);

      final back = tester.getSemantics(
        find.bySemanticsLabel('Back to scenarios'),
      );
      expect(back.flagsCollection.isButton, isTrue);

      final title = tester.getSemantics(find.text('The Waiter'));
      expect(title.flagsCollection.isHeader, isTrue);

      // MergeSemantics reads each section as ONE unit: eyebrow + body.
      final situation = tester.getSemantics(find.text('THE SITUATION'));
      expect(situation.label, contains('THE SITUATION'));
      expect(situation.label, contains(_kFullBriefing['context']!));

      final cta = tester.getSemantics(find.text('Pick up'));
      expect(cta.label, contains('Pick up'));
      expect(cta.flagsCollection.isButton, isTrue);

      handle.dispose();
    });
  });

  group('BriefingScreen — AC-C8 source discipline (review greps)', () {
    String source() {
      final fromClient = File('lib/features/briefing/views/briefing_screen.dart');
      final fromRoot =
          File('client/lib/features/briefing/views/briefing_screen.dart');
      final raw = (fromClient.existsSync() ? fromClient : fromRoot)
          .readAsStringSync();
      // Strip comments so documentation never counts as a reference.
      return raw
          .replaceAll(RegExp(r'/\*[\s\S]*?\*/'), '')
          .replaceAll(RegExp(r'//[^\n]*'), '');
    }

    test('AppColors.accent referenced exactly once (the pill fill)', () {
      expect(
        RegExp(r'AppColors\.accent\b').allMatches(source()).length,
        1,
        reason: 'green is the pill fill ONLY — never a text/icon tint',
      );
    });

    test('destructive / warning / status colors never referenced', () {
      final src = source();
      for (final banned in [
        'AppColors.destructive',
        'AppColors.warning',
        'AppColors.statusCompleted',
        'AppColors.statusInProgress',
      ]) {
        expect(src.contains(banned), isFalse, reason: '$banned must not appear');
      }
    });

    test('no string transformations on server fields (render verbatim)', () {
      final src = source();
      for (final op in [
        '.split(',
        '.replaceAll(',
        '.replaceFirst(',
        '.substring(',
        '.toUpperCase(',
        '.toLowerCase(',
        '.padLeft(',
        '.padRight(',
      ]) {
        expect(
          src.contains(op),
          isFalse,
          reason: '$op found — server strings must render untransformed',
        );
      }
    });

    test('each server field is read at exactly one site', () {
      final src = source();
      for (final read in [
        "briefing?['context']",
        "briefing?['expect']",
        "briefing?['vocabulary']",
      ]) {
        expect(
          read.allMatches(src).length,
          1,
          reason: '$read must feed exactly one Text',
        );
      }
    });
  });
}
