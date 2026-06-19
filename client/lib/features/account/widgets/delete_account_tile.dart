import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';

/// The quiet, destructive "Delete my account" action (Story 10.1, AC8).
///
/// Shared by the free-user [AccountSheet] and the paid Manage drawer. It
/// confirms first (a destructive-action dialog — confirmations are dialogs, only
/// ERRORS are inline per client/CLAUDE.md gotcha #10), then calls [onDelete]
/// (the server `DELETE /user/me`). On success it calls [onDeleted] (the caller
/// closes the sheet and signs out via the AuthBloc → `AuthInitial` path); on
/// failure it shows an INLINE error and stays put so the user can retry.
class DeleteAccountTile extends StatefulWidget {
  /// Performs the server deletion; throws on failure.
  final Future<void> Function() onDelete;

  /// Invoked once the server deletion succeeds — the caller pops the sheet and
  /// triggers the sign-out / offline-cache-wipe path.
  final VoidCallback onDeleted;

  const DeleteAccountTile({
    super.key,
    required this.onDelete,
    required this.onDeleted,
  });

  @override
  State<DeleteAccountTile> createState() => _DeleteAccountTileState();
}

class _DeleteAccountTileState extends State<DeleteAccountTile> {
  bool _deleting = false;
  bool _failed = false;

  Future<void> _onTap() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text(_kConfirmTitle),
        content: const Text(_kConfirmBody),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text(_kCancel),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            style: TextButton.styleFrom(foregroundColor: AppColors.destructive),
            child: const Text(_kConfirmDelete),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _deleting = true;
      _failed = false;
    });
    try {
      await widget.onDelete();
      if (!mounted) return;
      widget.onDeleted();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _deleting = false;
        _failed = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          height: _kTileHeight,
          child: _deleting
              ? const Center(
                  child: SizedBox(
                    width: _kSpinnerSize,
                    height: _kSpinnerSize,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: AppColors.destructive,
                    ),
                  ),
                )
              : TextButton(
                  onPressed: _onTap,
                  style: TextButton.styleFrom(
                    foregroundColor: AppColors.destructive,
                    textStyle: AppTypography.caption,
                  ),
                  child: const Text(_kDelete),
                ),
        ),
        if (_failed)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Semantics(
              liveRegion: true,
              child: Text(
                _kError,
                textAlign: TextAlign.center,
                style: AppTypography.caption.copyWith(
                  color: AppColors.destructive,
                ),
              ),
            ),
          ),
      ],
    );
  }
}

const String _kDelete = 'Delete my account';
const String _kConfirmTitle = 'Delete your account?';
const String _kConfirmBody =
    'This permanently deletes your account and all your data. This cannot be '
    'undone. It does not cancel an active subscription — cancel that in the '
    'store.';
const String _kCancel = 'Cancel';
const String _kConfirmDelete = 'Delete';
const String _kError = "Couldn't delete your account. Try again.";
const double _kTileHeight = 48.0;
const double _kSpinnerSize = 20.0;
