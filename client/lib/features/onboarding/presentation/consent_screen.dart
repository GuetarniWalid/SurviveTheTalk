import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:go_router/go_router.dart';
import 'package:rive/rive.dart' as rive;
import 'package:url_launcher/url_launcher.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../bloc/onboarding_bloc.dart';
import '../bloc/onboarding_event.dart';
import '../bloc/onboarding_state.dart';

class ConsentScreen extends StatefulWidget {
  const ConsentScreen({super.key});

  @override
  State<ConsentScreen> createState() => _ConsentScreenState();
}

class _ConsentScreenState extends State<ConsentScreen> {
  static const String _privacyPolicyUrl = 'https://survivethe.talk/privacy';
  static const String _riveAssetPath = 'assets/rive/ai_consent.riv';

  // Rive state
  rive.FileLoader? _riveLoader;
  bool _riveFallback = false;

  late final TapGestureRecognizer _privacyPolicyRecognizer;

  @override
  void initState() {
    super.initState();
    _privacyPolicyRecognizer = TapGestureRecognizer()
      ..onTap = _launchPrivacyPolicy;
    _initRive();
  }

  @override
  void dispose() {
    _privacyPolicyRecognizer.dispose();
    _riveLoader?.dispose();
    super.dispose();
  }

  Future<void> _initRive() async {
    if (!rive.RiveNative.isInitialized) {
      if (mounted) setState(() => _riveFallback = true);
      return;
    }
    try {
      await rootBundle.load(_riveAssetPath);
      _riveLoader = rive.FileLoader.fromAsset(
        _riveAssetPath,
        riveFactory: rive.Factory.rive,
      );
      if (mounted) setState(() {});
    } catch (_) {
      if (mounted) setState(() => _riveFallback = true);
    }
  }

