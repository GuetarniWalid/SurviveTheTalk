# Claude Code Instructions — `client/` (Flutter)

Loaded automatically when working in `client/`. These are hard-won traps and conventions from Epic 4. Read before starting any Flutter work to avoid rediscovering them.

## Pre-commit (non-negotiable, same as project root)

```bash
cd client && flutter analyze      # MUST print "No issues found!" — infos block CI too
cd client && flutter test         # MUST print "All tests passed!"
```

Never commit on red. Fix every info-level lint or explicitly silence it in `analysis_options.yaml` with a rationale comment.

---

## Flutter Gotchas

### 1. `FlutterSecureStorage` tests — `setMockInitialValues({})` in every `setUp`

Tests that exercise any code touching `FlutterSecureStorage` (directly or transitively via `TokenStorage`, `ConsentStorage`, etc.) will crash in CI without this line:

```dart
setUp(() {
  FlutterSecureStorage.setMockInitialValues({});
  // … rest of setup
});
```

Skip it and tests pass locally on a machine with the keystore primed, then fail in CI. This bit us on 4.3, 4.4, and 4.5 before becoming epic-wide reflex.

### 2. Mocktail + sealed classes — `registerFallbackValue`, not `Fake extends`

Our BLoC events are sealed (`AuthEvent`, `OnboardingEvent`, `IncomingCallEvent`). The usual `class FakeAuthEvent extends Fake implements AuthEvent {}` **does not compile** — sealed hierarchies can't be implemented outside the sealed file.

Use a concrete subclass as fallback instead:

```dart
setUpAll(() {
  registerFallbackValue(CheckAuthStatusEvent());  // or any concrete event
});
```

### 3. `pumpAndSettle` hangs on continuous animations

Any widget with a non-terminating animation (`CircularProgressIndicator`, custom `AnimationController` in `repeat()`, `Timer.periodic` that calls `setState`) will make `pumpAndSettle()` hang forever.

Use explicit pumps with a duration that covers the visible state:

```dart
// BAD — hangs if screen shows a spinner
await tester.pumpAndSettle();

// GOOD — advance just far enough to observe the expected frame
await tester.pump(const Duration(milliseconds: 300));
```

### 4. Same-`const` state in `BlocListener` — insert an intermediate state

`BlocListener` deduplicates emissions by equality. If your bloc emits the **same `const` state instance** twice in a row (e.g. `const MicDenied()` after the user returned from settings without granting), the second fire is silently dropped and the UI appears frozen.

Fix by emitting an intermediate state to force a transition:

```dart
// BAD — second MicDenied silently skipped
emit(const MicDenied());

// GOOD — forces re-fire by going through an intermediate state
emit(const MicPermissionRequested());
emit(const MicDenied());
```

This caused the "infinite loader" bug on mic permission re-check in Story 4.4.

### 5. GoRouter redirect must be sync — use `preload()` + `hasXSync()`

Async redirect logic (awaiting `FlutterSecureStorage.read`) inside `GoRouter.redirect` produces a flash-of-wrong-content during the await window. The pattern that works:

```dart
// In storage wrapper
class ConsentStorage {
  bool? _cachedHasConsent;
  Future<void> preload() async {
    _cachedHasConsent = (await _storage.read(key: _consentKey)) != null;
  }
  bool get hasConsentSync => _cachedHasConsent ?? false;
}

// Call preload() in bootstrap() before runApp(); then redirect uses hasConsentSync.
```

Use `refreshListenable: GoRouterRefreshStream(bloc.stream)` to trigger re-evaluation on bloc updates.

### 6. Token-enforcement test — never hex-literal, extend the class

The static test in `test/core/theme/theme_tokens_test.dart` scans `lib/` for any hex-color literal (`Color(0x…)`, `Color.fromARGB`, `Color.fromRGBO`, bare int constants). It will fail the build if you hardcode a color outside `lib/core/theme/`.

Two correct responses when you need a new color:

