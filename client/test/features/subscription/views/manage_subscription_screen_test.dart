import 'package:bloc_test/bloc_test.dart';
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
    // Auto-renew disclosure shown for paid.
    expect(find.textContaining('Auto-renewable'), findsOneWidget);
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
}
