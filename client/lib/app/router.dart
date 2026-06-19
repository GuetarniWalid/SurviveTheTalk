import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../core/api/api_client.dart';
import '../core/local_cache/debrief_cache_store.dart';
import '../core/local_cache/scenario_cache_store.dart';
import '../core/onboarding/consent_storage.dart';
import '../core/onboarding/difficulty_storage.dart';
import '../core/onboarding/vibration_service.dart';
import '../core/services/connectivity_service.dart';
import '../features/auth/bloc/auth_bloc.dart';
import '../features/auth/bloc/auth_state.dart';
import '../features/auth/presentation/code_verification_screen.dart';
import '../features/auth/presentation/email_entry_screen.dart';
import '../features/briefing/views/briefing_screen.dart';
import '../features/call/bloc/incoming_call_bloc.dart';
import '../features/call/repositories/call_repository.dart';
import '../features/call/views/incoming_call_screen.dart';
import '../features/debrief/views/cached_debrief_screen.dart';
import '../features/onboarding/presentation/consent_screen.dart';
import '../features/onboarding/presentation/mic_permission_screen.dart';
import '../features/scenarios/bloc/scenarios_bloc.dart';
import '../features/scenarios/bloc/scenarios_event.dart';
import '../features/scenarios/models/scenario.dart';
import '../features/scenarios/repositories/scenarios_repository.dart';
import '../features/scenarios/views/scenario_list_screen.dart';

/// Central registry of all route paths used by [AppRouter].
class AppRoutes {
  const AppRoutes._();

  static const String root = '/';
  static const String login = '/login';
  static const String verify = '/verify';
  static const String consent = '/consent';
  static const String micPermission = '/mic-permission';
  static const String incomingCall = '/incoming-call';
  static const String debrief = '/debrief';
  static const String briefing = '/briefing';
}

class AppRouter {
  const AppRouter._();

