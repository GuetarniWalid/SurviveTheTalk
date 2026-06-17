import 'package:in_app_purchase/in_app_purchase.dart';

sealed class SubscriptionEvent {
  const SubscriptionEvent();
}

/// User tapped the subscribe CTA.
final class SubscribePressed extends SubscriptionEvent {
  const SubscribePressed();
}

/// User tapped the "Restore purchases" affordance (Story 8.2, D2 — Apple
/// requires a visible restore for auto-renewable subs). A genuine restored
/// entitlement flows back through `purchaseStream` like a fresh purchase; an
/// empty restore is surfaced via [RestoreLapsed] so it never fakes success.
final class RestorePressed extends SubscriptionEvent {
  const RestorePressed();
}

/// Internal — the restore window elapsed with no restored entitlement landing
/// on the stream (Story 8.2, F16). Distinguishes a real restore (→ verify →
/// paid) from an empty one (→ neutral "Nothing to restore.").
final class RestoreLapsed extends SubscriptionEvent {
  const RestoreLapsed();
}

/// Internal — a batch of purchase updates arrived on the plugin stream. Driven
/// by the bloc's own `purchaseStream` subscription, not by the UI.
final class PurchaseUpdated extends SubscriptionEvent {
  final List<PurchaseDetails> purchases;
  const PurchaseUpdated(this.purchases);
}

/// Internal — the native-sheet recovery window elapsed with no terminal
/// purchase update (so the UI can recover; paywall-screen-design.md:401).
final class PurchaseTimedOut extends SubscriptionEvent {
  const PurchaseTimedOut();
}
