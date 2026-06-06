import 'package:flutter/material.dart';

import '../../../../core/onboarding/difficulty_storage.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_typography.dart';

/// Story 6.19 — modal bottom sheet to set the GLOBAL difficulty preference.
///
/// Cloned from `content_warning_sheet.dart` (the app's only proven modal): light
/// surface, 42px top radius, drag handle, a `StadiumBorder` "Done" button. Lists
/// Easy / Medium / Hard as radio rows with a mint dot on the selected one and an
/// honest, no-gamification one-liner each.
///
/// Returns the chosen level ("easy" | "medium" | "hard") when the user taps
/// "Done", or `null` on any non-explicit dismissal (swipe-down, scrim tap,
/// system back). The caller persists the result.
Future<String?> showDifficultySheet(
  BuildContext context, {
  required String current,
}) {
  return showModalBottomSheet<String>(
    context: context,
    // Sheet provides its own (light) surface — keep the modal background
    // transparent so the rounded corners aren't double-clipped (mirrors
    // content_warning_sheet.dart).
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    isDismissible: true,
    enableDrag: true,
    builder: (ctx) => _DifficultySheet(current: current),
  );
}

/// Honest, no-gamification copy (Story 6.19 AC1) — no stars, no levels-as-reward.
const Map<String, String> _kDifficultyCopy = <String, String>{
  'easy': 'They cut you slack',
  'medium': 'Normal human friction',
  'hard': 'No mercy, no hints',
};

String _label(String level) =>
    '${level[0].toUpperCase()}${level.substring(1)}';

class _DifficultySheet extends StatefulWidget {
  final String current;

  const _DifficultySheet({required this.current});

  @override
  State<_DifficultySheet> createState() => _DifficultySheetState();
}

class _DifficultySheetState extends State<_DifficultySheet> {
  late String _selected = DifficultyStorage.levels.contains(widget.current)
      ? widget.current
      : DifficultyStorage.defaultDifficulty;

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: AppColors.textPrimary,
        borderRadius: BorderRadius.vertical(top: Radius.circular(42)),
      ),
      child: Padding(
        padding: EdgeInsets.fromLTRB(36, 24, 36, 36 + bottomInset),
        // SingleChildScrollView guards against vertical overflow at narrow
        // viewports + large text scale (mirror content_warning_sheet.dart).
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const _DragHandle(),
              const SizedBox(height: 15),
              const _Title(),
              const SizedBox(height: 8),
              for (final level in DifficultyStorage.levels)
                _DifficultyRow(
                  level: level,
                  selected: _selected == level,
                  onTap: () => setState(() => _selected = level),
                ),
              const SizedBox(height: 24),
              _DoneButton(
                onPressed: () => Navigator.pop(context, _selected),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DragHandle extends StatelessWidget {
  const _DragHandle();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: 40,
        height: 4,
        decoration: const BoxDecoration(
          color: AppColors.overlaySubtitle,
          borderRadius: BorderRadius.all(Radius.circular(18)),
        ),
      ),
    );
  }
}

class _Title extends StatelessWidget {
  const _Title();

  @override
  Widget build(BuildContext context) {
    return const Text(
      'Difficulty',
      style: TextStyle(
        fontFamily: AppTypography.fontFamily,
        fontSize: 24,
        fontWeight: FontWeight.w700,
        color: AppColors.background,
        height: 29 / 24,
      ),
    );
  }
}

class _DifficultyRow extends StatelessWidget {
  final String level;
  final bool selected;
  final VoidCallback onTap;

  const _DifficultyRow({
    required this.level,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: const BorderRadius.all(Radius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Row(
          children: [
            _Dot(selected: selected),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _label(level),
                    style: const TextStyle(
                      fontFamily: AppTypography.fontFamily,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: AppColors.background,
                      height: 20 / 16,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    _kDifficultyCopy[level] ?? '',
                    style: TextStyle(
                      fontFamily: AppTypography.fontFamily,
                      fontSize: 13,
                      fontWeight: FontWeight.w400,
                      color: AppColors.background.withValues(alpha: 0.7),
                      height: 16 / 13,
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

class _Dot extends StatelessWidget {
  final bool selected;

  const _Dot({required this.selected});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 22,
      height: 22,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: selected ? AppColors.accent : Colors.transparent,
        border: Border.all(
          color: selected ? AppColors.accent : AppColors.overlaySubtitle,
          width: 2,
        ),
      ),
      child: selected
          ? const Icon(Icons.check, size: 14, color: AppColors.textPrimary)
          : null,
    );
  }
}

class _DoneButton extends StatelessWidget {
  final VoidCallback onPressed;

  const _DoneButton({required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton(
        onPressed: onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.accent,
          foregroundColor: AppColors.background,
          padding: const EdgeInsets.symmetric(vertical: 16),
          shape: const StadiumBorder(),
          elevation: 0,
          textStyle: const TextStyle(
            fontFamily: AppTypography.fontFamily,
            fontSize: 14,
            fontWeight: FontWeight.w700,
            height: 17 / 14,
          ),
        ),
        child: const Text('Done'),
      ),
    );
  }
}
