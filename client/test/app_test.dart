import 'package:client/app/app.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('App renders MaterialApp.router without errors', (tester) async {
    await tester.pumpWidget(const App());
    await tester.pumpAndSettle();
    expect(find.byType(MaterialApp), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Placeholder screen shows scaffold signature text', (tester) async {
    await tester.pumpWidget(const App());
    await tester.pumpAndSettle();
    expect(find.text('surviveTheTalk — MVP scaffold'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Placeholder survives textScaler 1.5 (dynamic type)', (
    tester,
  ) async {
    // Force a narrow phone surface so any layout overflow at 1.5× scaling
    // surfaces as a RenderFlex exception captured by `takeException`.
    // Otherwise the default large test viewport hides the regression.
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      const MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(1.5)),
        child: App(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('surviveTheTalk — MVP scaffold'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
