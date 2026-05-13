// Empathetic error screen — the single source of truth for "something
// is wrong" full-screen surfaces (Story 5.5 design → Figma `iPhone 16 - 8`).
//
// Used by:
//   - `scenario_list_screen.dart` — initial scenarios load failed.
//   - `no_network_screen.dart` — call-initiate / dial failed before the
//     server was reached (`ApiException.code == 'NETWORK_ERROR'`).
//
// Same visual & copy across both surfaces so a future polish (typography
// tweak, icon swap, new code variant) ships once and lands everywhere.
// Story 6.5 refactor (Deviation #12) — Walid's call to DRY this.
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// Full-bleed error surface with a code-driven copy table.
///
/// `code` is one of the `ApiException` codes ('NETWORK_ERROR',
/// 'SERVER_ERROR', 'MALFORMED_RESPONSE', 'UNKNOWN_ERROR'); unknown codes
/// fall through to the UNKNOWN_ERROR copy. `retryCount` toggles the
/// repeat-failure body variant (verbatim Story 5.5 copy). `onRetry` is
/// the green CTA — callers wire it to whatever "retry" means in their
/// context (re-fetch scenarios, pop back, etc.).
///
/// Story 6.5 review (D1 hybrid) — call-context callers (NoNetworkScreen)
/// need:
///   - `bodyOverride`: the default `_bodyFor('NETWORK_ERROR', ...)` copy
///     says "We need a connection to load your scenarios" which is wrong
///     for a call-failure surface. Pass a context-specific string here
///     to replace the default body text only.
///   - `retryLabel`: defaults to "Try again", but for NoNetworkScreen
///     the CTA pops back rather than retries — "Go back" is accurate.
///   - `semanticsLabel`: assistive-tech label for the CTA, defaults to
///     the visible `retryLabel`. NoNetworkScreen passes 'Close' (UX-DR12
///     accessibility — the action IS closing the no-network surface, not
///     retrying anything).
///
/// Returns the body content only (SafeArea + Padding + Column) — the
/// caller owns the Scaffold. Two usage patterns:
///   - Inside an existing Scaffold's body (scenario_list_screen): drop
///     in directly, the parent already provides Material context +
///     background.
///   - As a standalone route (NoNetworkScreen): wrap in
///     `Scaffold(backgroundColor: AppColors.background, body: ...)`.
class EmpatheticErrorScreen extends StatelessWidget {
  final String code;
  final int retryCount;
  final VoidCallback onRetry;
  final String retryLabel;
  final String? bodyOverride;
  final String? titleOverride;
  final String? semanticsLabel;

