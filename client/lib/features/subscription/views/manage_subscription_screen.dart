import 'dart:async';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_toast.dart';
import '../../../core/widgets/empathetic_error_screen.dart';
import '../../paywall/views/paywall_sheet.dart';
import '../bloc/subscription_bloc.dart';
import '../bloc/subscription_event.dart';
import '../bloc/subscription_state.dart';
import '../bloc/user_profile_cubit.dart';
import '../models/user_profile.dart';
import '../services/store_links.dart';

/// The Manage Subscription screen (Story 8.3, AC1) — built to the binding
/// `manage-subscription-screen-design.md`. Dark app surface, route-pushed, no
/// AppBar; a pinned-CTA structure (the EmpatheticErrorScreen pattern). Reads
/// `GET /user/profile` via [UserProfileCubit]; drives Restore/Subscribe through
/// the existing [SubscriptionBloc] / [PaywallSheet]. Reuses only existing
/// tokens (no new AppColors). The route provides both blocs.
class ManageSubscriptionScreen extends StatefulWidget {
  /// Test seam — production uses the default platform-resolving [StoreLinks].
  final StoreLinks? storeLinks;

  const ManageSubscriptionScreen({super.key, this.storeLinks});

  @override
  State<ManageSubscriptionScreen> createState() =>
      _ManageSubscriptionScreenState();
}

// Eyebrow recipe — a local const (12/w500/ls 1.0/textSecondary), the briefing /
// content-warning precedent. NOT an AppTypography token (none carries tracking).
const TextStyle _eyebrowStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 12,
  fontWeight: FontWeight.w500,
  letterSpacing: 1.0,
  color: AppColors.textSecondary,
);

// Legal links reuse the real domain the consent screen already links (NOT a
// placeholder). The Terms page sits on the same domain as the shipped privacy
// page (consent_screen.dart).
const String _kTermsUrl = 'https://survivethe.talk/terms';
const String _kPrivacyUrl = 'https://survivethe.talk/privacy';

const String _kPlanFree = 'Free plan';
const String _kPlanPaid = 'Premium';
const String _kCtaSubscribe = 'Subscribe';
const String _kCtaManage = 'Manage subscription';
const String _kRestore = 'Restore purchases';
const String _kNothingToRestore = 'Nothing to restore.';
const String _kRestoreFailed = 'Something went wrong. Try again.';
const String _kStoreOpenFailed = 'Store did not open. Try again.';
const String _kPriceLine = '\$1.99 per week';
const String _kRestoreSuccess = 'Subscription restored';

// CTA label — Inter 14 SemiBold (matches the paywall CTA recipe).
const TextStyle _kCtaTextStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 14,
  fontWeight: FontWeight.w600,
);

class _ManageSubscriptionScreenState extends State<ManageSubscriptionScreen> {
  late final StoreLinks _storeLinks = widget.storeLinks ?? StoreLinks();
  late final TapGestureRecognizer _termsRecognizer;
  late final TapGestureRecognizer _privacyRecognizer;

  /// Inline restore outcome ("Nothing to restore." / failure) — never a dialog.
  String? _restoreMessage;
  bool _restoreFailed = false;

  /// Inline "Store did not open." after a failed native manage handoff.
  bool _storeOpenFailed = false;

  @override
  void initState() {
    super.initState();
    _termsRecognizer = TapGestureRecognizer()..onTap = () => _launch(_kTermsUrl);
    _privacyRecognizer = TapGestureRecognizer()
      ..onTap = () => _launch(_kPrivacyUrl);
    final cubit = context.read<UserProfileCubit>();
    if (cubit.state is UserProfileInitial) cubit.load();
  }

  @override
  void dispose() {
    _termsRecognizer.dispose();
    _privacyRecognizer.dispose();
    super.dispose();
  }

  Future<void> _launch(String url) async {
    try {
      await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    } catch (_) {
      // Legal links are supplemental; a launch failure is silent (no dialog).
    }
  }

  void _onSubscriptionState(BuildContext context, SubscriptionState state) {
    if (state is SubscriptionPurchased) {
      // Genuine restore (this screen's bloc only fires Purchased via Restore —
      // Subscribe runs in the PaywallSheet's own bloc).
      AppToast.show(
        context,
        message: _kRestoreSuccess,
        type: AppToastType.success,
      );
      setState(() {
        _restoreMessage = null;
        _restoreFailed = false;
      });
      // refetch → flip to paid view (fire-and-forget; the cubit drives rebuild)
      unawaited(context.read<UserProfileCubit>().load());
    } else if (state is SubscriptionRestoreEmpty) {
      setState(() {
        _restoreMessage = _kNothingToRestore;
        _restoreFailed = false;
      });
    } else if (state is SubscriptionFailed) {
      setState(() {
        _restoreMessage = _kRestoreFailed;
        _restoreFailed = true;
      });
    } else if (state is SubscriptionLoading) {
      setState(() {
        _restoreMessage = null;
        _restoreFailed = false;
      });
    }
  }

