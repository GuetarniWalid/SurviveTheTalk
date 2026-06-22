import 'dart:async';

import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/core/widgets/legal_links_row.dart';
import 'package:client/features/account/views/account_sheet.dart';
import 'package:client/features/subscription/repositories/user_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:url_launcher/url_launcher.dart';

/// The free-user Account drawer carries only universal account actions — no
/// subscription to manage — so deletion is never tapped here; a bare mock that
/// never has its `deleteAccount` called is enough to satisfy the test seam.
class MockUserRepository extends Mock implements UserRepository {}

Widget _harness(GlobalKey<NavigatorState> key) => MaterialApp(
  theme: AppTheme.dark(),
  navigatorKey: key,
  home: const Scaffold(body: Center(child: Text('ROOT_STUB'))),
);

void main() {
  late MockUserRepository repository;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    repository = MockUserRepository();
    AccountSheet.debugRepositoryBuilder = () => repository;
    AccountSheet.debugLaunch =
        (uri, {mode = LaunchMode.platformDefault}) async => true;
  });

  tearDown(() {
    AccountSheet.debugRepositoryBuilder = null;
    AccountSheet.debugLaunch = null;
  });

  Future<void> open(WidgetTester tester, GlobalKey<NavigatorState> key) async {
    await tester.pumpWidget(_harness(key));
    unawaited(AccountSheet.show(key.currentContext!, onSignOut: () {}));
    await tester.pumpAndSettle();
  }

  testWidgets(
      'Delete is the full-width RED OUTLINED pill (outlined: true), not the '
      'quiet TextButton', (tester) async {
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    // The sparse free sheet passes `outlined: true` → a full-width OUTLINED
    // pill (Manage-button shape) with a RED border (Walid 2026-06-22), NOT the
    // quiet red TextButton the Manage drawer uses.
    final pill = find.widgetWithText(OutlinedButton, 'Delete my account');
    expect(pill, findsOneWidget);
    expect(
      tester.widget<OutlinedButton>(pill).style?.side?.resolve({})?.color,
      AppColors.paywallError,
    );
    expect(
      find.widgetWithText(TextButton, 'Delete my account'),
      findsNothing,
    );
  });

  testWidgets('LegalLinksRow is the ABSOLUTE last element (below Delete)', (
    tester,
  ) async {
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    // Quiet compliance fine print the user essentially never taps sits at the
    // very bottom, below the Delete action.
    final deleteDy = tester.getTopLeft(find.text('Delete my account')).dy;
    final legalDy = tester.getTopLeft(find.byType(LegalLinksRow)).dy;
    expect(legalDy, greaterThan(deleteDy));
  });
}
