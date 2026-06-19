import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api/api_client.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/legal_links_row.dart';
import '../../subscription/repositories/user_repository.dart';
import '../widgets/delete_account_tile.dart';

/// The minimal "Account" drawer for FREE users (Story 10.1, the 2026-06-19
/// decision: `Account` is visible to all; paid users get the Manage drawer,
/// free users get this). A free user has no subscription to manage, so this
/// surface only carries the universal account actions: the legal links and the
/// GDPR self-serve "Delete my account".
///
/// Shares the [PaywallSheet]/[ManageSheet] light-sheet scaffold. On a confirmed
/// deletion it closes itself and runs [onSignOut] (the AuthBloc → `AuthInitial`
/// sign-out, which fires the Story 9.1 cache wipe + the GoRouter redirect).
class AccountSheet {
  const AccountSheet._();

  static const double _topRadius = 16.0;

  /// Test seam — build the repository (the `DELETE /user/me` caller) from this
  /// instead of the production wiring. Mirrors `ManageSheet.debugCubitBuilder`.
  @visibleForTesting
  static UserRepository Function()? debugRepositoryBuilder;

  /// Test seam — inject the legal-links launcher (assert the URL without the
  /// real url_launcher plugin).
  @visibleForTesting
  static Future<bool> Function(Uri, {LaunchMode mode})? debugLaunch;

  static UserRepository _buildRepository() {
    final override = debugRepositoryBuilder;
    if (override != null) return override();
    return UserRepository(ApiClient());
  }

  /// Open the drawer. [onSignOut] is invoked after a successful account
  /// deletion (the caller dispatches `SignOutEvent` to the AuthBloc).
  static Future<void> show(
    BuildContext context, {
    required VoidCallback onSignOut,
  }) {
    final repository = _buildRepository();
    return showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppColors.textPrimary,
      isScrollControlled: true,
      isDismissible: true,
      enableDrag: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(_topRadius)),
      ),
      builder: (_) => _AccountSheetBody(
        repository: repository,
        onSignOut: onSignOut,
        launch: debugLaunch,
      ),
    );
  }
}

const String _kTitle = 'Account';

class _AccountSheetBody extends StatelessWidget {
  final UserRepository repository;
  final VoidCallback onSignOut;
  final Future<bool> Function(Uri, {LaunchMode mode})? launch;

  const _AccountSheetBody({
    required this.repository,
    required this.onSignOut,
    required this.launch,
  });

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return SingleChildScrollView(
      child: SafeArea(
        top: false,
        child: Padding(
          padding: EdgeInsets.fromLTRB(20, 8, 20, 20 + bottomInset),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const _DragHandle(),
              const SizedBox(height: 24),
              Text(
                _kTitle,
                textAlign: TextAlign.center,
                style: AppTypography.headline.copyWith(
                  color: AppColors.background,
                ),
              ),
              const SizedBox(height: 24),
              LegalLinksRow(
                color: AppColors.overlaySubtitle,
                launch: launch,
              ),
              const SizedBox(height: 16),
              DeleteAccountTile(
                onDelete: repository.deleteAccount,
                onDeleted: () {
                  final navigator = Navigator.of(context);
                  if (navigator.canPop()) navigator.pop();
                  onSignOut();
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Material 3 drag indicator — cloned from the paywall/manage sheets (the
/// duplication keeps each shipped sheet self-contained).
class _DragHandle extends StatelessWidget {
  const _DragHandle();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: 40,
        height: 4,
        decoration: BoxDecoration(
          color: AppColors.overlaySubtitle,
          borderRadius: BorderRadius.circular(2),
        ),
      ),
    );
  }
}
