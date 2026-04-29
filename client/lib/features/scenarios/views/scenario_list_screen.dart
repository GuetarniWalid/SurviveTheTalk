import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../paywall/views/paywall_sheet.dart';
import '../bloc/scenarios_bloc.dart';
import '../bloc/scenarios_event.dart';
import '../bloc/scenarios_state.dart';
import '../models/call_usage.dart';
import '../models/scenario.dart';
import 'widgets/bottom_overlay_card.dart';
import 'widgets/content_warning_sheet.dart';
import 'widgets/scenario_card.dart';

class ScenarioListScreen extends StatelessWidget {
  const ScenarioListScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      // Each state owns its own SafeArea + Padding envelope: the loaded
      // list uses iPhone 16 - 5 metrics (top: true, bottom: false, h-pad
      // 18) so the pinned BOC can bleed into the bottom safe-area, while
      // the error view (Story 5.5 Figma iphone-16-8) wants top + bottom
      // SafeArea + h-pad 36 because the "Try again" button sits at the
      // bottom and must respect the home-indicator inset.
      body: Stack(
        children: [
          BlocBuilder<ScenariosBloc, ScenariosState>(
            builder: (context, state) {
              switch (state) {
                case ScenariosInitial():
                case ScenariosLoading():
                  return const SizedBox.shrink();
                case ScenariosLoaded(:final scenarios, :final usage):
                  return SafeArea(
                    top: true,
                    bottom: false,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(
                        AppSpacing.screenHorizontalScenarioList,
                        AppSpacing.screenVerticalList,
                        AppSpacing.screenHorizontalScenarioList,
                        0,
                      ),
                      child: _List(scenarios: scenarios, usage: usage),
                    ),
                  );
                case ScenariosError(:final code, :final retryCount):
                  return _ErrorView(code: code, retryCount: retryCount);
              }
            },
          ),
          const Positioned(left: 0, right: 0, bottom: 0, child: _OverlayHost()),
        ],
      ),
    );
  }
}

/// Pinned bottom overlay that surfaces the user's remaining call budget /
/// paywall CTA when the scenarios list is loaded.
///
/// During Loading/Error/Initial we have no CallUsage to render — emitting
/// a half-state would mislead the user about their remaining calls. The
/// error view (full-area) is the entire screen.
class _OverlayHost extends StatelessWidget {
  const _OverlayHost();

  @override
  Widget build(BuildContext context) {
    // No `buildWhen` — `ScenariosLoaded` has no value-equality (spec: NO
    // Equatable) so any custom predicate based on identity would still
    // rebuild on every emit. Letting BlocBuilder rebuild unconditionally
    // is honest about the cost and avoids a misleading no-op predicate.
    return BlocBuilder<ScenariosBloc, ScenariosState>(
      builder: (context, state) {
        if (state is! ScenariosLoaded) return const SizedBox.shrink();
        return BottomOverlayCard(
          usage: state.usage,
          // `context.mounted` guards against the rare race where the
          // BlocBuilder rebuilds (unmounting this BOC) between gesture
          // recognition and the tap firing. Without the guard, the closure
          // would call `showModalBottomSheet` with a deactivated context.
          onPaywallTap: () {
            if (!context.mounted) return;
            PaywallSheet.show(context);
          },
        );
      },
    );
  }
}

class _List extends StatelessWidget {
  final List<Scenario> scenarios;
  final CallUsage usage;

  const _List({required this.scenarios, required this.usage});

  @override
  Widget build(BuildContext context) {
    // Reserve exactly the BOC's rendered height (static content + the
    // device's bottom safe-area inset) so the last ScenarioCard sits flush
    // above the pinned overlay. The split avoids LayoutBuilder jitter
    // (static portion is layout-known) while staying accurate per device
    // (safe-area portion comes from MediaQuery). When the BOC is absent
    // (paid-with-calls — `BottomOverlayCard.isVisibleFor` returns false),
    // reserve nothing so paid users don't see a phantom bottom gutter.
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    final reservedForOverlay = BottomOverlayCard.isVisibleFor(usage)
        ? BottomOverlayCard.staticContentHeight + bottomInset
        : 0.0;
    return ListView.separated(
      padding: EdgeInsets.only(bottom: reservedForOverlay),
      itemCount: scenarios.length,
      separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.cardGap),
      itemBuilder: (context, i) {
        final scenario = scenarios[i];
        return ScenarioCard(
          scenario: scenario,
          onCallTap: () => _onCallTap(context, scenario),
          onCardTap: () => _onCardTap(context, scenario),
          onReportTap: scenario.isNotAttempted
              ? null
              : () => _onReportTap(context, scenario),
        );
      },
    );
  }

  // Navigation strategy (AC5, post-review decision 4 — 2026-04-27):
  //   - /call uses `go` so back-swipe cannot exit a live WebRTC session
  //     mid-call; the call screen owns its own hang-up flow.
  //   - /briefing and /debrief use `push` so the user can back-swipe to the
  //     scenario list naturally (these are read-only "preview" surfaces).
  //
  // Story 5.4 (AC1): when `scenario.contentWarning != null`, await the
  // content-warning sheet gate before navigating; cancel returns to list
  // with no state change. Scenarios with no warning navigate directly.
  Future<void> _onCallTap(BuildContext context, Scenario scenario) async {
    if (scenario.contentWarning != null) {
      final proceed = await showContentWarningSheet(context, scenario);
      if (!proceed) return;
      if (!context.mounted) return;
    }
    context.go(AppRoutes.call, extra: scenario);
  }

  void _onReportTap(BuildContext context, Scenario scenario) {
    context.push('${AppRoutes.debrief}/${scenario.id}');
  }

  void _onCardTap(BuildContext context, Scenario scenario) {
    context.push('${AppRoutes.briefing}/${scenario.id}');
  }
}

