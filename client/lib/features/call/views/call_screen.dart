import 'dart:async';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:livekit_client/livekit_client.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/call_colors.dart';
import '../../scenarios/character_catalog.dart';
import '../../scenarios/models/character_identity.dart';
import '../../scenarios/models/scenario.dart';
import '../bloc/call_bloc.dart';
import '../bloc/call_event.dart';
import '../bloc/call_state.dart';
import '../models/call_session.dart';
import 'scenario_backgrounds.dart';
import 'widgets/animated_calling_text.dart';
import 'widgets/character_avatar.dart';
import 'widgets/rive_character_canvas.dart';

// Layout constants — mirrored from `IncomingCallScreen` so the outgoing
// dial state matches the onboarding incoming-call screen visually (per
// Walid feedback, Story 6.2 redesign of `CallConnecting`).
const double _kCallNameSize = 38.0;
const double _kCallRoleSize = 16.0;
const double _kCallStatusSize = 24.0;
const double _kAvatarDiameter = 166.0;
const double _kScreenHorizontalPadding = 30.0;
const double _kScreenTopPadding = 60.0;
const double _kScreenBottomPadding = 70.0;

/// Full-screen call surface for Story 6.1 + Story 6.2.
///
/// Detached from `go_router` (pushed via `Navigator.of(context, rootNavigator:
/// true)`) per ADR 003 §Tier 1. Story 6.1 owns the call lifecycle plumbing
/// (Room → CallBloc → root-Navigator pop). Story 6.2 layers the in-call
/// render on top of `CallConnected`: scenario background → gaussian blur →
/// full-body Rive canvas with the in-canvas hang-up button. Visemes and
/// emotion data-channel wiring land in Story 6.3.
///
/// `CallConnecting` clones the `IncomingCallScreen` layout (name + role +
/// circular avatar + "Calling..." dots + single hang-up button) so the
/// onboarding incoming-call surface and the outgoing dial surface share
/// the same visual language.
class CallScreen extends StatefulWidget {
  final Scenario scenario;
  final CallSession callSession;

  /// Optional injection seam for tests. Production callers pass nothing —
  /// `CallScreen` constructs `Room()` once in `initState` and forwards it to
  /// `CallBloc`. Tests pass a `MockRoom`.
  final Room? room;

  /// Test seam (Story 6.2 AC9). When non-null, locks `_canvasInFallback`
  /// to this value and ignores the `RiveCharacterCanvas.onFallback`
  /// callback. Production callers pass nothing — the real fallback signal
  /// from the Rive canvas drives the UI. Tests use `false` to assert the
  /// "Rive working" branch (no Flutter hang-up button) and `true` to
  /// assert the fallback branch (Flutter hang-up button rendered).
  @visibleForTesting
  final bool? debugCanvasFallback;

  const CallScreen({
    super.key,
    required this.scenario,
    required this.callSession,
    this.room,
    this.debugCanvasFallback,
  });

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  late final Room _room;

  /// Set true once `BlocProvider<CallBloc>` runs `create` — the bloc takes
  /// ownership of the Room from that point and `close()` will disconnect.
  /// While false (e.g. an exception aborted the route before the first
  /// `build()`), `dispose` is the only place the Room can be cleaned up.
  bool _blocCreated = false;

  /// Mirrors `RiveCharacterCanvas`'s fallback signal so we know whether to
  /// overlay the Flutter `_buildHangUpButton` (AC7). True only when Rive
  /// native is unavailable — production happy path keeps this false.
  bool _canvasInFallback = false;

  bool _backgroundPrecached = false;

  /// Idempotency guard — `BlocConsumer.listener` may fire on the same
  /// `CallEnded` more than once (e.g. const-equality dedup gotcha #4 + a
  /// transient rebuild). Track that the post-frame `maybePop` is already
  /// scheduled so we never queue two pops.
  bool _popScheduled = false;

  @override
  void initState() {
    super.initState();
    _room = widget.room ?? Room();
    _canvasInFallback = widget.debugCanvasFallback ?? false;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Saves the first-frame disk read on the CallConnected layer-1 image
    // (AC8 recommendation). Runs once.
    if (!_backgroundPrecached) {
      _backgroundPrecached = true;
      final path = kScenarioBackgrounds[widget.scenario.riveCharacter];
      if (path != null) {
        precacheImage(AssetImage(path), context);
      }
    }
  }

