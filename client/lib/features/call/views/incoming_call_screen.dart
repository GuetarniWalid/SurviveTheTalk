import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/call_colors.dart';
import '../../scenarios/character_catalog.dart';
import '../../scenarios/models/character_identity.dart';
import '../../scenarios/models/scenario.dart';
import '../bloc/incoming_call_bloc.dart';
import '../bloc/incoming_call_event.dart';
import '../bloc/incoming_call_state.dart';
import '../models/call_session.dart';
import 'call_screen.dart';
import 'tutorial_scenario.dart';
import 'widgets/animated_calling_text.dart';
import 'widgets/character_avatar.dart';

/// Builds the in-call surface to push from `IncomingCallConnected`.
/// Defaults to `CallScreen.new`. Tests pass a lightweight stub so we don't
/// build a real LiveKit `Room` (whose internal timers leak across tests).
/// Symmetric with the same-named typedef in `scenario_list_screen.dart`.
typedef CallScreenBuilder =
    Widget Function(Scenario scenario, CallSession session);

Widget _defaultCallScreenBuilder(Scenario scenario, CallSession session) {
  return CallScreen(scenario: scenario, callSession: session);
}

/// Tutorial scenario literal pushed to `CallScreen` from the onboarding
/// path. There is no DB-backed `Scenario` at onboarding time (the user
/// hasn't reached the scenario list yet); Story 6.1 keeps this hardcoded
/// per AC9 Option (a). Story 6.2's character-variant code reads
/// `scenario.riveCharacter` and assumes non-null — this literal is the
/// onboarding answer for that contract.
const Scenario _kTutorialScenario = Scenario(
  id: TutorialScenario.id,
  title: 'The Waiter',
  difficulty: 'easy',
  isFree: true,
  riveCharacter: TutorialScenario.riveCharacter,
  languageFocus: <String>['ordering food'],
  contentWarning: null,
  bestScore: null,
  attempts: 0,
  tagline: '',
);

/// Catalog entry for the onboarding character. `tutorial_scenario_test.dart`
/// guards `riveCharacter` against catalog drift, so the lookup is expected
/// to resolve. The fallback is defensive — a top-level `!` would crash the
/// app at module-load time if the catalog ever drifted, masking the real
/// failure (a blank circle on the onboarding screen is recoverable; a
/// startup crash is not).
final CharacterIdentity _kTutorialIdentity =
    kCharacterCatalog[TutorialScenario.riveCharacter] ??
        const CharacterIdentity(
          name: 'Tina',
          role: 'Waitress',
          imageAsset: 'assets/images/characters/waiter.jpg',
        );

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
  /// Optional injection seam for tests (symmetric with `ScenarioListScreen`).
  /// Production callers omit this — `CallScreen.new` is used. Tests pass a
  /// stub so the listener-driven push doesn't build a real `Room`.
  final CallScreenBuilder? callScreenBuilder;

  const IncomingCallScreen({super.key, this.callScreenBuilder});

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
          'Calling ${_kTutorialIdentity.name}, '
          '${_kTutorialIdentity.role}. '
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
          // Detached from go_router (ADR 003 §Tier 1) — push via root
          // Navigator so PopScope(canPop: false) is arbitrated against
          // the root navigator instead of the GoRouter shell.
          //
          // Awaiting the push lets us route the user OUT of
          // IncomingCallScreen when the call ends — without this, the
          // user pops back to a still-"ringing" Accept/Decline screen
          // with no exit path. `seenFirstCall` is already persisted by
          // the bloc, so the redirect at `/` lands on `/scenarios`.
          () async {
            final builder =
                widget.callScreenBuilder ?? _defaultCallScreenBuilder;
            await Navigator.of(context, rootNavigator: true).push<void>(
              MaterialPageRoute<void>(
                builder: (_) => builder(_kTutorialScenario, state.session),
                fullscreenDialog: true,
              ),
            );
            // `context.mounted` (not the State's `mounted`) is what the
            // analyzer wants here — the listener's BuildContext is not
            // tied to this widget's State. After the push the user is
            // back on IncomingCallScreen; route them out so the call
            // doesn't strand on the "ringing" surface.
            if (!context.mounted) return;
            context.go(AppRoutes.root);
          }();
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
    return Column(
      children: [
        Text(
          _kTutorialIdentity.name,
          textAlign: TextAlign.center,
          style: const TextStyle(
            fontFamily: 'Inter',
            fontSize: _kCallNameSize,
            fontWeight: FontWeight.w400,
            color: AppColors.textPrimary,
            height: 46 / 38,
          ),
        ),
        Text(
          _kTutorialIdentity.role,
          textAlign: TextAlign.center,
          style: const TextStyle(
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
          child: AnimatedCallingText(
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

