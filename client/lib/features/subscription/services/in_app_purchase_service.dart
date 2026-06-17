import 'package:in_app_purchase/in_app_purchase.dart';

/// The single weekly-subscription product id (Story 8.1, D4). MUST equal the
/// server constant `IAP_PRODUCT_ID` and the products created in App Store
/// Connect + Google Play Console. Lowercase + store-portable.
const String kIapWeeklyProductId = 'stt_weekly_199';

/// Thin, mockable wrapper over the `in_app_purchase` plugin — same
/// wrapper-for-testability convention as `PermissionService` /
/// `ConnectivityService`. Keeps the plugin singleton out of the bloc so tests
/// inject a `Mock implements InAppPurchaseService`.
class InAppPurchaseService {
  final InAppPurchase _iap;

  InAppPurchaseService({InAppPurchase? inAppPurchase})
    : _iap = inAppPurchase ?? InAppPurchase.instance;

  /// Real-time purchase updates (purchased / restored / error / canceled /
  /// pending). The plugin also re-delivers unfinished purchases here.
  Stream<List<PurchaseDetails>> get purchaseStream => _iap.purchaseStream;

  /// Whether the underlying store is reachable / available on this device.
  Future<bool> isAvailable() => _iap.isAvailable();

  /// Load a single product by id, or `null` if the store didn't return it
  /// (unknown id, not yet approved, store unavailable).
  Future<ProductDetails?> loadProduct(String productId) async {
    final response = await _iap.queryProductDetails(<String>{productId});
    if (response.productDetails.isEmpty) return null;
    return response.productDetails.first;
  }

  /// Trigger the native payment sheet for a subscription. Subscriptions go
  /// through the non-consumable buy API. The result of the purchase arrives
  /// asynchronously on [purchaseStream]; the returned bool only reports
  /// whether the request was initially sent.
  Future<bool> buy(ProductDetails product) {
    return _iap.buyNonConsumable(
      purchaseParam: PurchaseParam(productDetails: product),
    );
  }

  /// Finish a purchase (StoreKit / Play Billing require this for every
  /// purchased / restored transaction, else it is re-delivered every launch).
  Future<void> complete(PurchaseDetails purchase) =>
      _iap.completePurchase(purchase);

  /// Ask the store to re-deliver the user's existing entitlements. Any restored
  /// transaction lands on [purchaseStream] with `PurchaseStatus.restored` (so it
  /// flows through the SAME verify-then-flip path as a fresh purchase); an empty
  /// restore delivers nothing. Story 8.2 (D2) — Apple App Review REQUIRES a
  /// visible Restore affordance for auto-renewable subscriptions.
  Future<void> restore() => _iap.restorePurchases();
}
