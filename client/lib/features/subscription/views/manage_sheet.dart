import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api/api_client.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/legal_links_row.dart';
import '../../account/widgets/delete_account_tile.dart';
import '../bloc/user_profile_cubit.dart';
import '../models/user_profile.dart';
import '../repositories/user_repository.dart';
import '../services/store_links.dart';

/// The paid-only "Manage subscription" drawer (Story 8.3 client rewrite, the
/// 2026-06-18 pivot away from the full-screen page).
///
/// A light (`#F0F0F0`) modal bottom sheet sharing the [PaywallSheet] scaffold.
/// It is a RETENTION surface, not an info dump: a member opens it near a cancel
/// decision, so it OPENS ON VALUE (what their membership gives them, in the
/// paywall's calm benefit register) and ENDS on a quiet, present-but-never-green
/// "Manage subscription" handoff whose caption literally says "cancel" (honest,
/// de-emphasized by weight + position, never hidden — Apple 3.1.1 / FTC clean).
///
/// Reachable ONLY from the paid-user `Account` hub line (the entry gates on
/// `!usage.isFree`), so it never has to render a free state. Restore lives on
/// the [PaywallSheet] (where a free-seen returning payer actually lands), NOT
/// here — a recognized member has nothing to restore. Reads `GET /user/profile`
/// via [UserProfileCubit] for the renewal date; hands off to the native store
/// via [StoreLinks]. Reuses only existing tokens (no new `AppColors`).
class ManageSheet {
  const ManageSheet._();

  /// Sheet top-corner radius — identical to [PaywallSheet] (8px base × 2).
  static const double _topRadius = 16.0;

  /// Test seam — when set, [show] builds the cubit from this instead of the
  /// production wiring (which hits `GET /user/profile`). Production leaves it
  /// null. Mirrors `PaywallSheet.debugBlocBuilder`.
  @visibleForTesting
  static UserProfileCubit Function()? debugCubitBuilder;

  /// Test seam — inject a [StoreLinks] (mock launcher / forced platform) so
  /// tests assert the manage caption + handoff without touching real plugins.
  @visibleForTesting
  static StoreLinks? debugStoreLinks;

  /// Test seam — build the [UserRepository] that backs the "Delete my account"
  /// tile's `DELETE /user/me` call. Production wires `UserRepository(ApiClient())`.
  @visibleForTesting
  static UserRepository Function()? debugRepositoryBuilder;

  /// Test seam — inject the legal-links launcher (assert the Privacy / Terms
  /// URLs without the real url_launcher plugin).
  @visibleForTesting
  static Future<bool> Function(Uri, {LaunchMode mode})? debugLaunch;

  static UserProfileCubit _buildCubit() {
    final override = debugCubitBuilder;
    if (override != null) return override();
    return UserProfileCubit(UserRepository(ApiClient()))..load();
  }

  static UserRepository _buildRepository() {
    final override = debugRepositoryBuilder;
    if (override != null) return override();
    return UserRepository(ApiClient());
  }

  /// Open the drawer. [onSignOut] is invoked after a successful "Delete my
  /// account" (the caller dispatches `SignOutEvent` to the AuthBloc). Resolves
  /// when the sheet dismisses (swipe / scrim / back — there is no in-sheet
  /// dismiss button by design).
  static Future<void> show(
    BuildContext context, {
    required VoidCallback onSignOut,
  }) {
    final storeLinks = debugStoreLinks ?? StoreLinks();
    final repository = _buildRepository();
    return showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppColors.textPrimary,
      // Short content hugs to ~40-50% on a normal phone; `isScrollControlled`
      // lets the inner SingleChildScrollView scroll on iPhone-SE / 200% text.
      isScrollControlled: true,
      isDismissible: true,
      enableDrag: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(_topRadius)),
      ),
      builder: (_) => BlocProvider<UserProfileCubit>(
        create: (_) => _buildCubit(),
        child: _ManageSheetBody(
          storeLinks: storeLinks,
          repository: repository,
          onSignOut: onSignOut,
          launch: debugLaunch,
        ),
      ),
    );
  }
}

// ---- Copy deck (retention register: factual benefits, no praise / hype /
// urgency / emoji / exclamation; A2/B1) ----
const String _kPlanLabel = 'Premium';
const String _kStatusActive = 'Your membership is active.';
const String _kValueHeading = 'What your membership gives you';
const List<String> _kBenefits = <String>[
  'Every scenario, unlocked.',
  'Three calls a day, every day.',
  'Clear feedback on what to fix.',
];
const String _kCtaManage = 'Manage subscription';
const String _kManageCaptionApple = 'Update or cancel in the App Store.';
const String _kManageCaptionGoogle = 'Update or cancel in the Play Store.';
const String _kProfileError = "Couldn't load your details.";
const String _kRetry = 'Try again';
const String _kStoreOpenFailed = 'Store did not open. Try again.';

// Renewal-line price (matches the paywall's locked `$1.99 per week`).
const String _kPriceWeekly = '\$1.99 per week.';

