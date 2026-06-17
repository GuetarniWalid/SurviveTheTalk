import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/paywall/views/paywall_sheet.dart';
import 'package:client/features/subscription/bloc/subscription_bloc.dart';
import 'package:client/features/subscription/bloc/subscription_event.dart';
import 'package:client/features/subscription/bloc/subscription_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

/// Drives the sheet through bloc states directly (code-review 8.1 F23 pattern).
class MockSubscriptionBloc
    extends MockBloc<SubscriptionEvent, SubscriptionState>
    implements SubscriptionBloc {}

Widget _harness(GlobalKey<NavigatorState> navigatorKey) => MaterialApp(
  theme: AppTheme.dark(),
  navigatorKey: navigatorKey,
  home: const Scaffold(body: Center(child: Text('ROOT_STUB'))),
);

void main() {
  late MockSubscriptionBloc bloc;

  // The sheet's surface Material (#F0F0F0, rounded top) — present iff the sheet
  // is open. The CTA's FilledButton Material is `accent`, so this is unambiguous
  // and replaces the old `find.byType(BottomSheet)` (Story 8.2 D2 dropped the
  // framework bottom sheet for a custom route).
  final sheetSurface = find.byWidgetPredicate(
    (w) =>
        w is Material &&
        w.color == AppColors.textPrimary &&
        w.shape is RoundedRectangleBorder,
  );
  const handle = Key('paywall-drag-handle');

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    bloc = MockSubscriptionBloc();
    PaywallSheet.debugBlocBuilder = () => bloc;
  });

  tearDown(() {
    PaywallSheet.debugBlocBuilder = null;
  });

  /// Seed the mock bloc with [initial] (no further emissions unless [stream]).
  void seed(
    SubscriptionState initial, {
    Stream<SubscriptionState>? stream,
  }) {
    whenListen(
      bloc,
      stream ?? const Stream<SubscriptionState>.empty(),
      initialState: initial,
    );
  }

  Future<void> open(WidgetTester tester, GlobalKey<NavigatorState> key) async {
    await tester.pumpWidget(_harness(key));
    unawaited(PaywallSheet.show(key.currentContext!));
  }

  // ---- Default: the verbatim copy deck (paywall-screen-design.md §2) ----

  testWidgets('Default renders the full copy deck verbatim', (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    expect(find.text('Speak English for real'), findsOneWidget);
    expect(
      find.text("Practice with characters who won't go easy on you."),
      findsOneWidget,
    );
    expect(find.text('\$1.99'), findsOneWidget);
    expect(find.text('per week'), findsOneWidget);
    expect(find.text('All scenarios unlocked.'), findsOneWidget);
    expect(find.text('Daily calls. Daily progress.'), findsOneWidget);
    expect(find.text("Know exactly what you're doing wrong"), findsOneWidget);
    expect(find.text("Let's go"), findsOneWidget);
    expect(find.text('Not now'), findsOneWidget);
    expect(find.text('Restore purchases'), findsOneWidget);
    expect(
      find.text('Auto-renewable. 3 calls per day. Cancel anytime.'),
      findsOneWidget,
    );
  });

  testWidgets('sheet surface is #F0F0F0 with a 16px top radius (D4)', (
    tester,
  ) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    final sheet = tester.widget<Material>(sheetSurface);
    final shape = sheet.shape! as RoundedRectangleBorder;
    final radius = (shape.borderRadius as BorderRadius).topLeft.x;
    expect(radius, 16.0);
  });

  // ---- State 2: Loading ----

  testWidgets('Loading shows the in-CTA spinner and disables CTA/dismiss/restore',
      (tester) async {
    seed(const SubscriptionLoading());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    // Spinner is a continuous animation → explicit pumps (CLAUDE.md #3).
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    final cta = tester.widget<FilledButton>(find.byType(FilledButton));
    expect(cta.onPressed, isNull);
    final notNow =
        tester.widget<TextButton>(find.widgetWithText(TextButton, 'Not now'));
    expect(notNow.onPressed, isNull);
    final restore = tester.widget<TextButton>(
      find.widgetWithText(TextButton, 'Restore purchases'),
    );
    expect(restore.onPressed, isNull);
  });

  // ---- State 4: Error ----

  testWidgets('Failed shows the error caption in paywallError; CTA re-enabled', (
    tester,
  ) async {
    seed(const SubscriptionFailed('verification_failed'));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    final errorFinder = find.text('Something went wrong. Try again.');
    expect(errorFinder, findsOneWidget);
    expect(
      tester.widget<Text>(errorFinder).style?.color,
      AppColors.paywallError,
    );
    // CTA is back to "Let's go" and tappable; dismiss stays enabled.
    expect(find.text("Let's go"), findsOneWidget);
    expect(
      tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
      isNotNull,
    );
  });

  testWidgets('product_unavailable renders the Error state with dismiss enabled'
      ' (Open-Q2)', (tester) async {
    seed(const SubscriptionFailed('product_unavailable'));
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    expect(find.text('Something went wrong. Try again.'), findsOneWidget);
    final notNow =
        tester.widget<TextButton>(find.widgetWithText(TextButton, 'Not now'));
    expect(notNow.onPressed, isNotNull); // user can leave cleanly
  });

  // ---- State 3: Success ----

  testWidgets('Purchased → "You\'re in", holds, then auto-pops true (G2)', (
    tester,
  ) async {
    seed(
      const SubscriptionInitial(),
      stream: Stream<SubscriptionState>.fromIterable(
        [const SubscriptionPurchased()],
      ),
    );
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(key));
    bool? result;
    unawaited(
      PaywallSheet.show(key.currentContext!).then((r) => result = r),
    );
    // Sheet entrance + the Purchased emission → the success view appears.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text("You're in"), findsOneWidget);
    // Let the 200ms AnimatedSwitcher crossfade evict the offer view.
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text("Let's go"), findsNothing);

    // Hold (1.5s default) then the slide-down dismiss.
    await tester.pump(const Duration(milliseconds: 1600));
    await tester.pump(const Duration(milliseconds: 400));
    expect(result, isTrue);
    expect(sheetSurface, findsNothing);
  });

  // ---- Cancelled → Default (no error) ----

  testWidgets('Cancelled returns to Default (no error caption)', (tester) async {
    seed(const SubscriptionCancelled());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    expect(find.text("Let's go"), findsOneWidget);
    expect(find.text('Something went wrong. Try again.'), findsNothing);
    expect(find.text("You're in"), findsNothing);
  });

  // ---- Restore (D2) ----

  testWidgets('tapping "Restore purchases" dispatches RestorePressed', (
    tester,
  ) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Restore purchases'));
    await tester.pump();
    verify(() => bloc.add(const RestorePressed())).called(1);
  });

  testWidgets('RestoreEmpty shows a neutral "Nothing to restore." (F16, no fake'
      ' success)', (tester) async {
    seed(const SubscriptionRestoreEmpty());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    final line = find.text('Nothing to restore.');
    expect(line, findsOneWidget);
    // Neutral (secondary ink), NOT the error red, NOT the success state.
    expect(
      tester.widget<Text>(line).style?.color,
      AppColors.overlaySubtitle,
    );
    expect(find.text("You're in"), findsNothing);
    expect(find.text("Let's go"), findsOneWidget); // offer still present
  });

  // ---- CTA + dismiss wiring ----

  testWidgets('tapping "Let\'s go" dispatches SubscribePressed', (tester) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    await tester.tap(find.text("Let's go"));
    await tester.pump();
    verify(() => bloc.add(const SubscribePressed())).called(1);
  });

  testWidgets('"Not now" pops the sheet with false (clean dismiss, AC5)', (
    tester,
  ) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(key));
    bool? result;
    unawaited(
      PaywallSheet.show(key.currentContext!).then((r) => result = r),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(result, isFalse);
    expect(sheetSurface, findsNothing);
  });

  // ---- D2 dismiss matrix: swipe / scrim / system-back × the 4 states ----
  //
  // Default & Error are dismissible (swipe, scrim tap, back all return false);
  // Loading & the success hold are NOT (every manual path is a no-op — design
  // States 2 & 3). The custom route gates all three on the live bloc state.

  testWidgets('Default: scrim tap dismisses with false (AC5)', (tester) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(key));
    bool? result;
    unawaited(PaywallSheet.show(key.currentContext!).then((r) => result = r));
    await tester.pumpAndSettle();

    // (20,20) lands on the scrim above the bottom-anchored sheet.
    await tester.tapAt(const Offset(20, 20));
    await tester.pumpAndSettle();
    expect(result, isFalse);
    expect(sheetSurface, findsNothing);
  });

  testWidgets('Default: swiping the handle down dismisses with false (AC5)', (
    tester,
  ) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(key));
    bool? result;
    unawaited(PaywallSheet.show(key.currentContext!).then((r) => result = r));
    await tester.pumpAndSettle();

    await tester.fling(find.byKey(handle), const Offset(0, 300), 1500);
    await tester.pumpAndSettle();
    expect(result, isFalse);
    expect(sheetSurface, findsNothing);
  });

  testWidgets('Default: system back dismisses (AC8)', (tester) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(sheetSurface, findsNothing);
  });

  testWidgets('Error: scrim tap dismisses with false (AC5)', (tester) async {
    seed(const SubscriptionFailed('verification_failed'));
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(key));
    bool? result;
    unawaited(PaywallSheet.show(key.currentContext!).then((r) => result = r));
    await tester.pumpAndSettle();

    await tester.tapAt(const Offset(20, 20));
    await tester.pumpAndSettle();
    expect(result, isFalse);
    expect(sheetSurface, findsNothing);
  });

  testWidgets('Loading: scrim tap is a no-op (dismiss blocked, design State 2)',
      (tester) async {
    seed(const SubscriptionLoading());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    await tester.tapAt(const Offset(20, 20));
    await tester.pump(const Duration(milliseconds: 100));
    expect(sheetSurface, findsOneWidget); // still open
  });

  testWidgets('Loading: swiping the handle is a no-op (dismiss blocked)', (
    tester,
  ) async {
    seed(const SubscriptionLoading());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    await tester.fling(find.byKey(handle), const Offset(0, 300), 1500);
    await tester.pump(const Duration(milliseconds: 100));
    expect(sheetSurface, findsOneWidget); // still open
  });

  testWidgets('Loading: system back is blocked (PopScope, design State 2)', (
    tester,
  ) async {
    seed(const SubscriptionLoading());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    await tester.binding.handlePopRoute();
    await tester.pump(const Duration(milliseconds: 100));
    expect(sheetSurface, findsOneWidget); // still open
  });

  testWidgets('Success hold: system back is blocked (design State 3)', (
    tester,
  ) async {
    seed(
      const SubscriptionInitial(),
      stream: Stream<SubscriptionState>.fromIterable(
        [const SubscriptionPurchased()],
      ),
    );
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(key));
    unawaited(PaywallSheet.show(key.currentContext!));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    await tester.binding.handlePopRoute();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text("You're in"), findsOneWidget); // still held, not dismissed

    // Drain the 1.5s success-hold timer so teardown sees no pending timer.
    await tester.pump(const Duration(milliseconds: 1600));
    await tester.pump(const Duration(milliseconds: 400));
  });

  testWidgets('Success hold: scrim tap is a no-op (design State 3)', (
    tester,
  ) async {
    seed(
      const SubscriptionInitial(),
      stream: Stream<SubscriptionState>.fromIterable(
        [const SubscriptionPurchased()],
      ),
    );
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(key));
    unawaited(PaywallSheet.show(key.currentContext!));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    await tester.tapAt(const Offset(20, 20));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text("You're in"), findsOneWidget); // still held

    await tester.pump(const Duration(milliseconds: 1600));
    await tester.pump(const Duration(milliseconds: 400));
  });

  // ---- Accessibility (AC6) ----

  testWidgets('price is announced naturally ("one dollar ninety-nine per'
      ' week")', (tester) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    expect(
      find.bySemanticsLabel('One dollar ninety-nine per week'),
      findsOneWidget,
    );
  });

  // ---- iPhone SE overflow (#7) ----

  testWidgets('no overflow on a 320x480 viewport (iPhone-SE scroll)', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    // The scrollable container keeps the content reachable.
    expect(find.byType(SingleChildScrollView), findsWidgets);
  });
}