  Future<void> _onSubscribe() async {
    final purchased = await PaywallSheet.show(context);
    if (purchased && mounted) {
      unawaited(context.read<UserProfileCubit>().load());
    }
  }

  Future<void> _onManage() async {
    setState(() => _storeOpenFailed = false);
    final launched = await _storeLinks.openManageSubscriptions();
    if (!launched && mounted) {
      setState(() => _storeOpenFailed = true);
    }
  }

  void _onRestore() {
    context.read<SubscriptionBloc>().add(const RestorePressed());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: BlocListener<SubscriptionBloc, SubscriptionState>(
        listener: _onSubscriptionState,
        child: BlocBuilder<UserProfileCubit, UserProfileState>(
          builder: (context, state) {
            // Error → swap the WHOLE body to the error screen (it owns its own
            // SafeArea + 36 padding; nesting would double the inset).
            if (state is UserProfileError) {
              return EmpatheticErrorScreen(
                code: state.code,
                retryCount: state.retryCount,
                onRetry: () => context.read<UserProfileCubit>().load(),
              );
            }
            final profile = state is UserProfileLoaded ? state.profile : null;
            return _Frame(
              profile: profile,
              restoreMessage: _restoreMessage,
              restoreFailed: _restoreFailed,
              storeOpenFailed: _storeOpenFailed,
              termsRecognizer: _termsRecognizer,
              privacyRecognizer: _privacyRecognizer,
              onSubscribe: _onSubscribe,
              onManage: _onManage,
              onRestore: _onRestore,
            );
          },
        ),
      ),
    );
  }
}

/// The framed (non-error) layout: scrolling status + Restore, pinned CTA +
/// legal. `profile == null` → loading skeleton (CTA disabled, Restore enabled).
class _Frame extends StatelessWidget {
  final UserProfile? profile;
  final String? restoreMessage;
  final bool restoreFailed;
  final bool storeOpenFailed;
  final TapGestureRecognizer termsRecognizer;
  final TapGestureRecognizer privacyRecognizer;
  final VoidCallback onSubscribe;
  final VoidCallback onManage;
  final VoidCallback onRestore;

  const _Frame({
    required this.profile,
    required this.restoreMessage,
    required this.restoreFailed,
    required this.storeOpenFailed,
    required this.termsRecognizer,
    required this.privacyRecognizer,
    required this.onSubscribe,
    required this.onManage,
    required this.onRestore,
  });

  @override
  Widget build(BuildContext context) {
    final loading = profile == null;
    final isPaid = profile?.isPaid ?? false;
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return SafeArea(
      top: true,
      bottom: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.screenHorizontal,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const _BackArrow(),
                    const SizedBox(height: AppSpacing.screenVerticalList),
                    Semantics(
                      header: true,
                      child: Text(
                        'Subscription',
                        style: AppTypography.headline.copyWith(
                          color: AppColors.textPrimary,
                        ),
                      ),
                    ),
                    const SizedBox(height: 32),
                    if (profile == null)
                      const _StatusSkeleton()
                    else
                      _StatusBlock(profile: profile!),
                    const SizedBox(height: 40),
                    _RestoreButton(onPressed: onRestore),
                    if (restoreMessage != null) ...[
                      const SizedBox(height: 8),
                      Semantics(
                        liveRegion: true,
                        child: Text(
                          restoreMessage!,
                          style: AppTypography.caption.copyWith(
                            color: restoreFailed
                                ? AppColors.destructive
                                : AppColors.textSecondary,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            if (storeOpenFailed) ...[
              Semantics(
                liveRegion: true,
                child: Text(
                  _kStoreOpenFailed,
                  textAlign: TextAlign.center,
                  style: AppTypography.caption.copyWith(
                    color: AppColors.destructive,
                  ),
                ),
              ),
              const SizedBox(height: 8),
            ],
            _PrimaryCta(
              label: isPaid ? _kCtaManage : _kCtaSubscribe,
              onPressed: loading ? null : (isPaid ? onManage : onSubscribe),
            ),
            const SizedBox(height: 16),
            _LegalFooter(
              isPaid: isPaid,
              termsRecognizer: termsRecognizer,
              privacyRecognizer: privacyRecognizer,
            ),
            SizedBox(
              height: bottomInset > 0
                  ? AppSpacing.base
                  : AppSpacing.screenVerticalList,
            ),
          ],
        ),
      ),
    );
  }
}

class _BackArrow extends StatelessWidget {
  const _BackArrow();

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Back to scenarios',
      child: SizedBox(
        width: AppSpacing.minTouchTarget,
        height: AppSpacing.minTouchTarget,
        child: IconButton(
          padding: EdgeInsets.zero,
          iconSize: AppSpacing.iconSmall,
          color: AppColors.textPrimary,
          // The chevron carries heavy left optical whitespace; nudge it right
          // 8dp so the glyph sits on the 20 rail (codebase back-arrow recipe).
          icon: const Padding(
            padding: EdgeInsets.only(left: 8),
            child: Icon(Icons.arrow_back_ios_new),
          ),
          onPressed: () => context.pop(),
        ),
      ),
    );
  }
}

