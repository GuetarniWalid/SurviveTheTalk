import 'dart:async';

import 'package:flutter/material.dart';

/// "Calling" followed by three dots that pulse in sequence — classic
/// loader cadence. The text's total width never changes (all three dots
/// are always painted, only their alpha toggles) so the centered text
/// doesn't wobble as the animation cycles.
///
/// Shared between `IncomingCallScreen` (onboarding incoming call) and
/// `CallScreen.CallConnecting` (outgoing dial state).
class AnimatedCallingText extends StatefulWidget {
  final TextStyle style;

  const AnimatedCallingText({super.key, required this.style});

  @override
  State<AnimatedCallingText> createState() => _AnimatedCallingTextState();
}

class _AnimatedCallingTextState extends State<AnimatedCallingText> {
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
