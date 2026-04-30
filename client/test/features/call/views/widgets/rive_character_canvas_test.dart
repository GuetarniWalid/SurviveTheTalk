import 'package:client/core/theme/app_colors.dart';
import 'package:client/features/call/views/widgets/rive_character_canvas.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('RiveCharacterCanvas — fallback path', () {
    testWidgets(
      'renders a solid AppColors.background container when RiveNative is not initialized',
      (tester) async {
        // Tests never call RiveNative.init(), so RiveNative.isInitialized is
        // false and the widget must render the fallback Container without
        // crashing (per `rive-flutter-rules.md` §6 — never mock
        // RiveWidgetBuilder; only the fallback path is exercised).
        await tester.pumpWidget(
          const MaterialApp(
            home: Scaffold(
              body: SizedBox.expand(
                child: RiveCharacterCanvas(character: 'waiter'),
              ),
            ),
          ),
        );
        await tester.pump();

        expect(tester.takeException(), isNull);
        expect(find.byType(RiveCharacterCanvas), findsOneWidget);

        final canvas = find.byType(RiveCharacterCanvas);
        final containers = find.descendant(
          of: canvas,
          matching: find.byType(Container),
        );
        final match = containers.evaluate().any((el) {
          final c = el.widget as Container;
          return c.color == AppColors.background;
        });
        expect(match, isTrue,
            reason:
                'fallback must render a Container with AppColors.background');
      },
    );

    testWidgets('fires onFallback exactly once when entering the fallback path',
        (tester) async {
      var fallbackCount = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox.expand(
              child: RiveCharacterCanvas(
                character: 'waiter',
                onFallback: () => fallbackCount++,
              ),
            ),
          ),
        ),
      );
      // Two pumps to drain the post-frame setState that flips the fallback
      // flag and invokes the callback.
      await tester.pump();
      await tester.pump();

      expect(fallbackCount, 1);
    });

    testWidgets(
      'onFallback stays at 1 even after extra rebuilds (idempotency)',
      (tester) async {
        var fallbackCount = 0;
        Widget tree() => MaterialApp(
              home: Scaffold(
                body: SizedBox.expand(
                  child: RiveCharacterCanvas(
                    character: 'waiter',
                    onFallback: () => fallbackCount++,
                  ),
                ),
              ),
            );

        await tester.pumpWidget(tree());
        await tester.pump();
        await tester.pump();

        // Force extra rebuilds; the post-frame `_enterFallback` would re-fire
        // the callback if the idempotency guard were missing.
        await tester.pumpWidget(tree());
        await tester.pump();
        await tester.pumpWidget(tree());
        await tester.pump();

        expect(fallbackCount, 1);
      },
    );

    testWidgets('survives a character prop change in fallback mode',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SizedBox.expand(
              child: RiveCharacterCanvas(character: 'waiter'),
            ),
          ),
        ),
      );
      await tester.pump();

      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SizedBox.expand(
              child: RiveCharacterCanvas(character: 'cop'),
            ),
          ),
        ),
      );
      await tester.pump();

      expect(tester.takeException(), isNull);
    });
  });

  group('RiveCharacterCanvas — Rive event wiring', () {
    testWidgets(
      'dispatches onHangUp when the Rive event named "onHangUp" fires',
      (tester) async {
        var hangUpCount = 0;
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SizedBox.expand(
                child: RiveCharacterCanvas(
                  character: 'waiter',
                  onHangUp: () => hangUpCount++,
                ),
              ),
            ),
          ),
        );
        await tester.pump();

        final state = tester.state<RiveCharacterCanvasState>(
          find.byType(RiveCharacterCanvas),
        );

        // Simulate the Rive runtime firing the in-canvas hang-up event.
        // Catches typos in the Rive event-name string that would otherwise
        // only surface as a silent failure in production (the user taps the
        // hang-up button and nothing happens).
        state.debugDispatchRiveEventName(
          RiveCharacterCanvasState.hangUpEventName,
        );

        expect(hangUpCount, 1);
      },
    );

    testWidgets(
      'ignores Rive events whose name is not the hang-up event',
      (tester) async {
        var hangUpCount = 0;
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SizedBox.expand(
                child: RiveCharacterCanvas(
                  character: 'waiter',
                  onHangUp: () => hangUpCount++,
                ),
              ),
            ),
          ),
        );
        await tester.pump();

        final state = tester.state<RiveCharacterCanvasState>(
          find.byType(RiveCharacterCanvas),
        );

        state.debugDispatchRiveEventName('someOtherEvent');
        state.debugDispatchRiveEventName('OnHangUp'); // case-sensitive
        state.debugDispatchRiveEventName('hang_up');

        expect(hangUpCount, 0);
      },
    );
  });
}
