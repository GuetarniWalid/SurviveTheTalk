/// Parsed `data` block of `POST /subscription/verify`. Manual `fromJson`
/// (no codegen — project convention, cf. `call_session.dart`).
class SubscriptionStatus {
  /// `'free'` | `'paid'` — the user's tier AFTER the verify.
  final String tier;

  /// The store product id the server validated against (`stt_weekly_199`).
  final String? productId;

  /// Subscription expiry from the store, ISO 8601, or null when unknown.
  final String? expiresAt;

  /// `'valid'` (confirmed) | `'pending'` (D2 optimistic grant during a store
  /// outage — still re-checked server-side).
  final String status;

  const SubscriptionStatus({
    required this.tier,
    this.productId,
    this.expiresAt,
    required this.status,
  });

  factory SubscriptionStatus.fromJson(Map<String, dynamic> json) {
    return SubscriptionStatus(
      tier: json['tier'] as String,
      productId: json['product_id'] as String?,
      expiresAt: json['expires_at'] as String?,
      status: json['status'] as String,
    );
  }

  bool get isPaid => tier == 'paid';
}
