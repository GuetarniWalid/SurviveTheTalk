import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/scenarios/models/scenario.dart';
import 'package:client/features/scenarios/views/widgets/content_warning_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

Scenario _scenario({String? contentWarning = 'CW body 12345'}) {
  return Scenario(
    id: 's1',
    title: 'The Mugger',
    difficulty: 'hard',
    isFree: true,
    riveCharacter: 'mugger',
    languageFocus: const <String>[],
    contentWarning: contentWarning,
    bestScore: null,
    attempts: 0,
    tagline: 'Tagline',
  );
}

/// Pumps a tiny harness whose body button calls `showContentWarningSheet`
/// and stores the resolved bool. Tests call `trigger()` to open the sheet
/// then read the result via `get()`.
({bool? Function() get, Future<void> Function() trigger}) _harness(
  WidgetTester tester,
  Scenario scenario,
) {
  bool? captured;
  late BuildContext capturedCtx;
  return (
    get: () => captured,
    trigger: () async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.dark(),
          home: Builder(
            builder: (ctx) {
              capturedCtx = ctx;
              return Scaffold(
                body: Center(
                  child: ElevatedButton(
                    onPressed: () async {
                      captured = await showContentWarningSheet(
                        capturedCtx,
                        scenario,
                      );
                    },
                    child: const Text('OPEN'),
                  ),
                ),
              );
            },
          ),
        ),
      );
      await tester.tap(find.text('OPEN'));
      await tester.pumpAndSettle();
    },
  );
}

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  testWidgets(
    'sheet renders static frame + per-scenario body verbatim',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final h = _harness(tester, _scenario(contentWarning: 'CW body 12345'));
      await h.trigger();

      // Static chrome from the Figma mock.
      expect(find.text('HEADS UP'), findsOneWidget);
      expect(find.text('Buckle up'), findsOneWidget);
      expect(find.text('You can hang up anytime'), findsOneWidget);
      expect(find.text('Not now'), findsOneWidget);
      expect(find.text('Pick up'), findsOneWidget);
      // Per-scenario body, rendered verbatim (no prefix, no suffix).
      expect(find.text('CW body 12345'), findsOneWidget);
    },
  );

  testWidgets(
    'sheet shows the shield (HEADS UP) and phone (Pick up) icons',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final h = _harness(tester, _scenario());
      await h.trigger();

      expect(find.byIcon(Icons.shield_outlined), findsOneWidget);
      expect(find.byIcon(Icons.phone_outlined), findsOneWidget);
    },
  );

  testWidgets('tap Pick up resolves the future to true', (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final h = _harness(tester, _scenario());
    await h.trigger();

    await tester.tap(find.text('Pick up'));
    await tester.pumpAndSettle();

    expect(h.get(), isTrue);
    expect(find.text('Buckle up'), findsNothing);
  });

  testWidgets('tap Not now resolves the future to false', (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final h = _harness(tester, _scenario());
    await h.trigger();

    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();

    expect(h.get(), isFalse);
    expect(find.text('Buckle up'), findsNothing);
  });

  testWidgets(
    'tap on scrim (outside the sheet) dismisses with false',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final h = _harness(tester, _scenario());
      await h.trigger();

      // (20, 20) is in the top-left scrim region — clearly above the
      // bottom-anchored sheet on a 390×844 surface.
      await tester.tapAt(const Offset(20, 20));
      await tester.pumpAndSettle();

      expect(h.get(), isFalse);
      expect(find.text('Buckle up'), findsNothing);
    },
  );

  testWidgets(
    'swipe down on the sheet dismisses with false',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final h = _harness(tester, _scenario());
      await h.trigger();

      // Drag the title (a stable hit-target inside the sheet) downward by
      // more than the dismiss threshold (~half the sheet height).
      await tester.drag(find.text('Buckle up'), const Offset(0, 500));
      await tester.pumpAndSettle();

      expect(h.get(), isFalse);
      expect(find.text('Buckle up'), findsNothing);
    },
  );

  // AC7 — body wraps without overflow at 320×480 with 1.5× text scale.
  // The 320 floor is the UX-DR1 narrow-viewport bound; the 1.5 scaler is
  // the accessibility envelope. The Wrap action row drops to a second
  // line if the buttons no longer fit on one line — no RenderFlex overflow
  // either way.
  testWidgets(
    'sheet wraps without overflow at 320x480 + textScaler 1.5',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 480));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      const longBody =
          'A firm officer questioning you about a traffic stop. He will '
          'lean on you hard. No arrest, no detention. Just hold your ground '
          'and answer plainly.';

      bool? captured;
      final scenario = _scenario(contentWarning: longBody);
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.dark(),
          builder: (ctx, child) => MediaQuery(
            data: MediaQuery.of(ctx).copyWith(
              textScaler: const TextScaler.linear(1.5),
            ),
            child: child!,
          ),
          home: Builder(
            builder: (ctx) => Scaffold(
              body: Center(
                child: ElevatedButton(
                  onPressed: () async {
                    captured = await showContentWarningSheet(ctx, scenario);
                  },
                  child: const Text('OPEN'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('OPEN'));
      await tester.pumpAndSettle();

      expect(find.text(longBody), findsOneWidget);
      expect(find.text('Buckle up'), findsOneWidget);
      expect(find.text('Pick up'), findsOneWidget);
      expect(find.text('Not now'), findsOneWidget);
      // No overflow exception was thrown during the layout/paint pass.
      expect(tester.takeException(), isNull);
      // Silence "captured assigned but never used" — the setter is the
      // contract; this test only verifies layout.
      expect(captured, isNull);
    },
  );
}
