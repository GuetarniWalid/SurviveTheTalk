import 'package:bloc_test/bloc_test.dart';
import 'package:client/app/app.dart';
import 'package:client/features/auth/bloc/auth_bloc.dart';
import 'package:client/features/auth/bloc/auth_event.dart';
import 'package:client/features/auth/bloc/auth_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockAuthBloc extends MockBloc<AuthEvent, AuthState>
    implements AuthBloc {}

void main() {
  late MockAuthBloc mockAuthBloc;

  setUpAll(() {
    registerFallbackValue(CheckAuthStatusEvent());
  });

  setUp(() {
    mockAuthBloc = MockAuthBloc();
  });

  testWidgets('App renders email entry screen when not authenticated',
      (tester) async {
    when(() => mockAuthBloc.state).thenReturn(AuthInitial());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthInitial()),
      initialState: AuthInitial(),
    );

    await tester.pumpWidget(App(authBloc: mockAuthBloc));
    await tester.pumpAndSettle();

    expect(find.byType(MaterialApp), findsOneWidget);
    // When unauthenticated, should redirect to login and show email field
    expect(find.text('Survive\nThe Talk'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('App renders scenario list when returning user is authenticated',
      (tester) async {
    when(() => mockAuthBloc.state).thenReturn(AuthAuthenticated());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthAuthenticated()),
      initialState: AuthAuthenticated(),
    );

    await tester.pumpWidget(App(authBloc: mockAuthBloc));
    await tester.pumpAndSettle();

    expect(find.byType(MaterialApp), findsOneWidget);
    // AC5: returning user skips auth and lands on root (scenario list)
    expect(find.text('Scenario List — Story 5.2'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('App survives textScaler 1.5 (dynamic type)', (tester) async {
    when(() => mockAuthBloc.state).thenReturn(AuthInitial());
    whenListen(
      mockAuthBloc,
      Stream<AuthState>.value(AuthInitial()),
      initialState: AuthInitial(),
    );

    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.5)),
        child: App(authBloc: mockAuthBloc),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Survive\nThe Talk'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
