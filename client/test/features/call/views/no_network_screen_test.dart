import 'package:client/features/call/views/no_network_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // Story 6.5 Deviation #12 + review D1 hybrid — NoNetworkScreen
  // delegates to the shared EmpatheticErrorScreen with three call-
  // context-specific overrides (`bodyOverride`, `retryLabel: 'Go back'`,
  // `semanticsLabel: 'Close'`). These tests assert the overrides land
  // correctly. Detailed layout assertions for the shared widget itself
  // live in `test/core/widgets/empathetic_error_screen_test.dart`.

  testWidgets(
    'renders the NETWORK_ERROR empathetic surface with call-context copy',
    (tester) async {
      await tester.pumpWidget(const MaterialApp(home: NoNetworkScreen()));
      await tester.pump();

      // Title + icon come from the shared widget's NETWORK_ERROR branch
      // (verbatim Story 5.5 locked English).
      expect(find.text('HOLD ON'), findsOneWidget);
      expect(find.text("You're offline."), findsOneWidget);
      expect(find.byIcon(Icons.cloud_off_outlined), findsOneWidget);

      // Body MUST be the call-context override, not the scenarios-list
      // default ("...to load your scenarios"). Review D1 hybrid.
      expect(
        find.text(
          'We need a connection to start the call. Check your Wi-Fi or '
          'mobile data, then try again.',
        ),
        findsOneWidget,
        reason:
            'NoNetworkScreen must pass `bodyOverride` so the call-failure '
            'surface does not read "load your scenarios".',
      );

      // Retry CTA label is "Go back" (the action is a pop, not a retry).
      expect(find.text('Go back'), findsOneWidget);
      expect(
        find.text('Try again'),
        findsNothing,
        reason:
            'NoNetworkScreen must override the default "Try again" label — '
            'the action is a pop.',
      );
    },
  );

  testWidgets(
    'CTA has Semantics label "Close" for UX-DR12 accessibility',
    (tester) async {
      // Per AC7 (the original spec line 307) the dismiss action MUST be
      // labelled "Close" for assistive tech, regardless of the visible
      // label. Review D1 hybrid restored this via `semanticsLabel`.
      final handle = tester.ensureSemantics();
      try {
        await tester.pumpWidget(const MaterialApp(home: NoNetworkScreen()));
        await tester.pump();

        expect(
          find.bySemanticsLabel('Close'),
          findsOneWidget,
          reason:
              'Retry CTA must expose Semantics(label: "Close") for screen '
              'readers, independent of the visible "Go back" copy.',
        );
      } finally {
        handle.dispose();
      }
    },
  );

  testWidgets('Go back button pops the route', (tester) async {
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

    // Review P21 — tap by FilledButton type, not by the visible text.
    // The Text("Go back") inside the button lives under a FittedBox + Row;
    // tapping the text directly relies on the framework walking up to the
    // nearest tappable, which silently regresses if the widget tree ever
    // wraps the text differently.
    await tester.tap(find.byType(FilledButton));
    await tester.pumpAndSettle();
    expect(find.byType(NoNetworkScreen), findsNothing);
  });

  testWidgets('renders without overflow at 320×480', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final overflowErrors = <FlutterErrorDetails>[];
    final previousErrorHandler = FlutterError.onError;
    FlutterError.onError = overflowErrors.add;

    try {
      await tester.pumpWidget(const MaterialApp(home: NoNetworkScreen()));
      await tester.pump();

      expect(
        overflowErrors,
        isEmpty,
        reason:
            'EmpatheticErrorScreen relies on Expanded + SingleChildScrollView '
            'to absorb content overflow on small phones (Gotcha #7).',
      );
    } finally {
      FlutterError.onError = previousErrorHandler;
    }
  });
}
