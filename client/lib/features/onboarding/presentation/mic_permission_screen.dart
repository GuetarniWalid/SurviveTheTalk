import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:go_router/go_router.dart';
import 'package:rive/rive.dart' as rive;
import 'package:url_launcher/url_launcher.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';
import '../bloc/onboarding_bloc.dart';
import '../bloc/onboarding_event.dart';
import '../bloc/onboarding_state.dart';

class MicPermissionScreen extends StatefulWidget {
  const MicPermissionScreen({super.key});

  @override
  State<MicPermissionScreen> createState() => _MicPermissionScreenState();
}

class _MicPermissionScreenState extends State<MicPermissionScreen>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  late final AnimationController _fadeController;

  static const String _privacyPolicyUrl = 'https://survivethe.talk/privacy';
  static const String _riveAssetPath = 'assets/rive/mic_consent.riv';

  // Rive state
  rive.FileLoader? _riveLoader;
  bool _riveFallback = false;
  bool _isSheetOpen = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _fadeController.addStatusListener(_onFadeComplete);
    _initRive();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _fadeController.removeStatusListener(_onFadeComplete);
    _fadeController.dispose();
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

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && mounted) {
      final blocState = context.read<OnboardingBloc>().state;
      if (blocState is MicDenied) {
        context.read<OnboardingBloc>().add(const RecheckMicPermissionEvent());
      }
    }
  }

  void _onFadeComplete(AnimationStatus status) {
    if (status == AnimationStatus.completed && mounted) {
      context.go(AppRoutes.incomingCall);
    }
  }

  void _onMicGranted() {
    HapticFeedback.mediumImpact();
    _fadeController.forward();
  }

  Future<void> _launchPrivacyPolicy() async {
    final uri = Uri.parse(_privacyPolicyUrl);
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  void _showMicDeniedSheet() {
    if (_isSheetOpen) return;
    _isSheetOpen = true;
    showModalBottomSheet<void>(
      context: context,
      isDismissible: true,
      enableDrag: true,
      isScrollControlled: true,
      backgroundColor: AppColors.textPrimary,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(30)),
      ),
      builder: (sheetContext) {
        return Padding(
          padding: const EdgeInsets.fromLTRB(24, 12, 24, 60),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Drag handle
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.avatarBg,
                  borderRadius: BorderRadius.circular(18),
                ),
              ),
              const SizedBox(height: 24),
              // Mic icon
              Container(
                width: 50,
                height: 50,
                decoration: BoxDecoration(
                  color: AppColors.background,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: const Icon(
                  Icons.mic_rounded,
                  color: AppColors.textPrimary,
                  size: 28,
                ),
              ),
              const SizedBox(height: 24),
              // Title
              const Text(
                'Mic is blocked',
                style: TextStyle(
                  fontFamily: 'Inter',
                  fontSize: 28,
                  fontWeight: FontWeight.w700,
                  color: AppColors.background,
                  height: 1.21,
                ),
              ),
              const SizedBox(height: 24),
              // Description
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 14),
                child: Text(
                  "The officer can't hear you. Flip the switch in "
                  "Settings and come right back — we'll pick up "
                  'where you left off',
                  style: TextStyle(
                    fontFamily: 'Inter',
                    fontSize: 16,
                    fontWeight: FontWeight.w400,
                    color: AppColors.avatarBg,
                    height: 1.375,
                  ),
                ),
              ),
              const SizedBox(height: 24),
              // Steps card
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Column(
                  children: [
                    _buildStep('1', 'Open Settings'),
                    _buildDivider(),
                    _buildStep('2', 'Tap Microphone'),
                    _buildDivider(),
                    _buildStep('3', 'Turn SurviveTheTalk on'),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              // CTA button
              SizedBox(
                width: double.infinity,
                height: 64,
                child: FilledButton(
                  onPressed: () {
                    Navigator.of(sheetContext).pop();
                    context
                        .read<OnboardingBloc>()
                        .add(const OpenAppSettingsEvent());
                  },
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(32),
                    ),
                  ),
                  child: const Text(
                    'Open Settings',
                    style: TextStyle(
                      fontFamily: 'Inter',
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                      color: AppColors.background,
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    ).whenComplete(() {
      _isSheetOpen = false;
    });
  }

  Widget _buildStep(String number, String label) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
      child: Row(
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: const BoxDecoration(
              color: AppColors.background,
              shape: BoxShape.circle,
            ),
            alignment: Alignment.center,
            child: Text(
              number,
              style: const TextStyle(
                fontFamily: 'Inter',
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Text(
              label,
              style: const TextStyle(
                fontFamily: 'Inter',
                fontSize: 16,
                fontWeight: FontWeight.w500,
                color: AppColors.background,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildDivider() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Divider(
        height: 1,
        thickness: 1,
        color: Colors.black.withValues(alpha: 0.1),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return BlocListener<OnboardingBloc, OnboardingState>(
      listener: (context, state) {
        if (state is MicGranted) {
          Navigator.of(context).popUntil((route) => route.isFirst);
          _onMicGranted();
        } else if (state is MicDenied) {
          _showMicDeniedSheet();
        }
      },
      child: AnimatedBuilder(
        animation: _fadeController,
        builder: (context, child) {
          return Opacity(
            opacity: 1.0 - _fadeController.value,
            child: child,
          );
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
                      padding: const EdgeInsets.fromLTRB(24, 20, 24, 24),
                      child: Column(
                children: [
                  const SizedBox(height: 16),
                  _buildTitle(screenHeight),
                  const Spacer(),
                  _buildSpeechBubble(),
                  SizedBox(height: screenHeight < 700 ? 8 : 16),
                  _buildAvatar(screenHeight),
                  SizedBox(height: screenHeight < 700 ? 12 : 22),
                  _buildPrivacyText(),
                  const Spacer(),
                  _buildCtaButton(),
                  const SizedBox(height: 4),
                  _buildGhostLink(),
                ],
              ),
            ),
          ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _buildTitle(double screenHeight) {
    final titleSize = screenHeight < 700 ? 38.0 : 50.0;
    return Text.rich(
      TextSpan(
        style: TextStyle(
          fontFamily: 'Frijole',
          fontSize: titleSize,
          fontWeight: FontWeight.w400,
          color: AppColors.textPrimary,
          height: 1.05,
          letterSpacing: -0.6,
        ),
        children: [
          const TextSpan(text: 'He needs to '),
          const TextSpan(
            text: 'hear',
            style: TextStyle(color: AppColors.accent),
          ),
          const TextSpan(text: ' you.'),
        ],
      ),
      textAlign: TextAlign.center,
    );
  }

  Widget _buildSpeechBubble() {
    return SizedBox(
      width: 284,
      height: 139,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Positioned.fill(
            child: SvgPicture.string(_bubbleSvg, fit: BoxFit.fill),
          ),
          const Padding(
            padding: EdgeInsets.only(left: 35, right: 35, bottom: 13),
            child: Text(
              "Open the mic! I'm not repeating myself!",
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: 'Inter',
                fontSize: 18,
                fontWeight: FontWeight.w600,
                height: 1.22,
                color: Colors.black,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAvatar(double screenHeight) {
    // 30% of screen height, clamped for small/large phones
    final height = (screenHeight * 0.30).clamp(180.0, 280.0);
    return SizedBox(
      height: height,
      child: _buildRiveCharacter(),
    );
  }

  Widget _buildRiveCharacter() {
    if (_riveFallback || _riveLoader == null) {
      return Container(
        decoration: const BoxDecoration(
          shape: BoxShape.circle,
          color: AppColors.avatarBg,
        ),
      );
    }
    return rive.RiveWidgetBuilder(
        fileLoader: _riveLoader!,
        dataBind: rive.DataBind.auto(),
        builder: (context, state) {
          if (state is rive.RiveLoaded) {
            return rive.RiveWidget(
              controller: state.controller,
              fit: rive.Fit.contain,
            );
          }
          return Container(
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              color: AppColors.avatarBg,
            ),
          );
        },
      );
  }

  Widget _buildPrivacyText() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Text(
        'The AI only listens during calls.\nNothing is recorded or uploaded.',
        textAlign: TextAlign.center,
        style: AppTypography.body.copyWith(
          fontWeight: FontWeight.w500,
          color: AppColors.textPrimary.withValues(alpha: 0.8),
          height: 1.55,
          letterSpacing: -0.1,
        ),
      ),
    );
  }

  Widget _buildCtaButton() {
    return BlocBuilder<OnboardingBloc, OnboardingState>(
      builder: (context, state) {
        final isLoading = state is MicPermissionRequested;
        return SizedBox(
          width: double.infinity,
          height: 64,
          child: FilledButton(
            onPressed: isLoading
                ? null
                : () => context
                    .read<OnboardingBloc>()
                    .add(const RequestMicPermissionEvent()),
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
                : const Text(
                    'Allow microphone',
                    style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                      color: AppColors.background,
                      letterSpacing: -0.2,
                    ),
                  ),
          ),
        );
      },
    );
  }

  Widget _buildGhostLink() {
    return TextButton(
      onPressed: _launchPrivacyPolicy,
      child: Text(
        'What we do with your voice \u2192',
        style: AppTypography.caption.copyWith(
          fontSize: 14,
          color: AppColors.textPrimary.withValues(alpha: 0.8),
        ),
      ),
    );
  }
}

// Speech bubble with tail pointing down (from design handoff).
const String _bubbleSvg = '<svg viewBox="0 0 284 139" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<ellipse cx="142" cy="63" rx="142" ry="63" fill="#FBF7EA"/>'
    '<path d="M120 120 L136 139 L152 120" fill="#FBF7EA"/></svg>';
