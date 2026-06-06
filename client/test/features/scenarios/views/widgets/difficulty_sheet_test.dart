import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/scenarios/views/widgets/difficulty_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // Pumps a screen with one button that opens the difficulty sheet and reports
  // the result. Mirrors how the hub uses `showDifficultySheet`.
  Future<void> pumpOpener(
    WidgetTester tester, {
    required void Function(String?) onResult,
    String current = 'easy',
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.dark(),
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () async {
                final result = await showDifficultySheet(
                  context,
                  current: current,
                );
                onResult(result);
              },
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
  }

  testWidgets('lists Easy/Medium/Hard with honest copy + a Done button', (
    tester,
  ) async {
    // Force a small phone viewport to catch overflow (client/CLAUDE.md #7).
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await pumpOpener(tester, onResult: (_) {});
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    expect(find.text('Easy'), findsOneWidget);
    expect(find.text('Medium'), findsOneWidget);
    expect(find.text('Hard'), findsOneWidget);
    expect(find.text('They cut you slack'), findsOneWidget);
    expect(find.text('Normal human friction'), findsOneWidget);
    expect(find.text('No mercy, no hints'), findsOneWidget);
    expect(find.text('Done'), findsOneWidget);
  });

  testWidgets('selecting a level then Done returns the chosen value', (
    tester,
  ) async {
    String? result = 'UNSET';
    await pumpOpener(tester, onResult: (r) => result = r, current: 'easy');
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Hard'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Done'));
    await tester.pumpAndSettle();

    expect(result, 'hard');
  });

  testWidgets('Done without changing selection returns the current value', (
    tester,
  ) async {
    String? result = 'UNSET';
    await pumpOpener(tester, onResult: (r) => result = r, current: 'medium');
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Done'));
    await tester.pumpAndSettle();

    expect(result, 'medium');
  });

  testWidgets('dismissing via the scrim returns null', (tester) async {
    String? result = 'UNSET';
    await pumpOpener(tester, onResult: (r) => result = r, current: 'easy');
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    // Tap the scrim above the sheet to dismiss without choosing.
    await tester.tapAt(const Offset(20, 20));
    await tester.pumpAndSettle();

    expect(result, isNull);
  });
}
