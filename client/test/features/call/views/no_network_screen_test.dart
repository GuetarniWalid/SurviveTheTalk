import 'package:client/features/call/views/no_network_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('renders icon + copy + hang-up button', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: NoNetworkScreen()));
    await tester.pump();

    expect(find.byIcon(Icons.wifi_off), findsOneWidget);
    expect(find.text('No network'), findsOneWidget);
    expect(
      find.text('We need a connection to start the call.'),
      findsOneWidget,
    );
    expect(find.byIcon(Icons.call_end), findsOneWidget);
  });

  testWidgets('hang-up button pops the route', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: ElevatedButton(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => const NoNetworkScreen(),
                  ),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    expect(find.byType(NoNetworkScreen), findsOneWidget);

    await tester.tap(find.byIcon(Icons.call_end));
    await tester.pumpAndSettle();
    expect(find.byType(NoNetworkScreen), findsNothing);
  });
}
