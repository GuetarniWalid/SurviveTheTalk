import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../core/api/api_client.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';
import '../../subscription/bloc/subscription_bloc.dart';
import '../../subscription/bloc/subscription_event.dart';
import '../../subscription/bloc/subscription_state.dart';
import '../../subscription/repositories/subscription_repository.dart';
import '../../subscription/services/in_app_purchase_service.dart';

/// Bottom sheet that drives the weekly-subscription purchase (Story 8.1).
///
/// This is the MINIMAL working surface: a single "Subscribe — $1.99/week"
/// control wired to [SubscriptionBloc]. Story 8.2 restyles this into the real
/// invisible-tier paywall — the entry point ([PaywallSheet.show], a bottom
/// sheet matching the BOC's treatment) stays the same.
///
/// Returns `true` when the purchase completed (the caller reloads the
/// scenario list so the fresh `paid` tier flows back through `/scenarios`);
/// `false`/`null` on dismissal.
class PaywallSheet {
  const PaywallSheet._();

  /// Top-corner radius. Matches the BottomOverlayCard so the visual lineage
  /// reads as one continuous surface emerging from the bottom of the screen.
  static const double _topRadius = 42.0;

  /// Test seam — when set, [show] builds the sheet's bloc from this instead of
  /// the production wiring (which touches the real store plugin). Production
  /// leaves it null; covers BOTH internal call sites (BOC tap + the
  /// CALL_LIMIT_REACHED handler) without per-call plumbing.
  @visibleForTesting
  static SubscriptionBloc Function()? debugBlocBuilder;

  static SubscriptionBloc _buildBloc() {
    final override = debugBlocBuilder;
    if (override != null) return override();
    return SubscriptionBloc(
      repository: SubscriptionRepository(ApiClient()),
      iapService: InAppPurchaseService(),
    );
  }

  /// Open the sheet. Resolves to `true` when a purchase completed, else
  /// `false` (dismissed / failed / cancelled).
  static Future<bool> show(BuildContext context) async {
    final result = await showModalBottomSheet<bool>(
      context: context,
      backgroundColor: AppColors.textPrimary,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(_topRadius)),
      ),
      // Default Material slide-up animation; no override needed.
      builder: (_) => BlocProvider<SubscriptionBloc>(
        create: (_) => _buildBloc(),
        child: const _PaywallSheetBody(),
      ),
    );
    return result ?? false;
  }
}

class _PaywallSheetBody extends StatelessWidget {
  const _PaywallSheetBody();

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return BlocConsumer<SubscriptionBloc, SubscriptionState>(
      listener: (context, state) {
        // Hand the purchase signal back to the caller (which reloads the
        // scenario list so the new tier re-flows from `/scenarios`).
        if (state is SubscriptionPurchased) {
          Navigator.of(context).pop(true);
        }
      },
      builder: (context, state) {
        final loading = state is SubscriptionLoading;
        return Padding(
          padding: EdgeInsets.fromLTRB(20, 32, 20, 32 + bottomInset),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Drag-handle affordance.
              Container(
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.overlaySubtitle.withValues(alpha: 0.4),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(height: 24),
              Text(
                'Unlock all scenarios',
                textAlign: TextAlign.center,
                style: AppTypography.body.copyWith(color: AppColors.background),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: loading
                      ? null
                      : () => context.read<SubscriptionBloc>().add(
                          const SubscribePressed(),
                        ),
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.background,
                    foregroundColor: AppColors.textPrimary,
                    disabledBackgroundColor: AppColors.background,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  child: loading
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: AppColors.textPrimary,
                          ),
                        )
                      : const Text('Subscribe — \$1.99/week'),
                ),
              ),
              if (state is SubscriptionFailed) ...[
                const SizedBox(height: 12),
                Text(
                  'Something went wrong. Please try again.',
                  textAlign: TextAlign.center,
                  style: AppTypography.body.copyWith(
                    color: AppColors.destructive,
                    fontSize: 14,
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}
