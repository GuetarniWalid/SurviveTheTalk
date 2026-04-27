import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../models/scenario.dart';

/// Builds the screen-reader description for a scenario card.
///
/// Top-level free function so the AC7 strings are unit-testable without
/// pumping a widget tree.
///
/// Action hints (`View briefing`, `Call X`, `View debrief`) are NOT in this
/// string — they live on each focal `Semantics` node so the screen reader
/// announces each tappable area independently.
String buildCardDescriptionLabel(Scenario s) {
  final base = '${s.title}. ${s.tagline}.';
  if (s.isNotAttempted) {
    return '$base Not attempted.';
  }
  final score = s.bestScore ?? 0;
  final attemptsWord = _pluralAttempts(s.attempts);
  if (s.isCompleted) {
    return '$base Best $score%, ${s.attempts} $attemptsWord, completed.';
  }
  return '$base Best $score%, ${s.attempts} $attemptsWord, in progress.';
}

String _pluralAttempts(int n) => n == 1 ? 'attempt' : 'attempts';

/// One row in the scenario list. Mirrors the Figma `iPhone 16 - 5` frame:
/// fixed-height card (65 / 85 px), 50×50 character avatar on the left,
/// title + italic tagline + optional stats line in the middle, and
/// optional report + phone action icons on the right.
///
/// Semantic structure (AC7, 2026-04-27 restructure):
///   - The avatar+text block is a `Semantics(button: true, hint: 'View
///     briefing')` focal node — the row-tap target. Tapping anywhere on it
///     navigates to `/briefing/:id`.
///   - The two `_IconButton`s are sibling focal nodes with their own
///     `Semantics(button: true, label: ...)`. They never get merged into the
///     description because they sit OUTSIDE the description's Semantics
///     subtree.
///   - The outer GestureDetector(behavior: opaque) catches taps in the
///     padding gutters (between the description block and the icons, plus the
///     left/right horizontal padding) and routes them to `onCardTap` too —
///     so the user perceives the whole card as one tap zone for briefing.
class ScenarioCard extends StatelessWidget {
  final Scenario scenario;
  final VoidCallback onCallTap;
  final VoidCallback onCardTap;
  final VoidCallback? onReportTap;

  const ScenarioCard({
    super.key,
    required this.scenario,
    required this.onCallTap,
    required this.onCardTap,
    this.onReportTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onCardTap,
      child: Padding(
        // Figma card spec (Frame 21/19/20): padding 5 vertical, 20 horizontal.
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.cardPaddingHorizontal,
          vertical: AppSpacing.cardPaddingVertical,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Expanded(
              child: _DescriptionBlock(
                scenario: scenario,
                onTap: onCardTap,
              ),
            ),
            const SizedBox(width: AppSpacing.cardTextActionsGap),
            _Actions(
              onCallTap: onCallTap,
              onReportTap: onReportTap,
              callLabel: 'Call ${scenario.title}',
            ),
          ],
        ),
      ),
    );
  }
}

/// Avatar + text column wrapped in one focal `Semantics(button: true)` node.
///
/// MergeSemantics fuses the underlying Text widgets so VoiceOver/TalkBack
/// reads one composed announcement rather than four separate ones (title,
/// tagline, "Best:", stats tail). The outer Semantics carries the button
/// flag + hint so the announcement ends with "double-tap to View briefing".
class _DescriptionBlock extends StatelessWidget {
  final Scenario scenario;
  final VoidCallback onTap;

  const _DescriptionBlock({required this.scenario, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return MergeSemantics(
      child: Semantics(
        button: true,
        container: true,
        label: buildCardDescriptionLabel(scenario),
        hint: 'View briefing',
        onTap: onTap,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            _Avatar(character: scenario.riveCharacter),
            const SizedBox(width: AppSpacing.cardAvatarTextGap),
            Expanded(child: _TextColumn(scenario: scenario)),
          ],
        ),
      ),
    );
  }
}

/// Static character thumbnail.
///
/// Uses a pre-extracted JPG (square `assets/images/characters/<character>.jpg`)
/// inside a `ClipOval` so the list scales to N rows without the per-widget
/// GPU surface allocation that comes with `RiveWidget`. The animated puppet
/// is reserved for the in-call screen where only one instance is on-screen at
/// a time. If the asset is missing (e.g. a new scenario was added without
/// shipping a thumbnail), we fall back to the flat `#414143` circle.
class _Avatar extends StatelessWidget {
  final String character;

  const _Avatar({required this.character});

  @override
  Widget build(BuildContext context) {
    return ClipOval(
      child: Container(
        width: AppSpacing.avatarSmall,
        height: AppSpacing.avatarSmall,
        color: AppColors.avatarBg,
        child: Image.asset(
          'assets/images/characters/$character.jpg',
          width: AppSpacing.avatarSmall,
          height: AppSpacing.avatarSmall,
          fit: BoxFit.cover,
          errorBuilder: (_, _, _) => const SizedBox.shrink(),
        ),
      ),
    );
  }
}

class _TextColumn extends StatelessWidget {
  final Scenario scenario;

  const _TextColumn({required this.scenario});

  @override
  Widget build(BuildContext context) {
    final showStats = !scenario.isNotAttempted;
    return Padding(
      padding: const EdgeInsets.symmetric(
        vertical: AppSpacing.cardInternalPaddingVertical,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            scenario.title,
            style: AppTypography.cardTitle.copyWith(
              color: AppColors.textPrimary,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: AppSpacing.cardTextGap),
          Text(
            scenario.tagline,
            style: AppTypography.cardTagline.copyWith(
              color: AppColors.textPrimary,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          if (showStats) ...[
            const SizedBox(height: AppSpacing.cardTextGap),
            _StatsLine(scenario: scenario),
          ],
        ],
      ),
    );
  }
}

class _StatsLine extends StatelessWidget {
  final Scenario scenario;

  const _StatsLine({required this.scenario});

  @override
  Widget build(BuildContext context) {
    final score = scenario.bestScore ?? 0;
    final tailColor = scenario.isCompleted
        ? AppColors.statusCompleted
        : AppColors.statusInProgress;
    return Text.rich(
      TextSpan(
        style: AppTypography.cardStats.copyWith(color: AppColors.textPrimary),
        children: [
          const TextSpan(text: 'Best: '),
          TextSpan(
            text:
                '$score% · ${scenario.attempts} '
                '${_pluralAttempts(scenario.attempts)}',
            style: TextStyle(color: tailColor),
          ),
        ],
      ),
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
    );
  }
}

class _Actions extends StatelessWidget {
  final VoidCallback onCallTap;
  final VoidCallback? onReportTap;
  final String callLabel;

  const _Actions({
    required this.onCallTap,
    required this.onReportTap,
    required this.callLabel,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (onReportTap != null) ...[
          _IconButton(
            icon: Icons.assignment_outlined,
            label: 'View debrief',
            onTap: onReportTap!,
          ),
          const SizedBox(width: AppSpacing.cardIconGap),
        ],
        _IconButton(
          icon: Icons.phone_outlined,
          label: callLabel,
          onTap: onCallTap,
        ),
      ],
    );
  }
}

class _IconButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _IconButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: label,
      child: InkResponse(
        onTap: onTap,
        radius: AppSpacing.touchTargetComfortable / 2,
        child: SizedBox(
          width: AppSpacing.touchTargetComfortable,
          height: AppSpacing.touchTargetComfortable,
          child: Icon(
            icon,
            size: AppSpacing.iconSmall,
            color: AppColors.textPrimary,
          ),
        ),
      ),
    );
  }
}
