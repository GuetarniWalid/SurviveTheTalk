import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

import '../../../core/api/api_exception.dart';
import '../repositories/subscription_repository.dart';
import '../services/in_app_purchase_service.dart';
import 'subscription_event.dart';
import 'subscription_state.dart';

/// Drives the purchase flow: load product → buy → listen for the store's
/// terminal update → verify server-side → flip tier.
///
/// The purchase stream is subscribed for this bloc's WHOLE lifetime (not just
/// during a `SubscribePressed`), so a purchase that lands AFTER the 15 s UI
/// recovery window — while the sheet is still open — still gets verified. The
/// 15 s timeout only changes the UI STATE (so the sheet can recover); it never
/// stops the listening.
///
/// ⚠️ Scope (Story 8.1 deviation #2): this lifetime is the SHEET's lifetime —
/// the bloc is created when the paywall opens and closed when it dismisses. A
/// purchase the plugin re-delivers on NEXT LAUNCH (or an Ask-to-Buy that
/// resolves after the sheet closed) is NOT verified here; the app-scope
/// startup listener that closes that "charged but tier never flipped" hole is
/// deferred to Story 8.2/8.3 (see deferred-work.md).
class SubscriptionBloc extends Bloc<SubscriptionEvent, SubscriptionState> {
  final SubscriptionRepository _repository;
  final InAppPurchaseService _iapService;
  final Duration _sheetTimeout;
  final Duration _restoreTimeout;

  StreamSubscription<List<PurchaseDetails>>? _purchaseSub;
  Timer? _timeoutTimer;
  Timer? _restoreTimer;

  /// True between a `RestorePressed` and either a restored entitlement landing
  /// on the stream or [RestoreLapsed] firing. Lets the empty-restore branch
  /// (F16) distinguish "nothing came back" from a genuine restore.
  bool _restoreInFlight = false;

  SubscriptionBloc({
    required SubscriptionRepository repository,
    required InAppPurchaseService iapService,
    Duration sheetTimeout = const Duration(seconds: 15),
    Duration restoreTimeout = const Duration(seconds: 3),
  }) : _repository = repository,
       _iapService = iapService,
       _sheetTimeout = sheetTimeout,
       _restoreTimeout = restoreTimeout,
       super(const SubscriptionInitial()) {
    on<SubscribePressed>(_onSubscribePressed);
    on<RestorePressed>(_onRestorePressed);
    on<RestoreLapsed>(_onRestoreLapsed);
    on<PurchaseUpdated>(_onPurchaseUpdated);
    on<PurchaseTimedOut>(_onTimedOut);

    _purchaseSub = _iapService.purchaseStream.listen(
      (purchases) => add(PurchaseUpdated(purchases)),
    );
  }

  String get _platform =>
      defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android';

  Future<void> _onSubscribePressed(
    SubscribePressed event,
    Emitter<SubscriptionState> emit,
  ) async {
    // Drop a second tap while a sheet is already in flight.
    if (state is SubscriptionLoading) return;
    emit(const SubscriptionLoading());

    final ProductDetails? product;
    try {
      product = await _iapService.loadProduct(kIapWeeklyProductId);
    } catch (_) {
      emit(const SubscriptionFailed('product_query_failed'));
      return;
    }
    if (product == null) {
      emit(const SubscriptionFailed('product_unavailable'));
      return;
    }

    bool sent;
    try {
      sent = await _iapService.buy(product);
    } catch (_) {
      emit(const SubscriptionFailed('buy_failed'));
      return;
    }
    if (!sent) {
      emit(const SubscriptionFailed('buy_failed'));
      return;
    }

    // Arm the UI recovery timeout. The terminal purchase update (or a
    // `pending`) cancels it; a true no-response leaves the user on a failed
    // state they can retry from.
    _timeoutTimer?.cancel();
    _timeoutTimer = Timer(_sheetTimeout, () => add(const PurchaseTimedOut()));
  }

  /// Story 8.2 (D2) — kick a restore. A restored entitlement re-delivers on
  /// `purchaseStream` (→ `restored` → verify → paid, same as a fresh buy); if
  /// the window elapses with nothing, [RestoreLapsed] surfaces the neutral
  /// "nothing to restore" state (F16 — never a fake success).
  Future<void> _onRestorePressed(
    RestorePressed event,
    Emitter<SubscriptionState> emit,
  ) async {
    if (state is SubscriptionLoading) return;
    emit(const SubscriptionLoading());
    _restoreInFlight = true;
    try {
      await _iapService.restore();
    } catch (_) {
      _restoreInFlight = false;
      emit(const SubscriptionFailed('restore_failed'));
      return;
    }
    _restoreTimer?.cancel();
    _restoreTimer = Timer(_restoreTimeout, () => add(const RestoreLapsed()));
  }

