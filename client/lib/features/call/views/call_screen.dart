import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:livekit_client/livekit_client.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/call_colors.dart';
import '../../scenarios/models/scenario.dart';
import '../bloc/call_bloc.dart';
import '../bloc/call_event.dart';
import '../bloc/call_state.dart';
import '../models/call_session.dart';

/// Full-screen call surface for Story 6.1.
///
/// Detached from `go_router` (pushed via `Navigator.of(context, rootNavigator:
/// true)`) per ADR 003 §Tier 1. The Rive character canvas, viseme lip-sync,
/// and CheckpointStepper land in Story 6.2+; until then `CallConnected`
/// renders only a hang-up button on a black scaffold.
class CallScreen extends StatefulWidget {
  final Scenario scenario;
  final CallSession callSession;

  /// Optional injection seam for tests. Production callers pass nothing —
  /// `CallScreen` constructs `Room()` once in `initState` and forwards it to
  /// `CallBloc`. Tests pass a `MockRoom`.
  final Room? room;

  const CallScreen({
    super.key,
    required this.scenario,
    required this.callSession,
    this.room,
  });

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen>
    with SingleTickerProviderStateMixin {
  late final Room _room;
  late final AnimationController _dotsController;

  /// Set true once `BlocProvider<CallBloc>` runs `create` — the bloc takes
  /// ownership of the Room from that point and `close()` will disconnect.
  /// While false (e.g. an exception aborted the route before the first
  /// `build()`), `dispose` is the only place the Room can be cleaned up.
  bool _blocCreated = false;

  @override
  void initState() {
    super.initState();
    _room = widget.room ?? Room();
    _dotsController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _dotsController.dispose();
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
    return PopScope(
      canPop: false,
      child: BlocProvider<CallBloc>(
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
            if (state is CallEnded) {
              Navigator.of(context).maybePop();
            }
          },
          builder: (context, state) {
            return Scaffold(
              backgroundColor: AppColors.background,
              body: SafeArea(child: _buildBody(context, state)),
            );
          },
        ),
      ),
    );
  }

  Widget _buildBody(BuildContext context, CallState state) {
    return Column(
      children: [
        const Spacer(),
        if (state is CallConnecting) ..._buildConnecting(),
        if (state is CallError) _buildError(state.reason),
        const Spacer(),
        _buildHangUpButton(context),
        const SizedBox(height: 40),
      ],
    );
  }

  List<Widget> _buildConnecting() {
    return <Widget>[
      const Text(
        'Connecting...',
        textAlign: TextAlign.center,
        style: TextStyle(
          fontFamily: 'Inter',
          fontSize: 24,
          fontWeight: FontWeight.w400,
          color: CallColors.secondary,
        ),
      ),
      const SizedBox(height: 24),
      AnimatedBuilder(
        animation: _dotsController,
        builder: (context, _) => _buildPulsingDots(_dotsController.value),
      ),
    ];
  }

  Widget _buildError(String reason) {
    return Padding(
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
    );
  }

  Widget _buildPulsingDots(double progress) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List<Widget>.generate(3, (i) {
        final double offset = i / 3.0;
        final double local = (progress + (1.0 - offset)) % 1.0;
        final double scale =
            0.7 + 0.3 * (1.0 - (local - 0.5).abs() * 2.0).clamp(0.0, 1.0);
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4),
          child: Transform.scale(
            scale: scale,
            child: Container(
              width: 10,
              height: 10,
              decoration: const BoxDecoration(
                color: CallColors.secondary,
                shape: BoxShape.circle,
              ),
            ),
          ),
        );
      }),
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