  const EmpatheticErrorScreen({
    super.key,
    required this.code,
    required this.onRetry,
    this.retryCount = 0,
    this.retryLabel = 'Try again',
    this.bodyOverride,
    this.titleOverride,
    this.semanticsLabel,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: true,
      bottom: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.screenHorizontalErrorView,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Upper content scrolls if it overflows (small phones ×
            // textScaler 1.5). Retry button stays pinned at the bottom
            // as a sibling, never absorbed by the scroll view.
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const SizedBox(height: 36),
                    Center(child: _IconBadge(icon: _iconFor(code))),
                    const SizedBox(height: 36),
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: _HeadsUpBadge(),
                    ),
                    Semantics(
                      header: true,
                      child: const Text(
                        'HOLD ON',
                        style: TextStyle(
                          fontFamily: 'Frijole',
                          fontSize: 40,
                          fontWeight: FontWeight.w400,
                          color: AppColors.textPrimary,
                          height: 55 / 40,
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),
                    Text(
                      titleOverride ?? _titleFor(code),
                      style: const TextStyle(
                        fontFamily: AppTypography.fontFamily,
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary,
                        height: 29 / 24,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      bodyOverride ?? _bodyFor(code, retryCount),
                      style: const TextStyle(
                        fontFamily: AppTypography.fontFamily,
                        fontSize: 14,
                        fontWeight: FontWeight.w400,
                        color: AppColors.errorBody,
                        height: 17 / 14,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 10, 10, 30),
              child: Semantics(
                button: true,
                label: semanticsLabel ?? retryLabel,
                child: SizedBox(
                  width: double.infinity,
                  height: 64,
                  child: FilledButton(
                    onPressed: onRetry,
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.accent,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(32),
                      ),
                    ),
                    child: FittedBox(
                      fit: BoxFit.scaleDown,
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(
                            Icons.refresh,
                            color: AppColors.background,
                            size: 24,
                          ),
                          const SizedBox(width: 10),
                          Text(
                            retryLabel,
                            style: const TextStyle(
                              fontFamily: AppTypography.fontFamily,
                              fontSize: 17,
                              fontWeight: FontWeight.w700,
                              color: AppColors.background,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 105×105 circle wrapping the code-specific icon. Fill is `textSecondary`
/// at 10% alpha, stroke is `textSecondary` at 30% alpha — derived tones
/// that don't warrant new tokens (single-use, mathematically obvious).
class _IconBadge extends StatelessWidget {
  final IconData icon;
  const _IconBadge({required this.icon});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 105,
      height: 105,
      decoration: BoxDecoration(
        color: AppColors.textSecondary.withValues(alpha: 0.1),
        border: Border.all(
          color: AppColors.textSecondary.withValues(alpha: 0.3),
          width: 1,
        ),
        shape: BoxShape.circle,
      ),
      child: Icon(icon, size: 41, color: AppColors.textSecondary),
    );
  }
}

/// `· HEADS UP ·` accent-green badge above the HOLD ON title.
class _HeadsUpBadge extends StatelessWidget {
  const _HeadsUpBadge();

  @override
  Widget build(BuildContext context) {
    return const Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        ExcludeSemantics(child: _AccentDot()),
        SizedBox(width: 5),
        Text(
          'HEADS UP',
          style: TextStyle(
            fontFamily: AppTypography.fontFamily,
            fontSize: 12,
            fontWeight: FontWeight.w400,
            color: AppColors.accent,
            height: 15 / 12,
          ),
        ),
        SizedBox(width: 5),
        ExcludeSemantics(child: _AccentDot()),
      ],
    );
  }
}

class _AccentDot extends StatelessWidget {
  const _AccentDot();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 2,
      height: 2,
      decoration: const BoxDecoration(
        color: AppColors.accent,
        shape: BoxShape.circle,
      ),
    );
  }
}

// Code → copy / icon tables (verbatim from Story 5.5). Locked English
// copy — no near-miss rewordings without a UX-decision update. The
// repeat-failure body override kicks in at retryCount >= 1; title is
// sticky.
IconData _iconFor(String code) {
  switch (code) {
    case 'NETWORK_ERROR':
      return Icons.cloud_off_outlined;
    case 'SERVER_ERROR':
      return Icons.hourglass_empty_outlined;
    case 'MALFORMED_RESPONSE':
      return Icons.help_outline;
    case 'UNKNOWN_ERROR':
    default:
      return Icons.error_outline;
  }
}

String _titleFor(String code) {
  switch (code) {
    case 'NETWORK_ERROR':
      return "You're offline.";
    case 'SERVER_ERROR':
      return 'Our servers are catching their breath.';
    case 'MALFORMED_RESPONSE':
      return "Something didn't load right.";
    case 'UNKNOWN_ERROR':
    default:
      return 'Something went wrong.';
  }
}

String _bodyFor(String code, int retryCount) {
  final repeat = retryCount >= 1;
  switch (code) {
    case 'NETWORK_ERROR':
      return repeat
          ? 'Still no signal. Move somewhere with better reception, then try again.'
          : 'We need a connection to load your scenarios. Check your Wi-Fi or mobile data, then try again.';
    case 'SERVER_ERROR':
      return repeat
          ? 'Still struggling on our side. Give it a minute and try again, or restart the app if it persists.'
          : 'This is on us, not you. Try again in a moment.';
    case 'MALFORMED_RESPONSE':
      return repeat
          ? 'Still stuck. Restart the app to clear the slate.'
          : "We've logged the issue. Try again — it usually works on the second try.";
    case 'UNKNOWN_ERROR':
    default:
      return repeat
          ? 'Still failing. Restart the app if this keeps happening.'
          : "We're not sure what happened. Try again in a moment.";
  }
}