// ---- Local layout constants ----
const double _kHandleWidth = 40.0;
const double _kHandleHeight = 4.0;
const double _kBenefitIconSize = 20.0;
const double _kBenefitIconGap = 12.0;
const double _kSkeletonBarWidth = 200.0;
const double _kSkeletonBarHeight = 14.0;
// Manage button geometry — same shape/height as the paywall "Let's go" CTA
// (StadiumBorder, 64h) but OUTLINED (border only, no accent fill) so it reads
// as clearly tappable without being a loud conversion CTA (two-ink intact).
const double _kManageButtonHeight = 64.0;

// "Premium" hero label — a touch larger than `headline` (18) so the plan name
// has presence; a one-screen local style (the 7.4/7.5 local-const precedent).
const TextStyle _kPlanLabelStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 24,
  fontWeight: FontWeight.w600,
);

// Manage button label — Inter 14 SemiBold (matches the paywall CTA recipe).
const TextStyle _kManageButtonTextStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 14,
  fontWeight: FontWeight.w600,
);

class _ManageSheetBody extends StatefulWidget {
  final StoreLinks storeLinks;
  final UserRepository repository;
  final VoidCallback onSignOut;
  final Future<bool> Function(Uri, {LaunchMode mode})? launch;

  const _ManageSheetBody({
    required this.storeLinks,
    required this.repository,
    required this.onSignOut,
    required this.launch,
  });

  @override
  State<_ManageSheetBody> createState() => _ManageSheetBodyState();
}

class _ManageSheetBodyState extends State<_ManageSheetBody> {
  /// Inline "Store did not open." after a failed native manage handoff
  /// (never a dialog — gotcha #10).
  bool _storeOpenFailed = false;