  Future<void> _launchPrivacyPolicy() async {
    final uri = Uri.parse(_privacyPolicyUrl);
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    return BlocListener<OnboardingBloc, OnboardingState>(
      listener: (context, state) {
        if (state is ConsentAccepted) {
          context.go(AppRoutes.micPermission);
        } else if (state is OnboardingComplete) {
          context.go(AppRoutes.root);
        }
      },
      child: Scaffold(
        backgroundColor: AppColors.background,
        body: LayoutBuilder(
          builder: (context, constraints) {
            final screenWidth = constraints.maxWidth;
            final screenHeight = constraints.maxHeight;
            return Stack(
              children: [
                // Whirlwind background — centered
                Positioned(
                  left: (screenWidth - 922) / 2,
                  top: (screenHeight - 920) / 2,
                  width: 922,
                  height: 920,
                  child: SvgPicture.asset(
                    'assets/images/whirlwind.svg',
                    fit: BoxFit.contain,
                    colorFilter: ColorFilter.mode(
                      Colors.white.withValues(alpha: 0.19),
                      BlendMode.srcIn,
                    ),
                  ),
                ),
                // Foreground content
                SafeArea(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(18, 40, 18, 40),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        // Group 1: Title + Description
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _buildTitle(),
                            const SizedBox(height: 16),
                            _buildDescription(),
                          ],
                        ),

                        // Group 2: Rive animation
                        _buildRiveWidget(),

                        // Group 3: Error + CTA + Legal
                        Column(
                          children: [
                            _buildErrorArea(),
                            _buildCtaButton(),
                            const SizedBox(height: 16),
                            _buildLegalText(),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildTitle() {
    return const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'NOT',
          style: TextStyle(
            fontFamily: 'Frijole',
            fontSize: 40,
            fontWeight: FontWeight.w400,
            color: AppColors.textPrimary,
            height: 1.375,
          ),
        ),
        Text(
          'REAL.',
          style: TextStyle(
            fontFamily: 'Frijole',
            fontSize: 40,
            fontWeight: FontWeight.w400,
            color: AppColors.textPrimary,
            height: 1.375,
          ),
        ),
        Text(
          'STILL',
          style: TextStyle(
            fontFamily: 'Frijole',
            fontSize: 40,
            fontWeight: FontWeight.w400,
            color: AppColors.accent,
            height: 1.375,
          ),
        ),
        Text(
          'BRUTAL.',
          style: TextStyle(
            fontFamily: 'Frijole',
            fontSize: 40,
            fontWeight: FontWeight.w400,
            color: AppColors.textPrimary,
            height: 1.375,
          ),
        ),
      ],
    );
  }

  Widget _buildDescription() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 25),
      child: Text.rich(
        TextSpan(
          style: TextStyle(
            fontFamily: 'Inter',
            fontSize: 16,
            fontWeight: FontWeight.w400,
            color: AppColors.textPrimary.withValues(alpha: 0.8),
            height: 1.19,
          ),
          children: const [
            TextSpan(text: 'Every voice, every face, every comeback in this app is '),
            TextSpan(
              text: 'AI-generated',
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            TextSpan(text: '. These bots will make you '),
            TextSpan(
              text: 'sweat',
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            TextSpan(text: ', '),
            TextSpan(
              text: 'cry',
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            TextSpan(text: ', and '),
            TextSpan(
              text: 'rehearse at 2am',
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            TextSpan(
              text: '. Don\u2019t say we didn\u2019t warn you.',
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRiveWidget() {
    if (_riveFallback || _riveLoader == null) {
      return const SizedBox(
        width: double.infinity,
        height: 280,
      );
    }
    return SizedBox(
      width: double.infinity,
      height: 280,
      child: rive.RiveWidgetBuilder(
        fileLoader: _riveLoader!,
        dataBind: rive.DataBind.auto(),
        builder: (context, state) {
          if (state is rive.RiveLoaded) {
            return rive.RiveWidget(
              controller: state.controller,
              fit: rive.Fit.contain,
            );
          }
          return const SizedBox.shrink();
        },
      ),
    );
  }

  Widget _buildErrorArea() {
    return BlocBuilder<OnboardingBloc, OnboardingState>(
      buildWhen: (previous, current) =>
          current is OnboardingError ||
          (previous is OnboardingError && current is! OnboardingError),
      builder: (context, state) {
        if (state is OnboardingError) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Text(
              state.message,
              style: const TextStyle(
                fontFamily: 'Inter',
                fontSize: 12,
                color: AppColors.destructive,
              ),
            ),
          );
        }
        return const SizedBox.shrink();
      },
    );
  }

  Widget _buildCtaButton() {
    return BlocBuilder<OnboardingBloc, OnboardingState>(
      builder: (context, state) {
        final isLoading = state is ConsentAccepting;
        return SizedBox(
          width: double.infinity,
          height: 64,
          child: FilledButton(
            onPressed: isLoading
                ? null
                : () => context
                    .read<OnboardingBloc>()
                    .add(const AcceptConsentEvent()),
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.accent,
              disabledBackgroundColor:
                  AppColors.accent.withValues(alpha: 0.7),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(32),
              ),
            ),
            child: isLoading
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: AppColors.background,
                    ),
                  )
                : const Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        "I'm in - hit me",
                        style: TextStyle(
                          fontFamily: 'Inter',
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                          color: AppColors.background,
                        ),
                      ),
                      SizedBox(width: 10),
                      Icon(
                        Icons.arrow_forward_rounded,
                        color: AppColors.background,
                        size: 24,
                      ),
                    ],
                  ),
          ),
        );
      },
    );
  }

  Widget _buildLegalText() {
    return Center(
      child: Text.rich(
        TextSpan(
          style: TextStyle(
            fontFamily: 'Inter',
            fontSize: 12,
            fontWeight: FontWeight.w400,
            color: AppColors.textPrimary.withValues(alpha: 0.8),
            height: 1.25,
          ),
          children: [
            const TextSpan(text: 'By tapping '),
            const TextSpan(
              text: "I'm in",
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            const TextSpan(text: ' you accept the '),
            TextSpan(
              text: 'privacy policy',
              style: const TextStyle(
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
                decoration: TextDecoration.underline,
              ),
              recognizer: _privacyPolicyRecognizer,
            ),
          ],
        ),
        textAlign: TextAlign.center,
      ),
    );
  }
}
