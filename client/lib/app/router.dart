import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Central registry of all route paths used by [AppRouter].
///
/// Declared as static const members to avoid magic strings in navigation
/// calls throughout the codebase.
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

/// Deliberately private — this placeholder is removed when Story 4.3 adds
/// the real email entry screen as the initial route.
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
