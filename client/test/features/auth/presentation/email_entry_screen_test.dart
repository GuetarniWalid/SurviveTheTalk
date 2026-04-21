import 'package:bloc_test/bloc_test.dart';
import 'package:client/features/auth/bloc/auth_bloc.dart';
import 'package:client/features/auth/bloc/auth_event.dart';
import 'package:client/features/auth/bloc/auth_state.dart';
import 'package:client/features/auth/presentation/email_entry_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
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
    when(() => mockAuthBloc.state).thenReturn(AuthInitial());
  });

  Widget buildSubject() {
    return MaterialApp(
      home: BlocProvider<AuthBloc>.value(
        value: mockAuthBloc,
        child: const EmailEntryScreen(),
      ),
    );
  }

  group('EmailEntryScreen', () {
    testWidgets('renders email field and submit button', (tester) async {
      await tester.pumpWidget(buildSubject());

      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('Continue'), findsOneWidget);
    });

    testWidgets('submit dispatches SubmitEmailEvent', (tester) async {
      await tester.pumpWidget(buildSubject());

      await tester.enterText(find.byType(TextField), 'test@example.com');
      await tester.ensureVisible(find.text('Continue'));
      await tester.tap(find.text('Continue'));
      await tester.pump();

      verify(
        () => mockAuthBloc.add(
          any(that: isA<SubmitEmailEvent>()),
        ),
      ).called(1);
    });

    testWidgets('does not dispatch when email is empty', (tester) async {
      await tester.pumpWidget(buildSubject());

      await tester.ensureVisible(find.text('Continue'));
      await tester.tap(find.text('Continue'));
      await tester.pump();

      verifyNever(() => mockAuthBloc.add(any()));
    });

    testWidgets('does not dispatch when email has no @', (tester) async {
      await tester.pumpWidget(buildSubject());

      await tester.enterText(find.byType(TextField), 'invalidemail');
      await tester.ensureVisible(find.text('Continue'));
      await tester.tap(find.text('Continue'));
      await tester.pump();

      verifyNever(() => mockAuthBloc.add(any()));
    });

    testWidgets('shows error text when AuthError state', (tester) async {
      when(() => mockAuthBloc.state).thenReturn(
        AuthError('Network error', previousState: AuthInitial()),
      );
      whenListen(
        mockAuthBloc,
        Stream<AuthState>.value(
          AuthError('Network error', previousState: AuthInitial()),
        ),
        initialState: AuthError('Network error', previousState: AuthInitial()),
      );

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(find.text('Network error'), findsOneWidget);
    });

    testWidgets('shows loading indicator when AuthLoading state',
        (tester) async {
      when(() => mockAuthBloc.state).thenReturn(AuthLoading());
      whenListen(
        mockAuthBloc,
        Stream<AuthState>.value(AuthLoading()),
        initialState: AuthLoading(),
      );

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Continue'), findsNothing);
    });
  });
}
