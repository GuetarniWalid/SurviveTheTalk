/// Parsed `data` block of `GET /user/profile` (Story 8.3, AC5/D5). The
/// steady-state subscription status the Manage Subscription screen reads —
/// adds `subscriptionExpiresAt` (the renewal/expiry date) that `/scenarios`
/// meta / [CallUsage] never carries. Manual `fromJson` (project convention).
class UserProfile {
  /// `'free'` | `'paid'` (ADR 002 — `'Premium'` is a DISPLAY label only).
  final String tier;

  /// Calls left in the current period (clamped to >= 0; the server clamps too,
  /// this is belt-and-braces against a transient negative).
  final int callsRemaining;

  /// The period cap (free = 3 lifetime, paid = 3/day). Always > 0.
  final int callsPerPeriod;

  /// `'lifetime'` (free) | `'day'` (paid).
  final String period;

  /// Latest valid-purchase expiry, ISO 8601, or null when none on record
  /// (free users, legacy rows). `null` is meaningful — never fabricated.
  final String? subscriptionExpiresAt;

  const UserProfile({
    required this.tier,
    required this.callsRemaining,
    required this.callsPerPeriod,
    required this.period,
    this.subscriptionExpiresAt,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    final callsPerPeriod = json['calls_per_period'] as int;
    if (callsPerPeriod <= 0) {
      throw const FormatException('calls_per_period must be > 0');
    }
    final rawRemaining = json['calls_remaining'] as int;
    return UserProfile(
      tier: json['tier'] as String,
      // Negative clamp (Story 8.3 Task 7) — the screen displays this value, so
      // a transient negative must never render as "-1 calls left".
      callsRemaining: rawRemaining < 0 ? 0 : rawRemaining,
      callsPerPeriod: callsPerPeriod,
      period: json['period'] as String,
      subscriptionExpiresAt: json['subscription_expires_at'] as String?,
    );
  }

  bool get isFree => tier == 'free';
  bool get isPaid => tier == 'paid';
  bool get isLifetimePeriod => period == 'lifetime';
}
