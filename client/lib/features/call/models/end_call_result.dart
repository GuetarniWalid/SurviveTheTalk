// Story 6.5 Déviation #27 — parsed response from `POST /calls/{id}/end`.
//
// The bloc / retry-service use this to decide whether to surface a
// post-call notice screen ("on te l'offre, X cadeaux restants" /
// "ça compte, tu as utilisé tes cadeaux") on the user-visible exit.
// Constructed from the `data` block of the standard `{data, meta}`
// envelope.

class EndCallResult {
  /// True iff the server flipped the row to `'failed'` AND set
  /// `gifted=1` (one of the daily 3 was consumed). The cap counter
  /// query excludes `'failed'` rows so the user's quota is untouched.
  final bool wasGifted;

  /// Server-authoritative count of remaining gifts in the user's
  /// daily allowance, AFTER this call's accounting. Drives the
  /// "il te reste X cadeaux" copy on the notice screen. Clamped to
  /// >= 0 by the server.
  final int giftsRemainingToday;

  /// Computed duration the server persisted. Reflects the first /end's
  /// "now" (idempotent re-calls return the same value). Useful for
  /// debrief, analytics, the post-call screen's "tu as parlé X
  /// secondes" copy.
  final int durationSec;

  const EndCallResult({
    required this.wasGifted,
    required this.giftsRemainingToday,
    required this.durationSec,
  });

  factory EndCallResult.fromJson(Map<String, dynamic> json) {
    return EndCallResult(
      wasGifted: json['was_gifted'] as bool? ?? false,
      // Server uses `gifts_remaining_today` clamped >= 0; client mirrors
      // the clamp as a belt-and-braces against a future server bug.
      giftsRemainingToday:
          (json['gifts_remaining_today'] as int? ?? 3).clamp(0, 3),
      durationSec: json['duration_sec'] as int? ?? 0,
    );
  }
}
