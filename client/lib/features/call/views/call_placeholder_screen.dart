import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:livekit_client/livekit_client.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/call_colors.dart';
import '../models/call_session.dart';

/// Minimal in-call screen for Story 4.5.
///
/// Joins the LiveKit room and publishes the mic so the server-spawned
/// Pipecat bot can hear the user and the user can hear Tina's "speak first"
/// greeting (AC3). The Rive character canvas, viseme lip sync, checkpoint
/// HUD, and full hang-up UX belong to Epic 6 (Story 6.2+) — this screen is
/// a placeholder that intentionally does not render them.
class CallPlaceholderScreen extends StatefulWidget {
  final CallSession session;

  const CallPlaceholderScreen({super.key, required this.session});

  @override
  State<CallPlaceholderScreen> createState() => _CallPlaceholderScreenState();
}

class _CallPlaceholderScreenState extends State<CallPlaceholderScreen>
    with SingleTickerProviderStateMixin {
  Room? _room;
  String? _errorMessage;
  late final AnimationController _dotsController;

  @override
  void initState() {
    super.initState();
    _dotsController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
    _connect();
  }

  Future<void> _connect() async {
    try {
      final room = Room();
      await room.connect(widget.session.livekitUrl, widget.session.token);
      await room.localParticipant?.setMicrophoneEnabled(true);
      if (!mounted) {
        await room.disconnect();
        return;
      }
      setState(() {
        _room = room;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage = "Couldn't connect to the call.";
      });
    }
  }

  Future<void> _hangUp() async {
    await _room?.disconnect();
    _room = null;
    if (!mounted) return;
    context.go(AppRoutes.root);
  }

  @override
  void dispose() {
    _dotsController.dispose();
    unawaited(_room?.disconnect());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Column(
          children: [
            const Spacer(),
            const Text(
              'Connecting to Tina…',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: 'Inter',
                fontSize: 24,
                fontWeight: FontWeight.w400,
                color: CallColors.secondary,
              ),
            ),
            const SizedBox(height: 24),
            if (_errorMessage != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Text(
                  _errorMessage!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontFamily: 'Inter',
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                    color: AppColors.destructive,
                  ),
                ),
              )
            else
              AnimatedBuilder(
                animation: _dotsController,
                builder: (context, _) => _buildPulsingDots(_dotsController.value),
              ),
            const Spacer(),
            _buildHangUpButton(),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }

  Widget _buildPulsingDots(double progress) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List<Widget>.generate(3, (i) {
        final double offset = i / 3.0;
        final double local = ((progress + (1.0 - offset)) % 1.0);
        final double scale = 0.7 + 0.3 * (1.0 - (local - 0.5).abs() * 2.0).clamp(0.0, 1.0);
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

  Widget _buildHangUpButton() {
    return Semantics(
      button: true,
      label: 'Hang up',
      child: Material(
        color: CallColors.decline,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: _hangUp,
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