1. **Shared semantic color** → add to `AppColors` (as done with `AppColors.warning` in 4.3).
2. **Screen-specific palette** (e.g. native-phone UI colors) → create a parallel class in `lib/core/theme/`, like `CallColors` (4.5). Never inline the hex.

### 7. Test viewport — force phone size to catch overflow

Default test surface is desktop-sized (800×600+). Overflow that would show on a 320-wide phone is invisible. Force the size in any test where layout matters, especially under `MediaQuery(textScaler: ...)`:

```dart
testWidgets('renders without overflow', (tester) async {
  await tester.binding.setSurfaceSize(const Size(320, 480));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  // … pump and expect
});
```

### 8. `RiveNative.init()` in `bootstrap()` — try/catch with `FlutterError.reportError`

`rive_native.dll` / dylib isn't available in the widget-test environment. Initialization must be fail-soft in tests, loud in prod:

```dart
Future<void> bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    await RiveNative.init();
  } catch (e, stack) {
    FlutterError.reportError(FlutterErrorDetails(exception: e, stack: stack));
  }
  // … preload storage caches before runApp
}
```

Never silently swallow — use `FlutterError.reportError` so real prod failures surface in crash reports.

### 9. Lint traps that surface every story

- **`prefer_const_constructors`** — sealed-class subclasses, widget constructors, test fixtures all need `const`. Add `const` proactively; fix whatever `flutter analyze` flags.
- **`no_leading_underscores_for_local_identifiers`** — rename `_foo` → `foo` for local variables/functions inside a method body. Leading underscore is fine for private class members.
- **Mocktail `verifyNever(mock.call(…))`, not `verify(mock.call(…)).called(0)`** — the latter is flagged as a lint and also semantically different.
- **`unnecessary_nullable_for_final_variable_declarations`** — `final String? x = 'a';` should be `final String x = 'a';` unless actually nullable.
- **`deprecated_member_use`** — especially `SemanticsService.announce` which migrated API between Flutter versions.

### 10. UI error display convention — inline `Text`, never snackbar/dialog/toast

Per Epic 4 UX decisions (see `feedback_error_ux.md` in project memory):

- **Inline `Text` with `AppColors.destructive`** for field-level and operation errors (established in auth flow 4.3).
- **Toast / Overlay** reserved for **informational hints only** (e.g. "check your spam folder"), auto-dismiss after ~10s, never for errors.
- **Onboarding/transitional screens**: on error, **fade-nav back to a safe fallback screen** (like Decline), don't show an inline retry banner.

---

## Architecture patterns established in Epic 4 (reuse, don't reinvent)

- **`bootstrap()` entry-point function** — all app init (Rive, storage preloads, error reporters) lives here; `main.dart` just calls it. Pattern in 4.1.
- **Storage wrapper with `preload() + hasXSync()`** — any storage-backed router redirect uses this. Pattern in 4.4 ConsentStorage, extended in 4.5 for `firstCallShown`.
- **Thin service wrapper around platform packages** — `PermissionService` (4.4), `VibrationService` (4.5). Always wrap `permission_handler`, `vibration`, etc. in a mockable class — don't call the package directly from blocs.
- **`AUTH_DEPENDENCY`-style module-level reuse** — for any cross-cutting concern (auth guard, etc.), expose a single const/function others can one-line consume.
- **State carrying `previousState`** — `AuthError(previousState)`, `OnboardingError(previousState)` — so the UI can navigate back to the right screen after an error without losing context.
- **Sealed events + concrete `registerFallbackValue`** — every new bloc uses sealed events; tests use a concrete instance as the mocktail fallback (see gotcha #2).

---

## When in doubt

- Read the "Dev Notes" and "Previous Story Intelligence" sections of the most recent Epic 4 story (`_bmad-output/implementation-artifacts/4-5-*.md`) for concrete examples of every pattern above.
- The Epic 4 retrospective (`_bmad-output/implementation-artifacts/epic-4-retro-2026-04-23.md`) captures the synthesis of why these patterns exist.
