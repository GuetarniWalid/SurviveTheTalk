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
    return CallUsage(
      tier: meta['tier'] as String,
      callsRemaining: meta['calls_remaining'] as int,
      callsPerPeriod: meta['calls_per_period'] as int,
      period: meta['period'] as String,
    );
  }

  bool get isFree => tier == 'free';
  bool get hasCallsRemaining => callsRemaining > 0;
  bool get isLifetimePeriod => period == 'lifetime';
}
