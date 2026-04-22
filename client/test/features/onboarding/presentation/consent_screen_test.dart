import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/features/onboarding/bloc/onboarding_bloc.dart';
import 'package:client/features/onboarding/bloc/onboarding_event.dart';
import 'package:client/features/onboarding/bloc/onboarding_state.dart';
import 'package:client/features/onboarding/presentation/consent_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockOnboardingBloc
    extends MockBloc<OnboardingEvent, OnboardingState>
    implements OnboardingBloc {}

void main() {
  late MockOnboardingBloc mockBloc;

  setUpAll(() {
    registerFallbackValue(const AcceptConsentEvent());
  });

  setUp(() {
    mockBloc = MockOnboardingBloc();
  });

  Widget buildSubject() {
    return MaterialApp(
      home: BlocProvider<OnboardingBloc>.value(
        value: mockBloc,
        child: const ConsentScreen(),
      ),
    );
  }

  group('ConsentScreen', () {
    testWidgets('renders title with NOT REAL. STILL BRUTAL.', (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const ConsentRequired());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const ConsentRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(find.text('NOT'), findsOneWidget);
      expect(find.text('REAL.'), findsOneWidget);
      expect(find.text('STILL'), findsOneWidget);
      expect(find.text('BRUTAL.'), findsOneWidget);
    });

    testWidgets('renders AI disclosure description with bold segments',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const ConsentRequired());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const ConsentRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(find.textContaining('AI-generated'), findsOneWidget);
      expect(find.textContaining('sweat'), findsOneWidget);
    });

    testWidgets('renders "I\'m in - hit me" button', (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const ConsentRequired());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const ConsentRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(find.text("I'm in - hit me"), findsOneWidget);
      expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);
    });

    testWidgets('renders legal text with privacy policy link', (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const ConsentRequired());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const ConsentRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(find.textContaining('privacy policy'), findsOneWidget);
    });

    testWidgets('button tap dispatches AcceptConsentEvent', (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const ConsentRequired());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const ConsentRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      await tester.tap(find.text("I'm in - hit me"));

      verify(() => mockBloc.add(any(that: isA<AcceptConsentEvent>()))).called(1);
    });

    testWidgets('shows loading spinner when ConsentAccepting state',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const ConsentAccepting());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const ConsentAccepting());

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text("I'm in - hit me"), findsNothing);
    });

    testWidgets('shows error text when OnboardingError state',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state)
          .thenReturn(const OnboardingError('Could not save consent. Please try again.'));

      final controller = StreamController<OnboardingState>();
      whenListen(mockBloc, controller.stream,
          initialState: const OnboardingError('Could not save consent. Please try again.'));

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(
        find.text('Could not save consent. Please try again.'),
        findsOneWidget,
      );

      await controller.close();
    });
  });
}
