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
    // Story 8.3 — Restore moved OUT of the paywall (it lives on the Manage
    // Subscription screen now); the paywall is a pure buy moment.
    expect(find.text('Restore purchases'), findsNothing);
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

    // Scope to the sheet SURFACE Material (color #F0F0F0) — the CTA's
    // FilledButton is also a RoundedRectangleBorder Material (radius 12).
    final sheet = tester.widget<Material>(
      find.descendant(
        of: find.byType(BottomSheet),
        matching: find.byWidgetPredicate(
          (w) =>
              w is Material &&
              w.color == AppColors.textPrimary &&
              w.shape is RoundedRectangleBorder,
        ),
      ),
    );
    final shape = sheet.shape! as RoundedRectangleBorder;
    final radius = (shape.borderRadius as BorderRadius).topLeft.x;
    expect(radius, 16.0);
  });

  // ---- State 2: Loading ----

  testWidgets('Loading shows the in-CTA spinner and disables CTA/dismiss'
      ' + PopScope blocks back', (tester) async {
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

    final popScope = tester.widget<PopScope>(
      find.descendant(
        of: find.byType(BottomSheet),
        matching: find.byType(PopScope),
      ),
    );
    expect(popScope.canPop, isFalse);
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
    expect(tester.widget<Text>(errorFinder).style?.color, AppColors.paywallError);
    // CTA is back to "Let's go" and tappable; dismiss stays enabled.
    expect(find.text("Let's go"), findsOneWidget);
    expect(
      tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
      isNotNull,
    );
    final popScope = tester.widget<PopScope>(
      find.descendant(
        of: find.byType(BottomSheet),
        matching: find.byType(PopScope),
      ),
    );
    expect(popScope.canPop, isTrue);
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
    expect(find.byType(BottomSheet), findsNothing);
  });

  testWidgets('PopScope blocks back during the success hold', (tester) async {
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

    final popScope = tester.widget<PopScope>(
      find.descendant(
        of: find.byType(BottomSheet),
        matching: find.byType(PopScope),
      ),
    );
    expect(popScope.canPop, isFalse);

    // Drain the success-hold timer so teardown sees no pending timer.
    await tester.pump(const Duration(milliseconds: 1600));
    await tester.pump(const Duration(milliseconds: 400));
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

  // ---- Restore — Story 8.3: moved OUT of the paywall ----
  //
  // Restore purchases now lives ONLY on the Manage Subscription screen (reached
  // via the Account hub line), covered by manage_subscription_screen_test.dart.
  // The paywall is a pure transactional moment — no Restore affordance.

  testWidgets('paywall has NO Restore affordance (moved to Subscription screen)',
      (tester) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    expect(find.text('Restore purchases'), findsNothing);
  });

  testWidgets('PendingApproval (F17) shows the waiting copy + stays dismissible',
      (tester) async {
    seed(const SubscriptionPendingApproval());
    final key = GlobalKey<NavigatorState>();
    await open(tester, key);
    await tester.pumpAndSettle();

    // The dismissible "awaiting approval" copy (not a fake success, not error).
    expect(find.text('Waiting for approval. You can close this.'), findsOneWidget);
    expect(find.text("You're in"), findsNothing);
    // The sheet stays dismissible during pending (PopScope canPop true).
    final popScope = tester.widget<PopScope<dynamic>>(find.byType(PopScope));
    expect(popScope.canPop, isTrue);
    // Subscribe is disabled while pending (no double-buy).
    final cta = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, "Let's go"),
    );
    expect(cta.onPressed, isNull);
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
    expect(find.byType(BottomSheet), findsNothing);
  });

  testWidgets('scrim tap dismisses cleanly with false (AC5)', (tester) async {
    seed(const SubscriptionInitial());
    final key = GlobalKey<NavigatorState>();
    await tester.pumpWidget(_harness(key));
    bool? result;
    unawaited(
      PaywallSheet.show(key.currentContext!).then((r) => result = r),
    );
    await tester.pumpAndSettle();

    // (20,20) lands on the scrim above the bottom-anchored sheet.
    await tester.tapAt(const Offset(20, 20));
    await tester.pumpAndSettle();
    expect(result, isFalse);
    expect(find.byType(BottomSheet), findsNothing);
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
