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

PurchaseDetails _purchase(PurchaseStatus status, {String productId = kIapWeeklyProductId}) {
  return PurchaseDetails(
    productID: productId,
    verificationData: PurchaseVerificationData(
      localVerificationData: 'local',
      serverVerificationData: 'server-artifact',
      source: 'app_store',
    ),
    transactionDate: '0',
    status: status,
  );
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

  SubscriptionBloc buildBloc({Duration? timeout}) => SubscriptionBloc(
    repository: repository,
    iapService: service,
    sheetTimeout: timeout ?? const Duration(seconds: 15),
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
}
