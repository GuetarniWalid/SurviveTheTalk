// Story 6.5 Déviation #27 — post-call notice screen shown AFTER the
// `CallScreen` pops but BEFORE the user lands back on `/scenarios`.
//
// Triggered by the `CallScreen` listener on selected `CallEnded`
// variants:
//   - `endReason='network_lost'` (any gift outcome) — the user needs
//     to understand they were sent back because of connectivity, not
//     a bug. The message is reassuring: "this won't count against
//     your daily limit".
//   - `endReason='character_hung_up'` or `'inappropriate_content'`
//     AND `wasGifted=true` — the character cut the call at <30 s and
//     the server applied a "free gift" so the call doesn't count.
//
// All other paths (user_hung_up, character_hung_up >= 30 s, survived)
// skip this screen and pop straight back to the scenario list — those
// don't need a special explanation (the user owns the choice for the
// first; the future Story 7.2 Call-Ended overlay will own the rest).
//
// `wasGifted == null` handling — on the `network_lost` path the POST
// almost always fast-fails (the radio is off when the disconnect is
// detected) and gets queued, so the bloc emits `CallEnded` BEFORE the
// server has confirmed the gift. We display the reassuring "gifted"
// copy unconditionally on network_lost because the rule is permissive
// (any duration is eligible, up to 3/day) — the optimistic case is
// right 99 %+ of the time. A user who's already used their 3 gifts
// today will see the same reassuring message on a 4th drop; that's a
// small lie at the edge, but they're already aware they hit the limit
// (they paid attention to the previous notices). Acceptable trade-off
// for the much more common case where they get reassurance fast.

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/widgets/empathetic_error_screen.dart';

class CallEndedNoticeScreen extends StatelessWidget {
  /// Canonical exit reason from the bloc's `CallEnded.endReason` —
  /// one of `network_lost`, `character_hung_up`,
  /// `inappropriate_content`. Drives both the title and body copy.
  final String endReason;

  /// Server-confirmed gift outcome. `null` when the POST hadn't
  /// resolved by the time `CallEnded` was emitted (queued retry path).
  /// On `network_lost` we treat null as optimistic-gifted.
  final bool? wasGifted;

  /// Server-authoritative count of gifts left AFTER this call. Used
  /// to fill the "X free calls left today" line when known. Falls
  /// back to a generic line when `null`.
  final int? giftsRemainingToday;

  const CallEndedNoticeScreen({
    super.key,
    required this.endReason,
    this.wasGifted,
    this.giftsRemainingToday,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: EmpatheticErrorScreen(
        code: _codeFor(endReason),
        onRetry: () => Navigator.of(context).maybePop(),
        // Story 6.11 — the noisy-environment variant's CTA is a plain
        // "Got it" acknowledgement (close), not a "retry"; the other
        // variants keep "Back to scenarios".
        retryLabel: endReason == 'noisy_environment'
            ? 'Got it'
            : 'Back to scenarios',
        semanticsLabel: endReason == 'noisy_environment' ? 'Got it' : 'Back',
        titleOverride: _titleFor(endReason),
        bodyOverride: _bodyFor(
          endReason: endReason,
          wasGifted: wasGifted,
          giftsRemainingToday: giftsRemainingToday,
        ),
      ),
    );
  }

  /// Pick the `EmpatheticErrorScreen` code for the icon + brand
  /// styling. `NETWORK_ERROR` ships with `cloud_off_outlined` — right
  /// visual for a connection loss. Other reasons fall through to
  /// `UNKNOWN_ERROR` (neutral `error_outline` icon).
  String _codeFor(String reason) {
    if (reason == 'network_lost') return 'NETWORK_ERROR';
    // Story 6.11 — drives the `Icons.volume_off` glyph (matches the
    // in-call banner).
    if (reason == 'noisy_environment') return 'NOISY_ENVIRONMENT';
    return 'UNKNOWN_ERROR';
  }

  /// Replace the code's default title with a context-specific one.
  String _titleFor(String reason) {
    if (reason == 'network_lost') return 'Connection lost.';
    if (reason == 'noisy_environment') return 'Background voice was too loud';
    return 'Too short to count.';
  }

  String _bodyFor({
    required String endReason,
    required bool? wasGifted,
    required int? giftsRemainingToday,
  }) {
    // Story 6.11 — parasitic-voice cut. Always gifted (no-quota-burn
    // path); the copy reassures + nudges toward a quieter spot/earphones.
    if (endReason == 'noisy_environment') {
      return "We couldn't hear you clearly. Try a quieter spot or use "
          "earphones — and this call doesn't count toward your daily limit.";
    }
    if (endReason == 'network_lost') {
      // Quota exhausted: server confirmed `was_gifted=false` AND we
      // have a number to show. Honest about the cost so the user
      // isn't surprised when they next check their cap.
      if (wasGifted == false && giftsRemainingToday == 0) {
        return "You've already used your 3 free 'oops' calls today, "
            'so this one counted against your daily limit. Tomorrow '
            'you get a fresh batch.';
      }
      // Optimistic gifted (server confirmed OR null because POST
      // queued). Same reassuring copy in both cases — almost always
      // right.
      final tail = giftsRemainingToday != null
          ? " You've got $giftsRemainingToday free 'oops' calls left "
                'today.'
          : '';
      return "Don't worry — this one's on us, it doesn't count against "
          'your daily limit.$tail';
    }
    // character_hung_up / inappropriate_content gifted path. The
    // non-gifted branch on these reasons doesn't show this screen at
    // all (CallScreen routes straight to /scenarios).
    final tail = giftsRemainingToday != null
        ? " You've got $giftsRemainingToday free 'oops' calls left today."
        : '';
    return "That call was too short to be useful, so we're not "
        'counting it against your daily limit.$tail';
  }
}