  Future<void> _onManage() async {
    setState(() => _storeOpenFailed = false);
    final launched = await widget.storeLinks.openManageSubscriptions();
    if (!launched && mounted) {
      setState(() => _storeOpenFailed = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    final manageCaption = widget.storeLinks.isApplePlatform
        ? _kManageCaptionApple
        : _kManageCaptionGoogle;

    return BlocBuilder<UserProfileCubit, UserProfileState>(
      builder: (context, state) {
        // Defensive: the entry gates on `!usage.isFree`, but if a non-paid
        // profile somehow lands here, drop the sheet rather than render a
        // member surface to a free user.
        if (state is UserProfileLoaded && !state.profile.isPaid) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (context.mounted && Navigator.of(context).canPop()) {
              Navigator.of(context).pop();
            }
          });
        }
        return SingleChildScrollView(
          child: SafeArea(
            top: false,
            child: Padding(
              padding: EdgeInsets.fromLTRB(20, 8, 20, 20 + bottomInset),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                mainAxisSize: MainAxisSize.min,
                children: [
                  const _DragHandle(),
                  const SizedBox(height: 24),
                  // Reassure on open: status header + present-tense state.
                  Text(
                    _kPlanLabel,
                    textAlign: TextAlign.center,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: _kPlanLabelStyle.copyWith(
                      color: AppColors.background,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _kStatusActive,
                    textAlign: TextAlign.center,
                    style: AppTypography.body.copyWith(
                      color: AppColors.overlaySubtitle,
                    ),
                  ),
                  const SizedBox(height: 32),
                  // Value reinforcement — what the member HAS (the retention
                  // core), in the paywall's accent-check benefit style.
                  Text(
                    _kValueHeading,
                    style: AppTypography.body.copyWith(
                      color: AppColors.background,
                    ),
                  ),
                  const SizedBox(height: 16),
                  for (var i = 0; i < _kBenefits.length; i++) ...[
                    if (i > 0) const SizedBox(height: 8),
                    _BenefitRow(text: _kBenefits[i]),
                  ],
                  const SizedBox(height: 24),
                  // Profile-dependent slot — the ONLY thing the fetch gates.
                  // The value block + manage button always render (a member must
                  // always reach Manage, even if the profile fetch fails).
                  _RenewalSlot(state: state),
                  if (_storeOpenFailed) ...[
                    const SizedBox(height: 8),
                    Semantics(
                      liveRegion: true,
                      child: Text(
                        _kStoreOpenFailed,
                        textAlign: TextAlign.center,
                        style: AppTypography.caption.copyWith(
                          color: AppColors.paywallError,
                        ),
                      ),
                    ),
                  ],
                  const SizedBox(height: 24),
                  // The exit — a clearly-tappable OUTLINED pill (same shape as
                  // the paywall CTA), with the "cancel" cue caption centered
                  // directly below it (the paywall CTA→legal pattern).
                  _ManageButton(onTap: _onManage),
                  const SizedBox(height: 8),
                  Text(
                    manageCaption,
                    textAlign: TextAlign.center,
                    style: AppTypography.caption.copyWith(
                      color: AppColors.overlaySubtitle,
                    ),
                  ),
                  // Story 10.1 — universal account actions below the manage
                  // handoff: legal links (AC6) + the GDPR "Delete my account"
                  // (AC8). On a confirmed delete the sheet closes and signs out
                  // via the AuthBloc → AuthInitial path.
                  const SizedBox(height: 24),
                  LegalLinksRow(
                    color: AppColors.overlaySubtitle,
                    launch: widget.launch,
                  ),
                  const SizedBox(height: 8),
                  DeleteAccountTile(
                    onDelete: widget.repository.deleteAccount,
                    onDeleted: () {
                      final navigator = Navigator.of(context);
                      if (navigator.canPop()) navigator.pop();
                      widget.onSignOut();
                    },
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

/// The renewal/status line — the only profile-driven element. Loaded → real
/// date; Loading → a dim skeleton bar; Error → a compact inline retry (NOT the
/// full-screen `EmpatheticErrorScreen`, which owns its own SafeArea + padding
/// and would flood the sheet).
class _RenewalSlot extends StatelessWidget {
  final UserProfileState state;

  const _RenewalSlot({required this.state});

  @override
  Widget build(BuildContext context) {
    final state = this.state;
    if (state is UserProfileLoaded) {
      return Text(
        _renewalLine(state.profile),
        textAlign: TextAlign.center,
        style: AppTypography.caption.copyWith(color: AppColors.overlaySubtitle),
      );
    }
    if (state is UserProfileError) {
      return Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            _kProfileError,
            textAlign: TextAlign.center,
            style: AppTypography.body.copyWith(
              color: AppColors.overlaySubtitle,
            ),
          ),
          TextButton(
            onPressed: () => context.read<UserProfileCubit>().load(),
            style: TextButton.styleFrom(
              foregroundColor: AppColors.background,
              minimumSize: const Size(0, AppSpacing.touchTargetComfortable),
              textStyle: AppTypography.body,
            ),
            child: const Text(_kRetry),
          ),
        ],
      );
    }
    // Initial / Loading — one dim bar in the renewal line's place.
    return Center(
      child: Container(
        width: _kSkeletonBarWidth,
        height: _kSkeletonBarHeight,
        decoration: BoxDecoration(
          color: AppColors.background.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(4),
        ),
      ),
    );
  }
}

/// Renewal line copy (design §2a) — present+future → "Renews {date} for $1.99
/// per week."; null expiry → "$1.99 per week." (never fabricate a date);
/// present+past (auto-renew off) → "Active until {date}.".
String _renewalLine(UserProfile profile) {
  final iso = profile.subscriptionExpiresAt;
  if (iso == null) return _kPriceWeekly;
  final dt = DateTime.tryParse(iso)?.toLocal();
  if (dt == null) return _kPriceWeekly;
  final date = DateFormat('d MMM yyyy').format(dt);
  if (dt.isAfter(DateTime.now())) {
    return 'Renews $date for $_kPriceWeekly';
  }
  return 'Active until $date.';
}

/// Material 3 drag indicator — a visual "swipe to dismiss" affordance (cloned
/// verbatim from `paywall_sheet.dart`; duplication keeps the shipped paywall
/// untouched — design §5).
class _DragHandle extends StatelessWidget {
  const _DragHandle();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: _kHandleWidth,
        height: _kHandleHeight,
        decoration: BoxDecoration(
          color: AppColors.overlaySubtitle,
          borderRadius: BorderRadius.circular(_kHandleHeight / 2),
        ),
      ),
    );
  }
}

/// Accent check + benefit text. The checkmark is decorative (`ExcludeSemantics`
/// — the text carries the meaning), which justifies its sub-3:1 accent-on-light
/// contrast under WCAG SC 1.4.11. Cloned verbatim from the paywall's
/// `_BenefitRow`.
class _BenefitRow extends StatelessWidget {
  final String text;

  const _BenefitRow({required this.text});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const ExcludeSemantics(
          child: Icon(
            Icons.check_circle,
            size: _kBenefitIconSize,
            color: AppColors.accent,
          ),
        ),
        const SizedBox(width: _kBenefitIconGap),
        Expanded(
          child: Text(
            text,
            style: AppTypography.body.copyWith(color: AppColors.background),
          ),
        ),
      ],
    );
  }
}

/// The exit — a clearly-tappable OUTLINED pill, same shape/height as the paywall
/// "Let's go" CTA but border-only (no accent fill, two-ink intact) so it reads
/// as a button without being a loud conversion CTA. The "Update or cancel …"
/// caption sits centered directly BELOW it (the paywall CTA→legal pattern),
/// keeping the honest "cancel" cue present and findable. `OutlinedButton`
/// already exposes proper button+label semantics to assistive tech.
class _ManageButton extends StatelessWidget {
  final VoidCallback onTap;

  const _ManageButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: _kManageButtonHeight,
      child: OutlinedButton(
        onPressed: onTap,
        style: OutlinedButton.styleFrom(
          backgroundColor: Colors.transparent,
          foregroundColor: AppColors.background,
          // `side` set explicitly so Material never recolors it to a theme
          // default (this is a LIGHT sheet — the border must be the dark ink).
          side: const BorderSide(color: AppColors.background, width: 1),
          shape: const StadiumBorder(),
          textStyle: _kManageButtonTextStyle,
        ),
        child: const Text(_kCtaManage),
      ),
    );
  }
}
