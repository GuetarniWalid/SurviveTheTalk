import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:rive/rive.dart' as rive;

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';
import '../bloc/auth_bloc.dart';
import '../bloc/auth_event.dart';
import '../bloc/auth_state.dart';

class EmailEntryScreen extends StatefulWidget {
  const EmailEntryScreen({super.key});

  @override
  State<EmailEntryScreen> createState() => _EmailEntryScreenState();
}

class _EmailEntryScreenState extends State<EmailEntryScreen> {
  final _emailController = TextEditingController();
  final _focusNode = FocusNode();

  bool _emailValid = false;
  bool _submitAttempted = false;

  bool _serverError = false;

  // Rive state
  rive.FileLoader? _riveLoader;
  rive.ViewModelInstanceBoolean? _wrongMailInput;
  rive.ViewModelInstanceBoolean? _isWritingInput;
  bool _riveFallback = false;

  @override
  void initState() {
    super.initState();
    _emailController.addListener(_onEmailChanged);
    _focusNode.addListener(_onFocusChanged);
    _initRive();
  }

  @override
  void dispose() {
    _emailController.removeListener(_onEmailChanged);
    _focusNode.removeListener(_onFocusChanged);
    _riveLoader?.dispose();
    _emailController.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  Future<void> _initRive() async {
    if (!rive.RiveNative.isInitialized) {
      if (mounted) setState(() => _riveFallback = true);
      return;
    }
    try {
      await rootBundle.load('assets/rive/email_character.riv');
      _riveLoader = rive.FileLoader.fromAsset(
        'assets/rive/email_character.riv',
        riveFactory: rive.Factory.rive,
      );
      if (mounted) setState(() {});
    } catch (_) {
      if (mounted) setState(() => _riveFallback = true);
    }
  }

  void _onRiveLoaded(rive.RiveLoaded state) {
    final viewModel = state.viewModelInstance;
    if (viewModel != null) {
      _wrongMailInput = viewModel.boolean('wrongMail');
      _isWritingInput = viewModel.boolean('isWriting');
      // Sync initial focus state
      _isWritingInput?.value = _focusNode.hasFocus;
    }
  }

  void _onFocusChanged() {
    _isWritingInput?.value = _focusNode.hasFocus;
  }

  void _onEmailChanged() {
    final valid = _emailController.text.trim().contains('@');
    _wrongMailInput?.value = false;
    setState(() {
      _emailValid = valid;
      _submitAttempted = false;
      _serverError = false;
    });
  }

  void _onSubmit() {
    if (!_emailValid) {
      _wrongMailInput?.value = true;
      setState(() {
        _submitAttempted = true;
      });
      return;
    }
    _wrongMailInput?.value = false;
    context.read<AuthBloc>().add(SubmitEmailEvent(_emailController.text.trim()));
  }

  Color get _inputBorderColor {
    if (_serverError) return AppColors.destructive;
    if (_submitAttempted && !_emailValid) return AppColors.destructive;
    if (_emailValid) return AppColors.accent;
    return AppColors.textPrimary;
  }

  Widget _buildCharacter() {
    if (_riveFallback || _riveLoader == null) {
      return const SizedBox.shrink();
    }
    return rive.RiveWidgetBuilder(
      fileLoader: _riveLoader!,
      dataBind: rive.DataBind.auto(),
      onLoaded: _onRiveLoaded,
      builder: (context, state) {
        if (state is rive.RiveLoaded) {
          return rive.RiveWidget(
            controller: state.controller,
            fit: rive.Fit.contain,
          );
        }
        return const SizedBox.shrink();
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final screenSize = MediaQuery.of(context).size;
    final borderColor = _inputBorderColor;

    return Scaffold(
      resizeToAvoidBottomInset: false,
      body: Stack(
        children: [
          // Layer 1: Whirlwind background (19% white tint)
          Positioned(
            left: (screenSize.width - 922) / 2,
            top: screenSize.height * 0.30,
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

          // Layer 2: Content + Character in a single column flow
          Positioned.fill(
            child: SafeArea(
              bottom: false,
              child: Column(
                children: [
                  // Form content (scrollable on small screens)
                  Expanded(
                    flex: 3,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 30),
                      child: SingleChildScrollView(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                        const SizedBox(height: 23),

                        // Title: "Survive\nThe Talk"
                        const Text(
                          'Survive\nThe Talk',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontFamily: 'Frijole',
                            fontSize: 48,
                            fontWeight: FontWeight.w400,
                            color: AppColors.textPrimary,
                            height: 66 / 48,
                          ),
                        ),
                        // 23px Frame 1 bottom padding + 10px gap
                        const SizedBox(height: 33),

                        // Tagline
                        Padding(
                          padding: const EdgeInsets.only(
                            left: 41,
                            right: 41,
                            bottom: 20,
                          ),
                          child: Text(
                            'Speak English.\nFor real this time !',
                            textAlign: TextAlign.center,
                            style: AppTypography.body.copyWith(
                              fontSize: 23,
                              fontWeight: FontWeight.w500,
                              fontStyle: FontStyle.italic,
                              color: Colors.white,
                              height: 1.6,
                            ),
                          ),
                        ),
                        const SizedBox(height: 20),

                        // Form section
                        BlocConsumer<AuthBloc, AuthState>(
                          listener: (context, state) {
                            if (state is AuthError) {
                              _wrongMailInput?.value = true;
                              setState(() => _serverError = true);
                            }
                          },
                          builder: (context, state) {
                            final isLoading = state is AuthLoading;
                            final errorMessage =
                                state is AuthError ? state.message : null;

                            return Padding(
                              padding:
                                  const EdgeInsets.fromLTRB(10, 10, 10, 30),
                              child: Column(
                                crossAxisAlignment:
                                    CrossAxisAlignment.start,
                                children: [
                                  // Label
                                  Padding(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 9,
                                    ),
                                    child: Text(
                                      'Enter your email',
                                      style: AppTypography.label.copyWith(
                                        color: AppColors.textPrimary,
                                        fontWeight: FontWeight.w600,
                                        height: 15 / 12,
                                      ),
                                    ),
                                  ),
                                  const SizedBox(height: 10),

                                  // Email input field
                                  TextField(
                                    controller: _emailController,
                                    focusNode: _focusNode,
                                    keyboardType:
                                        TextInputType.emailAddress,
                                    textInputAction: TextInputAction.done,
                                    onSubmitted: (_) => _onSubmit(),
                                    style: AppTypography.label.copyWith(
                                      color: AppColors.textPrimary,
                                      fontWeight: FontWeight.w400,
                                    ),
                                    decoration: InputDecoration(
                                      hintText: 'name@example.com',
                                      hintStyle:
                                          AppTypography.label.copyWith(
                                        color: AppColors.textSecondary,
                                        fontWeight: FontWeight.w400,
                                      ),
                                      filled: true,
                                      fillColor: AppColors.avatarBg,
                                      contentPadding:
                                          const EdgeInsets.symmetric(
                                        horizontal: 24,
                                        vertical: 20,
                                      ),
                                      enabledBorder: OutlineInputBorder(
                                        borderRadius:
                                            BorderRadius.circular(32),
                                        borderSide: BorderSide(
                                          color: borderColor,
                                        ),
                                      ),
                                      focusedBorder: OutlineInputBorder(
                                        borderRadius:
                                            BorderRadius.circular(32),
                                        borderSide: BorderSide(
                                          color: borderColor,
                                        ),
                                      ),
                                    ),
                                  ),

                                  const SizedBox(height: 28),

                                  // Continue button
                                  SizedBox(
                                    width: double.infinity,
                                    height: 64,
                                    child: FilledButton(
                                      onPressed:
                                          isLoading ? null : _onSubmit,
                                      style: FilledButton.styleFrom(
                                        backgroundColor: AppColors.accent,
                                        disabledBackgroundColor:
                                            AppColors.accent,
                                        shape: RoundedRectangleBorder(
                                          borderRadius:
                                              BorderRadius.circular(32),
                                        ),
                                      ),
                                      child: isLoading
                                          ? const SizedBox(
                                              width: 20,
                                              height: 20,
                                              child:
                                                  CircularProgressIndicator(
                                                strokeWidth: 2,
                                                color:
                                                    AppColors.background,
                                              ),
                                            )
                                          : const Text(
                                              'Continue',
                                              style: TextStyle(
                                                fontFamily: 'Inter',
                                                fontSize: 17,
                                                fontWeight: FontWeight.w700,
                                                color: AppColors.background,
                                              ),
                                            ),
                                    ),
                                  ),

                                  // Error message
                                  if (errorMessage != null) ...[
                                    const SizedBox(height: 10),
                                    Text(
                                      errorMessage,
                                      style:
                                          AppTypography.caption.copyWith(
                                        color: AppColors.destructive,
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            );
                          },
                        ),
                          ],
                        ),
                      ),
                    ),
                  ),

                  // Character: fills remaining space below the form,
                  // clipped at screen bottom on small screens
                  Expanded(
                    flex: 2,
                    child: _buildCharacter(),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