class _ErrorView extends StatelessWidget {
  final String code;
  final int retryCount;

  const _ErrorView({required this.code, required this.retryCount});

  @override
  Widget build(BuildContext context) {
    // Retry is dispatched ONLY through the "Try again" button (Story 5.5
    // post-Figma decision — 2026-04-29). The previous full-area
    // GestureDetector (Story 5.2 post-review decision 6) is intentionally
    // removed: with a discoverable accent-green CTA at the bottom, the
    // hidden "tap anywhere" affordance was redundant and could fire on
    // accidental scroll-to-end gestures.
    //
    // Layout follows Figma `iPhone 16 - 8` (Story 5.5 redesign): SafeArea
    // both ends (the simulated 30px vertical padding becomes the system
    // safe-area inset), horizontal 36 padding, vertical sequence:
    //   - Expanded + SingleChildScrollView wrap the upper content so the
    //     button stays pinned at the bottom even when the column would
    //     overflow (small phones × textScaler 1.5)
    //     · 36 gap (Frame 32 top padding)
    //     · 105×105 circle with the code-specific icon
    //     · 36 gap (Frame 32 bottom padding)
    //     · · HEADS UP · badge in accent green
    //     · HOLD ON title in Frijole 40 (common across all error codes)
    //     · 20 gap (Frame 34 bottom padding)
    //     · code-specific subtitle in Inter 24 w700
    //     · 10 gap (Frame 35 bottom padding)
    //     · body in Inter 14 (with retry-count variant)
    //   - Try again pill (accent green, onboarding-harmonised) wrapped in
    //     EdgeInsets.fromLTRB(10, 10, 10, 30) — the 30 bottom lifts the
    //     CTA above the home-indicator gesture area
    void retry() =>
        context.read<ScenariosBloc>().add(const LoadScenariosEvent());

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
            // Content scrolls if it doesn't fit (small phones × big
            // textScaler) — the button stays pinned at the bottom as a
            // sibling, never absorbed by the scroll view. Verified by
            // the "320×480 with textScaler 1.5" overflow regression.
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
                      _titleFor(code),
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
                      _bodyFor(code, retryCount),
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
            // Primary CTA — harmonised with onboarding (consent_screen +
            // mic_permission_screen): SizedBox h:64 + FilledButton +
            // RoundedRectangleBorder r:32 (pill) + Inter 17 w700 on
            // accent. Single source of visual truth across the app's
            // primary actions; if onboarding's pattern shifts, this
            // moves with it.
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 10, 10, 30),
              child: SizedBox(
                width: double.infinity,
                height: 64,
                child: FilledButton(
                  onPressed: retry,
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(32),
                    ),
                  ),
                  // FittedBox handles textScaler 1.5+ on narrow phones —
                  // scales the icon+label cluster down rather than
                  // overflowing horizontally. At normal scale the cluster
                  // sits at its natural size, centered.
                  child: const FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.refresh,
                          color: AppColors.background,
                          size: 24,
                        ),
                        SizedBox(width: 10),
                        Text(
                          'Try again',
                          style: TextStyle(
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

/// `· HEADS UP ·` accent-green badge above the HOLD ON title. Two 2-px
/// dots flank the label with a 5-px gap. Wrapped in `mainAxisSize.min` so
/// the badge cluster hugs its content and sits left-aligned in the column.
/// The dots are decorative — `ExcludeSemantics` keeps them out of the
/// screen-reader narration so TalkBack/VoiceOver hears just "HEADS UP".
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

// Code → copy / icon tables (AC4, AC5). Locked English copy — no near-miss
// rewordings without a UX-decision update. The repeat-failure body
// override kicks in at retryCount >= 1; the title is sticky.
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
