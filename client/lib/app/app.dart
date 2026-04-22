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
import '../features/auth/data/auth_repository.dart';
import '../features/onboarding/bloc/onboarding_bloc.dart';
import '../features/onboarding/bloc/onboarding_event.dart';
import 'router.dart';

class App extends StatefulWidget {
  final AuthBloc? authBloc;
  final OnboardingBloc? onboardingBloc;
  final ConsentStorage? consentStorage;

  const App({
    super.key,
    this.authBloc,
    this.onboardingBloc,
    this.consentStorage,
  });

  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> {
  late final AuthBloc _authBloc;
  late final OnboardingBloc _onboardingBloc;
  late final ConsentStorage _consentStorage;
  late final GoRouter _router;

  @override
  void initState() {
    super.initState();
    _consentStorage = widget.consentStorage ?? ConsentStorage();

    if (widget.authBloc != null) {
      _authBloc = widget.authBloc!;
    } else {
      _authBloc = AuthBloc(
        authRepository: AuthRepository(ApiClient()),
        tokenStorage: TokenStorage(),
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

    _router = AppRouter.createRouter(
      _authBloc,
      consentStorage: _consentStorage,
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
