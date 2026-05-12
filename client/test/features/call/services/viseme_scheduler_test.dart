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
}
