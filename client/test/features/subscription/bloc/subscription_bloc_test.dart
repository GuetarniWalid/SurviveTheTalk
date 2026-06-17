import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/features/subscription/bloc/subscription_bloc.dart';
import 'package:client/features/subscription/bloc/subscription_event.dart';
import 'package:client/features/subscription/bloc/subscription_state.dart';
import 'package:client/features/subscription/models/subscription_status.dart';
import 'package:client/features/subscription/repositories/subscription_repository.dart';
import 'package:client/features/subscription/services/in_app_purchase_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:mocktail/mocktail.dart';

class MockInAppPurchaseService extends Mock implements InAppPurchaseService {}

class MockSubscriptionRepository extends Mock
    implements SubscriptionRepository {}

ProductDetails _product() => ProductDetails(
  id: kIapWeeklyProductId,
  title: 'Weekly',
  description: 'Weekly subscription',
  price: '\$1.99',
  rawPrice: 1.99,
  currencyCode: 'USD',
);

PurchaseDetails _purchase(
  PurchaseStatus status, {
  String productId = kIapWeeklyProductId,
  bool pendingComplete = false,
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

void main() {
  late MockInAppPurchaseService service;
  late MockSubscriptionRepository repository;
  late StreamController<List<PurchaseDetails>> purchaseController;

  setUpAll(() {
    registerFallbackValue(_product());
    registerFallbackValue(_purchase(PurchaseStatus.purchased));
  });

  setUp(() {
    service = MockInAppPurchaseService();
    repository = MockSubscriptionRepository();
    purchaseController = StreamController<List<PurchaseDetails>>.broadcast();
    when(() => service.purchaseStream)
        .thenAnswer((_) => purchaseController.stream);
    when(() => service.complete(any())).thenAnswer((_) async {});
  });

  tearDown(() => purchaseController.close());

  SubscriptionBloc buildBloc({Duration? timeout, Duration? restoreTimeout}) =>
      SubscriptionBloc(
        repository: repository,
        iapService: service,
        sheetTimeout: timeout ?? const Duration(seconds: 15),
        restoreTimeout: restoreTimeout ?? const Duration(seconds: 3),
      );

  void stubBuyOk() {
    when(() => service.loadProduct(kIapWeeklyProductId))
        .thenAnswer((_) async => _product());
    when(() => service.buy(any())).thenAnswer((_) async => true);
  }

  blocTest<SubscriptionBloc, SubscriptionState>(
    'purchased → [Loading, Purchased] and verifies + completes',
    setUp: () {
      stubBuyOk();
      when(
        () => repository.verifyPurchase(
          platform: any(named: 'platform'),
          productId: any(named: 'productId'),
          verificationData: any(named: 'verificationData'),
        ),
      ).thenAnswer(
        (_) async => const SubscriptionStatus(tier: 'paid', status: 'valid'),
      );
    },
    build: buildBloc,
    act: (bloc) async {
      bloc.add(const SubscribePressed());
      await Future<void>.delayed(const Duration(milliseconds: 20));
      purchaseController.add([_purchase(PurchaseStatus.purchased)]);
    },
    wait: const Duration(milliseconds: 60),
    expect: () => [isA<SubscriptionLoading>(), isA<SubscriptionPurchased>()],
    verify: (_) {
      verify(() => service.complete(any())).called(1);
    },
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'store error → [Loading, Failed]',
    setUp: stubBuyOk,
    build: buildBloc,
    act: (bloc) async {
      bloc.add(const SubscribePressed());
      await Future<void>.delayed(const Duration(milliseconds: 20));
      purchaseController.add([_purchase(PurchaseStatus.error)]);
    },
    wait: const Duration(milliseconds: 60),
    expect: () => [isA<SubscriptionLoading>(), isA<SubscriptionFailed>()],
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'user cancels → [Loading, Cancelled]',
    setUp: stubBuyOk,
    build: buildBloc,
    act: (bloc) async {
      bloc.add(const SubscribePressed());
      await Future<void>.delayed(const Duration(milliseconds: 20));
      purchaseController.add([_purchase(PurchaseStatus.canceled)]);
    },
    wait: const Duration(milliseconds: 60),
    expect: () => [isA<SubscriptionLoading>(), isA<SubscriptionCancelled>()],
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'verification ApiException → [Loading, Failed(code)]',
    setUp: () {
      stubBuyOk();
      when(
        () => repository.verifyPurchase(
          platform: any(named: 'platform'),
          productId: any(named: 'productId'),
          verificationData: any(named: 'verificationData'),
        ),
      ).thenThrow(
        const ApiException(code: 'PURCHASE_INVALID', message: 'no', statusCode: 402),
      );
    },
    build: buildBloc,
    act: (bloc) async {
      bloc.add(const SubscribePressed());
      await Future<void>.delayed(const Duration(milliseconds: 20));
      purchaseController.add([_purchase(PurchaseStatus.purchased)]);
    },
    wait: const Duration(milliseconds: 60),
    expect: () => [
      isA<SubscriptionLoading>(),
      isA<SubscriptionFailed>().having((s) => s.code, 'code', 'PURCHASE_INVALID'),
    ],
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'product unavailable → [Loading, Failed(product_unavailable)]',
    setUp: () {
      when(() => service.loadProduct(kIapWeeklyProductId))
          .thenAnswer((_) async => null);
    },
    build: buildBloc,
    act: (bloc) => bloc.add(const SubscribePressed()),
    expect: () => [
      isA<SubscriptionLoading>(),
      isA<SubscriptionFailed>()
          .having((s) => s.code, 'code', 'product_unavailable'),
    ],
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'no native-sheet response within the timeout → [Loading, Failed(timeout)]',
    setUp: stubBuyOk,
    build: () => buildBloc(timeout: const Duration(milliseconds: 30)),
    act: (bloc) => bloc.add(const SubscribePressed()),
    wait: const Duration(milliseconds: 90),
    expect: () => [
      isA<SubscriptionLoading>(),
      isA<SubscriptionFailed>().having((s) => s.code, 'code', 'timeout'),
    ],
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'ignores purchase updates for a different product id',
    setUp: stubBuyOk,
    build: () => buildBloc(timeout: const Duration(milliseconds: 40)),
    act: (bloc) async {
      bloc.add(const SubscribePressed());
      await Future<void>.delayed(const Duration(milliseconds: 15));
      purchaseController.add([
        _purchase(PurchaseStatus.purchased, productId: 'some_other_product'),
      ]);
    },
    wait: const Duration(milliseconds: 90),
    // The foreign product is skipped → only the timeout fires.
    expect: () => [
      isA<SubscriptionLoading>(),
      isA<SubscriptionFailed>().having((s) => s.code, 'code', 'timeout'),
    ],
  );

  // ---- code-review 8.1 F5 / F22 — complete() guard + branch coverage ----

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

  blocTest<SubscriptionBloc, SubscriptionState>(
    'F5 — a throwing complete() is swallowed; still reaches Purchased (no crash)',
    setUp: () {
      stubBuyOk();
      stubVerifyPaid();
      when(() => service.complete(any())).thenThrow(Exception('store boom'));
    },
    build: buildBloc,
    act: (bloc) async {
      bloc.add(const SubscribePressed());
      await Future<void>.delayed(const Duration(milliseconds: 20));
      purchaseController.add([_purchase(PurchaseStatus.purchased)]);
    },
    wait: const Duration(milliseconds: 60),
    expect: () => [isA<SubscriptionLoading>(), isA<SubscriptionPurchased>()],
    verify: (_) => verify(() => service.complete(any())).called(1),
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'F22 — restored (re-delivered) → verifies + completes → Purchased',
    setUp: () {
      stubVerifyPaid();
    },
    build: buildBloc,
    act: (bloc) async {
      // No SubscribePressed — the lifetime listener catches a re-delivered txn.
      await Future<void>.delayed(const Duration(milliseconds: 10));
      purchaseController.add([_purchase(PurchaseStatus.restored)]);
    },
    wait: const Duration(milliseconds: 60),
    expect: () => [isA<SubscriptionPurchased>()],
    verify: (_) => verify(() => service.complete(any())).called(1),
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'F22 — error with pendingCompletePurchase finishes the transaction',
    setUp: stubBuyOk,
    build: buildBloc,
    act: (bloc) async {
      bloc.add(const SubscribePressed());
      await Future<void>.delayed(const Duration(milliseconds: 20));
      purchaseController.add(
        [_purchase(PurchaseStatus.error, pendingComplete: true)],
      );
    },
    wait: const Duration(milliseconds: 60),
    expect: () => [isA<SubscriptionLoading>(), isA<SubscriptionFailed>()],
    verify: (_) => verify(() => service.complete(any())).called(1),
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'F22 — pending keeps Loading and the recovery timeout does NOT fire',
    setUp: stubBuyOk,
    build: () => buildBloc(timeout: const Duration(milliseconds: 30)),
    act: (bloc) async {
      bloc.add(const SubscribePressed());
      await Future<void>.delayed(const Duration(milliseconds: 15));
      purchaseController.add([_purchase(PurchaseStatus.pending)]);
    },
    wait: const Duration(milliseconds: 90),
    // pending cancels the timeout and stays Loading — no terminal state.
    expect: () => [isA<SubscriptionLoading>()],
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'buy() throwing → Failed(buy_failed)',
    setUp: () {
      when(() => service.loadProduct(kIapWeeklyProductId))
          .thenAnswer((_) async => _product());
      when(() => service.buy(any())).thenThrow(Exception('boom'));
    },
    build: buildBloc,
    act: (bloc) => bloc.add(const SubscribePressed()),
    expect: () => [
      isA<SubscriptionLoading>(),
      isA<SubscriptionFailed>().having((s) => s.code, 'code', 'buy_failed'),
    ],
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'loadProduct throwing → Failed(product_query_failed)',
    setUp: () {
      when(() => service.loadProduct(kIapWeeklyProductId))
          .thenThrow(Exception('boom'));
    },
    build: buildBloc,
    act: (bloc) => bloc.add(const SubscribePressed()),
    expect: () => [
      isA<SubscriptionLoading>(),
      isA<SubscriptionFailed>()
          .having((s) => s.code, 'code', 'product_query_failed'),
    ],
  );

  // ---- Story 8.2 (D2) — Restore purchases ----

  blocTest<SubscriptionBloc, SubscriptionState>(
    'restore → restored entitlement → [Loading, Purchased] + verify + complete',
    setUp: () {
      stubVerifyPaid();
      when(() => service.restore()).thenAnswer((_) async {});
    },
    build: buildBloc,
    act: (bloc) async {
      bloc.add(const RestorePressed());
      await Future<void>.delayed(const Duration(milliseconds: 20));
      purchaseController.add([_purchase(PurchaseStatus.restored)]);
    },
    wait: const Duration(milliseconds: 60),
    expect: () => [isA<SubscriptionLoading>(), isA<SubscriptionPurchased>()],
    verify: (_) {
      verify(() => service.restore()).called(1);
      verify(() => service.complete(any())).called(1);
    },
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'restore → nothing to restore (F16) → [Loading, RestoreEmpty] (no fake success)',
    setUp: () {
      when(() => service.restore()).thenAnswer((_) async {});
    },
    build: () => buildBloc(restoreTimeout: const Duration(milliseconds: 30)),
    act: (bloc) => bloc.add(const RestorePressed()),
    wait: const Duration(milliseconds: 90),
    expect: () => [
      isA<SubscriptionLoading>(),
      isA<SubscriptionRestoreEmpty>(),
    ],
    verify: (_) => verify(() => service.restore()).called(1),
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'restore() throwing → [Loading, Failed(restore_failed)]',
    setUp: () {
      when(() => service.restore()).thenThrow(Exception('boom'));
    },
    build: buildBloc,
    act: (bloc) => bloc.add(const RestorePressed()),
    expect: () => [
      isA<SubscriptionLoading>(),
      isA<SubscriptionFailed>().having((s) => s.code, 'code', 'restore_failed'),
    ],
  );

  blocTest<SubscriptionBloc, SubscriptionState>(
    'restore: a restored txn cancels the lapse timer (no RestoreEmpty after Purchased)',
    setUp: () {
      stubVerifyPaid();
      when(() => service.restore()).thenAnswer((_) async {});
    },
    build: () => buildBloc(restoreTimeout: const Duration(milliseconds: 30)),
    act: (bloc) async {
      bloc.add(const RestorePressed());
      await Future<void>.delayed(const Duration(milliseconds: 10));
      purchaseController.add([_purchase(PurchaseStatus.restored)]);
    },
    // Wait well past the 30ms restore window — RestoreEmpty must NOT appear.
    wait: const Duration(milliseconds: 90),
    expect: () => [isA<SubscriptionLoading>(), isA<SubscriptionPurchased>()],
  );

  test('close() cancels the purchaseStream subscription (no add-after-close)',
      () async {
    final bloc = buildBloc();
    await bloc.close();
    // If the subscription leaked, this would call add() on a closed bloc and
    // throw a StateError; a cancelled subscription simply drops it.
    purchaseController.add([_purchase(PurchaseStatus.purchased)]);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(bloc.state, isA<SubscriptionInitial>());
  });
}
