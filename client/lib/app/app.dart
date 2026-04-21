import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../core/api/api_client.dart';
import '../core/auth/token_storage.dart';
import '../core/theme/app_theme.dart';
import '../features/auth/bloc/auth_bloc.dart';
import '../features/auth/bloc/auth_event.dart';
import '../features/auth/data/auth_repository.dart';
import 'router.dart';

class App extends StatefulWidget {
  final AuthBloc? authBloc;

  const App({super.key, this.authBloc});

  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> {
  late final AuthBloc _authBloc;
  late final GoRouter _router;

  @override
  void initState() {
    super.initState();
    if (widget.authBloc != null) {
      _authBloc = widget.authBloc!;
    } else {
      _authBloc = AuthBloc(
        authRepository: AuthRepository(ApiClient()),
        tokenStorage: TokenStorage(),
      )..add(CheckAuthStatusEvent());
    }
    _router = AppRouter.createRouter(_authBloc);
  }

  @override
  void dispose() {
    if (widget.authBloc == null) {
      _authBloc.close();
    }
    _router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return BlocProvider<AuthBloc>.value(
      value: _authBloc,
      child: MaterialApp.router(
        title: 'surviveTheTalk',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.dark(),
        routerConfig: _router,
      ),
    );
  }
}
