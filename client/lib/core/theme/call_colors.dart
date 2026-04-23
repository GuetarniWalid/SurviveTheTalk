// Native-phone incoming-call colors.
//
// These tokens are intentionally NOT part of AppColors: the incoming-call
// screen mirrors the system FaceTime/WhatsApp UI, not the SurviveTheTalk
// design system. Keeping them in a separate theme file honours both
// constraints:
//   1. UX design doc lines 527-545 — "scope these as screen-specific".
//   2. theme_tokens_test.dart — "no hex literals outside lib/core/theme/".
//
// Do NOT reuse these anywhere else in the app. Any other screen that needs
// red/green/grey should pull from AppColors (destructive / accent / etc.)
// to preserve the product's visual identity.

import 'package:flutter/painting.dart';

class CallColors {
  const CallColors._();

  /// Native-phone secondary grey — used for role text, "Calling..." label,
  /// and button labels on the incoming-call screen.
  static const Color secondary = Color(0xFFC6C6C8);

  /// Accept button green (matches native FaceTime).
  static const Color accept = Color(0xFF50D95D);

  /// Decline button red (matches native FaceTime).
  static const Color decline = Color(0xFFFD3833);

  /// Circle background behind the character avatar on the incoming-call
  /// screen. Slightly darker than `AppColors.avatarBg` because the native
  /// incoming-call UI uses a deeper grey than the rest of the product.
  static const Color avatarBackground = Color(0xFF38383A);
}
