import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';

/// Stub screen used until Story 7.4 ships the real pre-scenario briefing.
class BriefingPlaceholderScreen extends StatelessWidget {
  final String scenarioId;

  const BriefingPlaceholderScreen({super.key, required this.scenarioId});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.screenHorizontal,
            vertical: AppSpacing.screenVerticalList,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Semantics(
                button: true,
                label: 'Back to scenarios',
                child: IconButton(
                  icon: const Icon(Icons.arrow_back),
                  color: AppColors.textPrimary,
                  // canPop covers the normal `push` entry from the scenario
                  // list; the `go(root)` fallback covers deep-link or
                  // refresh-style entries where the stack is empty.
                  onPressed: () => context.canPop()
                      ? context.pop()
                      : context.go(AppRoutes.root),
                ),
              ),
              Expanded(
                child: Center(
                  child: Text(
                    'Briefing placeholder — scenario $scenarioId (Story 7.4)',
                    textAlign: TextAlign.center,
                    style: AppTypography.body.copyWith(
                      color: AppColors.textPrimary,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
