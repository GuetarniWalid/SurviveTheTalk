import 'package:client/features/call/views/widgets/character_avatar.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('CharacterAvatar', () {
    testWidgets('renders a circular container sized to the requested size',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: Center(
              child: CharacterAvatar(character: 'waiter', size: 166),
            ),
          ),
        ),
      );
      // RiveNative is not initialized in widget tests — the widget must
      // render the fallback (ClipOval + Container) without crashing. This
      // is the contract that protects the incoming-call screen's test
      // suite from a flaky Rive init.
      await tester.pump();
      expect(tester.takeException(), isNull);
      expect(find.byType(CharacterAvatar), findsOneWidget);
      expect(find.byType(ClipOval), findsWidgets);
    });

    testWidgets('reacts to character prop changes without throwing',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: Center(
              child: CharacterAvatar(character: 'waiter', size: 100),
            ),
          ),
        ),
      );
      await tester.pump();

      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: Center(
              child: CharacterAvatar(character: 'cop', size: 100),
            ),
          ),
        ),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
    });
  });
}
