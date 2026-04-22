import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_toast.dart';
import '../bloc/auth_bloc.dart';
import '../bloc/auth_event.dart';
import '../bloc/auth_state.dart';

class CodeVerificationScreen extends StatefulWidget {
  final String email;

  const CodeVerificationScreen({super.key, required this.email});

  @override
  State<CodeVerificationScreen> createState() => _CodeVerificationScreenState();
}

class _CodeVerificationScreenState extends State<CodeVerificationScreen> {
  final _codeController = TextEditingController();
  final _focusNode = FocusNode();
  bool _hasError = false;

  static const _cooldownDuration = 60;
  int _cooldownSeconds = _cooldownDuration;
  Timer? _cooldownTimer;

  @override
  void initState() {
    super.initState();
    _codeController.addListener(_onCodeChanged);
    _startCooldown();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _focusNode.requestFocus();
      AppToast.show(
        context,
        message: "Check your spam folder if you don't see the code",
        type: AppToastType.warning,
      );
    });
  }

  @override
  void dispose() {
    _cooldownTimer?.cancel();
    _codeController.removeListener(_onCodeChanged);
    _codeController.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _startCooldown() {
    _cooldownSeconds = _cooldownDuration;
    _cooldownTimer?.cancel();
    _cooldownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      setState(() => _cooldownSeconds--);
      if (_cooldownSeconds <= 0) timer.cancel();
    });
  }

  void _onCodeChanged() {
    setState(() => _hasError = false);
    if (_codeController.text.length == 6) {
      _onVerify();
    }
  }

  void _onVerify() {
    if (context.read<AuthBloc>().state is AuthLoading) return;
    final code = _codeController.text.trim();
    if (code.length != 6 || int.tryParse(code) == null) return;
    // Dismiss keyboard before auth flow to prevent keyboard close animation
    // from interfering with page transition.
    FocusScope.of(context).unfocus();
    context.read<AuthBloc>().add(
      SubmitCodeEvent(email: widget.email, code: code),
    );
  }

  void _onResend() {
    context.read<AuthBloc>().add(SubmitEmailEvent(widget.email));
    _codeController.clear();
    _startCooldown();
  }

  Color get _boxBorderColor {
    if (_hasError) return AppColors.destructive;
    if (_codeController.text.length == 6) return AppColors.accent;
    return AppColors.textSecondary;
  }

  @override
  Widget build(BuildContext context) {
    final code = _codeController.text;
    final borderColor = _boxBorderColor;

    final screenSize = MediaQuery.of(context).size;

    return Scaffold(
      resizeToAvoidBottomInset: true,
      body: Stack(
        children: [
          // Whirlwind background — absolute center
          Positioned(
            left: (screenSize.width - 922) / 2,
            top: (screenSize.height - 920) / 2,
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

          // Content
          SafeArea(
            child: Stack(
              children: [
                // Back button
            Positioned(
              top: 8,
              left: 4,
              child: IconButton(
                icon: const Icon(
                  Icons.arrow_back_ios_new,
                  color: AppColors.textPrimary,
                  size: 20,
                ),
                onPressed: () {
                  context.read<AuthBloc>().add(ResetAuthEvent());
                },
              ),
            ),

            // Centered content
            Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.screenHorizontal,
                ),
                child: BlocConsumer<AuthBloc, AuthState>(
                  listener: (context, state) {
                    if (state is AuthError) {
                      setState(() => _hasError = true);
                    }
                  },
                  builder: (context, state) {
                    final isLoading = state is AuthLoading;
                    final errorMessage =
                        state is AuthError ? state.message : null;

                    return Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          'Enter verification code',
                          style: AppTypography.headline.copyWith(
                            color: AppColors.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Code sent to ${widget.email}',
                          style: AppTypography.caption.copyWith(
                            color: AppColors.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 32),

                        // 6 digit boxes with transparent TextField
                        SizedBox(
                          height: 72,
                          child: Stack(
                            children: [
                              Row(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: List.generate(6, (i) {
                                  return Container(
                                    width: 48,
                                    height: 72,
                                    margin: EdgeInsets.only(
                                      left: i > 0 ? 8 : 0,
                                    ),
                                    decoration: BoxDecoration(
                                      color: AppColors.avatarBg,
                                      borderRadius: BorderRadius.circular(12),
                                      border: Border.all(color: borderColor),
                                    ),
                                    alignment: Alignment.center,
                                    child: Text(
                                      i < code.length ? code[i] : '',
                                      style: AppTypography.headline.copyWith(
                                        color: AppColors.textPrimary,
                                      ),
                                    ),
                                  );
                                }),
                              ),
                              Positioned.fill(
                                child: TextField(
                                  controller: _codeController,
                                  focusNode: _focusNode,
                                  keyboardType: TextInputType.number,
                                  maxLength: 6,
                                  showCursor: false,
                                  style: const TextStyle(
                                    color: Colors.transparent,
                                  ),
                                  inputFormatters: [
                                    FilteringTextInputFormatter.digitsOnly,
                                  ],
                                  textInputAction: TextInputAction.done,
                                  onSubmitted: (_) => _onVerify(),
                                  decoration: const InputDecoration(
                                    counterText: '',
                                    border: InputBorder.none,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),

                        const SizedBox(height: 24),
                        SizedBox(
                          width: double.infinity,
                          height: 60,
                          child: FilledButton(
                            onPressed: isLoading ? null : _onVerify,
                            style: FilledButton.styleFrom(
                              backgroundColor: AppColors.accent,
                              disabledBackgroundColor: AppColors.accent,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                            child: isLoading
                                ? const SizedBox(
                                    width: 24,
                                    height: 24,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: AppColors.background,
                                    ),
                                  )
                                : Text(
                                    'Verify',
                                    style: AppTypography.body.copyWith(
                                      color: AppColors.background,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                          ),
                        ),
                        const SizedBox(height: 16),
                        if (_cooldownSeconds > 0)
                          Text(
                            'You can request a new code in ${_cooldownSeconds}s',
                            style: AppTypography.caption.copyWith(
                              color: AppColors.textSecondary,
                            ),
                          )
                        else
                          TextButton(
                            onPressed: isLoading ? null : _onResend,
                            child: Text(
                              'Resend code',
                              style: AppTypography.caption.copyWith(
                                color: AppColors.textPrimary,
                              ),
                            ),
                          ),
                        if (errorMessage != null) ...[
                          const SizedBox(height: 16),
                          Text(
                            errorMessage,
                            style: AppTypography.caption.copyWith(
                              color: AppColors.destructive,
                            ),
                          ),
                        ],
                      ],
                    );
                  },
                ),
              ),
            ),
          ],
        ),
          ),
        ],
      ),
    );
  }
}
