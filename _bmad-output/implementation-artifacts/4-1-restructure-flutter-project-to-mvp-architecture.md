# Story 4.1: Restructure Flutter Project to MVP Architecture

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Intention (UX / Why)

Epic 4 is the **first code-heavy MVP epic** (5 stories after this one). Every subsequent Flutter story — passwordless auth (4.3), consent + mic permission flow (4.4), first-call onboarding (4.5), scenario list (5.2), call screen (6.2), debrief (7.3), paywall (8.2) — builds on the folder layout, state management, routing, and initialization choices made here.

This story is an **infrastructure investment, not a user-visible feature**. The PoC was intentionally a single `main.dart` to validate the voice pipeline without wasted effort. Now the PoC is validated (PROCEED TO MVP, Epic 1 retro), we must migrate to the architecture-defined feature-based BLoC structure **before** writing any feature code — otherwise later stories will either (a) build against a half-restructured tree (wasted rework), or (b) silently entrench the PoC shape (architectural drift).

**What the user will see after this story:** the app launches and shows a single placeholder landing screen (no auth, no call button, no features yet). The visible app is deliberately barren — every pixel of actual UX arrives in 4.1b (design system) through 4.5 (first-call).

**What the user will NOT see but will benefit from later:**
- Auth guards in GoRouter so unauthenticated users can never accidentally reach the scenario list
- BLoC separation so bugs in one feature can't cascade across the app
- Centralized Dio + JWT interceptor so every authenticated request is secure by default
- Rive hot-update infrastructure so character animations can be iterated without App Store resubmission

**Non-goals for this story (hard scope boundaries):**
- ❌ Full theme tokens, colors, typography, spacing — those belong to **Story 4.1b** (Design System)
- ❌ Actual auth screens or AuthBloc logic — **Story 4.3**
- ❌ Dio + API client wired to real endpoints — **Story 4.2** ships the backend; Dio plumbing arrives with 4.3
- ❌ Rive loader downloading from VPS — **Story 6.2** (uses `core/rive/rive_loader.dart` scaffolded here)
- ❌ Removing or modifying the Pipecat server (`server/pipeline/prompts.py` Waiter stays live for backend manual testing)

## Concrete User Walk-Through (Adversarial)

> Per Epic 3 retro Action Item #1: every code story must trace one concrete user path end-to-end before implementation begins.

**Scenario: Developer Walid pulls `main`, runs the restructured app on his iPhone simulator after this story ships.**

1. `cd client && flutter pub get` — resolves all new dependencies (`flutter_bloc`, `go_router`, `dio`, `flutter_secure_storage`) without version conflicts against existing `rive: ^0.14.2` and `livekit_client: ^2.6.4`.
2. `flutter analyze` → `No issues found!` (MUST — pre-commit gate).
3. `flutter test` → `All tests passed!` (MUST — pre-commit gate).
4. `flutter run` on iPhone simulator → app launches.
5. `main()` calls `RiveNative.init()` **before** `runApp(...)`. A log line confirms init success.
6. `MaterialApp.router` mounts with GoRouter. The single initial route (`/`) renders a placeholder `Scaffold` with centered text like `"surviveTheTalk — MVP scaffold. Features arrive in upcoming stories."` on a dark background.
7. No crashes, no red screens, no unused-import warnings, no font errors.

**Adversarial walk-through — what if the developer forgets a step?**
- Forgets `RiveNative.init()` → Rive integration in Story 6.2 will silent-hang or crash. **Preventive AC: unit test verifies `RiveNative.init()` is awaited before `runApp` in `main.dart`.** (Technically testable via `main()` refactored into a testable `bootstrap()` function — see Task 4.)
- Forgets one of the dependencies → later stories hit `Target of URI doesn't exist` import errors. **Preventive AC: all 4 new dependencies are resolvable in `flutter pub get` AND a trivial import-smoke test in `test/dependencies_smoke_test.dart` imports each package once.**
- Adds a dependency but it triggers a Dart SDK lower-bound conflict → `pub get` fails. **Preventive action: run `flutter pub outdated` after adding deps; pin ranges conservatively.**
- Preserves the old PoC `main.dart` content alongside the new structure → future stories import the wrong `CallScreen`, creating duplicate state management. **Preventive action: delete old `main.dart` and `config.dart` entirely; their permissions setup (AndroidManifest, Info.plist) is retained, their code is not.**

## Story

As a developer,
I want the Flutter project restructured from PoC single-file to MVP feature-based BLoC architecture with all core MVP dependencies installed and `RiveNative.init()` wired into bootstrap,
So that all subsequent MVP features (auth, design system, call, debrief, paywall) can be built on a solid, organized, immediately-ready foundation without rework.

## Dependencies

