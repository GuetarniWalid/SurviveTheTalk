// Empathetic no-network surface for the call-dial path (FR8).
//
// Pushed by `scenario_list_screen._handleCallInitiate` when dio surfaces
// `ApiException.code == 'NETWORK_ERROR'`. Reuses the shared
// `EmpatheticErrorScreen` so the visual is identical to the
// scenarios-list offline error — one polish, one update site.
//
// Story 6.5 refactor (Deviation #12 + review D1 hybrid): replaced the
// UX-DR7-specific WiFi-barred / avatar-circle / hang-up-button layout
// with the shared empathetic surface. Walid's call — DRY over spec
// literalism. Three context-specific overrides keep the surface
// faithful to the call-failure semantics:
//   - `bodyOverride`: the default scenarios-list body ("...to load your
//     scenarios") is wrong here — the user was dialing a call, not
//     loading the list. Override to "...to start the call".
//   - `retryLabel: 'Go back'`: the CTA pops back to the scenario list
//     rather than retrying anything; "Try again" was misleading.
//   - `semanticsLabel: 'Close'`: UX-DR12 accessibility — assistive tech
//     announces the action ("Close"), not the visible label.
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/widgets/empathetic_error_screen.dart';

class NoNetworkScreen extends StatelessWidget {
  const NoNetworkScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: EmpatheticErrorScreen(
        code: 'NETWORK_ERROR',
        onRetry: () => Navigator.of(context).maybePop(),
        retryLabel: 'Go back',
        semanticsLabel: 'Close',
        bodyOverride:
            'We need a connection to start the call. Check your Wi-Fi or '
            'mobile data, then try again.',
      ),
    );
  }
}
