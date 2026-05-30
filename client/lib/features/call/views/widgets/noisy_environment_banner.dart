import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../services/env_warning_payload.dart';

/// Story 6.11 AC7 — in-call banner shown when the server's
/// `EnvironmentMonitor` detects a parasitic background voice (the
/// `env_warning` data-channel envelope). It appears the moment the
/// warning arrives and persists through the character's noisy-environment
/// exit line, so the user SEES the cause while they HEAR the character
/// react — connecting "background voice → the character is cutting the
/// call → it won't count against my daily limit".
///
/// Rendered by `CallScreen` as a top overlay, BELOW the checkpoint HUD and
/// ABOVE the Rive character. The call screen wraps it in `IgnorePointer` so
/// taps fall through to the character / hang-up button (AC7: must not block
/// either).
///
/// Renders [SizedBox.shrink] when [payload] is null (no warning active) —
/// same null-contract as `CheckpointStepHud`, so the call screen can drive
/// it straight from a `ValueListenableBuilder<EnvWarningPayload?>`.
///
/// Design: amber ([AppColors.warning]) surface with dark
/// ([AppColors.background]) icon + text for high contrast (~9:1). Uses
/// existing [AppColors] + [AppSpacing] tokens only — NO new design tokens
/// (AC7).
class NoisyEnvironmentBanner extends StatelessWidget {
  final EnvWarningPayload? payload;

  const NoisyEnvironmentBanner({super.key, required this.payload});

  @override
  Widget build(BuildContext context) {
    if (payload == null) return const SizedBox.shrink();

    return Semantics(
      liveRegion: true,
      label: 'Background voice detected. Call ending. '
          "Your daily call won't be counted.",
      container: true,
      child: Container(
        margin: const EdgeInsets.symmetric(
          horizontal: AppSpacing.screenHorizontal,
        ),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.cardPaddingHorizontal,
          vertical: AppSpacing.cardInternalPaddingVertical,
        ),
        decoration: BoxDecoration(
          color: AppColors.warning,
          borderRadius: BorderRadius.circular(AppSpacing.base * 1.5),
        ),
        child: const Row(
          children: [
            Icon(
              Icons.volume_off,
              color: AppColors.background,
              size: AppSpacing.iconSmall,
            ),
            SizedBox(width: AppSpacing.overlayIconTextGap),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'Background voice detected',
                    style: TextStyle(
                      fontFamily: 'Inter',
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.background,
                      height: 1.2,
                    ),
                  ),
                  SizedBox(height: 2),
                  Text(
                    "Call ending — your daily call won't be counted",
                    style: TextStyle(
                      fontFamily: 'Inter',
                      fontSize: 13,
                      fontWeight: FontWeight.w400,
                      color: AppColors.background,
                      height: 1.25,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
