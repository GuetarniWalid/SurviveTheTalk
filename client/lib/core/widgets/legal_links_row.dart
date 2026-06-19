import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../legal_urls.dart';
import '../theme/app_typography.dart';

/// Two quiet, underlined external links — "Privacy Policy" · "Terms of Use" —
/// that open the hosted legal pages ([LegalUrls]) in an external browser
/// (Story 10.1, AC6). Shared by the paywall, the account sheet, and the manage
/// drawer.
///
/// The launcher is injectable (the `StoreLinks._launch` seam) so widget tests
/// assert the URL without touching the real `url_launcher` plugin. Rendered as
/// quiet underlined caption text (the Handler's Brief two-ink, zero-furniture
/// rule — links, not buttons/boxes); [color] is the sheet's secondary ink.
class LegalLinksRow extends StatefulWidget {
  final Color color;

  /// Injectable launcher (defaults to `url_launcher`'s `launchUrl` at call time
  /// when null) — the `StoreLinks._launch` test seam.
  final Future<bool> Function(Uri, {LaunchMode mode})? launch;

  const LegalLinksRow({super.key, required this.color, this.launch});

  @override
  State<LegalLinksRow> createState() => _LegalLinksRowState();
}

class _LegalLinksRowState extends State<LegalLinksRow> {
  late final TapGestureRecognizer _privacyRecognizer;
  late final TapGestureRecognizer _termsRecognizer;

  @override
  void initState() {
    super.initState();
    _privacyRecognizer = TapGestureRecognizer()
      ..onTap = () => _open(LegalUrls.privacyPolicy);
    _termsRecognizer = TapGestureRecognizer()
      ..onTap = () => _open(LegalUrls.termsOfService);
  }

  @override
  void dispose() {
    _privacyRecognizer.dispose();
    _termsRecognizer.dispose();
    super.dispose();
  }

  Future<void> _open(String url) async {
    final launch = widget.launch ?? launchUrl;
    await launch(Uri.parse(url), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final base = AppTypography.caption.copyWith(color: widget.color);
    final link = base.copyWith(decoration: TextDecoration.underline);
    return Text.rich(
      TextSpan(
        style: base,
        children: [
          TextSpan(
            text: 'Privacy Policy',
            style: link,
            recognizer: _privacyRecognizer,
          ),
          const TextSpan(text: '   ·   '),
          TextSpan(
            text: 'Terms of Use',
            style: link,
            recognizer: _termsRecognizer,
          ),
        ],
      ),
      textAlign: TextAlign.center,
    );
  }
}
