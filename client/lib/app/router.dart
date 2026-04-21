import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/bloc/auth_bloc.dart';
import '../features/auth/bloc/auth_state.dart';
import '../features/auth/presentation/code_verification_screen.dart';
import '../features/auth/presentation/email_entry_screen.dart';

/// Central registry of all route paths used by [AppRouter].
class AppRoutes {
  const AppRoutes._();

  static const String root = '/';
  static const String login = '/login';
  static const String verify = '/verify';
  static const String consent = '/consent';
}

class AppRouter {
  const AppRouter._();

  static GoRouter createRouter(AuthBloc authBloc) {
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

        if (isAuthenticated && isAuthRoute) {
          return AppRoutes.consent;
        }

        // Navigate to verify screen when code has been sent
        if (authState is AuthCodeSent && currentPath == AppRoutes.login) {
          return AppRoutes.verify;
        }

        // Redirect back to login only on explicit reset
        if (currentPath == AppRoutes.verify && authState is AuthInitial) {
          return AppRoutes.login;
        }

        return null;
      },
      routes: <RouteBase>[
        GoRoute(
          path: AppRoutes.root,
          pageBuilder: (context, state) => _slidePage(
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
          pageBuilder: (context, state) => _slidePage(
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
            return _slidePage(
              key: state.pageKey,
              child: CodeVerificationScreen(email: email),
            );
          },
        ),
        GoRoute(
          path: AppRoutes.consent,
          pageBuilder: (context, state) => _slidePage(
            key: state.pageKey,
            child: const Scaffold(
              body: Center(
                child: Text('Consent — Story 4.4'),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

CustomTransitionPage<void> _slidePage({
  required LocalKey key,
  required Widget child,
}) {
  return CustomTransitionPage<void>(
    key: key,
    child: child,
    transitionsBuilder: (context, animation, secondaryAnimation, child) {
      return SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(1, 0),
          end: Offset.zero,
        ).animate(CurvedAnimation(
          parent: animation,
          curve: Curves.easeInOut,
        )),
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
