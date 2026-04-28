import 'dart:async';

import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/paywall/views/paywall_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _harness(GlobalKey<NavigatorState> navigatorKey) => MaterialApp(
      theme: AppTheme.dark(),
      navigatorKey: navigatorKey,
      home: const Scaffold(body: Center(child: Text('ROOT_STUB'))),
    );

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  testWidgets('PaywallSheet.show renders the placeholder copy on a sheet',
      (tester) async {
    final navigatorKey = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(navigatorKey));

    unawaited(PaywallSheet.show(navigatorKey.currentContext!));
    await tester.pumpAndSettle();

    expect(find.text('Paywall — coming in Story 8.2'), findsOneWidget);
  });

  testWidgets(
      'PaywallSheet uses the BOC fill colour and a top-rounded shape',
      (tester) async {
    final navigatorKey = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(navigatorKey));

    unawaited(PaywallSheet.show(navigatorKey.currentContext!));
    await tester.pumpAndSettle();

    // Match the sheet's Material by predicate (shape == RoundedRectangleBorder)
    // rather than `.first` of the descendant chain — Flutter SDK upgrades that
    // add intermediate Material wrappers inside BottomSheet would otherwise
    // silently bind to the wrong widget.
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
