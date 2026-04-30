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

  group('RiveCharacterCanvas — wire-format constants (Story 6.3)', () {
    test(
      'kVisemeIdToCase covers the full 12-case Rive contract from Story 2.6',
      () {
        // Catches drift if a future edit removes a viseme id without
        // also updating the server-side `_PRIORITY` table. A missing id
        // would silently no-op on the client — the server emits an int
        // the client cannot map.
        expect(
          kVisemeIdToCase.keys.toSet(),
          Set<int>.from(List<int>.generate(12, (i) => i)),
        );
        // Spot-check the canonical name mapping (Story 2.6 §3 verbatim).
        expect(kVisemeIdToCase[0], 'rest');
        expect(kVisemeIdToCase[1], 'aei');
        expect(kVisemeIdToCase[11], 'fv');
      },
    );

    test(
      'kAllowedEmotions matches the 7-value subset from Story 2.6 §1',
      () {
        // Mirrors `server/pipeline/emotion_emitter.py:_ALLOWED_EMOTIONS`.
        // Drift between server and client surfaces here — a server-side
        // emotion outside this set is silently dropped by `setEmotion`.
        expect(kAllowedEmotions, {
          'satisfaction',
          'smirk',
          'frustration',
          'impatience',
          'anger',
          'confusion',
          'disgust_hangup',
        });
        // Reserved values for downstream stories MUST stay out.
        for (final reserved in ['sadness', 'boredom', 'impressed']) {
          expect(
            kAllowedEmotions.contains(reserved),
            isFalse,
            reason: '$reserved is reserved for Stories 6.4 / 6.6',
          );
        }
      },
    );
  });

  group('RiveCharacterCanvas — emotion + viseme setters (Story 6.3)', () {
    testWidgets(
      'setEmotion no-ops in fallback mode without throwing',
      (tester) async {
        // In fallback mode the cached `_emotionEnum` is null (no Rive
        // ViewModel ever loaded). The setter MUST be null-safe per AC5.
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

        final state = tester.state<RiveCharacterCanvasState>(
          find.byType(RiveCharacterCanvas),
        );

        // No exception, no crash — just a silent write into a null cache.
        state.setEmotion('satisfaction');
        state.setEmotion('confusion');
        // Same value twice — Rive deduplicates ViewModel writes
        // internally; the public setter is idempotent at the call site.
        state.setEmotion('confusion');

        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'setEmotion silently drops values outside the allow-list',
      (tester) async {
        // Defense in depth: a server-side typo or a stale envelope from a
        // future story (e.g. `sadness` reserved for 6.4) MUST NOT crash
        // and MUST NOT reach the Rive ViewModel even if the cache were
        // present.
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

        final state = tester.state<RiveCharacterCanvasState>(
          find.byType(RiveCharacterCanvas),
        );

        state.setEmotion('sastisfaction'); // typo
        state.setEmotion('sadness'); // reserved for downstream stories
        state.setEmotion(''); // empty
        state.setEmotion('not_a_real_emotion');

        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'setVisemeId handles in-range and out-of-range ids without throwing',
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

        final state = tester.state<RiveCharacterCanvasState>(
          find.byType(RiveCharacterCanvas),
        );

        // 4 = ee, in range; 99 = unknown, must drop silently. Both go
        // through the int → string lookup — neither path may throw.
        state.setVisemeId(4);
        state.setVisemeId(99);
        state.setVisemeId(0); // rest
        state.setVisemeId(11); // fv (last valid id)
        state.setVisemeId(-1); // negative — also unknown

        expect(tester.takeException(), isNull);
      },
    );
  });
}
