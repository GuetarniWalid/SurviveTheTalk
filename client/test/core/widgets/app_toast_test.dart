import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/widgets/app_toast.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('AppToast', () {
    testWidgets('shows message text when triggered', (tester) async {
      late BuildContext savedContext;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) {
                savedContext = context;
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      AppToast.show(savedContext, message: 'Hello toast');
      await tester.pump(); // insert overlay
      await tester.pump(const Duration(milliseconds: 600)); // wait for delay
      await tester.pump(const Duration(milliseconds: 400)); // slide-in animation

      expect(find.text('Hello toast'), findsOneWidget);
    });

    testWidgets('shows warning icon for warning type', (tester) async {
      late BuildContext savedContext;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) {
                savedContext = context;
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      AppToast.show(savedContext, message: 'Warning', type: AppToastType.warning);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byIcon(Icons.warning_amber_rounded), findsOneWidget);
    });

    testWidgets('shows error icon for error type', (tester) async {
      late BuildContext savedContext;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) {
                savedContext = context;
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      AppToast.show(savedContext, message: 'Error', type: AppToastType.error);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byIcon(Icons.error_outline), findsOneWidget);
    });

    testWidgets('shows success icon for success type', (tester) async {
      late BuildContext savedContext;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) {
                savedContext = context;
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      AppToast.show(savedContext, message: 'Done', type: AppToastType.success);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byIcon(Icons.check_circle_outline), findsOneWidget);
    });

    testWidgets('auto-dismisses after timeout', (tester) async {
      late BuildContext savedContext;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) {
                savedContext = context;
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      AppToast.show(savedContext, message: 'Bye');
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600)); // delay
      await tester.pump(const Duration(milliseconds: 400)); // slide-in

      expect(find.text('Bye'), findsOneWidget);

      // Fast-forward past the 10s auto-dismiss + 300ms slide-out
      await tester.pump(const Duration(seconds: 10)); // dismiss timer fires
      await tester.pumpAndSettle(); // slide-out animation completes

      expect(find.text('Bye'), findsNothing);
    });

    testWidgets('uses warning color for warning type border', (tester) async {
      late BuildContext savedContext;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) {
                savedContext = context;
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      AppToast.show(savedContext, message: 'Warn', type: AppToastType.warning);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
      await tester.pump(const Duration(milliseconds: 400));

      final icon = tester.widget<Icon>(find.byIcon(Icons.warning_amber_rounded));
      expect(icon.color, AppColors.warning);
    });

    testWidgets('width does not exceed 75% of screen', (tester) async {
      late BuildContext savedContext;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) {
                savedContext = context;
                return const SizedBox.shrink();
              },
            ),
          ),
        ),
      );

      AppToast.show(
        savedContext,
        message: 'A very long message that should be constrained '
            'to at most three quarters of the screen width',
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
      await tester.pump(const Duration(milliseconds: 400));

      final screenWidth = tester.view.physicalSize.width /
          tester.view.devicePixelRatio;
      final constrained = tester.widget<ConstrainedBox>(
        find.descendant(
          of: find.byType(SlideTransition),
          matching: find.byType(ConstrainedBox),
        ),
      );
      expect(
        constrained.constraints.maxWidth,
        moreOrLessEquals(screenWidth * 0.75, epsilon: 1),
      );
    });
  });
}
