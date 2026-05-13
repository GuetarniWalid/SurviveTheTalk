import 'dart:async';

import 'package:client/core/services/connectivity_service.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class _MockConnectivity extends Mock implements Connectivity {}

void main() {
  late _MockConnectivity rawConnectivity;
  late StreamController<List<ConnectivityResult>> rawController;
  late ConnectivityService service;

  setUp(() {
    rawConnectivity = _MockConnectivity();
    rawController = StreamController<List<ConnectivityResult>>.broadcast();
    when(
      () => rawConnectivity.onConnectivityChanged,
    ).thenAnswer((_) => rawController.stream);
    service = ConnectivityService(connectivity: rawConnectivity);
  });

  tearDown(() async {
    await rawController.close();
  });

  group('onConnectivityLost', () {
    test('emits true when ALL transports go to none', () async {
      final emitted = <bool>[];
      final sub = service.onConnectivityLost.listen(emitted.add);

      rawController.add([ConnectivityResult.wifi]);
      rawController.add([ConnectivityResult.none]);
      await Future<void>.delayed(const Duration(milliseconds: 10));
      await sub.cancel();

      expect(emitted, [false, true]);
    });

    test(
      'treats partial connectivity (WiFi only, no mobile) as online',
      () async {
        // Modern devices can have multiple transports — only when EVERY
        // transport is `none` do we consider the device offline.
        final emitted = <bool>[];
        final sub = service.onConnectivityLost.listen(emitted.add);

        rawController.add([
          ConnectivityResult.wifi,
          ConnectivityResult.mobile,
        ]);
        rawController.add([ConnectivityResult.wifi]); // mobile dropped
        await Future<void>.delayed(const Duration(milliseconds: 10));
        await sub.cancel();

        // Only one emission — `false` (online); the partial drop did
        // not toggle the boolean.
        expect(emitted, [false]);
      },
    );

    test('distinct() collapses runs of the same state', () async {
      final emitted = <bool>[];
      final sub = service.onConnectivityLost.listen(emitted.add);

      rawController.add([ConnectivityResult.none]);
      rawController.add([ConnectivityResult.none]);
      rawController.add([ConnectivityResult.none]);
      await Future<void>.delayed(const Duration(milliseconds: 10));
      await sub.cancel();

      expect(emitted, [true]);
    });
  });

  group('onConnectivityRegained', () {
    test('fires only on a lost → regained transition', () async {
      final emitted = <void>[];
      final sub = service.onConnectivityRegained.listen(emitted.add);

      rawController.add([ConnectivityResult.wifi]); // online → online
      rawController.add([ConnectivityResult.none]); // lost
      rawController.add([ConnectivityResult.wifi]); // REGAINED
      rawController.add([ConnectivityResult.mobile]); // online → online
      await Future<void>.delayed(const Duration(milliseconds: 10));
      await sub.cancel();

      expect(emitted, hasLength(1));
    });

    test('does NOT fire on a transport hop (wifi → mobile)', () async {
      final emitted = <void>[];
      final sub = service.onConnectivityRegained.listen(emitted.add);

      rawController.add([ConnectivityResult.wifi]);
      rawController.add([ConnectivityResult.mobile]);
      await Future<void>.delayed(const Duration(milliseconds: 10));
      await sub.cancel();

      // Neither was a "lost → online" transition.
      expect(emitted, isEmpty);
    });
  });
}