class _StatusBlock extends StatelessWidget {
  final UserProfile profile;
  const _StatusBlock({required this.profile});

  @override
  Widget build(BuildContext context) {
    final detailStyle = AppTypography.caption.copyWith(
      color: AppColors.errorBody,
    );
    final details = <String>[];
    if (profile.isPaid) {
      details.add(_kPriceLine);
      final date = _formatDate(profile.subscriptionExpiresAt);
      if (date != null) details.add('Renews $date');
    } else {
      details.add(
        '${profile.callsRemaining} of ${profile.callsPerPeriod} free calls left',
      );
      // State D — a reverted user may carry a past expiry; state it flatly.
      final ended = _endedDate(profile.subscriptionExpiresAt);
      if (ended != null) details.add('Subscription ended $ended');
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('PLAN', style: _eyebrowStyle),
        const SizedBox(height: AppSpacing.base),
        // Plan + details read as one screen-reader sentence (design §7).
        MergeSemantics(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                profile.isPaid ? _kPlanPaid : _kPlanFree,
                style: AppTypography.bodyEmphasis.copyWith(
                  color: AppColors.textPrimary,
                ),
              ),
              for (final line in details) ...[
                const SizedBox(height: AppSpacing.cardTextGap),
                Text(line, style: detailStyle),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

/// Loading placeholder — keeps the eyebrow + stable-height dim bars so nothing
/// jumps when the profile lands. Never renders "Free plan" while merely loading.
class _StatusSkeleton extends StatelessWidget {
  const _StatusSkeleton();

  @override
  Widget build(BuildContext context) {
    Widget bar(double width, double height) => Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: AppColors.avatarBg,
        borderRadius: BorderRadius.circular(4),
      ),
    );
    return Semantics(
      label: 'Loading subscription status',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('PLAN', style: _eyebrowStyle),
          const SizedBox(height: AppSpacing.base),
          bar(140, 18),
          const SizedBox(height: AppSpacing.cardTextGap + 3),
          bar(180, 14),
        ],
      ),
    );
  }
}

class _PrimaryCta extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  const _PrimaryCta({required this.label, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: AppSpacing.touchTargetComfortable,
      child: FilledButton(
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.accent,
          foregroundColor: AppColors.background,
          disabledBackgroundColor: AppColors.accent.withValues(alpha: 0.4),
          disabledForegroundColor: AppColors.background,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: _kCtaTextStyle,
        ),
        child: Text(label),
      ),
    );
  }
}

class _RestoreButton extends StatelessWidget {
  final VoidCallback onPressed;
  const _RestoreButton({required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton(
        onPressed: onPressed,
        style: TextButton.styleFrom(
          minimumSize: const Size.fromHeight(AppSpacing.touchTargetComfortable),
          foregroundColor: AppColors.textSecondary,
          alignment: Alignment.centerLeft,
          padding: EdgeInsets.zero,
        ),
        child: const Text(_kRestore),
      ),
    );
  }
}

class _LegalFooter extends StatelessWidget {
  final bool isPaid;
  final TapGestureRecognizer termsRecognizer;
  final TapGestureRecognizer privacyRecognizer;

  const _LegalFooter({
    required this.isPaid,
    required this.termsRecognizer,
    required this.privacyRecognizer,
  });

  @override
  Widget build(BuildContext context) {
    final base = AppTypography.caption.copyWith(color: AppColors.textSecondary);
    final link = base.copyWith(decoration: TextDecoration.underline);
    return Text.rich(
      TextSpan(
        style: base,
        children: [
          // Paid: the store-required auto-renew disclosure (compliance carve-out
          // from the A2/B1 rule). Free: nothing is renewing — omit it.
          if (isPaid)
            const TextSpan(text: 'Auto-renewable. Cancel anytime.\n'),
          TextSpan(
            text: 'Terms',
            style: link,
            recognizer: termsRecognizer,
            semanticsLabel: 'Terms, link',
          ),
          const TextSpan(text: '   ·   '),
          TextSpan(
            text: 'Privacy',
            style: link,
            recognizer: privacyRecognizer,
            semanticsLabel: 'Privacy, link',
          ),
        ],
      ),
      textAlign: TextAlign.center,
    );
  }
}

/// ISO 8601 → "18 Jul 2026", or null on a missing / unparseable value.
String? _formatDate(String? iso) {
  if (iso == null) return null;
  try {
    return DateFormat('d MMM yyyy').format(DateTime.parse(iso).toLocal());
  } catch (_) {
    return null;
  }
}

/// Like [_formatDate] but only returns a date that is in the PAST (state D's
/// "Subscription ended {date}"); a future date on a free user is not shown.
String? _endedDate(String? iso) {
  if (iso == null) return null;
  try {
    final dt = DateTime.parse(iso);
    if (dt.isAfter(DateTime.now())) return null;
    return DateFormat('d MMM yyyy').format(dt.toLocal());
  } catch (_) {
    return null;
  }
}
