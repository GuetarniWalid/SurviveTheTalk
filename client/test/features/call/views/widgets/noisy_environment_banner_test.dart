import 'package:client/core/theme/app_colors.dart';
import 'package:client/features/call/services/env_warning_payload.dart';
import 'package:client/features/call/views/widgets/noisy_environment_banner.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // Story 6.11 AC7 — the in-call noisy-environment banner.

  Future<void> pumpBanner(
    WidgetTester tester,
    EnvWarningPayload? payload,
  ) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: NoisyEnvironmentBanner(payload: payload),
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('renders title + subtitle + icon when a payload is present', (
    tester,
  ) async {
    await pumpBanner(
      tester,
      const EnvWarningPayload(reason: 'background_voice', detectedSpeakers: 2),
    );

    expect(find.text('Background voice detected'), findsOneWidget);
    expect(
      find.text("Call ending — your daily call won't be counted"),
      findsOneWidget,
    );
    expect(find.byIcon(Icons.volume_off), findsOneWidget);
  });

  testWidgets('renders nothing (SizedBox.shrink) when payload is null', (
    tester,
  ) async {
    await pumpBanner(tester, null);

    expect(find.text('Background voice detected'), findsNothing);
    expect(find.byIcon(Icons.volume_off), findsNothing);
  });

  testWidgets('uses the amber warning token for the surface', (tester) async {
    await pumpBanner(
      tester,
      const EnvWarningPayload(reason: 'background_voice', detectedSpeakers: 2),
    );

    final container = tester.widget<Container>(
      find
          .descendant(
            of: find.byType(NoisyEnvironmentBanner),
            matching: find.byType(Container),
          )
          .first,
    );
    final decoration = container.decoration as BoxDecoration;
    expect(decoration.color, AppColors.warning);
  });

  testWidgets('exposes a semantics label for screen readers', (tester) async {
    await pumpBanner(
      tester,
      const EnvWarningPayload(reason: 'background_voice', detectedSpeakers: 2),
    );

    expect(
      find.bySemanticsLabel(
        RegExp("Background voice detected.*won't be counted"),
      ),
      findsOneWidget,
    );
  });
}