  static GoRouter createRouter(
    AuthBloc authBloc, {
    required ConsentStorage consentStorage,
    // Story 6.19 — the bootstrap-preloaded global difficulty store, threaded to
    // the hub (ScenarioListScreen) so the discreet "Difficulty:" line + the
    // outgoing call reflect the persisted choice.
    required DifficultyStorage difficultyStorage,
    ScenariosBloc? scenariosBloc,
    // Story 9.1 — the offline cache stores (bootstrap-opened). NULLABLE on
    // purpose: app.dart cannot synchronously default a DB-backed store and the
    // many App-constructing widget tests pass none. Production always supplies
    // them; null falls back to today's network-only behaviour (the bloc + the
    // debrief route are both null-tolerant).
    ScenarioCacheStore? scenarioCacheStore,
    DebriefCacheStore? debriefCacheStore,
    // Story 9.2 — the bootstrap-owned ConnectivityService. NULLABLE (same
    // rationale as `scenarioCacheStore`): App-constructing widget tests pass
    // none; production always supplies it. Fed into the inline hub bloc so an
    // offline→online regain triggers a silent refresh.
    ConnectivityService? connectivityService,
  }) {
    return GoRouter(
      initialLocation: AppRoutes.root,
      refreshListenable: _GoRouterRefreshStream(authBloc.stream),
      redirect: (context, state) {
        final authState = authBloc.state;
        final isAuthenticated = authState is AuthAuthenticated;
        final currentPath = state.matchedLocation;

        final isAuthRoute =
            currentPath == AppRoutes.login || currentPath == AppRoutes.verify;

        if (!isAuthenticated && !isAuthRoute) {
          return AppRoutes.login;
        }

        // Navigate to verify screen when code has been sent
        if (authState is AuthCodeSent && currentPath == AppRoutes.login) {
          return AppRoutes.verify;
        }

        // Redirect back to login only on explicit reset
        if (currentPath == AppRoutes.verify && authState is AuthInitial) {
          return AppRoutes.login;
        }

        if (isAuthenticated) {
          final hasConsent = consentStorage.hasConsentSync;
          final hasMic = consentStorage.hasMicPermissionSync;
          final seenFirstCall = consentStorage.hasSeenFirstCallSync;

          if (!hasConsent) {
            if (currentPath != AppRoutes.consent) {
              return AppRoutes.consent;
            }
          } else if (!hasMic) {
            if (currentPath != AppRoutes.micPermission) {
              return AppRoutes.micPermission;
            }
          } else if (!seenFirstCall) {
            if (currentPath != AppRoutes.incomingCall) {
              return AppRoutes.incomingCall;
            }
          } else if (isAuthRoute ||
              currentPath == AppRoutes.consent ||
              currentPath == AppRoutes.micPermission ||
              currentPath == AppRoutes.incomingCall) {
            return AppRoutes.root;
          }
        }

        return null;
      },
      routes: <RouteBase>[
        GoRoute(
          path: AppRoutes.root,
          pageBuilder: (context, state) => _fadePage(
            key: state.pageKey,
            child: scenariosBloc != null
                ? BlocProvider<ScenariosBloc>.value(
                    value: scenariosBloc,
                    child: ScenarioListScreen(
                      difficultyStorage: difficultyStorage,
                      debriefCacheStore: debriefCacheStore,
                    ),
                  )
                // Story 9.1 — the PRODUCTION hub bloc is THIS inline fallback
                // (App.scenariosBloc is null in prod). Feed it the cache store
                // here too, or the offline feature silently no-ops while every
                // injected-bloc test stays green.
                : BlocProvider<ScenariosBloc>(
                    create: (_) => ScenariosBloc(
                      ScenariosRepository(ApiClient()),
                      cacheStore: scenarioCacheStore,
                      // Story 9.2 — feed connectivity to the PRODUCTION inline
                      // bloc; without this the regain auto-sync silently no-ops
                      // in prod (App.scenariosBloc is null) while tests pass.
                      connectivityService: connectivityService,
                    )..add(const LoadScenariosEvent()),
                    child: ScenarioListScreen(
                      difficultyStorage: difficultyStorage,
                      debriefCacheStore: debriefCacheStore,
                    ),
                  ),
          ),
        ),
        GoRoute(
          path: AppRoutes.login,
          pageBuilder: (context, state) => _fadePage(
            key: state.pageKey,
            child: const EmailEntryScreen(),
          ),
        ),
        GoRoute(
          path: AppRoutes.verify,
          pageBuilder: (context, state) {
            final authState = authBloc.state;
            final email =
                authState is AuthCodeSent
                    ? authState.email
                    : authState is AuthError &&
                        authState.previousState is AuthCodeSent
                    ? (authState.previousState as AuthCodeSent).email
                    : '';
            return _fadePage(
              key: state.pageKey,
              child: CodeVerificationScreen(email: email),
            );
          },
        ),
        GoRoute(
          path: AppRoutes.consent,
          pageBuilder: (context, state) => _fadePage(
            key: state.pageKey,
            child: const ConsentScreen(),
          ),
        ),
        GoRoute(
          path: AppRoutes.micPermission,
          pageBuilder: (context, state) => _fadePage(
            key: state.pageKey,
            child: const MicPermissionScreen(),
          ),
        ),
        GoRoute(
          path: AppRoutes.incomingCall,
          pageBuilder: (context, state) => _fadePage(
            key: state.pageKey,
            // The bloc is route-scoped (not promoted to MultiBlocProvider in
            // app.dart) because its lifecycle is tied to this screen: it
            // stops the vibration in close() and saves the first-call-shown
            // flag. A global instance would keep vibrating after navigation.
            child: BlocProvider<IncomingCallBloc>(
              create: (_) => IncomingCallBloc(
                callRepository: CallRepository(ApiClient()),
                consentStorage: consentStorage,
                vibrationService: VibrationService(),
              ),
              child: const IncomingCallScreen(),
            ),
          ),
        ),
        GoRoute(
          path: '${AppRoutes.debrief}/:scenarioId',
          // Story 9.1 (Task 5) — resolve the cached debrief for this scenario;
          // render the real DebriefScreen on a hit, an empathetic "no saved
          // report" state on a miss (cache-only, no server backfill).
          pageBuilder: (context, state) => _fadePage(
            key: state.pageKey,
            child: CachedDebriefScreen(
              scenarioId: state.pathParameters['scenarioId'] ?? 'unknown',
              cacheStore: debriefCacheStore,
            ),
          ),
        ),
        GoRoute(
          path: '${AppRoutes.briefing}/:scenarioId',
          // Story 7.4 AC-C3 — both hub entries push with `extra: scenario`.
          // A deep-link / refresh entry carries no extra: bounce to the hub
          // (graceful fade, no fallback widget) instead of rendering a
          // briefing with nothing to show.
          redirect: (context, state) =>
              state.extra is Scenario ? null : AppRoutes.root,
          // The 500ms fade IS the title-card beat — no further motion ever.
          pageBuilder: (context, state) => _fadePage(
            key: state.pageKey,
            child: BriefingScreen(scenario: state.extra! as Scenario),
          ),
        ),
      ],
    );
  }
}

CustomTransitionPage<void> _fadePage({
  required LocalKey key,
  required Widget child,
}) {
  return CustomTransitionPage<void>(
    key: key,
    child: child,
    transitionDuration: const Duration(milliseconds: 500),
    transitionsBuilder: (context, animation, secondaryAnimation, child) {
      return FadeTransition(
        opacity: CurvedAnimation(parent: animation, curve: Curves.easeOut),
        child: child,
      );
    },
  );
}

/// Converts a [Stream] into a [ChangeNotifier] for GoRouter's
/// `refreshListenable` parameter.
class _GoRouterRefreshStream extends ChangeNotifier {
  late final StreamSubscription<dynamic> _subscription;

  _GoRouterRefreshStream(Stream<dynamic> stream) {
    _subscription = stream.asBroadcastStream().listen((_) {
      notifyListeners();
    });
  }

  @override
  void dispose() {
    _subscription.cancel();
    super.dispose();
  }
}
