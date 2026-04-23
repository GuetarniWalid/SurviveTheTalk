import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../core/api/api_client.dart';
import '../core/onboarding/consent_storage.dart';
import '../core/onboarding/vibration_service.dart';
import '../features/auth/bloc/auth_bloc.dart';
import '../features/auth/bloc/auth_state.dart';
import '../features/auth/presentation/code_verification_screen.dart';
import '../features/auth/presentation/email_entry_screen.dart';
import '../features/call/bloc/incoming_call_bloc.dart';
import '../features/call/models/call_session.dart';
import '../features/call/repositories/call_repository.dart';
import '../features/call/views/call_placeholder_screen.dart';
import '../features/call/views/incoming_call_screen.dart';
import '../features/onboarding/presentation/consent_screen.dart';
import '../features/onboarding/presentation/mic_permission_screen.dart';

/// Central registry of all route paths used by [AppRouter].
class AppRoutes {
  const AppRoutes._();

  static const String root = '/';
  static const String login = '/login';
  static const String verify = '/verify';
  static const String consent = '/consent';
  static const String micPermission = '/mic-permission';
  static const String incomingCall = '/incoming-call';
  static const String call = '/call';
}

class AppRouter {
  const AppRouter._();

  static GoRouter createRouter(
    AuthBloc authBloc, {
    required ConsentStorage consentStorage,
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
            if (currentPath != AppRoutes.incomingCall &&
                currentPath != AppRoutes.call) {
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
            child: const Scaffold(
              body: Center(
                child: Text('Scenario List — Story 5.2'),
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
          path: AppRoutes.call,
          pageBuilder: (context, state) {
            final session = state.extra;
            if (session is! CallSession) {
              // Defensive fallback — if someone deep-links /call with no
              // CallSession, send them to the scenario list placeholder
              // rather than crashing. This shouldn't happen under normal
              // navigation because Accept always passes extra.
              return _fadePage(
                key: state.pageKey,
                child: const Scaffold(
                  body: Center(
                    child: Text('No active call'),
                  ),
                ),
              );
            }
            return _fadePage(
              key: state.pageKey,
              child: CallPlaceholderScreen(session: session),
            );
          },
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
