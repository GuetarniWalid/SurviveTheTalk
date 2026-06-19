import 'package:client/core/legal_urls.dart';
import 'package:client/core/theme/app_colors.dart';
import 'package:client/core/widgets/legal_links_row.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:url_launcher/url_launcher.dart';

/// Fire the [TapGestureRecognizer] on the inline span whose text == [text].
void tapTextSpan(WidgetTester tester, String text) {
  for (final rt in tester.widgetList<RichText>(find.byType(RichText))) {
    TapGestureRecognizer? recognizer;
    rt.text.visitChildren((span) {
      if (span is TextSpan &&
          span.text == text &&
          span.recognizer is TapGestureRecognizer) {
        recognizer = span.recognizer as TapGestureRecognizer;
        return false;
      }
      return true;
    });
    if (recognizer != null) {
      recognizer!.onTap!();
      return;
    }
  }
  fail('No tappable text span "$text" found');
}

void main() {
  Future<void> pump(
    WidgetTester tester,
    List<Uri> launched,
  ) {
    return tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LegalLinksRow(
            color: AppColors.background,
            launch: (uri, {mode = LaunchMode.platformDefault}) async {
              launched.add(uri);
              return true;
            },
          ),
        ),
      ),
    );
  }

  testWidgets('renders both legal links', (tester) async {
    await pump(tester, []);
    // One Text.rich → match by substring (exact find.text sees the combined
    // "Privacy Policy   ·   Terms of Use" plain text).
    expect(find.textContaining('Privacy Policy'), findsOneWidget);
    expect(find.textContaining('Terms of Use'), findsOneWidget);
  });

  testWidgets('Privacy Policy tap launches the configured privacy URL', (
    tester,
  ) async {
    final launched = <Uri>[];
    await pump(tester, launched);
    tapTextSpan(tester, 'Privacy Policy');
    await tester.pump();
    expect(launched, [Uri.parse(LegalUrls.privacyPolicy)]);
  });

  testWidgets('Terms of Use tap launches the configured terms URL', (
    tester,
  ) async {
    final launched = <Uri>[];
    await pump(tester, launched);
    tapTextSpan(tester, 'Terms of Use');
    await tester.pump();
    expect(launched, [Uri.parse(LegalUrls.termsOfService)]);
  });
}
