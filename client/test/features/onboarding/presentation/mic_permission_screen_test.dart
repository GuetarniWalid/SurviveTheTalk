import 'dart:async';

import 'package:bloc_test/bloc_test.dart';
import 'package:client/features/onboarding/bloc/onboarding_bloc.dart';
import 'package:client/features/onboarding/bloc/onboarding_event.dart';
import 'package:client/features/onboarding/bloc/onboarding_state.dart';
import 'package:client/features/onboarding/presentation/mic_permission_screen.dart';
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
    registerFallbackValue(const RequestMicPermissionEvent());
    registerFallbackValue(const OpenAppSettingsEvent());
  });

  setUp(() {
    mockBloc = MockOnboardingBloc();
  });

  Widget buildSubject() {
    return MaterialApp(
      home: BlocProvider<OnboardingBloc>.value(
        value: mockBloc,
        child: const MicPermissionScreen(),
      ),
    );
  }

  group('MicPermissionScreen', () {
    testWidgets('renders title, CTA button, and privacy text', (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const MicRequired());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const MicRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pumpAndSettle();

      expect(find.textContaining('hear'), findsOneWidget);
      expect(find.text('Allow microphone'), findsOneWidget);
      expect(
        find.textContaining('The AI only listens during calls'),
        findsOneWidget,
      );
      expect(
        find.textContaining('What we do with your voice'),
        findsOneWidget,
      );
    });

    testWidgets('shows loading spinner in CTA when MicPermissionRequested',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state)
          .thenReturn(const MicPermissionRequested());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const MicPermissionRequested());

      await tester.pumpWidget(buildSubject());
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Allow microphone'), findsNothing);
    });

    testWidgets(
        'tapping Allow microphone dispatches RequestMicPermissionEvent',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const MicRequired());
      whenListen(mockBloc, const Stream<OnboardingState>.empty(),
          initialState: const MicRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Allow microphone'));
      await tester.pump();

      verify(
        () => mockBloc.add(any(that: isA<RequestMicPermissionEvent>())),
      ).called(1);
    });

    testWidgets('shows mic denied bottom sheet when MicDenied state',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const MicRequired());

      final controller = StreamController<OnboardingState>();
      whenListen(mockBloc, controller.stream,
          initialState: const MicRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pumpAndSettle();

      // Transition to MicDenied
      when(() => mockBloc.state).thenReturn(const MicDenied());
      controller.add(const MicDenied());
      await tester.pumpAndSettle();

      expect(find.text('Mic is blocked'), findsOneWidget);
      expect(find.textContaining("officer can't hear you"), findsOneWidget);
      expect(find.text('Open Settings'), findsWidgets);

      await controller.close();
    });

    testWidgets(
        'bottom sheet "Open Settings" dispatches OpenAppSettingsEvent',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 1200));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      when(() => mockBloc.state).thenReturn(const MicRequired());

      final controller = StreamController<OnboardingState>();
      whenListen(mockBloc, controller.stream,
          initialState: const MicRequired());

      await tester.pumpWidget(buildSubject());
      await tester.pumpAndSettle();

      // Trigger MicDenied
      when(() => mockBloc.state).thenReturn(const MicDenied());
      controller.add(const MicDenied());
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'Open Settings'));
      await tester.pump();

      verify(() => mockBloc.add(any(that: isA<OpenAppSettingsEvent>())));

      await controller.close();
    });
  });
}
