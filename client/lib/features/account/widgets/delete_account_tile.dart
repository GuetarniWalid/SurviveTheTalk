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

  /// Ink for the destructive label / spinner / inline error. Defaults to
  /// [AppColors.destructive] (dark-host callers untouched); the light account &
  /// manage sheets pass [AppColors.paywallError], a darker red that meets WCAG
  /// AA on their light background (the default red is sub-AA on light).
  final Color color;

  /// When true (the FREE Account sheet, which is otherwise sparse), render
  /// Delete as a full-width OUTLINED pill — the same shape as the Manage button
  /// but with a RED border + red label ([color]) — to give that empty sheet
  /// presence (Walid 2026-06-22). The Manage drawer leaves this false: there
  /// Delete stays a quiet red text appendage so it is not spotlighted next to
  /// the Manage button.
  final bool outlined;

  const DeleteAccountTile({
    super.key,
    required this.onDelete,
    required this.onDeleted,
    this.color = AppColors.destructive,
    this.outlined = false,
  });

  @override
  State<DeleteAccountTile> createState() => _DeleteAccountTileState();
}

class _DeleteAccountTileState extends State<DeleteAccountTile> {
  bool _deleting = false;
  bool _failed = false;

  Future<void> _onTap() async {
    // Synchronous re-entry guard: the `_deleting` latch below is only set after
    // the await, so without this two rapid taps could stack two confirm dialogs
    // → two `DELETE /user/me` calls (the second 401s and could flip `_failed`
    // after a successful delete).
    if (_deleting) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text(_kConfirmTitle),
        content: const Text(_kConfirmBody),
        actions: [
          TextButton(
            // Quiet grey, NOT the theme's default accent green — green on the
            // SAFE action of a destructive dialog is confusing (Walid 2026-06-22).
            style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
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
          width: widget.outlined ? double.infinity : null,
          height: widget.outlined ? _kOutlinedHeight : _kTileHeight,
          child: _deleting
              ? Center(
                  child: SizedBox(
                    width: _kSpinnerSize,
                    height: _kSpinnerSize,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: widget.color,
                    ),
                  ),
                )
              : widget.outlined
                  // Free Account sheet — a full-width red OUTLINED pill (Manage
                  // button shape, red border + label) to fill the sparse sheet.
                  ? OutlinedButton(
                      onPressed: _onTap,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: widget.color,
                        side: BorderSide(color: widget.color, width: 1),
                        shape: const StadiumBorder(),
                        textStyle: _kOutlinedTextStyle,
                      ),
                      child: const Text(_kDelete),
                    )
                  // Manage drawer — quiet red text appendage (not spotlighted).
                  : TextButton(
                      onPressed: _onTap,
                      style: TextButton.styleFrom(
                        foregroundColor: widget.color,
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
                  color: widget.color,
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
// Outlined variant — matches the Manage button (64h, Inter 14/w600 label).
const double _kOutlinedHeight = 64.0;
const double _kSpinnerSize = 20.0;
const TextStyle _kOutlinedTextStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 14,
  fontWeight: FontWeight.w600,
);
