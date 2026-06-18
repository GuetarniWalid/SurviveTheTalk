class CallUsage {
  final String tier;
  final int callsRemaining;
  final int callsPerPeriod;
  final String period;

  const CallUsage({
    required this.tier,
    required this.callsRemaining,
    required this.callsPerPeriod,
    required this.period,
  });

  factory CallUsage.fromMeta(Map<String, dynamic> meta) {
    final callsPerPeriod = meta['calls_per_period'] as int;
    // Story 8.3 (Task 7) — guard the period (a 0/negative cap is corrupt) and
    // clamp calls_remaining to >= 0 so a transient negative never surfaces as
    // "-1 calls left" anywhere it's displayed.
    if (callsPerPeriod <= 0) {
      throw const FormatException('calls_per_period must be > 0');
    }
    final rawRemaining = meta['calls_remaining'] as int;
    return CallUsage(
      tier: meta['tier'] as String,
      callsRemaining: rawRemaining < 0 ? 0 : rawRemaining,
      callsPerPeriod: callsPerPeriod,
      period: meta['period'] as String,
    );
  }

  bool get isFree => tier == 'free';
  bool get hasCallsRemaining => callsRemaining > 0;
  bool get isLifetimePeriod => period == 'lifetime';
}
