import 'package:client/features/call/views/call_ended_notice_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // Story 6.5 Déviation #27 — these tests pin the copy variants of
  // the post-call notice screen. Layout assertions for the shared
  // EmpatheticErrorScreen widget the notice wraps live in
  // `test/features/call/views/no_network_screen_test.dart` and
  // `test/features/scenarios/views/scenario_list_screen_test.dart` —
  // no duplication here.

  testWidgets(
    'network_lost + gifted shows reassuring "on us" copy with gift count',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: CallEndedNoticeScreen(
            endReason: 'network_lost',
            wasGifted: true,
            giftsRemainingToday: 2,
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Connection lost.'), findsOneWidget);
      // Reassuring tone.
      expect(find.textContaining("this one's on us"), findsOneWidget);
      // Concrete remaining count.
      expect(find.textContaining('2 free'), findsOneWidget);
    },
  );

  testWidgets(
    'network_lost with null gift info (POST queued during airplane mode) '
    'uses the SAME optimistic copy — the rule almost always grants the gift',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: CallEndedNoticeScreen(endReason: 'network_lost'),
        ),
      );
      await tester.pump();

      expect(find.text('Connection lost.'), findsOneWidget);
      // Same reassurance — no hedged "we'll check later" copy.
      expect(find.textContaining("this one's on us"), findsOneWidget);
      // No count when unknown.
      expect(find.textContaining('free'), findsNothing);
    },
  );

  testWidgets(
    'network_lost + quota exhausted (wasGifted=false AND 0 remaining) is '
    'honest about the cost',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: CallEndedNoticeScreen(
            endReason: 'network_lost',
            wasGifted: false,
            giftsRemainingToday: 0,
          ),
        ),
      );
      await tester.pump();

      expect(
        find.textContaining('used your 3 free'),
        findsOneWidget,
        reason: 'User hit the 3/day quota — copy must say so honestly.',
      );
      expect(
        find.textContaining('Tomorrow you get a fresh batch'),
        findsOneWidget,
      );
    },
  );

  testWidgets(
    'character_hung_up + gifted shows the "too short" reassurance',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: CallEndedNoticeScreen(
            endReason: 'character_hung_up',
            wasGifted: true,
            giftsRemainingToday: 1,
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Too short to count.'), findsOneWidget);
      expect(find.textContaining('too short to be useful'), findsOneWidget);
      expect(find.textContaining('1 free'), findsOneWidget);
    },
  );

  testWidgets(
    'inappropriate_content + gifted reuses the same "too short" copy',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: CallEndedNoticeScreen(
            endReason: 'inappropriate_content',
            wasGifted: true,
            giftsRemainingToday: 3,
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Too short to count.'), findsOneWidget);
      expect(find.textContaining('too short to be useful'), findsOneWidget);
    },
  );

  testWidgets(
    'noisy_environment (Story 6.11) shows the 5th variant + volume_off icon '
    '+ "Got it" CTA',
    (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: CallEndedNoticeScreen(
            endReason: 'noisy_environment',
            wasGifted: true,
            giftsRemainingToday: 2,
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Background voice was too loud'), findsOneWidget);
      expect(find.textContaining("couldn't hear you clearly"), findsOneWidget);
      expect(
        find.textContaining("doesn't count toward your daily limit"),
        findsOneWidget,
      );
      // Visual continuity with the in-call banner.
      expect(find.byIcon(Icons.volume_off), findsOneWidget);
      // Close-only CTA, not "retry"/"back to scenarios".
      expect(find.text('Got it'), findsOneWidget);
      expect(find.text('Back to scenarios'), findsNothing);
    },
  );

  testWidgets('CTA pops the route', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: ElevatedButton(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => const CallEndedNoticeScreen(
                      endReason: 'network_lost',
                      wasGifted: true,
                      giftsRemainingToday: 2,
                    ),
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
    expect(find.byType(CallEndedNoticeScreen), findsOneWidget);
    expect(find.text('Back to scenarios'), findsOneWidget);

    await tester.tap(find.byType(FilledButton));
    await tester.pumpAndSettle();
    expect(find.byType(CallEndedNoticeScreen), findsNothing);
  });
}
