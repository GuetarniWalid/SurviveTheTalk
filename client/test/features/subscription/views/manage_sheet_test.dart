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
    // Renewal line: "Renews 18 Jul 2026 for $1.99 per week." (single Text).
    expect(find.textContaining('Renews'), findsOneWidget);
    expect(find.textContaining('Jul 2026'), findsOneWidget);
    expect(find.textContaining('\$1.99 per week.'), findsOneWidget);
  });

  testWidgets('Loaded paid, null expiry → "\$1.99 per week." (no fabricated'
      ' date)', (tester) async {
    seed(const UserProfileLoaded(_paidNullExpiry));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.text('\$1.99 per week.'), findsOneWidget);
    expect(find.textContaining('Renews'), findsNothing);
  });

  testWidgets('Loaded paid, past expiry → "Active until {date}." (auto-renew'
      ' off)', (tester) async {
    seed(const UserProfileLoaded(_paidPastExpiry));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.textContaining('Active until'), findsOneWidget);
    expect(find.textContaining('2020'), findsOneWidget);
    expect(find.textContaining('Renews'), findsNothing);
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

  testWidgets('Manage caption is App Store on iOS', (tester) async {
    ManageSheet.debugStoreLinks = _store(platform: TargetPlatform.iOS);
    seed(const UserProfileLoaded(_paidFuture));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.text('Update or cancel in the App Store.'), findsOneWidget);
    expect(find.text('Update or cancel in the Play Store.'), findsNothing);
  });

  testWidgets('Manage caption is Play Store on Android', (tester) async {
    ManageSheet.debugStoreLinks = _store(platform: TargetPlatform.android);
    seed(const UserProfileLoaded(_paidFuture));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    expect(find.text('Update or cancel in the Play Store.'), findsOneWidget);
    expect(find.text('Update or cancel in the App Store.'), findsNothing);
  });

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

  testWidgets('Manage is a clear OUTLINED button + a cancel-cue caption below',
      (tester) async {
    seed(const UserProfileLoaded(_paidFuture));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);

    // A real, clearly-tappable outlined pill (not a bare text row) — exposes
    // proper button+label semantics on its own.
    expect(
      find.widgetWithText(OutlinedButton, 'Manage subscription'),
      findsOneWidget,
    );
    // The honest "cancel" cue sits in the caption centered directly below it.
    expect(find.textContaining('cancel'), findsOneWidget);
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
