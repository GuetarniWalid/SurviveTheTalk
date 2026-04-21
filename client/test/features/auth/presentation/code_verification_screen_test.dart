import 'package:bloc_test/bloc_test.dart';
import 'package:client/features/auth/bloc/auth_bloc.dart';
import 'package:client/features/auth/bloc/auth_event.dart';
import 'package:client/features/auth/bloc/auth_state.dart';
import 'package:client/features/auth/presentation/code_verification_screen.dart';
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
    when(() => mockAuthBloc.state).thenReturn(AuthCodeSent('test@example.com'));
  });

  Widget buildSubject() {
    return MaterialApp(
      home: BlocProvider<AuthBloc>.value(
        value: mockAuthBloc,
        child: const CodeVerificationScreen(email: 'test@example.com'),
      ),
    );
  }

  /// Pump past the AppToast delayed entry (600ms) and auto-dismiss (10s)
  /// to avoid pending timer errors at test teardown.
  Future<void> clearToastTimers(WidgetTester tester) async {
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump(const Duration(seconds: 10));
    await tester.pump(const Duration(milliseconds: 300));
  }

  group('CodeVerificationScreen', () {
    testWidgets('renders code field, verify button, and resend button',
        (tester) async {
      await tester.pumpWidget(buildSubject());

      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('Verify'), findsOneWidget);
      expect(find.textContaining('You can request a new code in'), findsOneWidget);

      await clearToastTimers(tester);
    });

    testWidgets('shows email confirmation text', (tester) async {
      await tester.pumpWidget(buildSubject());

      expect(find.text('Code sent to test@example.com'), findsOneWidget);

      await clearToastTimers(tester);
    });

    testWidgets('auto-submits when 6 digits entered', (tester) async {
      await tester.pumpWidget(buildSubject());

      await tester.enterText(find.byType(TextField), '123456');
      await tester.pump();

      verify(
        () => mockAuthBloc.add(
          any(that: isA<SubmitCodeEvent>()),
        ),
      ).called(1);

      await clearToastTimers(tester);
    });

    testWidgets('resend dispatches SubmitEmailEvent after cooldown',
        (tester) async {
      await tester.pumpWidget(buildSubject());

      // Cooldown message visible
      expect(find.textContaining('You can request a new code in'), findsOneWidget);

      // Fast-forward past the 60s cooldown
      for (int i = 0; i < 60; i++) {
        await tester.pump(const Duration(seconds: 1));
      }

      await tester.tap(find.text('Resend code'));
      await tester.pump();

      verify(
        () => mockAuthBloc.add(
          any(that: isA<SubmitEmailEvent>()),
        ),
      ).called(1);
    });

    testWidgets('does not dispatch when code is too short', (tester) async {
      await tester.pumpWidget(buildSubject());

      await tester.enterText(find.byType(TextField), '123');
      await tester.tap(find.text('Verify'));
      await tester.pump();

      verifyNever(
        () => mockAuthBloc.add(any(that: isA<SubmitCodeEvent>())),
      );

      await clearToastTimers(tester);
    });

    testWidgets('shows error text when AuthError state', (tester) async {
      when(() => mockAuthBloc.state).thenReturn(
        AuthError(
          'Invalid code. Please check and try again.',
          previousState: AuthCodeSent('test@example.com'),
        ),
      );
      whenListen(
        mockAuthBloc,
        Stream<AuthState>.value(
          AuthError(
            'Invalid code. Please check and try again.',
            previousState: AuthCodeSent('test@example.com'),
          ),
        ),
        initialState: AuthError(
          'Invalid code. Please check and try again.',
          previousState: AuthCodeSent('test@example.com'),
        ),
      );

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(
        find.text('Invalid code. Please check and try again.'),
        findsOneWidget,
      );

      await clearToastTimers(tester);
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
      expect(find.text('Verify'), findsNothing);

      await clearToastTimers(tester);
    });
  });
}
