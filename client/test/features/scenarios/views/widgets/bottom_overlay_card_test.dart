import 'package:client/core/theme/app_theme.dart';
import 'package:client/features/scenarios/models/call_usage.dart';
import 'package:client/features/scenarios/views/widgets/bottom_overlay_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

const _kFreeWithCalls = CallUsage(
  tier: 'free',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'lifetime',
);

const _kFreeExhausted = CallUsage(
  tier: 'free',
  callsRemaining: 0,
  callsPerPeriod: 3,
  period: 'lifetime',
);

const _kPaidWithCalls = CallUsage(
  tier: 'paid',
  callsRemaining: 3,
  callsPerPeriod: 3,
  period: 'day',
);

const _kPaidExhausted = CallUsage(
  tier: 'paid',
  callsRemaining: 0,
  callsPerPeriod: 3,
  period: 'day',
);

const String _kSubtitleSurvive =
    "If you can survive us, real humans don't stand a chance";

Widget _harness({required CallUsage usage, VoidCallback? onTap}) =>
    MaterialApp(
      theme: AppTheme.dark(),
      home: Scaffold(
        body: Stack(
          children: [
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: BottomOverlayCard(usage: usage, onPaywallTap: onTap),
            ),
          ],
        ),
      ),
    );

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  testWidgets('freeWithCalls renders Unlock title + survive subtitle',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(_harness(usage: _kFreeWithCalls, onTap: () {}));

    expect(find.text('Unlock all scenarios'), findsOneWidget);
    expect(find.text(_kSubtitleSurvive), findsOneWidget);
    // Diamond image slot is present (the Image widget itself; whether it
    // renders the asset or the errorBuilder placeholder is asset-dependent).
    expect(find.byType(Image), findsOneWidget);
  });

  testWidgets(
      'title font is 16 (bumped from Figma 14 for on-device legibility)',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(_harness(usage: _kFreeWithCalls, onTap: () {}));

    final title = tester.widget<Text>(find.text('Unlock all scenarios'));
    expect(
      title.style?.fontSize,
      16,
      reason:
          'Title was bumped from Figma 14 to 16 for legibility on-device. '
          'A re-align with Figma must be deliberate, not silent.',
    );
  });

  testWidgets(
      'subtitle font is 13 (bumped from Figma 11 for on-device legibility)',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(_harness(usage: _kFreeWithCalls, onTap: () {}));

    final subtitle = tester.widget<Text>(find.text(_kSubtitleSurvive));
    expect(
      subtitle.style?.fontSize,
      13,
      reason:
          'Subtitle was bumped from Figma 11 to 13 for legibility on-device. '
          'A re-align with Figma must be deliberate, not silent.',
    );
  });

  testWidgets('freeExhausted renders Subscribe to keep calling',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(_harness(usage: _kFreeExhausted, onTap: () {}));

    expect(find.text('Subscribe to keep calling'), findsOneWidget);
    expect(find.text(_kSubtitleSurvive), findsOneWidget);
  });

  testWidgets('paidWithCalls renders SizedBox.shrink (no visible card)',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(_harness(usage: _kPaidWithCalls));

    expect(find.text('Unlock all scenarios'), findsNothing);
    expect(find.text('Subscribe to keep calling'), findsNothing);
    expect(find.text('No more calls today'), findsNothing);
    // No diamond image slot rendered when the BOC short-circuits to
    // SizedBox.shrink (paid + has calls).
    expect(find.byType(Image), findsNothing);
  });

  testWidgets(
      'paidExhausted renders No more calls today + Come back tomorrow + non-actionable',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    var tapCount = 0;
    await tester.pumpWidget(
      _harness(usage: _kPaidExhausted, onTap: () => tapCount += 1),
    );

    expect(find.text('No more calls today'), findsOneWidget);
    expect(find.text('Come back tomorrow'), findsOneWidget);

    await tester.tap(find.byType(BottomOverlayCard));
    await tester.pump();
    expect(tapCount, 0, reason: 'paidExhausted is informational; no tap');
  });

  testWidgets('tap on freeWithCalls fires onPaywallTap', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    var taps = 0;
    await tester.pumpWidget(
      _harness(usage: _kFreeWithCalls, onTap: () => taps += 1),
    );

    await tester.tap(find.byType(BottomOverlayCard));
    await tester.pump();

    expect(taps, 1);
  });

  testWidgets('tap on freeExhausted fires onPaywallTap', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    var taps = 0;
    await tester.pumpWidget(
      _harness(usage: _kFreeExhausted, onTap: () => taps += 1),
    );

    await tester.tap(find.byType(BottomOverlayCard));
    await tester.pump();

    expect(taps, 1);
  });

  testWidgets('Semantics announces composed label for freeWithCalls',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final handle = tester.ensureSemantics();
    await tester.pumpWidget(_harness(usage: _kFreeWithCalls, onTap: () {}));

    // The wrapping Semantics node must carry the composed label AND be
    // marked as a button (it's an actionable variant — VoiceOver should
    // announce both "tap to subscribe" affordance and the composed copy).
    // Asserting both fields together makes a partial refactor
    // (e.g., dropping `button: true`) fail loudly instead of silently.
    const composedLabel =
        'Unlock all scenarios. $_kSubtitleSurvive. Tap to view subscription options.';
    final matches = find.byWidgetPredicate(
      (w) =>
          w is Semantics &&
          w.properties.label == composedLabel &&
          w.properties.button == true,
    );
    expect(matches, findsOneWidget);

    handle.dispose();
  });

  testWidgets('Semantics is not a button on paidExhausted', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final handle = tester.ensureSemantics();

    await tester.pumpWidget(_harness(usage: _kPaidExhausted));

    final node = tester.getSemantics(find.byType(BottomOverlayCard));
    expect(node.flagsCollection.isButton, isFalse);

    handle.dispose();
  });
}
