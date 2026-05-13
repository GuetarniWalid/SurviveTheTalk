import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../core/api/api_client.dart';
import '../core/auth/token_storage.dart';
import '../core/onboarding/consent_storage.dart';
import '../core/onboarding/permission_service.dart';
import '../core/services/end_call_retry_service.dart';
import '../core/theme/app_theme.dart';
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

  const App({
    super.key,
    this.authBloc,
    this.onboardingBloc,
    this.consentStorage,
    this.tokenStorage,
    this.scenariosBloc,
    this.endCallRetryService,
  });

  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> with WidgetsBindingObserver {
  late final AuthBloc _authBloc;
  late final OnboardingBloc _onboardingBloc;
  late final ConsentStorage _consentStorage;
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

    if (widget.authBloc != null) {
      _authBloc = widget.authBloc!;
    } else {
      // Use the preloaded TokenStorage from bootstrap if provided so that
      // hasValidTokenSync returns the cached answer; falls back to a fresh
      // (non-preloaded → false) instance for tests that rely on App's own
      // construction path.
      final tokenStorage = widget.tokenStorage ?? TokenStorage();
      _authBloc = AuthBloc(
        authRepository: AuthRepository(ApiClient()),
        tokenStorage: tokenStorage,
        // Seed with AuthAuthenticated when preload found a valid JWT — the
        // router's first redirect pass then sees the correct auth state and
        // skips the brief /login flash. CheckAuthStatusEvent still runs
        // below as a refresh-and-cleanup pass (catches expired tokens that
        // slipped past the cache, etc.).
        initialState: tokenStorage.hasValidTokenSync
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
      scenariosBloc: _scenariosBloc,
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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
    // covers the test surface).
    final retryService = widget.endCallRetryService;
    if (retryService == null) return blocs;
    return RepositoryProvider<EndCallRetryService>.value(
      value: retryService,
      child: blocs,
    );
  }
}
