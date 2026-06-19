import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../core/api/api_client.dart';
import '../core/api/auth_interceptor.dart';
import '../core/auth/token_storage.dart';
import '../core/local_cache/app_database.dart';
import '../core/local_cache/debrief_cache_store.dart';
import '../core/local_cache/scenario_cache_store.dart';
import '../core/onboarding/consent_storage.dart';
import '../core/onboarding/difficulty_storage.dart';
import '../core/onboarding/permission_service.dart';
import '../core/services/end_call_retry_service.dart';
import '../core/theme/app_theme.dart';
import '../core/widgets/app_toast.dart';
import '../features/subscription/services/purchase_sync_service.dart';
import '../features/auth/bloc/auth_bloc.dart';
import '../features/auth/bloc/auth_event.dart';
import '../features/auth/bloc/auth_state.dart';
import '../features/auth/data/auth_repository.dart';
import '../features/onboarding/bloc/onboarding_bloc.dart';
import '../features/onboarding/bloc/onboarding_event.dart';
import '../features/scenarios/bloc/scenarios_bloc.dart';
import 'router.dart';

class App extends StatefulWidget {
  final AuthBloc? authBloc;
  final OnboardingBloc? onboardingBloc;
  final ConsentStorage? consentStorage;
  final TokenStorage? tokenStorage;
  final ScenariosBloc? scenariosBloc;
  final EndCallRetryService? endCallRetryService;
  // Story 6.19 — global difficulty preference store (bootstrap-preloaded).
  final DifficultyStorage? difficultyStorage;
  // Story 8.3 (Task 6) — app-lifetime purchase listener (bootstrap-owned).
  final PurchaseSyncService? purchaseSyncService;
  // Story 9.1 — offline cache (bootstrap-opened). `appDatabase` backs the
  // auth-reset wipe (Task 6b); the two stores are threaded to the router (hub
  // bloc + debrief route) and the call flow. All null in tests / when the DB
  // isn't wired — the feature degrades to network-only.
  final AppDatabase? appDatabase;
  final ScenarioCacheStore? scenarioCacheStore;
  final DebriefCacheStore? debriefCacheStore;

