import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/widgets/empathetic_error_screen.dart';
import 'package:client/features/paywall/views/paywall_sheet.dart';
import 'package:client/features/subscription/bloc/subscription_bloc.dart';
import 'package:client/features/subscription/bloc/subscription_event.dart';
import 'package:client/features/subscription/bloc/subscription_state.dart';
import 'package:client/features/subscription/bloc/user_profile_cubit.dart';
import 'package:client/features/subscription/models/user_profile.dart';
import 'package:client/features/subscription/services/store_links.dart';
import 'package:client/features/subscription/views/manage_subscription_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockUserProfileCubit extends MockCubit<UserProfileState>
    implements UserProfileCubit {}

class MockSubscriptionBloc extends MockBloc<SubscriptionEvent, SubscriptionState>
    implements SubscriptionBloc {}

class MockStoreLinks extends Mock implements StoreLinks {}

const _free = UserProfile(
  tier: 'free',
  callsRemaining: 2,
  callsPerPeriod: 3,
  period: 'lifetime',
);
const _paid = UserProfile(
  tier: 'paid',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'day',
  subscriptionExpiresAt: '2099-07-18T00:00:00Z',
);
// A reverted/churned user: now free, carries a PAST expiry (state D).
const _expired = UserProfile(
  tier: 'free',
  callsRemaining: 1,
  callsPerPeriod: 3,
  period: 'lifetime',
  subscriptionExpiresAt: '2020-01-01T00:00:00Z',
);

