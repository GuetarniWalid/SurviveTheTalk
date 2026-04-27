import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../core/api/api_client.dart';
import '../core/auth/token_storage.dart';
import '../core/onboarding/consent_storage.dart';
import '../core/onboarding/permission_service.dart';
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

  const App({
    super.key,
    this.authBloc,
    this.onboardingBloc,
    this.consentStorage,
    this.tokenStorage,
    this.scenariosBloc,
  });

  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> {
  late final AuthBloc _authBloc;
  late final OnboardingBloc _onboardingBloc;
  late final ConsentStorage _consentStorage;
  ScenariosBloc? _scenariosBloc;
  late final GoRouter _router;

  @override
  void initState() {
    super.initState();
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
  Widget build(BuildContext context) {
    return MultiBlocProvider(
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
  }
}