- **Story 1.3 (done)** — Existing PoC `lib/main.dart` + `lib/config.dart` provide the working HTTP-to-VPS + LiveKit connection pattern. Permissions setup (`AndroidManifest.xml`, `Info.plist`) MUST be preserved.
- **Epic 1 Retro (done)** — Rive 0.14.x non-negotiable rules confirmed: see `CLAUDE.md` memory file and architecture §"Production-Proven Rive 0.14.x Integration Rules" (lines 184–207).
- **Epic 3 Retro (done)** — PoC → MVP known-issues mapping (`_bmad-output/planning-artifacts/poc-known-issues-mvp-impact.md`) confirms Issue #2 (cold start ~8s) and Issue #4 (response length) do NOT affect Story 4.1 directly.
- **Architecture (done)** — `_bmad-output/planning-artifacts/architecture.md` §"Flutter MVP Client Structure" (lines 756–840) is the **canonical layout**. Deviation requires a sprint change proposal.

## Acceptance Criteria

1. **AC1 — Directory structure matches architecture spec (lines 760–840):**
   Given the PoC single-file layout (`lib/main.dart`, `lib/config.dart`),
   When the restructure is complete,
   Then `client/lib/` contains:
   ```
   lib/
   ├── main.dart                            # bootstrap (RiveNative.init + runApp)
   ├── app/
   │   ├── app.dart                         # MaterialApp.router wrapper
   │   ├── router.dart                      # GoRouter config + (stub) auth guards
   │   └── theme.dart                       # Minimal dark theme placeholder (4.1b fills in)
   ├── features/
   │   ├── auth/{bloc,models,repositories,views}/.gitkeep
   │   ├── call/{bloc,models,repositories,services,views}/.gitkeep
   │   ├── scenarios/{bloc,models,repositories,views}/.gitkeep
   │   └── debrief/{bloc,models,repositories,views}/.gitkeep
   ├── core/
   │   ├── api/.gitkeep
   │   ├── auth/.gitkeep
   │   ├── rive/.gitkeep
   │   └── theme/.gitkeep
   └── shared/
       └── widgets/.gitkeep
   ```
   **And** the old `lib/config.dart` is deleted; old `lib/main.dart` is replaced (not preserved).

2. **AC2 — MVP dependencies installed and resolvable:**
   Given `pubspec.yaml` is updated,
   When `flutter pub get` runs on a clean checkout,
   Then all of the following are installed at current-stable versions compatible with `flutter: sdk ^3.11.0`:
   - `flutter_bloc` (state management)
   - `go_router` (declarative routing with auth guards)
   - `dio` (HTTP client with interceptor support)
   - `flutter_secure_storage` (JWT in Keychain/Keystore)
   - `rive: ^0.14.2` (preserved, already installed)
   - `livekit_client: ^2.6.4` (preserved, already installed)
   **And** `http` is removed from `dependencies` (replaced by `dio`).
   **And** `bloc_test` and `mocktail` are added to `dev_dependencies` (required by 4.3+ BLoC tests).

3. **AC3 — `RiveNative.init()` awaited in bootstrap before `runApp`:**
   Given Rive 0.14.x requires `RiveNative.init()` or animations silently hang,
   When `main()` executes,
   Then:
   - `WidgetsFlutterBinding.ensureInitialized()` is called first
   - `RiveNative.init()` is `await`-ed second
   - `runApp(const App())` is called third
   **And** `main()` logic is extracted into a testable `bootstrap()` function (for future migration to flavored entry points: `main_development.dart`, `main_staging.dart`, `main_production.dart`).

4. **AC4 — GoRouter mounted with one initial placeholder route:**
   Given no feature screens exist yet,
   When the app launches,
   Then a `GoRouter` instance is defined in `lib/app/router.dart` with:
   - Exactly one route: `/` → `PlaceholderScreen` (a trivial widget with centered text `"surviveTheTalk — MVP scaffold"`)
   - Route constants declared as `static const` class members (e.g., `AppRoutes.root = '/'`) — no magic strings in navigation calls
   - A stub `redirect:` parameter on the router (empty function returning `null`) with a `// TODO(4.3): add auth guard` comment — primes the hook point for Story 4.3

5. **AC5 — Pre-commit checks pass with zero issues:**
   Given `CLAUDE.md` enforces pre-commit validation,
   When `flutter analyze` runs,
   Then `No issues found!` (including infos).
   **And** when `flutter test` runs, all tests pass.
   **And** at least 3 tests exist (exactly these files — see Task 8):
   - `test/app_test.dart` test A: pumps `App`, expects `MaterialApp` widget renders without errors
   - `test/app_test.dart` test B: pumps `App` + `pumpAndSettle`, expects the placeholder screen's signature text `"surviveTheTalk — MVP scaffold"` renders at route `/`
   - `test/dependencies_smoke_test.dart`: trivially imports each new dependency package — catches broken/missing package imports at compile time

6. **AC6 — Existing native permissions preserved:**
   Given PoC `AndroidManifest.xml` and `Info.plist` already declare microphone + network permissions (Story 1.3),
   When the restructure completes,
   Then **no changes** to `client/android/app/src/main/AndroidManifest.xml` or `client/ios/Runner/Info.plist`.
   **And** the `assets:` section of `pubspec.yaml` is preserved exactly (Rive character file + splash + icon + scenario backgrounds + character avatars stay declared).

## Tasks / Subtasks

### Phase 1: Dependencies & Cleanup