  const App({
    super.key,
    this.authBloc,
    this.onboardingBloc,
    this.consentStorage,
    this.tokenStorage,
    this.scenariosBloc,
    this.endCallRetryService,
    this.difficultyStorage,
    this.purchaseSyncService,
    this.appDatabase,
    this.scenarioCacheStore,
    this.debriefCacheStore,
  });

  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> with WidgetsBindingObserver {
  late final AuthBloc _authBloc;
  late final OnboardingBloc _onboardingBloc;
  late final ConsentStorage _consentStorage;
  late final TokenStorage _tokenStorage;
  late final DifficultyStorage _difficultyStorage;
  ScenariosBloc? _scenariosBloc;
  late final GoRouter _router;

  @override
  void initState() {
    super.initState();
    // Story 6.5 Option B (post-deploy PD3) — observe app lifecycle so
    // `EndCallRetryService.replayAll()` runs every time the user brings
    // the app back to foreground, not only on `onConnectivityRegained`.
    // Live VPS test 2026-05-15: `connectivity_plus`'s
    // `NetworkCallback` on Android can silently miss the regain
    // transition after a brief background trip (notification panel for
    // airplane-mode toggle, switching to a browser to verify net),
    // leaving a queued POST stuck until the next cold-start. Wiring
    // the resume hook here is a belt-and-braces drain trigger — three
    // independent paths (boot, connectivity-regain, lifecycle-resume)
    // converge on the same idempotent `replayAll()`.
    WidgetsBinding.instance.addObserver(this);
    _consentStorage = widget.consentStorage ?? ConsentStorage();
    // Story 6.19 — use the bootstrap-preloaded difficulty store if provided so
    // the hub line reads the persisted choice synchronously; tests fall back to
    // a fresh (default-easy) instance.
    _difficultyStorage = widget.difficultyStorage ?? DifficultyStorage();
    // Use the preloaded TokenStorage from bootstrap if provided so the
    // 401 handler clears the SAME store the AuthBloc reads from
    // (hasValidTokenSync cache stays consistent).
    _tokenStorage = widget.tokenStorage ?? TokenStorage();

    if (widget.authBloc != null) {
      _authBloc = widget.authBloc!;
    } else {
      _authBloc = AuthBloc(
        authRepository: AuthRepository(ApiClient()),
        tokenStorage: _tokenStorage,
        // Seed with AuthAuthenticated when preload found a valid JWT — the
        // router's first redirect pass then sees the correct auth state and
        // skips the brief /login flash. CheckAuthStatusEvent still runs
        // below as a refresh-and-cleanup pass (catches expired tokens that
        // slipped past the cache, etc.).
        initialState: _tokenStorage.hasValidTokenSync
            ? AuthAuthenticated()
            : null,
      )..add(CheckAuthStatusEvent());
    }

    if (widget.onboardingBloc != null) {
      _onboardingBloc = widget.onboardingBloc!;
    } else {
      _onboardingBloc = OnboardingBloc(
        consentStorage: _consentStorage,
        permissionService: PermissionService(),
      )..add(const CheckOnboardingStatusEvent());
    }

    _scenariosBloc = widget.scenariosBloc;

    _router = AppRouter.createRouter(
      _authBloc,
      consentStorage: _consentStorage,
      difficultyStorage: _difficultyStorage,
      scenariosBloc: _scenariosBloc,
      // Story 9.1 — feed the cache stores so the PRODUCTION inline hub bloc and
      // the debrief route get them (App.scenariosBloc is null in prod).
      scenarioCacheStore: widget.scenarioCacheStore,
      debriefCacheStore: widget.debriefCacheStore,
    );

    // Story 6.13 AC4 — wire the cross-cutting 401 handler. When ANY
    // backend endpoint returns 401, the AuthInterceptor (installed
    // on every ApiClient) fires this callback:
    //   (a) clear the JWT from secure storage,
    //   (b) dispatch ResetAuthEvent so AuthBloc emits AuthInitial —
    //       GoRouter's refreshListenable observes the state change
    //       and redirects to /login (the existing pattern from
    //       Story 4.2),
    //   (c) show a one-shot AppToast explaining what happened.
    // Closes the Story 5.5 "AUTH_UNAUTHORIZED silent loop" MUST-FIX
    // gap that's been open ~1 month.
    AuthInterceptor.globalHandler = () async {
      // Capture the navigator key handle UP FRONT so the toast push
      // below doesn't dereference `_router` across an async gap (lint
      // `use_build_context_synchronously`). `currentContext` is still
      // resolved freshly at toast-time — what matters is that the
      // outer `_router` reference is captured before any await.
      final navigatorKey = _router.routerDelegate.navigatorKey;
      // Best-effort delete: even if it fails (locked keystore, etc.)
      // we still dispatch the reset so the bloc emits AuthInitial
      // and the router redirects — the stale token will be
      // overwritten on next successful login anyway.
      try {
        await _tokenStorage.deleteToken();
      } catch (_) {
        // Swallow — the bloc reset below is the load-bearing step.
      }
      // Story 9.1 (Task 6b — privacy) — wipe the offline cache on auth reset so
      // a DIFFERENT account signing in on the same device never inherits the
      // previous user's cached scenarios/progression/budget OR their debriefs
      // (which quote their spoken transcript). Best-effort, like the token
      // delete above — the bloc reset stays the load-bearing step.
      try {
        await widget.appDatabase?.clearAll();
      } catch (_) {
        // Swallow — a failed wipe must not block the auth reset; a stale cache
        // is overwritten on the next account's network refresh.
      }
      if (!mounted) return;
      // Avoid double-dispatch: if the bloc is already in AuthInitial
      // (the redirect already fired), skip re-emitting (BlocListener
      // skips equal const states anyway — see client/CLAUDE.md
      // gotcha #4 — but ResetAuthEvent emits a fresh AuthInitial
      // each time, which the bloc accepts).
      if (_authBloc.state is! AuthInitial) {
        _authBloc.add(ResetAuthEvent());
      }
      // Toast is fire-and-forget — if the navigator isn't mounted yet
      // (very first frame, pre-mount), skip silently rather than crash.
      // The redirect itself is the load-bearing UX signal; the toast is
      // supplemental copy.
      //
      // Story 6.13 review (2026-05-27) — insert into the navigator's
      // OverlayState DIRECTLY. The previous `Overlay.of(navigatorKey.
      // currentContext)` threw "No Overlay widget found": the root
      // Navigator's Overlay is a CHILD of that context, not an ancestor,
      // so the ancestor lookup failed and the exception was swallowed by
      // the interceptor's `catch (_)` — the toast never actually showed.
      final overlay = navigatorKey.currentState?.overlay;
      if (overlay != null && overlay.mounted) {
        AppToast.showInOverlay(
          overlay,
          message: 'Session expired, please sign in again',
          type: AppToastType.warning,
        );
      }
    };
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    // Story 6.13 AC4 — clear the global 401 handler so a recreated
    // App (e.g. hot restart, integration-test tear-down) doesn't
    // race with a stale handler closure that references the
    // disposed _authBloc / _router.
    AuthInterceptor.globalHandler = null;
    if (widget.authBloc == null) {
      _authBloc.close();
    }
    if (widget.onboardingBloc == null) {
      _onboardingBloc.close();
    }
    _router.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    if (state == AppLifecycleState.resumed) {
      // Fire-and-forget — `replayAll()` is internally idempotent (the
      // `_replayInFlight` guard prevents overlapping drains) and
      // tolerates an empty queue (returns 0, no POST traffic).
      // No await: lifecycle callbacks must return quickly.
      final retryService = widget.endCallRetryService;
      if (retryService != null) {
        unawaited(retryService.replayAll());
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final blocs = MultiBlocProvider(
      providers: [
        BlocProvider<AuthBloc>.value(value: _authBloc),
        BlocProvider<OnboardingBloc>.value(value: _onboardingBloc),
      ],
      child: MaterialApp.router(
        title: 'surviveTheTalk',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.dark(),
        routerConfig: _router,
      ),
    );
    // Story 6.5 Option B — expose the retry singleton to descendants
    // (CallScreen reads it via `context.read<EndCallRetryService>()`
    // in initState). `.value` because the lifecycle is owned by
    // `bootstrap()`, not by this widget — App should not dispose
    // the service. Tests that construct `App` without passing the
    // service simply skip this wrapper (the bloc's null-tolerant path
    // covers the test surface). Story 8.3 (Task 6) — the
    // PurchaseSyncService is exposed the same way (the hub reads it via
    // `context.read<PurchaseSyncService>()` to refresh on entitlement change).
    Widget tree = blocs;
    final retryService = widget.endCallRetryService;
    if (retryService != null) {
      tree = RepositoryProvider<EndCallRetryService>.value(
        value: retryService,
        child: tree,
      );
    }
    final purchaseSync = widget.purchaseSyncService;
    if (purchaseSync != null) {
      tree = RepositoryProvider<PurchaseSyncService>.value(
        value: purchaseSync,
        child: tree,
      );
    }
    return tree;
  }
}
