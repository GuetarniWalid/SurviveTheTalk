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
}