- [x] **Task 1: Update `pubspec.yaml` with MVP dependencies** (AC: #2)
  - [x] 1.1 In `client/`, remove `http: ^1.6.0` from `dependencies` (replaced by `dio`)
  - [x] 1.2 Add to `dependencies` (use `flutter pub add <pkg>` for each to pin current stable):
    - `flutter_bloc`
    - `go_router`
    - `dio`
    - `flutter_secure_storage`
  - [x] 1.3 Add to `dev_dependencies`:
    - `bloc_test`
    - `mocktail`
  - [x] 1.4 Run `flutter pub get` — verify zero resolution errors
  - [x] 1.5 Commit checkpoint: `pubspec.yaml` + `pubspec.lock` updated, app still builds

- [x] **Task 2: Delete PoC single-file code** (AC: #1, #6)
  - [x] 2.1 Delete `client/lib/main.dart` (will be replaced in Task 4)
  - [x] 2.2 Delete `client/lib/config.dart` (the VPS URL moves to `core/api/api_client.dart` in Story 4.3 — not needed yet)
  - [x] 2.3 **DO NOT TOUCH** `client/android/app/src/main/AndroidManifest.xml` — mic/network permissions must stay
  - [x] 2.4 **DO NOT TOUCH** `client/ios/Runner/Info.plist` — mic permission + background audio mode must stay
  - [x] 2.5 **DO NOT TOUCH** `client/assets/` folder or `assets:` block in `pubspec.yaml` — Rive + image assets from Stories 2.6 / 2.7 must stay declared

### Phase 2: Create Directory Scaffold

- [x] **Task 3: Create feature-based directory structure** (AC: #1)
  - [x] 3.1 Create directories (use `.gitkeep` placeholder file in each leaf directory to ensure git tracks them):
    ```
    lib/app/
    lib/features/auth/bloc/
    lib/features/auth/models/
    lib/features/auth/repositories/
    lib/features/auth/views/
    lib/features/call/bloc/
    lib/features/call/models/
    lib/features/call/repositories/
    lib/features/call/services/
    lib/features/call/views/
    lib/features/scenarios/bloc/
    lib/features/scenarios/models/
    lib/features/scenarios/repositories/
    lib/features/scenarios/views/
    lib/features/debrief/bloc/
    lib/features/debrief/models/
    lib/features/debrief/repositories/
    lib/features/debrief/views/
    lib/core/api/
    lib/core/auth/
    lib/core/rive/
    lib/core/theme/
    lib/shared/widgets/
    ```
  - [x] 3.2 For each `.gitkeep`, add a one-line comment: `# Placeholder — populated by Story 4.X` (replace X with the story that fills it per the FR → structure mapping in architecture lines 900–919)

### Phase 3: Bootstrap & App Shell

- [x] **Task 4: Implement `main.dart` + `bootstrap()`** (AC: #3, #5)
  - [x] 4.1 Create `lib/main.dart` with this exact pattern:
    ```dart
    import 'package:flutter/widgets.dart';
    import 'package:rive/rive.dart';

    import 'app/app.dart';

    Future<void> bootstrap() async {
      WidgetsFlutterBinding.ensureInitialized();
      await RiveNative.init();
      runApp(const App());
    }

    Future<void> main() async {
      await bootstrap();
    }
    ```
  - [x] 4.2 Confirm `RiveNative.init()` is imported from `package:rive/rive.dart` (NOT `package:rive_native/...` — `rive: ^0.14.2` re-exports it).
  - [x] 4.3 If `RiveNative.init()` throws in test environment (per `rive-flutter-rules.md` §6, rive_native.dll is unavailable in tests), wrap in try/catch inside `bootstrap()` with a fallback that reports the failure via `FlutterError.reportError` and continues. Pattern:
    ```dart
    try {
      await RiveNative.init();
    } on ArgumentError catch (error, stack) {
      FlutterError.reportError(
        FlutterErrorDetails(
          exception: error,
          stack: stack,
          library: 'bootstrap',
          context: ErrorDescription(
            'RiveNative.init() unavailable (likely test environment). Continuing without Rive.',
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
            'RiveNative.init() not implemented on this platform. Continuing without Rive.',
          ),
        ),
      );
    }
    ```
    — this mirrors the fallback pattern used throughout Epic 2's Rive integration. `FlutterError.reportError` keeps widget tests green (rive_native.dll missing is expected there) while still surfacing real production failures through the Flutter error pipeline, ready for future Sentry/Crashlytics wiring. Silent swallow is NOT acceptable: it would hide cases where the first `RiveWidget` mount later crashes with no diagnostic.

- [x] **Task 5: Implement `app.dart` (MaterialApp.router shell)** (AC: #4, #5)
  - [x] 5.1 Create `lib/app/app.dart`:
    ```dart
    import 'package:flutter/material.dart';

    import 'router.dart';
    import 'theme.dart';

    class App extends StatelessWidget {
      const App({super.key});

      @override
      Widget build(BuildContext context) {
        return MaterialApp.router(
          title: 'surviveTheTalk',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.dark(),
          routerConfig: AppRouter.instance,
        );
      }
    }
    ```

- [x] **Task 6: Implement `router.dart` (GoRouter config)** (AC: #4)
  - [x] 6.1 Create `lib/app/router.dart`:
    ```dart
    import 'package:flutter/material.dart';
    import 'package:go_router/go_router.dart';

    class AppRoutes {
      const AppRoutes._();
      static const String root = '/';
    }

    class AppRouter {
      const AppRouter._();

      static final GoRouter instance = GoRouter(
        initialLocation: AppRoutes.root,
        redirect: (context, state) {
          // TODO(4.3): add auth guard — redirect unauthenticated users to /login
          return null;
        },
        routes: <RouteBase>[
          GoRoute(
            path: AppRoutes.root,
            builder: (context, state) => const _PlaceholderScreen(),
          ),
        ],
      );
    }

    class _PlaceholderScreen extends StatelessWidget {
      const _PlaceholderScreen();

      @override
      Widget build(BuildContext context) {
        return const Scaffold(
          body: Center(
            child: Padding(
              padding: EdgeInsets.symmetric(horizontal: 32),
              child: Text(
                'surviveTheTalk — MVP scaffold',
                textAlign: TextAlign.center,
              ),
            ),
          ),
        );
      }
    }
    ```
  - [x] 6.2 The `_PlaceholderScreen` is intentionally private (underscore prefix) — it will be deleted when Story 4.3 adds the real email entry screen.

- [x] **Task 7: Implement `theme.dart` (minimal dark theme placeholder)** (AC: #4, #5)
  - [x] 7.1 Create `lib/app/theme.dart` — **minimal dark theme only** (full token system is Story 4.1b's job):
    ```dart
    import 'package:flutter/material.dart';

    class AppTheme {
      const AppTheme._();

      static ThemeData dark() {
        return ThemeData(
          brightness: Brightness.dark,
          useMaterial3: true,
          scaffoldBackgroundColor: const Color(0xFF1E1F23),
          colorScheme: const ColorScheme.dark(
            surface: Color(0xFF1E1F23),
            primary: Color(0xFF00E5A0),
          ),
        );
      }
    }
    ```
  - [x] 7.2 Add a top-of-file comment: `// NOTE: Minimal dark theme. Full token system (8 colors, 10 text styles, 8px spacing) arrives in Story 4.1b. Do not expand scope here.`

### Phase 4: Tests

- [x] **Task 8: Replace/create widget + bootstrap tests** (AC: #5)
  - [x] 8.1 Delete `client/test/widget_test.dart` (tests old PoC `CallScreen`).
  - [x] 8.2 Create `client/test/app_test.dart`:
    ```dart
    import 'package:client/app/app.dart';
    import 'package:flutter/material.dart';
    import 'package:flutter_test/flutter_test.dart';

    void main() {
      testWidgets('App renders MaterialApp.router without errors', (tester) async {
        await tester.pumpWidget(const App());
        expect(find.byType(MaterialApp), findsOneWidget);
      });

      testWidgets('Placeholder screen shows scaffold signature text', (tester) async {
        await tester.pumpWidget(const App());
        await tester.pumpAndSettle();
        expect(find.text('surviveTheTalk — MVP scaffold'), findsOneWidget);
      });
    }
    ```
  - [x] 8.3 Create `client/test/dependencies_smoke_test.dart` — a compile-only test that imports each new dependency to catch missing/broken imports:
    ```dart
    // ignore_for_file: unused_import
    import 'package:dio/dio.dart';
    import 'package:flutter_bloc/flutter_bloc.dart';
    import 'package:flutter_secure_storage/flutter_secure_storage.dart';
    import 'package:go_router/go_router.dart';
    import 'package:livekit_client/livekit_client.dart';
    import 'package:rive/rive.dart';
    import 'package:flutter_test/flutter_test.dart';

    void main() {
      test('all MVP dependencies import cleanly', () {
        expect(true, isTrue);
      });
    }
    ```
  - [x] 8.4 Run `flutter test` locally — expect `All tests passed!` (typically 3 tests).

### Phase 5: Validation & Commit

- [x] **Task 9: Pre-commit gates** (AC: #5)
  - [x] 9.1 `cd client && flutter analyze` → MUST return `No issues found!` (zero errors, zero warnings, zero infos).
  - [x] 9.2 `cd client && flutter test` → MUST return `All tests passed!`.
  - [x] 9.3 If any issue surfaces, fix it **before** continuing. Do not add `// ignore_for_file:` to suppress lints unless there is a documented architectural reason (like the deliberate `unused_import` in `dependencies_smoke_test.dart`).

- [x] **Task 10: Sprint status + commit** (non-AC, process discipline)
  - [x] 10.1 Update `_bmad-output/implementation-artifacts/sprint-status.yaml`:
    - `epic-4: backlog` → `epic-4: in-progress` (first story in epic — see workflow step 1 auto-logic)
    - `4-1-restructure-flutter-project-to-mvp-architecture: ready-for-dev` → `in-progress` (at start of dev)
    - `4-1-restructure-flutter-project-to-mvp-architecture: in-progress` → `review` (at end of dev)
    - Bump `last_updated` field to today's date.
  - [x] 10.2 Update this story's `Status:` field from `ready-for-dev` → `in-progress` (start) → `review` (end).
  - [x] 10.3 Single commit, format per `CLAUDE.md`:
    ```
    feat: restructure Flutter project to MVP feature-based BLoC architecture (Story 4.1)

    - Remove PoC single-file main.dart + config.dart
    - Add MVP dependencies: flutter_bloc, go_router, dio, flutter_secure_storage, bloc_test, mocktail
    - Remove http dependency (replaced by dio)
    - Create lib/{app,features,core,shared} scaffold per architecture spec
    - Add bootstrap() with RiveNative.init() before runApp
    - Add MaterialApp.router + GoRouter with placeholder route and auth-guard hook
    - Add 3 widget/smoke tests (total 3 passing)
    ```
  - [x] 10.4 Verify `git status` is clean, VPS Pipecat service (Waiter scenario) is unaffected.

## Dev Notes

### Library Versions & Install Commands

Verified at Epic 4 kickoff (2026-04-16) — pin current stable on install, do not chase pre-release versions:

| Package | Purpose | Install | Notes |
|---------|---------|---------|-------|
| `flutter_bloc` | State management per architecture | `flutter pub add flutter_bloc` | Current stable 9.x line. All MVP features depend on this. |
| `go_router` | Declarative routing + auth guards | `flutter pub add go_router` | Current stable 16.x line. Use `MaterialApp.router` + `routerConfig`, NOT deprecated `MaterialApp` with separate delegates. |
| `dio` | HTTP client + interceptors | `flutter pub add dio` | Current stable 5.x line. Architecture §API specifies JWT interceptor + retry logic live on the Dio client (Story 4.3 wires this). |
| `flutter_secure_storage` | JWT in Keychain / Keystore | `flutter pub add flutter_secure_storage` | Current stable 9.x line. Architecture §Authentication mandates this for JWT — NOT `shared_preferences`. |
| `bloc_test` (dev) | BLoC testing utilities | `flutter pub add --dev bloc_test` | Required by 4.3 AuthBloc tests. |
| `mocktail` (dev) | Null-safety-friendly mocking | `flutter pub add --dev mocktail` | Preferred over `mockito` for Dart 3. |
| `rive: ^0.14.2` | Preserve existing pin | *(already installed)* | DO NOT upgrade to 0.15.x or 1.x without a sprint change proposal — Rive rules in memory are validated against 0.14.x only. |
| `livekit_client: ^2.6.4` | Preserve existing pin | *(already installed)* | DO NOT upgrade — PoC validated at this version. |

**Post-install sanity check:**
```bash
cd client && flutter pub outdated
```
Verify no UPGRADE arrows on `rive` or `livekit_client`. If `flutter_bloc` or `go_router` pin resolves to a pre-1.0 version, escalate before committing.

### Architecture Compliance — Non-Negotiable Rules

1. **Folder structure:** EXACTLY matches architecture lines 756–840. Do not invent helper folders (no `lib/utils/`, no `lib/common/`, no `lib/constants/`). If something must live somewhere, it belongs in `core/` or `shared/`.
2. **File naming (architecture §Naming lines 456–490):**
   - Dart files → `snake_case.dart` (e.g., `auth_bloc.dart`, NOT `AuthBloc.dart`)
   - Dart classes → `PascalCase`
   - Dart variables/functions → `camelCase`
3. **BLoC naming convention (architecture lines 492–516) — reserved for future stories, NOT 4.1:**
   - Events → `VerbNounEvent` (e.g., `SubmitEmailEvent`)
   - States → `NounStatusState` (e.g., `AuthLoading`)
   - Blocs → `FeatureBloc` (e.g., `AuthBloc`)
4. **JSON mapping (architecture lines 472–490) — reserved for Story 4.3+:**
   - Python server sends `snake_case` natively
   - Dart models map to `camelCase` in `fromJson`/`toJson`
   - NEVER use `json_serializable` code generation at this stage — keep mappings explicit and hand-written
5. **Rive 0.14.x rules (memory `rive-flutter-rules.md`, non-negotiable):**
   - `RiveNative.init()` MUST be called in `main()` before ANY Rive usage
   - Bootstrap pattern enables this correctly (Task 4)
6. **Pre-commit (`CLAUDE.md`, non-negotiable):**
   - `flutter analyze` must return `No issues found!` — even infos block the commit
   - `flutter test` must pass ALL tests — not just new ones

### What NOT to Do

| Anti-pattern | Why it fails |
|--------------|--------------|
| ❌ Create `lib/features/auth/auth_bloc.dart` directly (skip `bloc/` subfolder) | Architecture explicitly mandates `features/<feature>/bloc/` subfolder. Later stories expect this path. |
| ❌ Replicate full theme tokens (all 8 colors, 10 text styles) in `theme.dart` now | Scope creep. Story 4.1b owns the design system. `theme.dart` here is a **minimal dark shell** only. |
| ❌ Add `json_serializable` + `build_runner` to generate model mappings | PoC and MVP use hand-written `fromJson`/`toJson`. Code gen adds build complexity for near-zero benefit at 4-5 models. |
| ❌ Port the old PoC `CallScreen` into `features/call/views/call_screen.dart` "as a reference" | Creates a tempting-but-wrong implementation. Story 6.2 writes the real BLoC-driven call screen from scratch. The PoC CallScreen can be recovered from git history (commit `8248513^`) if ever needed. |
| ❌ Skip `WidgetsFlutterBinding.ensureInitialized()` in bootstrap | Required before any async plugin call (`RiveNative.init()`). Without it, Flutter throws `ServicesBinding not initialized`. |
| ❌ Use `Fit.contain` anywhere visible | Per Rive rules, causes black bars. Not relevant to 4.1 (no Rive widgets yet) but noted for future stories. |
| ❌ Add a splash screen or launch animation | Out of scope — MVP splash is handled by native `flutter_native_splash` config in Story 4.5 or 10.x. |
| ❌ Touch `server/` code | This is a client-only restructure. Server stays exactly as it is (Waiter scenario running on VPS). |
| ❌ Expand `pubspec.yaml` `assets:` block | Keep exactly what Story 2.7 declared. Adding assets belongs to their owning story. |
| ❌ Modify `AndroidManifest.xml` or `Info.plist` | Mic + network permissions already set correctly by Story 1.3. No changes needed. |
| ❌ Commit without running `flutter analyze` + `flutter test` | Epic 1 retro lesson: sprint-status + pre-commit gates are non-negotiable. See `CLAUDE.md`. |

### Previous Story Intelligence — Lessons to Carry Forward

From **Story 1.3** (the last Flutter-code story):
- Kept dependencies minimal and pinned (`http: ^1.6.0`, `livekit_client: ^2.6.4`, `rive: ^0.14.2`). MVP expands but preserves this discipline — no speculative deps.
- PoC `main.dart` used a state enum (`CallState.idle/connecting/connected/error`). The **MVP equivalent** of this pattern IS flutter_bloc States — but 4.1 does not implement CallBloc yet (Story 6.2 owns it). Noted here so the dev does not conflate the two.
- `config.dart` held a single constant (`serverUrl`). In MVP, the API base URL belongs to `core/api/api_client.dart` (configured in Story 4.3). Leaving `config.dart` around tempts bad imports — hence Task 2.2 deletes it.

From **Epic 1 Retro** (`epic-1-retro-2026-03-31.md`):
- **Sprint-status discipline is non-negotiable** — Dev and reviewer both forgot in Epic 1, causing team confusion. Task 10.1 is explicit: update at every transition.
- **Detailed story specs (exact imports, verified code patterns, "What NOT to Do" lists) are the #1 velocity multiplier.** This story applies that lesson heavily — every new file has exact code.

From **Epic 2 Retro** (`epic-2-retro-2026-04-14.md`):
- Action Item #2: "Add 'Intention UX' section to every story" — present in this story (top).
- Action Item #4 carried forward: "Complete PoC → MVP known issues mapping" — **DONE 2026-04-16** (see file `poc-known-issues-mvp-impact.md`).

From **Epic 3 Retro** (`epic-3-retro-2026-04-16.md`):
- Action Item #1: "Bake 'Intention UX' + concrete-user-walk-through into create-story template" — this story is the FIRST application of that change (both sections present at top).
- Action Item #2: "Define pre-dev smoke test gate (compile + deploy + round-trip call for server/app-boot stories)" — for 4.1 (client-only, no server change), the gate is: `flutter pub get` + `flutter analyze` + `flutter test` + `flutter run` on simulator. No VPS round-trip needed.

### PoC Known Issues → Story 4.1 Impact

Per `poc-known-issues-mvp-impact.md`:

| Issue | Severity for 4.1 | Action in 4.1 |
|-------|------------------|---------------|
| #1 Silence handling | None | Owned by Story 6.4 |
| #2 Cold start ~8s | None | Owned by Story 6.1; Story 4.5 onboarding considers it |
| #3 VAD stop_secs | None | Owned by Story 6.1 |
| #4 Response length | None | Scenario prompts already enforce (Epic 3) |
| #5 Barge-in | None | Owned by Story 6.4 |
| #6 TTS cost | None | Owned by Epic 10.x ops |
| #7 Break-even | None | PRD doc update only |
| #8 Double user messages | None | Owned by Story 6.2/6.3 |

**Verdict:** Story 4.1 is a pure client-infra restructure with zero PoC-issue exposure.

### Architectural Hooks Primed for Future Stories

Each placeholder created now has a TODO anchor for the story that fills it:

| File | Future Story | Hook |
|------|--------------|------|
| `lib/app/router.dart` | 4.3 (Email auth flow) | `redirect:` function (currently returns null) — adds `/login` redirect when JWT absent |
| `lib/app/router.dart` | 4.3, 4.4, 4.5, 5.2, 6.2, 7.3 | `routes: []` list — each story adds its `GoRoute` |
| `lib/app/theme.dart` | 4.1b (Design System) | Fills in full 8-color, 10-typography, 8px spacing token system |
| `lib/core/api/` | 4.3 | Adds `api_client.dart` (Dio instance + JWT interceptor) + `api_exceptions.dart` |
| `lib/core/auth/` | 4.3 | Adds `token_storage.dart` (flutter_secure_storage wrapper) |
| `lib/core/rive/` | 6.2 | Adds `rive_loader.dart` (network fetch + manifest check) + `rive_manifest.dart` |
| `lib/core/theme/` | 4.1b | Adds `app_colors.dart`, `app_typography.dart`, `app_theme.dart` (replacing the minimal placeholder in `app/theme.dart` or consolidating into `core/theme/`) |
| `lib/features/auth/` | 4.3 | AuthBloc, login_screen, code_screen, auth_repository |
| `lib/features/scenarios/` | 5.2 | ScenariosBloc, scenario_list_screen |
| `lib/features/call/` | 6.2 | CallBloc, call_screen, livekit_service, viseme_handler |
| `lib/features/debrief/` | 7.3 | DebriefBloc, debrief_screen |
| `lib/shared/widgets/` | 4.3+ | `loading_indicator.dart`, `error_display.dart` |

**Important:** The minimal `app/theme.dart` and the future `core/theme/app_theme.dart` must NOT both exist post-4.1b. Story 4.1b resolves this (either by replacing `app/theme.dart` contents to delegate to `core/theme/` builders, or by moving `theme.dart` entirely into `core/theme/`). For 4.1, one minimal `app/theme.dart` is sufficient.

### Testing Standards

Per architecture §Test Structure (lines 598–602):
- Tests live in `test/`, mirroring `lib/` structure
- File naming: `<module>_test.dart`
- No co-location

For Story 4.1, three tests suffice (see AC5). Subsequent stories add feature-specific BLoC tests via `bloc_test`.

**Rive in tests reminder** (memory `rive-flutter-rules.md` §6): Rive native library doesn't load in Flutter tests. Task 4.3 pre-wraps `RiveNative.init()` in try/catch so tests don't fail at bootstrap. No Rive widget tests in this story (nothing renders Rive yet).

### Project Structure Notes — Alignment Check

| Architecture spec (lines 760–840) | Story 4.1 creates | Alignment |
|------------------------------------|-------------------|-----------|
| `main.dart` | ✅ with `bootstrap()` | ✅ |
| `app/app.dart` | ✅ | ✅ |
| `app/router.dart` | ✅ | ✅ |
| `app/theme.dart` | ✅ (minimal) | ✅ deferred full impl to 4.1b |
| `features/{auth,call,scenarios,debrief}/{bloc,models,repositories,views}/` | ✅ (`.gitkeep` placeholders) | ✅ |
| `features/call/services/` | ✅ (`.gitkeep`) | ✅ |
| `core/{api,auth,rive,theme}/` | ✅ (`.gitkeep`) | ✅ |
| `shared/widgets/` | ✅ (`.gitkeep`) | ✅ |

**No detected conflicts or variances.** Full alignment with architecture spec.

### References

- [Source: `_bmad-output/planning-artifacts/architecture.md` §"Flutter MVP Client Structure"] — lines 756–840 (canonical directory layout)
- [Source: `_bmad-output/planning-artifacts/architecture.md` §"Implementation Patterns & Consistency Rules"] — lines 448–687 (naming, API format, BLoC conventions)
- [Source: `_bmad-output/planning-artifacts/architecture.md` §"Production-Proven Rive 0.14.x Integration Rules"] — lines 184–207
- [Source: `_bmad-output/planning-artifacts/epics.md` §"Story 4.1: Restructure Flutter Project to MVP Architecture"] — lines 685–702 (acceptance criteria source)
- [Source: `_bmad-output/planning-artifacts/poc-known-issues-mvp-impact.md`] — confirms zero PoC-issue exposure for 4.1
- [Source: `_bmad-output/implementation-artifacts/epic-1-retro-2026-03-31.md`] — sprint-status discipline, detailed-story-spec velocity pattern
- [Source: `_bmad-output/implementation-artifacts/epic-3-retro-2026-04-16.md`] — Intention UX + concrete walk-through template change (Action Item #1)
- [Source: `CLAUDE.md` (project root)] — pre-commit rules, commit message format
- [Source: `~/.claude/projects/.../memory/rive-flutter-rules.md`] — Rive 0.14.x non-negotiable integration rules

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (claude-opus-4-6) — bmad-dev-story workflow

### Debug Log References

- `flutter pub remove http` — moved `http` from direct to transitive dep (LiveKit still depends on it transitively, which is acceptable per AC2).
- `flutter pub add flutter_bloc go_router dio flutter_secure_storage` — resolved to `flutter_bloc 9.1.1`, `go_router 17.2.1`, `dio 5.9.2`, `flutter_secure_storage 10.0.0`. Note: `go_router` resolved to `17.x` (not `16.x` as referenced in Dev Notes); `17.2.1` is current stable (not pre-release), matches the "pin current stable on install" rule. No escalation required.
- `flutter pub add --dev bloc_test mocktail` — resolved to `bloc_test 10.0.0`, `mocktail 1.0.5`.
- `flutter analyze` → `No issues found!` (run in 39.2s).
- `flutter test` → 3 tests passed (`app_test.dart` × 2, `dependencies_smoke_test.dart` × 1).

### Completion Notes List

- **AC1 (directory structure)**: Full scaffold created with 22 `.gitkeep` files. Each `.gitkeep` carries a one-line comment referencing the owning future story (per Task 3.2). Old `lib/main.dart` and `lib/config.dart` deleted.
- **AC2 (dependencies)**: `http` removed from direct deps; `flutter_bloc`, `go_router`, `dio`, `flutter_secure_storage` added as runtime deps; `bloc_test`, `mocktail` added as dev deps. `rive: ^0.14.2` and `livekit_client: ^2.6.4` preserved unchanged. `flutter pub get` resolved without errors.
- **AC3 (bootstrap)**: `main.dart` calls `WidgetsFlutterBinding.ensureInitialized()` → `await RiveNative.init()` (wrapped in try/catch for `ArgumentError` and `UnimplementedError` to keep widget tests green — per rive-flutter-rules §6) → `runApp(const App())`. Logic extracted to testable `bootstrap()` function for future flavored entry points.
- **AC4 (router)**: `AppRouter.instance` is a `GoRouter` with `initialLocation: AppRoutes.root`, a stub `redirect:` returning `null` + `TODO(4.3): add auth guard` comment, and exactly one `GoRoute` (`/` → `_PlaceholderScreen`). Route constants declared as `static const` on `AppRoutes` class — no magic strings.
- **AC5 (pre-commit)**: `flutter analyze` returned `No issues found!` (zero errors/warnings/infos). `flutter test` returned `All tests passed!` for all 3 tests.
- **AC6 (native permissions preserved)**: `AndroidManifest.xml`, `Info.plist`, and `pubspec.yaml` assets block not modified — only `dependencies` / `dev_dependencies` blocks changed.
- **Rive-in-tests note**: The `App` widget does not render any Rive content, so widget tests render cleanly even when `RiveNative.init()` is skipped via try/catch.
- **Non-goal boundaries respected**: No theme tokens, no auth screens, no Dio client wiring, no Rive loader implementation, no server code touched.

### File List

**Created:**
- `client/lib/main.dart` — bootstrap() + main()
- `client/lib/app/app.dart` — MaterialApp.router shell
- `client/lib/app/router.dart` — GoRouter + AppRoutes + _PlaceholderScreen
- `client/lib/app/theme.dart` — minimal dark theme
- `client/lib/features/auth/bloc/.gitkeep`
- `client/lib/features/auth/models/.gitkeep`
- `client/lib/features/auth/repositories/.gitkeep`
- `client/lib/features/auth/views/.gitkeep`
- `client/lib/features/call/bloc/.gitkeep`
- `client/lib/features/call/models/.gitkeep`
- `client/lib/features/call/repositories/.gitkeep`
- `client/lib/features/call/services/.gitkeep`
- `client/lib/features/call/views/.gitkeep`
- `client/lib/features/scenarios/bloc/.gitkeep`
- `client/lib/features/scenarios/models/.gitkeep`
- `client/lib/features/scenarios/repositories/.gitkeep`
- `client/lib/features/scenarios/views/.gitkeep`
- `client/lib/features/debrief/bloc/.gitkeep`
- `client/lib/features/debrief/models/.gitkeep`
- `client/lib/features/debrief/repositories/.gitkeep`
- `client/lib/features/debrief/views/.gitkeep`
- `client/lib/core/api/.gitkeep`
- `client/lib/core/auth/.gitkeep`
- `client/lib/core/rive/.gitkeep`
- `client/lib/core/theme/.gitkeep`
- `client/lib/shared/widgets/.gitkeep`
- `client/test/app_test.dart` — 2 widget tests
- `client/test/dependencies_smoke_test.dart` — 1 compile-only smoke test

**Modified:**
- `client/pubspec.yaml` — dependencies adjusted per AC2
- `client/pubspec.lock` — regenerated by `flutter pub get`
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `4-1` status `ready-for-dev` → `in-progress` → `review`; `last_updated` bumped to 2026-04-16
- `_bmad-output/implementation-artifacts/4-1-restructure-flutter-project-to-mvp-architecture.md` — Status → `review`; Tasks/Subtasks all checked; Dev Agent Record populated; Change Log updated

**Deleted:**
- `client/lib/main.dart` (old PoC single-file — replaced by new bootstrap)
- `client/lib/config.dart` (old VPS URL constant — VPS URL will move to `core/api/api_client.dart` in Story 4.3)
- `client/test/widget_test.dart` (old PoC CallScreen test — no longer relevant)

## Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2026-04-16 | 1.0 | Initial restructure from PoC single-file to MVP feature-based BLoC scaffold. 4 core files (main/app/router/theme), 22 `.gitkeep` placeholders, 3 new tests, 6 MVP deps added, http removed. | walid |
| 2026-04-16 | 1.1 | Code review corrections applied: (1) bootstrap catch blocks now call `FlutterError.reportError` instead of silently swallowing Rive init failures — Task 4.3 example code + prose amended (BS-1); (2) `app_test.dart` test 1 now awaits `pumpAndSettle` for consistency with test 2 (P-2); (3) both widget tests now assert `tester.takeException() isNull` so AC5 "renders without errors" is actually verified (P-1). | walid |
