sealed class SubscriptionState {
  const SubscriptionState();
}

final class SubscriptionInitial extends SubscriptionState {
  const SubscriptionInitial();
}

/// The native payment sheet is in flight (request sent, awaiting the store).
final class SubscriptionLoading extends SubscriptionState {
  const SubscriptionLoading();
}

/// Purchase validated server-side → tier is now paid.
final class SubscriptionPurchased extends SubscriptionState {
  const SubscriptionPurchased();
}

/// The purchase or its validation failed. `code` is a stable identifier
/// (store error code, server error code, `'timeout'`, `'product_unavailable'`,
/// `'verification_failed'`) the UI can key copy on (8.2 owns the real copy).
final class SubscriptionFailed extends SubscriptionState {
  final String code;
  const SubscriptionFailed(this.code);
}

/// The user dismissed the native payment sheet without buying.
final class SubscriptionCancelled extends SubscriptionState {
  const SubscriptionCancelled();
}

/// A "Restore purchases" tap returned no entitlement to restore (Story 8.2,
/// F16). The UI returns to the Default offer with a neutral "Nothing to
/// restore." line — NEVER the "You're in" success state (no false confirmation).
final class SubscriptionRestoreEmpty extends SubscriptionState {
  const SubscriptionRestoreEmpty();
}

/// The store reported the purchase as `pending` — awaiting external approval
/// (StoreKit "Ask to Buy" parental consent, or SCA bank verification). It is
/// NOT a failure and NOT a confirmed purchase: it may resolve to purchased
/// (→ verify) or canceled minutes/hours later, possibly after the sheet has
/// closed (the app-lifetime listener catches that). Story 8.3 (F17) — the
/// paywall renders this dismissible with "Waiting for approval. You can close
/// this." instead of spinning on Loading forever.
final class SubscriptionPendingApproval extends SubscriptionState {
  const SubscriptionPendingApproval();
}
