import 'dart:async';

import 'package:client/features/call/services/viseme_scheduler.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

StreamController<int> _newController() {
  // Broadcast so multiple listeners can attach in negative-control tests.
  // Each test closes the controller through `addTearDown` (or its own
  // sequence of `dispose() + close()`), but the analyser can't follow
  // that across functions — silence with rationale.
  // ignore: close_sinks
  return StreamController<int>.broadcast();
}

/// Hand control to the event loop so async stream events propagate.
Future<void> _flush() => Future<void>.delayed(Duration.zero);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  group('VisemeScheduler — native-viseme architecture', () {
    test('forwards each native viseme to applyViseme in order', () async {
      final controller = _newController();
      final applied = <int>[];
      final scheduler = VisemeScheduler(
        applyViseme: applied.add,
        eventStream: controller.stream,
      );
      addTearDown(() async {
        await scheduler.dispose();
        await controller.close();
      });

      controller.add(1);
      controller.add(4);
      controller.add(0);
      await _flush();

      expect(applied, [1, 4, 0]);
    });

    test('after dispose, no further visemes are applied', () async {
      final controller = _newController();
      final applied = <int>[];
      final scheduler = VisemeScheduler(
        applyViseme: applied.add,
        eventStream: controller.stream,
      );

      controller.add(2);
      await _flush();
      expect(applied, [2]);

      await scheduler.dispose();
      controller.add(7);
      await _flush();

      expect(applied, [2]);
      await controller.close();
    });

    test('dispose is idempotent', () async {
      final controller = _newController();
      final scheduler = VisemeScheduler(
        applyViseme: (_) {},
        eventStream: controller.stream,
      );

      await scheduler.dispose();
      await scheduler.dispose();
      await controller.close();
    });

    test('debugAttached reflects the subscription lifecycle', () async {
      final controller = _newController();
      final scheduler = VisemeScheduler(
        applyViseme: (_) {},
        eventStream: controller.stream,
      );

      expect(scheduler.debugAttached, isTrue);

      await scheduler.dispose();
      expect(scheduler.debugAttached, isFalse);
      await controller.close();
    });
  });

  group('VisemeScheduler — onSilenceConfirmed (Story 6.4)', () {
    test(
      'fires after sustained REST emission',
      () async {
        final controller = _newController();
        var silenceCount = 0;
        final scheduler = VisemeScheduler(
          applyViseme: (_) {},
          onSilenceConfirmed: () => silenceCount++,
          silenceConfirmation: const Duration(milliseconds: 50),
          eventStream: controller.stream,
        );
        addTearDown(() async {
          await scheduler.dispose();
          await controller.close();
        });

        // Speech then REST. The silence timer should fire ~50 ms after
        // the REST event (no more events arrive).
        controller.add(1);
        controller.add(4);
        controller.add(0);
        await _flush();
        expect(silenceCount, 0, reason: 'not yet — timer still pending');

        await Future<void>.delayed(const Duration(milliseconds: 80));
        expect(silenceCount, 1);
      },
    );

    test(
      'non-REST event before the window expires cancels the silence timer',
      () async {
        final controller = _newController();
        var silenceCount = 0;
        final scheduler = VisemeScheduler(
          applyViseme: (_) {},
          onSilenceConfirmed: () => silenceCount++,
          silenceConfirmation: const Duration(milliseconds: 100),
          eventStream: controller.stream,
        );
        addTearDown(() async {
          await scheduler.dispose();
          await controller.close();
        });

        controller.add(0); // start a silence timer (100 ms)
        await Future<void>.delayed(const Duration(milliseconds: 30));
        controller.add(4); // pre-window resumption → cancel
        await Future<void>.delayed(const Duration(milliseconds: 120));

        expect(silenceCount, 0, reason: 'speech resumed → no silence fired');
      },
    );

    test(
      'a fresh REST after a cancellation restarts the silence timer',
      () async {
        final controller = _newController();
        var silenceCount = 0;
        final scheduler = VisemeScheduler(
          applyViseme: (_) {},
          onSilenceConfirmed: () => silenceCount++,
          silenceConfirmation: const Duration(milliseconds: 50),
          eventStream: controller.stream,
        );
        addTearDown(() async {
          await scheduler.dispose();
          await controller.close();
        });

        controller.add(0); // arms
        await Future<void>.delayed(const Duration(milliseconds: 20));
        controller.add(7); // cancels
        await Future<void>.delayed(const Duration(milliseconds: 20));
        controller.add(0); // arms again
        await Future<void>.delayed(const Duration(milliseconds: 80));

        expect(silenceCount, 1);
      },
    );

    test('dispose cancels a pending silence timer', () async {
      final controller = _newController();
      var silenceCount = 0;
      final scheduler = VisemeScheduler(
        applyViseme: (_) {},
        onSilenceConfirmed: () => silenceCount++,
        silenceConfirmation: const Duration(milliseconds: 50),
        eventStream: controller.stream,
      );

      controller.add(0); // arms
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await scheduler.dispose();

      // Wait past the original window — the timer should NOT have
      // fired post-dispose.
      await Future<void>.delayed(const Duration(milliseconds: 80));
      expect(silenceCount, 0);

      await controller.close();
    });

    test(
      'duplicate consecutive REST visemes do not reset the silence timer '
      '(Dart-side dedup defense)',
      () async {
        // Regression for code-review P12 — the silence-confirm logic
        // assumes the native analyzer dedupes consecutive same-value
        // emissions, but a future native build could regress to
        // per-chunk emit. Without Dart-side dedup, every duplicate REST
        // chunk would re-cancel + re-arm the silence timer at ~50 Hz
        // and `onSilenceConfirmed` would NEVER fire (timer reset
        // before it could expire).
        final controller = _newController();
        var silenceCount = 0;
        final scheduler = VisemeScheduler(
          applyViseme: (_) {},
          onSilenceConfirmed: () => silenceCount++,
          silenceConfirmation: const Duration(milliseconds: 80),
          eventStream: controller.stream,
        );
        addTearDown(() async {
          await scheduler.dispose();
          await controller.close();
        });

        // Single REST arms the timer (80 ms).
        controller.add(0);
        await _flush();

        // Simulated native regression: 5 duplicate REST emissions over
        // the window. With dedup, none of them reset the timer.
        for (var i = 0; i < 5; i++) {
          await Future<void>.delayed(const Duration(milliseconds: 12));
          controller.add(0);
        }
        // Past the 80 ms window from the FIRST REST.
        await Future<void>.delayed(const Duration(milliseconds: 40));

        expect(
          silenceCount,
          1,
          reason:
              'duplicate REST events must NOT reset the silence timer; '
              'native-side regression must be tolerated',
        );
      },
    );

    test(
      'absent onSilenceConfirmed callback is a no-op (back-compat)',
      () async {
        // Existing Story 6.3b call sites construct VisemeScheduler
        // without the new argument. The class must still work.
        final controller = _newController();
        final scheduler = VisemeScheduler(
          applyViseme: (_) {},
          eventStream: controller.stream,
        );
        addTearDown(() async {
          await scheduler.dispose();
          await controller.close();
        });

        controller.add(0);
        controller.add(1);
        controller.add(0);
        await Future<void>.delayed(const Duration(milliseconds: 80));
        // No crash, no callback registered — implicit success.
      },
    );
  });
}
