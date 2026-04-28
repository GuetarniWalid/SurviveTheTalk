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
import 'widgets/scenario_card.dart';

class ScenarioListScreen extends StatelessWidget {
  const ScenarioListScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: Stack(
        children: [
          SafeArea(
            top: true,
            bottom: false,
            // Figma `iPhone 16 - 5` frame: padding 30 18 0 18, gap 12 between
            // cards. Bottom padding stays 0 so the BOC can extend into the
            // bottom safe area without an awkward gutter.
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.screenHorizontalScenarioList,
                AppSpacing.screenVerticalList,
                AppSpacing.screenHorizontalScenarioList,
                0,
              ),
              child: BlocBuilder<ScenariosBloc, ScenariosState>(
                builder: (context, state) {
                  switch (state) {
                    case ScenariosInitial():
                    case ScenariosLoading():
                      return const SizedBox.shrink();
                    case ScenariosLoaded(:final scenarios, :final usage):
                      return _List(scenarios: scenarios, usage: usage);
                    case ScenariosError(:final message):
                      return _ErrorView(message: message);
                  }
                },
              ),
            ),
          ),
          const Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: _OverlayHost(),
          ),
        ],
      ),
    );
  }
}

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
  void _onCallTap(BuildContext context, Scenario scenario) {
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
  final String message;

  const _ErrorView({required this.message});

  @override
  Widget build(BuildContext context) {
    // Whole scaffold body is the retry hit-target (AC3, post-review
    // decision 6 — 2026-04-27). The GestureDetector wraps the Center so
    // it inherits the full available area; HitTestBehavior.opaque catches
    // taps in the empty space above/below the centered message too. The
    // text remains visually centred for legibility.
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () =>
          context.read<ScenariosBloc>().add(const LoadScenariosEvent()),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              message,
              textAlign: TextAlign.center,
              style: AppTypography.body.copyWith(color: AppColors.destructive),
            ),
            const SizedBox(height: AppSpacing.base),
            Text(
              'Tap to retry',
              textAlign: TextAlign.center,
              style: AppTypography.caption.copyWith(
                color: AppColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
