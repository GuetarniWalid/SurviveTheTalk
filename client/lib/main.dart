import 'package:flutter/widgets.dart';
import 'package:rive/rive.dart';

import 'app/app.dart';
import 'core/auth/token_storage.dart';
import 'core/onboarding/consent_storage.dart';

/// Bootstrap sequence required by Rive 0.14.x:
///   1. WidgetsFlutterBinding.ensureInitialized() — enables async plugins
///   2. RiveNative.init() — mandatory before any Rive widget mounts
///   3. runApp(...)
///
/// Extracted to a testable function so future flavored entry points
/// (main_development.dart, main_staging.dart, main_production.dart) can
/// share the same bootstrap logic without duplicating it.
///
/// If [RiveNative.init] throws [ArgumentError] or [UnimplementedError] the
/// failure is reported through [FlutterError.reportError] and bootstrap
/// continues without Rive. This keeps widget tests green (rive_native.dll
/// is not available in test environments, per `rive-flutter-rules.md` §6)
/// while still surfacing real native-init failures on production devices
/// via the Flutter error pipeline — ready for future Sentry/Crashlytics
/// wiring. Swallowing silently here would hide a class of production bugs
/// where the first `RiveWidget` mount crashes with no diagnostic.
Future<void> bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();

  try {
    await RiveNative.init();
  } on ArgumentError catch (error, stack) {
    FlutterError.reportError(
      FlutterErrorDetails(
        exception: error,
        stack: stack,
        library: 'bootstrap',
        context: ErrorDescription(
          'RiveNative.init() unavailable (likely test environment — rive_native '
          'library missing). Continuing without Rive.',
        ),
      ),
    );
  } on UnimplementedError catch (error, stack) {
    FlutterError.reportError(
      FlutterErrorDetails(
        exception: error,
        stack: stack,
        library: 'bootstrap',
        context: ErrorDescription(
          'RiveNative.init() not implemented on this platform. Continuing '
          'without Rive.',
        ),
      ),
    );
  }

  // Preload sync caches in parallel — both reads hit FlutterSecureStorage
  // and the router needs both answers synchronously on the first frame
  // (client/CLAUDE.md gotcha #5: async router redirect = flash of wrong
  // content). TokenStorage tells the auth gate whether to seed the bloc as
  // already-authenticated; ConsentStorage covers the onboarding gates.
  final consentStorage = ConsentStorage();
  final tokenStorage = TokenStorage();
  await Future.wait<void>([
    consentStorage.preload(),
    tokenStorage.preload(),
  ]);

  runApp(App(consentStorage: consentStorage, tokenStorage: tokenStorage));
}

Future<void> main() async {
  await bootstrap();
}