  void _onRestoreLapsed(RestoreLapsed event, Emitter<SubscriptionState> emit) {
    if (!_restoreInFlight) return;
    _restoreInFlight = false;
    // Only surface "nothing to restore" if we're still waiting — a restored
    // entitlement that landed first already moved us off Loading.
    if (state is SubscriptionLoading) emit(const SubscriptionRestoreEmpty());
  }

  Future<void> _onPurchaseUpdated(
    PurchaseUpdated event,
    Emitter<SubscriptionState> emit,
  ) async {
    for (final purchase in event.purchases) {
      if (purchase.productID != kIapWeeklyProductId) continue;
      switch (purchase.status) {
        case PurchaseStatus.pending:
          // The sheet responded — don't let the UI timeout fire on a slow
          // (but live) purchase. Story 8.3 (F17) — surface a dismissible
          // "awaiting approval" state instead of spinning on Loading forever
          // (Ask-to-Buy / SCA can take minutes). The eventual terminal update
          // (purchased / canceled) transitions normally; if it lands after the
          // sheet closed, the app-lifetime listener (Task 6) catches it.
          _timeoutTimer?.cancel();
          emit(const SubscriptionPendingApproval());
        case PurchaseStatus.purchased:
        case PurchaseStatus.restored:
          // A real entitlement landed — cancel BOTH the buy and the restore
          // windows and clear the restore flag so its lapse can't later fake a
          // "nothing to restore" over a confirmed purchase.
          _cancelTerminalTimers();
          await _verifyAndComplete(purchase, emit);
        case PurchaseStatus.error:
          _cancelTerminalTimers();
          if (purchase.pendingCompletePurchase) {
            await _safeComplete(purchase);
          }
          emit(SubscriptionFailed(purchase.error?.code ?? 'purchase_error'));
        case PurchaseStatus.canceled:
          _cancelTerminalTimers();
          if (purchase.pendingCompletePurchase) {
            await _safeComplete(purchase);
          }
          emit(const SubscriptionCancelled());
      }
    }
  }

  /// Cancel the buy + restore recovery windows and clear the restore flag on a
  /// terminal purchase update (purchased / restored / error / canceled).
  void _cancelTerminalTimers() {
    _timeoutTimer?.cancel();
    _restoreTimer?.cancel();
    _restoreInFlight = false;
  }

  Future<void> _verifyAndComplete(
    PurchaseDetails purchase,
    Emitter<SubscriptionState> emit,
  ) async {
    try {
      final status = await _repository.verifyPurchase(
        platform: _platform,
        productId: kIapWeeklyProductId,
        verificationData: purchase.verificationData.serverVerificationData,
      );
      emit(
        status.isPaid
            ? const SubscriptionPurchased()
            : const SubscriptionFailed('verification_failed'),
      );
    } on ApiException catch (e) {
      emit(SubscriptionFailed(e.code));
    } catch (_) {
      emit(const SubscriptionFailed('verification_failed'));
    } finally {
      // Finish the transaction regardless of validation outcome — an
      // unfinished purchase is re-delivered every launch and blocks re-buys.
      await _safeComplete(purchase);
    }
  }

  /// Finish a transaction, swallowing a completion failure (code-review 8.1 F5).
  ///
  /// The plugin's `completePurchase` is documented to throw on a transient
  /// store/Billing error. Letting it escape would (a) crash the event handler
  /// as an unhandled bloc error AND (b) leave the transaction unfinished — the
  /// exact "charged but stuck, can't re-buy" failure this flow exists to close.
  /// We log and rely on the next `purchaseStream` re-delivery to retry (the
  /// subscription lives for the whole bloc lifetime).
  Future<void> _safeComplete(PurchaseDetails purchase) async {
    try {
      await _iapService.complete(purchase);
    } catch (e) {
      debugPrint('SubscriptionBloc: completePurchase failed (will retry on '
          're-delivery): $e');
    }
  }

  void _onTimedOut(PurchaseTimedOut event, Emitter<SubscriptionState> emit) {
    if (state is SubscriptionLoading) {
      emit(const SubscriptionFailed('timeout'));
    }
  }

  @override
  Future<void> close() {
    _timeoutTimer?.cancel();
    _restoreTimer?.cancel();
    _purchaseSub?.cancel();
    return super.close();
  }
}
