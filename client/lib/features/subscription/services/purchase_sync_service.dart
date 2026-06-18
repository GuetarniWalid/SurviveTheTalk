import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

import '../repositories/subscription_repository.dart';
import 'in_app_purchase_service.dart';

/// App-lifetime listener on `purchaseStream` (Story 8.3, Task 6 — closes the
/// 8.1 F4-func hole). The paywall's [SubscriptionBloc] only listens while the
/// sheet is open, so a purchase the store re-delivers on NEXT LAUNCH (or an
/// Ask-to-Buy / SCA that resolves after the sheet closed) would never be
/// verified → "charged but tier never flipped". This singleton subscribes for
/// the WHOLE app lifetime and verifies + completes every re-delivered
/// purchased/restored transaction, independent of any open sheet.
///
/// Mirrors the [EndCallRetryService] app-singleton precedent: constructed in
/// `bootstrap()` before `runApp`, provided via `RepositoryProvider.value`.
///
/// Coexists with the paywall bloc's own (sheet-scoped) subscription — both may
/// verify the same transaction, but `POST /subscription/verify` is idempotent
/// (409-guarded server-side) and `complete()` is safe to call once the winner
/// finishes, so a duplicate is harmless (restore semantics, 8.2 F16, preserved).
class PurchaseSyncService {
  final InAppPurchaseService _iapService;
  final SubscriptionRepository _repository;

  StreamSubscription<List<PurchaseDetails>>? _sub;
  final StreamController<void> _entitlementChanged =
      StreamController<void>.broadcast();

  PurchaseSyncService({
    required InAppPurchaseService iapService,
    required SubscriptionRepository repository,
  }) : _iapService = iapService,
       _repository = repository;

  /// Fires after a re-delivered purchase verifies server-side as paid, so the
  /// hub can silently refresh `/scenarios` and re-flow the now-`paid` tier.
  Stream<void> get onEntitlementChanged => _entitlementChanged.stream;

  String get _platform =>
      defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android';

  /// Begin listening for the app's lifetime. Idempotent — a second call no-ops.
  void start() {
    if (_sub != null) return;
    _sub = _iapService.purchaseStream.listen(_onPurchases);
  }

  Future<void> _onPurchases(List<PurchaseDetails> purchases) async {
    for (final purchase in purchases) {
      if (purchase.productID != kIapWeeklyProductId) continue;
      switch (purchase.status) {
        case PurchaseStatus.purchased:
        case PurchaseStatus.restored:
          await _verifyAndComplete(purchase);
        case PurchaseStatus.error:
        case PurchaseStatus.canceled:
          // Finish a terminal-but-unverifiable transaction so the store stops
          // re-delivering it every launch (mirrors the bloc's _safeComplete).
          if (purchase.pendingCompletePurchase) {
            await _safeComplete(purchase);
          }
        case PurchaseStatus.pending:
          // Awaiting external approval — wait for the next delivery.
          break;
      }
    }
  }

  Future<void> _verifyAndComplete(PurchaseDetails purchase) async {
    var flipped = false;
    try {
      final status = await _repository.verifyPurchase(
        platform: _platform,
        productId: kIapWeeklyProductId,
        verificationData: purchase.verificationData.serverVerificationData,
      );
      flipped = status.isPaid;
    } catch (e) {
      // Swallow — the next `purchaseStream` re-delivery retries (the
      // subscription lives for the whole app lifetime).
      debugPrint('PurchaseSyncService: verify failed (will retry on '
          're-delivery): $e');
    } finally {
      if (purchase.pendingCompletePurchase) {
        await _safeComplete(purchase);
      }
    }
    if (flipped && !_entitlementChanged.isClosed) {
      _entitlementChanged.add(null);
    }
  }

  Future<void> _safeComplete(PurchaseDetails purchase) async {
    try {
      await _iapService.complete(purchase);
    } catch (e) {
      debugPrint('PurchaseSyncService: completePurchase failed (will retry on '
          're-delivery): $e');
    }
  }

  Future<void> dispose() async {
    await _sub?.cancel();
    _sub = null;
    await _entitlementChanged.close();
  }
}
