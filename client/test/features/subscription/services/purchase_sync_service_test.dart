import 'dart:async';

import 'package:client/core/api/api_exception.dart';
import 'package:client/features/subscription/models/subscription_status.dart';
import 'package:client/features/subscription/repositories/subscription_repository.dart';
import 'package:client/features/subscription/services/in_app_purchase_service.dart';
import 'package:client/features/subscription/services/purchase_sync_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:mocktail/mocktail.dart';

class MockInAppPurchaseService extends Mock implements InAppPurchaseService {}

class MockSubscriptionRepository extends Mock
    implements SubscriptionRepository {}

PurchaseDetails _purchase(
  PurchaseStatus status, {
  String productId = kIapWeeklyProductId,
  bool pendingComplete = true,
}) {
  return PurchaseDetails(
    productID: productId,
    verificationData: PurchaseVerificationData(
      localVerificationData: 'local',
      serverVerificationData: 'server-artifact',
      source: 'app_store',
    ),
    transactionDate: '0',
    status: status,
  )..pendingCompletePurchase = pendingComplete;
}

Future<void> _settle() => Future<void>.delayed(const Duration(milliseconds: 10));

void main() {
  late MockInAppPurchaseService service;
  late MockSubscriptionRepository repository;
  late StreamController<List<PurchaseDetails>> controller;
  late PurchaseSyncService sync;

  setUpAll(() => registerFallbackValue(_purchase(PurchaseStatus.purchased)));

  setUp(() {
    service = MockInAppPurchaseService();
    repository = MockSubscriptionRepository();
    controller = StreamController<List<PurchaseDetails>>.broadcast();
    when(() => service.purchaseStream).thenAnswer((_) => controller.stream);
    when(() => service.complete(any())).thenAnswer((_) async {});
    sync = PurchaseSyncService(iapService: service, repository: repository);
  });

  tearDown(() async {
    await sync.dispose();
    if (!controller.isClosed) await controller.close();
  });

  void stubVerifyPaid() {
    when(
      () => repository.verifyPurchase(
        platform: any(named: 'platform'),
        productId: any(named: 'productId'),
        verificationData: any(named: 'verificationData'),
      ),
    ).thenAnswer(
      (_) async => const SubscriptionStatus(tier: 'paid', status: 'valid'),
    );
  }

  test(
    'a purchased event with no paywall open → verify + complete + fires '
    'onEntitlementChanged',
    () async {
      stubVerifyPaid();
      final events = <void>[];
      sync.onEntitlementChanged.listen(events.add);
      sync.start();

      controller.add([_purchase(PurchaseStatus.purchased)]);
      await _settle();

      verify(
        () => repository.verifyPurchase(
          platform: any(named: 'platform'),
          productId: any(named: 'productId'),
          verificationData: 'server-artifact',
        ),
      ).called(1);
      verify(() => service.complete(any())).called(1);
      expect(events, hasLength(1));
    },
  );

  test('a restored event is verified + completed too', () async {
    stubVerifyPaid();
    final events = <void>[];
    sync.onEntitlementChanged.listen(events.add);
    sync.start();

    controller.add([_purchase(PurchaseStatus.restored)]);
    await _settle();

    verify(
      () => repository.verifyPurchase(
        platform: any(named: 'platform'),
        productId: any(named: 'productId'),
        verificationData: any(named: 'verificationData'),
      ),
    ).called(1);
    verify(() => service.complete(any())).called(1);
    expect(events, hasLength(1));
  });

  test('a verify failure still completes but fires NO entitlement event',
      () async {
    when(
      () => repository.verifyPurchase(
        platform: any(named: 'platform'),
        productId: any(named: 'productId'),
        verificationData: any(named: 'verificationData'),
      ),
    ).thenThrow(const ApiException(code: 'PURCHASE_INVALID', message: 'no'));
    final events = <void>[];
    sync.onEntitlementChanged.listen(events.add);
    sync.start();

    controller.add([_purchase(PurchaseStatus.purchased)]);
    await _settle();

    verify(() => service.complete(any())).called(1); // not re-delivered forever
    expect(events, isEmpty);
  });

  test('a different product id is ignored', () async {
    stubVerifyPaid();
    sync.start();

    controller.add([_purchase(PurchaseStatus.purchased, productId: 'other')]);
    await _settle();

    verifyNever(
      () => repository.verifyPurchase(
        platform: any(named: 'platform'),
        productId: any(named: 'productId'),
        verificationData: any(named: 'verificationData'),
      ),
    );
    verifyNever(() => service.complete(any()));
  });

  test('a pending event neither verifies nor completes', () async {
    sync.start();

    controller.add([_purchase(PurchaseStatus.pending)]);
    await _settle();

    verifyNever(
      () => repository.verifyPurchase(
        platform: any(named: 'platform'),
        productId: any(named: 'productId'),
        verificationData: any(named: 'verificationData'),
      ),
    );
    verifyNever(() => service.complete(any()));
  });

  test('start() is idempotent — a second call does not double-subscribe',
      () async {
    stubVerifyPaid();
    final events = <void>[];
    sync.onEntitlementChanged.listen(events.add);
    sync.start();
    sync.start(); // no-op

    controller.add([_purchase(PurchaseStatus.purchased)]);
    await _settle();

    // One verify, one entitlement event — not doubled.
    verify(
      () => repository.verifyPurchase(
        platform: any(named: 'platform'),
        productId: any(named: 'productId'),
        verificationData: any(named: 'verificationData'),
      ),
    ).called(1);
    expect(events, hasLength(1));
  });
}
