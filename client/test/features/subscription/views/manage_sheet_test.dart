import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/subscription/bloc/user_profile_cubit.dart';
import 'package:client/features/subscription/models/user_profile.dart';
import 'package:client/features/subscription/services/store_links.dart';
import 'package:client/features/subscription/views/manage_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:url_launcher/url_launcher.dart';

/// Drives the drawer through profile states directly (paywall test pattern).
class MockUserProfileCubit extends MockCubit<UserProfileState>
    implements UserProfileCubit {}

// ---- Fixtures (paid-only surface; expiries use midday-UTC so the formatted
// local date is stable across CI/local time zones). ----
const _paidFuture = UserProfile(
  tier: 'paid',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'day',
  subscriptionExpiresAt: '2026-07-18T12:00:00Z',
);
const _paidNullExpiry = UserProfile(
  tier: 'paid',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'day',
);
const _paidPastExpiry = UserProfile(
  tier: 'paid',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'day',
  subscriptionExpiresAt: '2020-01-01T12:00:00Z',
);

StoreLinks _store({
  TargetPlatform platform = TargetPlatform.android,
  Future<bool> Function(Uri, {LaunchMode mode})? launch,
}) => StoreLinks(
  platform: platform,
  launch:
      launch ?? (uri, {mode = LaunchMode.platformDefault}) async => true,
);

Widget _harness(GlobalKey<NavigatorState> key) => MaterialApp(
  theme: AppTheme.dark(),
  navigatorKey: key,
  home: const Scaffold(body: Center(child: Text('ROOT_STUB'))),
);

