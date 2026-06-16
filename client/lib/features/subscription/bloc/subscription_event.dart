import 'package:in_app_purchase/in_app_purchase.dart';

sealed class SubscriptionEvent {
  const SubscriptionEvent();
}

/// User tapped the subscribe CTA.
final class SubscribePressed extends SubscriptionEvent {
  const SubscribePressed();
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
