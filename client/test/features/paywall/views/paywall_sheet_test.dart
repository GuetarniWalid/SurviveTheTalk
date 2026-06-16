import 'dart:async';

import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/paywall/views/paywall_sheet.dart';
import 'package:client/features/subscription/bloc/subscription_bloc.dart';
import 'package:client/features/subscription/repositories/subscription_repository.dart';
import 'package:client/features/subscription/services/in_app_purchase_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:mocktail/mocktail.dart';

class MockInAppPurchaseService extends Mock implements InAppPurchaseService {}

class MockSubscriptionRepository extends Mock
    implements SubscriptionRepository {}

Widget _harness(GlobalKey<NavigatorState> navigatorKey) => MaterialApp(
  theme: AppTheme.dark(),
  navigatorKey: navigatorKey,
  home: const Scaffold(body: Center(child: Text('ROOT_STUB'))),
);

void main() {
  late MockInAppPurchaseService mockService;
  late MockSubscriptionRepository mockRepository;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    mockService = MockInAppPurchaseService();
    mockRepository = MockSubscriptionRepository();
    // The bloc subscribes to this in its constructor — keep it inert.
    when(() => mockService.purchaseStream)
        .thenAnswer((_) => const Stream<List<PurchaseDetails>>.empty());
    // Build the sheet's bloc from mocks instead of the real store plugin.
    PaywallSheet.debugBlocBuilder = () => SubscriptionBloc(
      repository: mockRepository,
      iapService: mockService,
    );
  });

  tearDown(() {
    PaywallSheet.debugBlocBuilder = null;
  });

  testWidgets('PaywallSheet.show renders the minimal subscribe control', (
    tester,
  ) async {
    final navigatorKey = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(navigatorKey));

    unawaited(PaywallSheet.show(navigatorKey.currentContext!));
    await tester.pumpAndSettle();

    expect(find.text('Unlock all scenarios'), findsOneWidget);
    expect(find.text('Subscribe — \$1.99/week'), findsOneWidget);
  });

  testWidgets('PaywallSheet uses the BOC fill colour and a top-rounded shape', (
    tester,
  ) async {
    final navigatorKey = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(navigatorKey));

    unawaited(PaywallSheet.show(navigatorKey.currentContext!));
    await tester.pumpAndSettle();

    final sheet = tester.widget<Material>(
      find.descendant(
        of: find.byType(BottomSheet),
        matching: find.byWidgetPredicate(
          (w) => w is Material && w.shape is RoundedRectangleBorder,
        ),
      ),
    );
    expect(sheet.color, AppColors.textPrimary);
    final shape = sheet.shape! as RoundedRectangleBorder;
    final radius = (shape.borderRadius as BorderRadius).topLeft.x;
    expect(radius, 42.0);
  });
}