void main() {
  late MockUserProfileCubit cubit;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    cubit = MockUserProfileCubit();
    ManageSheet.debugCubitBuilder = () => cubit;
    ManageSheet.debugStoreLinks = _store();
  });

  tearDown(() {
    ManageSheet.debugCubitBuilder = null;
    ManageSheet.debugStoreLinks = null;
  });

  void seed(UserProfileState initial) {
    whenListen(
      cubit,
      const Stream<UserProfileState>.empty(),
      initialState: initial,
    );
  }

  Future<void> open(WidgetTester tester, GlobalKey<NavigatorState> key) async {
    await tester.pumpWidget(_harness(key));
    unawaited(ManageSheet.show(key.currentContext!, onSignOut: () {}));
    await tester.pumpAndSettle();
  }

  // ---- Loaded: the retention value block + renewal line ----

  testWidgets('Loaded paid → header, status, 3 benefits, renewal line', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    seed(const UserProfileLoaded(_paidFuture));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.text('Premium'), findsOneWidget);
    expect(find.text('Your membership is active.'), findsOneWidget);
    expect(find.text('What your membership gives you'), findsOneWidget);
    expect(find.text('Every scenario, unlocked.'), findsOneWidget);
    expect(find.text('Three calls a day, every day.'), findsOneWidget);
    expect(find.text('Clear feedback on what to fix.'), findsOneWidget);
    // Price line — just "$1.99 per week.", no renewal/expiry date (Walid
    // 2026-06-22: the date was removed).
    expect(find.text('\$1.99 per week.'), findsOneWidget);
    expect(find.textContaining('Renews'), findsNothing);
    expect(find.textContaining('2026'), findsNothing);
  });

  testWidgets('Loaded paid, null expiry → "\$1.99 per week." (no fabricated'
      ' date)', (tester) async {
    seed(const UserProfileLoaded(_paidNullExpiry));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.text('\$1.99 per week.'), findsOneWidget);
    expect(find.textContaining('Renews'), findsNothing);
  });

  testWidgets('Loaded paid, past expiry → "\$1.99 per week." (no date leaks)',
      (tester) async {
    seed(const UserProfileLoaded(_paidPastExpiry));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    // Date removed everywhere (Walid 2026-06-22) — even the old "Active until
    // {date}." auto-renew-off line is now just the flat price.
    expect(find.text('\$1.99 per week.'), findsOneWidget);
    expect(find.textContaining('Active until'), findsNothing);
    expect(find.textContaining('2020'), findsNothing);
  });

  // ---- Loading: short skeleton, no ring, no spinner-hang ----

  testWidgets('Loading renders the value block + a dim bar, no spinner', (
    tester,
  ) async {
    seed(const UserProfileLoading());
    final key = GlobalKey<NavigatorState>();
    // No pumpAndSettle (CLAUDE.md #3) — but there is no continuous animation
    // here, so an explicit pump is enough to lay out the sheet.
    await tester.pumpWidget(_harness(key));
    unawaited(ManageSheet.show(key.currentContext!, onSignOut: () {}));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('Premium'), findsOneWidget);
    expect(find.text('Every scenario, unlocked.'), findsOneWidget);
    // No survival-ring gauge spinner, no renewal text yet.
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.textContaining('per week'), findsNothing);
  });

  // ---- Error: compact inline retry, value + Manage still reachable ----

  testWidgets('Error → compact retry; value block + Manage still render', (
    tester,
  ) async {
    when(() => cubit.load()).thenAnswer((_) async {});
    seed(const UserProfileError('NETWORK_ERROR'));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.text("Couldn't load your details."), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    // The member must always reach value + Manage even on a fetch failure.
    expect(find.text('Every scenario, unlocked.'), findsOneWidget);
    expect(find.text('Manage subscription'), findsOneWidget);

    await tester.tap(find.text('Try again'));
    await tester.pump();
    verify(() => cubit.load()).called(1);
  });

  // ---- Manage handoff ----

  testWidgets('Manage tap launches the store; failure shows the inline caption',
      (tester) async {
    var launched = false;
    ManageSheet.debugStoreLinks = _store(
      platform: TargetPlatform.iOS,
      launch: (uri, {mode = LaunchMode.platformDefault}) async {
        launched = true;
        return false; // simulate the store failing to open
      },
    );
    seed(const UserProfileLoaded(_paidFuture));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.text('Store did not open. Try again.'), findsNothing);
    await tester.tap(find.text('Manage subscription'));
    await tester.pump();

    expect(launched, isTrue);
    final failCaption = find.text('Store did not open. Try again.');
    expect(failCaption, findsOneWidget);
    // Story 8.3 — failure caption uses the AA-safe paywallError on #F0F0F0,
    // NOT destructive (which fails contrast on the light sheet).
    expect(
      tester.widget<Text>(failCaption).style?.color,
      AppColors.paywallError,
    );
  });

  // (Removed: the "Update or cancel in the {store}." caption tests — Walid
  // 2026-06-22 dropped that caption entirely; the "Manage subscription" button
  // label already conveys it.)

  // ---- Short-sheet guards (no full-page furniture ported over) ----

  testWidgets('no back arrow (drawer drag-dismisses, not a pushed page)', (
    tester,
  ) async {
    seed(const UserProfileLoaded(_paidFuture));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.byIcon(Icons.arrow_back_ios_new), findsNothing);
    // It IS a bottom sheet (drawer), not a routed screen.
    expect(find.byType(BottomSheet), findsOneWidget);
  });

  testWidgets(
      'layout (Walid 2026-06-22): price ABOVE Manage; Delete directly below; '
      'legal links at the very bottom', (tester) async {
    seed(const UserProfileLoaded(_paidFuture));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    // A real, clearly-tappable outlined pill (not a bare text row) — exposes
    // proper button+label semantics on its own.
    final manage = find.widgetWithText(OutlinedButton, 'Manage subscription');
    expect(manage, findsOneWidget);
    // The old "update or cancel" caption is gone — the button label says it.
    expect(find.textContaining('cancel'), findsNothing);

    // Vertical order: the quiet price line sits ABOVE the button, the two
    // account actions (Manage then Delete) form one cluster, and the legal
    // links are the ABSOLUTE last element (quiet compliance fine print the user
    // essentially never taps).
    final priceDy = tester.getTopLeft(find.text('\$1.99 per week.')).dy;
    final manageDy = tester.getTopLeft(manage).dy;
    final deleteDy = tester.getTopLeft(find.text('Delete my account')).dy;
    final legalDy = tester.getTopLeft(find.textContaining('Privacy Policy')).dy;
    expect(priceDy, lessThan(manageDy));
    expect(manageDy, lessThan(deleteDy));
    expect(deleteDy, lessThan(legalDy));
  });

  // ---- iPhone-SE / large-text overflow ----

  testWidgets('no overflow at 320x480 with textScaler 2.0', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    seed(const UserProfileLoaded(_paidFuture));
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.dark(),
        navigatorKey: key,
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: const TextScaler.linear(2),
          ),
          child: child!,
        ),
        home: const Scaffold(body: Center(child: Text('ROOT_STUB'))),
      ),
    );
    unawaited(ManageSheet.show(key.currentContext!, onSignOut: () {}));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.byType(SingleChildScrollView), findsWidgets);
  });
}