  @override
  void dispose() {
    if (!_blocCreated) {
      // Safety net: the bloc never ran, so `CallBloc.close()` will not.
      // Drop the Room ourselves so we don't leak background timers (TTLMap
      // cleanup, SignalClient connect timer) or a half-open WebRTC peer.
      unawaited(_room.disconnect());
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return BlocProvider<CallBloc>(
      create: (_) {
        _blocCreated = true;
        return CallBloc(
          session: widget.callSession,
          scenario: widget.scenario,
          room: _room,
        )..add(const CallStarted());
      },
      child: BlocConsumer<CallBloc, CallState>(
        listenWhen: (previous, current) => current is CallEnded,
        listener: (context, state) {
          if (state is! CallEnded) return;
          if (_popScheduled) return;
          _popScheduled = true;
          // Defer to post-frame so the builder rebuilds with `canPop:
          // true` BEFORE the pop is attempted — otherwise the still-
          // mounted `PopScope(canPop: false)` of the previous frame
          // intercepts the maybePop and the screen stays stuck on a
          // CallEnded state with the fallback Scaffold visible.
          //
          // `rootNavigator: true` mirrors the push contract documented on
          // the `CallScreen` dartdoc (ADR 003 §Tier 1) so the pop targets
          // the same Navigator the route was pushed onto, even when the
          // listener's BuildContext could resolve to a nested navigator.
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (context.mounted) {
              Navigator.of(context, rootNavigator: true).maybePop();
            }
          });
        },
        builder: (context, state) {
          // PopScope blocks system back-press during connecting/connected
          // /errored (ADR 003 §Tier 1) but MUST allow pop once the call
          // has ended, otherwise the listener's programmatic
          // Navigator.maybePop() is also blocked. CallError is
          // intentionally treated like an in-call state — the user must
          // confirm the exit via the on-screen "End call" button so a
          // stray back-gesture doesn't drop them out of an error they
          // haven't seen yet.
          return PopScope(
            canPop: state is CallEnded,
            child: Scaffold(
              backgroundColor: AppColors.background,
              body: _buildBody(context, state),
            ),
          );
        },
      ),
    );
  }

  Widget _buildBody(BuildContext context, CallState state) {
    if (state is CallConnected) {
      return _buildConnected(context);
    }
    if (state is CallError) {
      return _buildErrorBody(context, state.reason);
    }
    // CallConnecting (initial) and CallEnded (transient terminal state
    // before pop) both fall through to the dial surface. CallEnded only
    // renders for a single frame before the post-frame `maybePop` runs.
    return _buildDialSurface(context);
  }

  /// Outgoing dial surface — clones `IncomingCallScreen`'s visual structure
  /// (name + role on top, circular avatar at center, "Calling..." dots,
  /// single hang-up button at the bottom). Reads identity from
  /// `kCharacterCatalog`.
  ///
  /// Wrapped in `LayoutBuilder + SingleChildScrollView + IntrinsicHeight`
  /// (Story 5.4 pattern) so the natural Spacer-driven layout fills tall
  /// viewports while gracefully scrolling on small phones at large text
  /// scalers (320×480 + 1.5× safety net).
  Widget _buildDialSurface(BuildContext context) {
    final identity = kCharacterCatalog[widget.scenario.riveCharacter];
    assert(
      identity != null,
      'No character identity registered for riveCharacter '
      '"${widget.scenario.riveCharacter}". Add an entry to '
      'kCharacterCatalog.',
    );
    return SafeArea(
      child: LayoutBuilder(
        builder: (context, constraints) {
          return SingleChildScrollView(
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: IntrinsicHeight(
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
                      _buildIdentityHeader(identity),
                      const Spacer(),
                      _buildAvatarBlock(),
                      const Spacer(),
                      Center(child: _buildHangUpButton(context)),
                    ],
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildIdentityHeader(CharacterIdentity? identity) {
    if (identity == null) {
      return const SizedBox.shrink();
    }
    return Column(
      children: [
        Text(
          identity.name,
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
          identity.role,
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
    return Column(
      children: [
        CharacterAvatar(
          character: widget.scenario.riveCharacter,
          size: _kAvatarDiameter,
        ),
        const SizedBox(height: 12),
        const Padding(
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

  Widget _buildErrorBody(BuildContext context, String reason) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          _kScreenHorizontalPadding,
          _kScreenTopPadding,
          _kScreenHorizontalPadding,
          _kScreenBottomPadding,
        ),
        child: Column(
          children: [
            const Spacer(),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 32),
              child: Text(
                reason,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'Inter',
                  fontSize: 16,
                  fontWeight: FontWeight.w500,
                  color: AppColors.destructive,
                ),
              ),
            ),
            const Spacer(),
            Center(child: _buildHangUpButton(context)),
          ],
        ),
      ),
    );
  }

  Widget _buildConnected(BuildContext context) {
    final backgroundPath =
        kScenarioBackgrounds[widget.scenario.riveCharacter];
    assert(
      backgroundPath != null,
      'No scenario background registered for riveCharacter '
      '"${widget.scenario.riveCharacter}". Add an entry to '
      'kScenarioBackgrounds or update the scenario.',
    );
    return Stack(
      fit: StackFit.expand,
      children: [
        // Layer 1 — scenario background image.
        if (backgroundPath != null)
          Image.asset(
            backgroundPath,
            fit: BoxFit.cover,
            errorBuilder: (_, _, _) =>
                Container(color: AppColors.background),
          )
        else
          Container(color: AppColors.background),
        // Layer 2 — gaussian blur. SizedBox.expand gives BackdropFilter a
        // child to clip against; without one the filter is a no-op. Sigma 3
        // is intentional (depth-of-field), see project memory
        // `project_call_screen_blur_sigma_3.md`.
        BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 3, sigmaY: 3),
          child: const SizedBox.expand(),
        ),
        // Layer 3 — full-screen Rive canvas (character + in-canvas hang-up
        // button). The Semantics wrapper applies to ONLY this layer (per
        // AC6: "wired on the Rive canvas region for screen readers"),
        // not the entire Stack. On fallback it renders a solid
        // AppColors.background and we overlay the Flutter hang-up button
        // so the user retains an exit affordance.
        Positioned.fill(
          child: Semantics(
            button: true,
            label: 'End call',
            child: RiveCharacterCanvas(
              character: widget.scenario.riveCharacter,
              onHangUp: () =>
                  context.read<CallBloc>().add(const HangUpPressed()),
              onFallback: () {
                if (widget.debugCanvasFallback != null) return;
                if (mounted) setState(() => _canvasInFallback = true);
              },
            ),
          ),
        ),
        if (_canvasInFallback)
          Positioned.fill(
            child: SafeArea(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 40),
                  child: _buildHangUpButton(context),
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildHangUpButton(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Hang up',
      child: Material(
        color: CallColors.decline,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: () => context.read<CallBloc>().add(const HangUpPressed()),
          child: const SizedBox(
            width: 60,
            height: 60,
            child: Icon(
              Icons.call_end,
              color: AppColors.textPrimary,
              size: 28,
            ),
          ),
        ),
      ),
    );
  }
}
