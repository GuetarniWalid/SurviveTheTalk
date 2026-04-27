import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../bloc/scenarios_bloc.dart';
import '../bloc/scenarios_event.dart';
import '../bloc/scenarios_state.dart';
import '../models/scenario.dart';
import 'widgets/scenario_card.dart';

class ScenarioListScreen extends StatelessWidget {
  const ScenarioListScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        top: true,
        bottom: false,
        // Figma `iPhone 16 - 5` frame: padding 30 18 0 18, gap 12 between
        // cards. Bottom padding stays 0 so Story 5.3's overlay card can
        // extend into the bottom safe area without an awkward gutter.
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
                case ScenariosLoaded(:final scenarios):
                  return _List(scenarios: scenarios);
                case ScenariosError(:final message):
                  return _ErrorView(message: message);
              }
            },
          ),
        ),
      ),
    );
  }
}

class _List extends StatelessWidget {
  final List<Scenario> scenarios;

  const _List({required this.scenarios});

  @override
  Widget build(BuildContext context) {
    return ListView.separated(
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
