import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/call_colors.dart';
import '../bloc/incoming_call_bloc.dart';
import '../bloc/incoming_call_event.dart';
import '../bloc/incoming_call_state.dart';
import 'tutorial_scenario.dart';
import 'widgets/character_avatar.dart';

// Screen-specific typography — mirrors the native incoming-call visual.
// Not promoted to AppTypography because these sizes exist only on this screen.
const double _kCallNameSize = 38.0;
const double _kCallRoleSize = 16.0;
const double _kCallStatusSize = 24.0;
const double _kCallLabelSize = 14.0;

// Layout constants — sourced from the Figma spec (iPhone 16 — 14, 393×852).
const double _kAvatarDiameter = 166.0;
const double _kButtonDiameter = 60.0;
const double _kScreenHorizontalPadding = 30.0;
const double _kScreenTopPadding = 60.0;
const double _kScreenBottomPadding = 70.0;
const double _kButtonRowHorizontalPadding = 40.0;

class IncomingCallScreen extends StatefulWidget {
  const IncomingCallScreen({super.key});

  @override
  State<IncomingCallScreen> createState() => _IncomingCallScreenState();
}

class _IncomingCallScreenState extends State<IncomingCallScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _fadeController;
  Timer? _announceTimer;
  bool _vibrationStarted = false;

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );

    // Fire vibration + haptic once after first frame. `initState` races the
    // initial build on slow devices, so we defer until the frame lands.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      HapticFeedback.mediumImpact();
      _startVibrationViaBloc(context.read<IncomingCallBloc>());

      _announceTimer = Timer(const Duration(milliseconds: 500), () {
        if (!mounted) return;
        // Deprecated after Flutter 3.35 in favour of a multi-window
        // `sendAnnouncement`; replacement is not yet stable in our SDK
        // floor. Suppress until a Flutter bump lands.
        // ignore: deprecated_member_use
        SemanticsService.announce(
          'Calling ${TutorialScenario.characterName}, '
          '${TutorialScenario.characterRole}. '
          'Double tap Accept to pick up, or Decline to dismiss.',
          TextDirection.ltr,
        );
      });
    });
  }

  void _startVibrationViaBloc(IncomingCallBloc bloc) {
    if (_vibrationStarted) return;
    _vibrationStarted = true;
    bloc.vibrationService.startRingPattern();
  }

  @override
  void dispose() {
    _announceTimer?.cancel();
    _fadeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return BlocListener<IncomingCallBloc, IncomingCallState>(
      listener: (context, state) {
        if (state is IncomingCallConnected) {
          context.go(AppRoutes.call, extra: state.session);
        } else if (state is IncomingCallDeclined ||
            state is IncomingCallError) {
          // Error path mirrors Decline: a failed first call should never
          // strand the user on a vibrating screen with no affordance. Fade
          // out and drop them on the scenario list — the tutorial remains
          // accessible from there.
          _fadeController.forward().whenComplete(() {
            if (!mounted) return;
            context.go(AppRoutes.root);
          });
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
          body: SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                _kScreenHorizontalPadding,
                _kScreenTopPadding,
                _kScreenHorizontalPadding,
                _kScreenBottomPadding,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _buildCharacterIdentity(),
                  const Spacer(),
                  _buildAvatarBlock(),
                  const Spacer(),
                  BlocBuilder<IncomingCallBloc, IncomingCallState>(
                    builder: (context, state) => _buildButtons(state),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCharacterIdentity() {
    return const Column(
      children: [
        Text(
          TutorialScenario.characterName,
          textAlign: TextAlign.center,
          style: TextStyle(
            fontFamily: 'Inter',
            fontSize: _kCallNameSize,
            fontWeight: FontWeight.w400,
            color: AppColors.textPrimary,
            height: 46 / 38,
          ),
        ),
        Text(
          TutorialScenario.characterRole,
          textAlign: TextAlign.center,
          style: TextStyle(
            fontFamily: 'Inter',
            fontSize: _kCallRoleSize,
            fontWeight: FontWeight.w400,
            color: CallColors.secondary,
            height: 19 / 16,
          ),
        ),
      ],
    );
  }

  Widget _buildAvatarBlock() {
    return const Column(
      children: [
        CharacterAvatar(
          character: TutorialScenario.riveCharacter,
          size: _kAvatarDiameter,
        ),
        SizedBox(height: 12),
        Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: _AnimatedCallingText(
            style: TextStyle(
              fontFamily: 'Inter',
              fontSize: _kCallStatusSize,
              fontWeight: FontWeight.w400,
              color: CallColors.secondary,
              height: 29 / 24,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildButtons(IncomingCallState state) {
    final isAccepting = state is IncomingCallAccepting;
    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: _kButtonRowHorizontalPadding,
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Semantics(
            button: true,
            label: 'Decline call',
            child: _CallButton(
              color: CallColors.decline,
              icon: Icons.call_end,
              label: 'Decline',
              onTap: isAccepting
                  ? null
                  : () => context
                      .read<IncomingCallBloc>()
                      .add(const DeclineCallEvent()),
            ),
          ),
          Semantics(
            button: true,
            label: 'Accept call',
            child: _CallButton(
              color: CallColors.accept,
              icon: Icons.call,
              label: isAccepting ? 'Connecting…' : 'Accept',
              loading: isAccepting,
              onTap: isAccepting
                  ? null
                  : () => context
                      .read<IncomingCallBloc>()
                      .add(const AcceptCallEvent()),
            ),
          ),
        ],
      ),
    );
  }
}

class _CallButton extends StatelessWidget {
  final Color color;
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final bool loading;

  const _CallButton({
    required this.color,
    required this.icon,
    required this.label,
    required this.onTap,
    this.loading = false,
  });

  // Lock the button's total column width so the circle stays centered at
  // the same screen-X coordinate regardless of the label. Without this, the
  // Row's `spaceBetween` + a Column sized by intrinsic text width would
  // shift the Accept circle left by ~17px when the label grows from
  // "Accept" (~47px) to "Connecting…" (~95px).
  static const double _kColumnWidth = 100.0;

  @override
  Widget build(BuildContext context) {
    final disabled = onTap == null;
    return SizedBox(
      width: _kColumnWidth,
      child: Opacity(
      opacity: disabled && !loading ? 0.8 : 1.0,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Material(
            color: color,
            shape: const CircleBorder(),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: onTap,
              child: SizedBox(
                width: _kButtonDiameter,
                height: _kButtonDiameter,
                child: Center(
                  child: loading
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: AppColors.textPrimary,
                          ),
                        )
                      : Icon(icon, color: AppColors.textPrimary, size: 28),
                ),
              ),
            ),
          ),
          const SizedBox(height: 10),
          Text(
            label,
            textAlign: TextAlign.center,
            maxLines: 1,
            softWrap: false,
            overflow: TextOverflow.visible,
            style: const TextStyle(
              fontFamily: 'Inter',
              fontSize: _kCallLabelSize,
              fontWeight: FontWeight.w400,
              color: CallColors.secondary,
              height: 17 / 14,
            ),
          ),
        ],
      ),
      ),
    );
  }
}

/// "Calling" followed by three dots that pulse in sequence — classic
/// loader cadence. The text's total width never changes (all three dots
/// are always painted, only their alpha toggles) so the centered text
/// doesn't wobble as the animation cycles.
class _AnimatedCallingText extends StatefulWidget {
  final TextStyle style;

  const _AnimatedCallingText({required this.style});

  @override
  State<_AnimatedCallingText> createState() => _AnimatedCallingTextState();
}

class _AnimatedCallingTextState extends State<_AnimatedCallingText> {
  static const Duration _kDotInterval = Duration(milliseconds: 400);

  Timer? _timer;
  int _dotCount = 0;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(_kDotInterval, (_) {
      if (!mounted) return;
      setState(() {
        _dotCount = (_dotCount + 1) % 4;
      });
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final baseStyle = widget.style;
    final hiddenStyle = baseStyle.copyWith(color: Colors.transparent);
    TextStyle dotStyle(int index) =>
        index <= _dotCount ? baseStyle : hiddenStyle;

    return Text.rich(
      TextSpan(
        style: baseStyle,
        children: [
          const TextSpan(text: 'Calling'),
          TextSpan(text: '.', style: dotStyle(1)),
          TextSpan(text: '.', style: dotStyle(2)),
          TextSpan(text: '.', style: dotStyle(3)),
        ],
      ),
      textAlign: TextAlign.center,
    );
  }
}