void main() {
  late MockUserProfileCubit cubit;
  late MockSubscriptionBloc subBloc;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    cubit = MockUserProfileCubit();
    subBloc = MockSubscriptionBloc();
    when(() => cubit.load()).thenAnswer((_) async {});
    when(() => subBloc.state).thenReturn(const SubscriptionInitial());
  });

  tearDown(() => PaywallSheet.debugBlocBuilder = null);

  void seedCubit(UserProfileState state) {
    when(() => cubit.state).thenReturn(state);
    whenListen(
      cubit,
      const Stream<UserProfileState>.empty(),
      initialState: state,
    );
  }

  void seedSubStream(Iterable<SubscriptionState> states) {
    whenListen(
      subBloc,
      Stream<SubscriptionState>.fromIterable(states),
      initialState: const SubscriptionInitial(),
    );
  }

  Widget harness({StoreLinks? storeLinks}) {
    return MaterialApp(
      home: MultiBlocProvider(
        providers: [
          BlocProvider<UserProfileCubit>.value(value: cubit),
          BlocProvider<SubscriptionBloc>.value(value: subBloc),
        ],
        child: ManageSubscriptionScreen(storeLinks: storeLinks),
      ),
    );
  }

  testWidgets('free → Free plan + calls + Subscribe CTA', (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    await tester.pumpWidget(harness());
    await tester.pump();

    expect(find.text('Subscription'), findsOneWidget);
    expect(find.text('Free plan'), findsOneWidget);
    expect(find.text('2 of 3 free calls left'), findsOneWidget);
    expect(find.text('Subscribe'), findsOneWidget);
    expect(find.text('Manage subscription'), findsNothing);
    expect(find.text('Restore purchases'), findsOneWidget);
    // Free "Subscribe" stays the loud accent FILL pill (conversion).
    expect(find.widgetWithText(FilledButton, 'Subscribe'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, 'Subscribe'), findsNothing);
    // No auto-renewable line on the free footer either.
    expect(find.textContaining('Auto-renewable'), findsNothing);
  });

  testWidgets('paid Manage is a neutral OUTLINED pill, not the accent fill',
      (tester) async {
    seedCubit(const UserProfileLoaded(_paid));
    await tester.pumpWidget(harness());
    await tester.pump();

    // Discreet (retention): outlined, NOT a green FilledButton.
    expect(find.widgetWithText(FilledButton, 'Manage subscription'), findsNothing);
    final manage = find.widgetWithText(OutlinedButton, 'Manage subscription');
    expect(manage, findsOneWidget);
    final side = tester.widget<OutlinedButton>(manage).style?.side?.resolve({});
    expect(side?.color, AppColors.textSecondary); // neutral border, not accent
  });

  testWidgets('free: Restore sits BELOW the Subscribe pill', (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    await tester.pumpWidget(harness());
    await tester.pump();
    final ctaY = tester
        .getTopLeft(find.widgetWithText(FilledButton, 'Subscribe'))
        .dy;
    final restoreY = tester
        .getTopLeft(find.widgetWithText(TextButton, 'Restore purchases'))
        .dy;
    expect(restoreY, greaterThan(ctaY));
  });

  testWidgets('paid: Restore sits BELOW the Manage button', (tester) async {
    seedCubit(const UserProfileLoaded(_paid));
    await tester.pumpWidget(harness());
    await tester.pump();
    final ctaY = tester
        .getTopLeft(find.widgetWithText(OutlinedButton, 'Manage subscription'))
        .dy;
    final restoreY = tester
        .getTopLeft(find.widgetWithText(TextButton, 'Restore purchases'))
        .dy;
    expect(restoreY, greaterThan(ctaY));
  });

  testWidgets('paid → Premium + price + Renews date + Manage CTA',
      (tester) async {
    seedCubit(const UserProfileLoaded(_paid));
    await tester.pumpWidget(harness());
    await tester.pump();

    expect(find.text('Premium'), findsOneWidget);
    expect(find.text('\$1.99 per week'), findsOneWidget);
    expect(find.textContaining('Renews'), findsOneWidget);
    expect(find.textContaining('2099'), findsOneWidget);
    expect(find.text('Manage subscription'), findsOneWidget);
    expect(find.text('Subscribe'), findsNothing);
    // Auto-renewable disclosure removed from the status screen (it lives at the
    // point of sale — the paywall — per the compliance verdict).
    expect(find.textContaining('Auto-renewable'), findsNothing);
  });

  testWidgets('loading → skeleton, CTA disabled, Restore enabled',
      (tester) async {
    seedCubit(const UserProfileLoading());
    await tester.pumpWidget(harness());
    await tester.pump();

    // Never render a real plan label while merely loading.
    expect(find.text('Free plan'), findsNothing);
    expect(find.text('Premium'), findsNothing);
    expect(find.text('Restore purchases'), findsOneWidget);

    // CTA renders the Subscribe label (unknown tier) but is disabled.
    final cta = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Subscribe'),
    );
    expect(cta.onPressed, isNull);
  });

  testWidgets('error → EmpatheticErrorScreen', (tester) async {
    seedCubit(const UserProfileError('NETWORK_ERROR'));
    await tester.pumpWidget(harness());
    await tester.pump();

    expect(find.byType(EmpatheticErrorScreen), findsOneWidget);
  });

  testWidgets('paid → tap Manage → StoreLinks.openManageSubscriptions',
      (tester) async {
    final storeLinks = MockStoreLinks();
    when(() => storeLinks.openManageSubscriptions())
        .thenAnswer((_) async => true);
    seedCubit(const UserProfileLoaded(_paid));
    await tester.pumpWidget(harness(storeLinks: storeLinks));
    await tester.pump();

    await tester.tap(find.text('Manage subscription'));
    await tester.pump();

    verify(() => storeLinks.openManageSubscriptions()).called(1);
  });

  testWidgets('paid → Manage launch fails → inline "Store did not open"',
      (tester) async {
    final storeLinks = MockStoreLinks();
    when(() => storeLinks.openManageSubscriptions())
        .thenAnswer((_) async => false);
    seedCubit(const UserProfileLoaded(_paid));
    await tester.pumpWidget(harness(storeLinks: storeLinks));
    await tester.pump();

    await tester.tap(find.text('Manage subscription'));
    await tester.pump();

    expect(find.text('Store did not open. Try again.'), findsOneWidget);
  });

  testWidgets('tapping Restore dispatches RestorePressed', (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    await tester.pumpWidget(harness());
    await tester.pump();

    await tester.tap(find.text('Restore purchases'));
    await tester.pump();

    verify(() => subBloc.add(const RestorePressed())).called(1);
  });

  testWidgets('Restore empty → inline "Nothing to restore."', (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    seedSubStream(const [SubscriptionRestoreEmpty()]);
    await tester.pumpWidget(harness());
    await tester.pump();
    await tester.pump();

    expect(find.text('Nothing to restore.'), findsOneWidget);
  });

  testWidgets('Restore success → refetches profile (flip)', (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    seedSubStream(const [SubscriptionPurchased()]);
    await tester.pumpWidget(harness());
    await tester.pump();
    await tester.pump();

    // The load-bearing flip: refetch the profile so the view flips to paid.
    verify(() => cubit.load()).called(1);

    // Flush the AppToast lifecycle (600ms delayed forward + 10s auto-dismiss)
    // so no Timer is left pending at teardown.
    await tester.pump(const Duration(milliseconds: 700));
    await tester.pump(const Duration(seconds: 11));
    await tester.pumpAndSettle();
  });

  testWidgets('free → tap Subscribe → opens the paywall sheet', (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    await tester.pumpWidget(harness());
    await tester.pump();

    await tester.tap(find.text('Subscribe'));
    await tester.pumpAndSettle();

    expect(find.byType(BottomSheet), findsOneWidget);
  });

  testWidgets('renders without overflow at 320x480 × textScaler 2.0 (paid)',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    seedCubit(const UserProfileLoaded(_paid));

    await tester.pumpWidget(
      MaterialApp(
        home: MediaQuery(
          data: const MediaQueryData(textScaler: TextScaler.linear(2.0)),
          child: MultiBlocProvider(
            providers: [
              BlocProvider<UserProfileCubit>.value(value: cubit),
              BlocProvider<SubscriptionBloc>.value(value: subBloc),
            ],
            child: const ManageSubscriptionScreen(),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(tester.takeException(), isNull);
  });

  // ---------- Story 8.3 hero-ring redesign ----------

  testWidgets('free hero shows the count in the ring + a gauge, no inner label',
      (tester) async {
    seedCubit(const UserProfileLoaded(_free)); // remaining 2 of 3
    await tester.pumpWidget(harness());
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 800)); // finish the sweep

    expect(find.text('2'), findsOneWidget); // the count in the ring bore
    expect(find.byType(CustomPaint), findsWidgets); // the gauge painter
    // No invented inner ring labels (the dropped-copy decision).
    expect(find.text('CALLS LEFT'), findsNothing);
    expect(find.text('calls a day'), findsNothing);
  });

  testWidgets('paid hero is a Premium medallion — word in the ring, not doubled',
      (tester) async {
    seedCubit(const UserProfileLoaded(_paid));
    await tester.pumpWidget(harness());
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 800));

    expect(find.text('Premium'), findsOneWidget); // in the ring, not repeated
    expect(find.text('\$1.99 per week'), findsOneWidget);
    expect(find.textContaining('Renews'), findsOneWidget);
  });

  testWidgets('expired/reverted (state D) shows a quiet "Subscription ended" line',
      (tester) async {
    seedCubit(const UserProfileLoaded(_expired));
    await tester.pumpWidget(harness());
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 800));

    expect(find.text('Free plan'), findsOneWidget);
    expect(find.text('1 of 3 free calls left'), findsOneWidget);
    final ended = find.textContaining('Subscription ended');
    expect(ended, findsOneWidget);
    // Historical line uses the quiet chrome grey, never destructive red.
    expect(tester.widget<Text>(ended).style?.color, AppColors.textSecondary);
    expect(find.text('Subscribe'), findsOneWidget);
  });

  testWidgets('Restore is a centered pill (not the glued-left full-width slab)',
      (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    await tester.pumpWidget(harness());
    await tester.pump();

    final restoreBtn = find.widgetWithText(TextButton, 'Restore purchases');
    expect(restoreBtn, findsOneWidget);
    // Centered (the layout fix), not Alignment.centerLeft.
    expect(
      find.ancestor(of: restoreBtn, matching: find.byType(Center)),
      findsWidgets,
    );
  });

  testWidgets('Restore in-flight shows a spinner (label hidden)', (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    seedSubStream(const [SubscriptionLoading()]);
    await tester.pumpWidget(harness());
    await tester.pump();
    await tester.pump();

    expect(find.text('Restore purchases'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('Restore pending (F17) → inline "Waiting for approval." (not red)',
      (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    seedSubStream(const [SubscriptionPendingApproval()]);
    await tester.pumpWidget(harness());
    await tester.pump();
    await tester.pump();

    final pending = find.text('Waiting for approval.');
    expect(pending, findsOneWidget);
    expect(tester.widget<Text>(pending).style?.color, AppColors.textSecondary);
  });

  testWidgets('hero entrance animation settles with no exception', (tester) async {
    seedCubit(const UserProfileLoaded(_free));
    await tester.pumpWidget(harness());
    await tester.pump(); // fire the post-frame forward()
    await tester.pump(const Duration(milliseconds: 800)); // past the 700ms sweep
    expect(tester.takeException(), isNull);
  });
}
