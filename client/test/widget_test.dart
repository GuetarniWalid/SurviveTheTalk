import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:client/main.dart';

void main() {
  testWidgets('SurviveTheTalkApp renders without errors', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const SurviveTheTalkApp());
    expect(find.byType(MaterialApp), findsOneWidget);
  });

  testWidgets('Call button is displayed on initial screen', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const SurviveTheTalkApp());
    expect(find.byIcon(Icons.phone), findsOneWidget);
  });

  testWidgets('End Call button is NOT displayed on initial screen', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const SurviveTheTalkApp());
    expect(find.byIcon(Icons.phone_disabled), findsNothing);
  });
}
