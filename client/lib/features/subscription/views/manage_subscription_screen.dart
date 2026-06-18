import 'dart:async';
import 'dart:math' as math;

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
/// `manage-subscription-screen-design.md` + the 2026-06-18 hero-ring redesign.
///
/// Dark app surface, route-pushed, no AppBar; a pinned-CTA structure. The focal
/// element is a 180px "survival ring" (the debrief gauge visual language) that
/// sweeps in on entrance: FREE shows a remaining/cap usage ring with the count
/// in the bore; PAID shows a full accent "Premium" membership medallion (it
/// visualizes entitlement state, NOT the daily call meter, so a Premium user is
/// never shown an alarming empty ring). Reads `GET /user/profile` via
/// [UserProfileCubit]; drives Restore/Subscribe through [SubscriptionBloc] /
/// [PaywallSheet]. Reuses only existing tokens (no new AppColors; count==16).
class ManageSubscriptionScreen extends StatefulWidget {
  /// Test seam — production uses the default platform-resolving [StoreLinks].
  final StoreLinks? storeLinks;

  const ManageSubscriptionScreen({super.key, this.storeLinks});

  @override
  State<ManageSubscriptionScreen> createState() =>
      _ManageSubscriptionScreenState();
}

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
const String _kRestorePending = 'Waiting for approval.';
const String _kStoreOpenFailed = 'Store did not open. Try again.';
const String _kPriceLine = '\$1.99 per week';
const String _kRestoreSuccess = 'Subscription restored';

// Hero ring — dimensions copied from the debrief gauge (the validated visual
// language). Local dimension/timing consts (the briefing `_kGaugeSize`
// precedent), NOT shared tokens.
const double _kHeroRingSize = 180.0; // == debrief _kGaugeSize
const double _kHeroRingStroke = 12.0; // == debrief _kGaugeStroke
const double _kHeroInnerWidth = 100.0; // == debrief _kGaugeInnerWidth
const double _kHeroCaptionGap = 20.0; // ring -> caption
const Duration _kSweepDuration = Duration(milliseconds: 700);

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

  /// Inline restore outcome ("Nothing to restore." / pending / failure) — never
  /// a dialog (gotcha #10).
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
    } else if (state is SubscriptionPendingApproval) {
      // F17 — a restore that hit an Ask-to-Buy / SCA hold.
      setState(() {
        _restoreMessage = _kRestorePending;
        _restoreFailed = false;
      });
    } else if (state is SubscriptionFailed) {
      setState(() {
        _restoreMessage = _kRestoreFailed;
        _restoreFailed = true;
      });
    } else if (state is SubscriptionCancelled) {
      // User backed out of the restore — clear any stale message, no error.
      setState(() {
        _restoreMessage = null;
        _restoreFailed = false;
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

/// The framed (non-error) layout: a focal hero ring + Restore scroll, pinned CTA
/// + legal. `profile == null` → loading skeleton (CTA disabled, Restore enabled).
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
    final profile = this.profile; // promote for the null checks below
    final loading = profile == null;
    final isPaid = profile?.isPaid ?? false;
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;

    final Widget hero;
    if (profile == null) {
      hero = const _HeroSkeleton();
    } else if (profile.isPaid) {
      hero = _PlanHero(
        // Membership medallion: a full ring = active entitlement (NOT a daily
        // usage meter — a paid /user/profile is a point-in-time daily count, so
        // a remaining/cap ring would alarm a Premium user at end of day).
        targetFraction: 1.0,
        center: FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            _kPlanPaid,
            maxLines: 1,
            style: AppTypography.headline.copyWith(color: AppColors.textPrimary),
          ),
        ),
        caption: _paidCaption(profile),
        semanticsLabel: 'Premium plan',
      );
    } else {
      final fraction = profile.callsPerPeriod > 0
          ? (profile.callsRemaining / profile.callsPerPeriod).clamp(0.0, 1.0)
          : 0.0;
      hero = _PlanHero(
        // Usage ring: full when calls remain, drains as they are spent — ring
        // and number always agree (a fresh user sees a satisfying near-full
        // ring, not the old "vide" empty void).
        targetFraction: fraction,
        center: FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            '${profile.callsRemaining}',
            maxLines: 1,
            style: AppTypography.display.copyWith(
              color: AppColors.textPrimary,
              height: 1.0,
            ),
          ),
        ),
        caption: _freeCaption(profile),
        // State-aware: at 0 the reader hears the calm sentence, never a bare
        // "0 of 3 remaining" (the alarm in audio).
        semanticsLabel: profile.callsRemaining == 0
            ? 'You have used your ${profile.callsPerPeriod} free calls'
            : '${profile.callsRemaining} of ${profile.callsPerPeriod} calls '
                  'remaining',
      );
    }

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
              child: LayoutBuilder(
                builder: (context, constraints) {
                  return SingleChildScrollView(
                    child: ConstrainedBox(
                      // Floor the scroll child to the viewport so the inner
                      // Expanded has slack to balance the hero in the optical
                      // middle on a TALL phone; on a short screen (SE / 200%
                      // text) the content exceeds minHeight, the Expanded
                      // collapses to the hero's natural height and this scrolls.
                      constraints: BoxConstraints(
                        minHeight: constraints.maxHeight,
                      ),
                      child: IntrinsicHeight(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            const Align(
                              alignment: Alignment.centerLeft,
                              child: _BackArrow(),
                            ),
                            const SizedBox(
                              height: AppSpacing.screenVerticalList,
                            ),
                            Semantics(
                              header: true,
                              child: Text(
                                'Subscription',
                                style: AppTypography.headline.copyWith(
                                  color: AppColors.textPrimary,
                                ),
                              ),
                            ),
                            // Hero takes the remaining slack and self-centers
                            // in it (_PlanHero / _HeroSkeleton already wrap in
                            // Center) — no redundant outer Center.
                            Expanded(child: hero),
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
            // Restore sits ABOVE the primary CTA (quieter, cleaner reading
            // order); reachable in every purchasable state (Apple 3.1.1).
            BlocBuilder<SubscriptionBloc, SubscriptionState>(
              builder: (context, s) => _RestoreRow(
                onPressed: onRestore,
                inFlight: s is SubscriptionLoading,
              ),
            ),
            if (restoreMessage != null) ...[
              const SizedBox(height: AppSpacing.base),
              Semantics(
                liveRegion: true,
                child: Text(
                  restoreMessage!,
                  textAlign: TextAlign.center,
                  style: AppTypography.caption.copyWith(
                    color: restoreFailed
                        ? AppColors.destructive
                        : AppColors.textSecondary,
                  ),
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.base * 3),
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
              const SizedBox(height: AppSpacing.base),
            ],
            _PrimaryCta(
              label: isPaid ? _kCtaManage : _kCtaSubscribe,
              isPaid: isPaid,
              onPressed: loading ? null : (isPaid ? onManage : onSubscribe),
            ),
            const SizedBox(height: AppSpacing.base * 2),
            _LegalFooter(
              termsRecognizer: termsRecognizer,
              privacyRecognizer: privacyRecognizer,
            ),
            SizedBox(
              height: bottomInset > 0
                  ? AppSpacing.base * 2
                  : AppSpacing.screenVerticalList,
            ),
          ],
        ),
      ),
    );
  }
}

/// The free/expired caption (plan word + calls-left, optional "ended" line),
/// read as one screen-reader sentence (design §7). Centered under the ring.
Widget _freeCaption(UserProfile profile) {
  final ended = _endedDate(profile.subscriptionExpiresAt);
  final detail = AppTypography.caption.copyWith(color: AppColors.errorBody);
  // At 0 the count line is reframed as a completed, expected fact — no leading
  // bare "0", no fear/urgency. The empty ring then has a referent (it explains
  // WHY it is empty); the forward path is the Subscribe button alone, never a
  // second imperative line here. Live cap, never a hardcoded 3.
  final usageLine = profile.callsRemaining == 0
      ? 'You have used your ${profile.callsPerPeriod} free calls'
      : '${profile.callsRemaining} of ${profile.callsPerPeriod} free calls left';
  return MergeSemantics(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          _kPlanFree,
          textAlign: TextAlign.center,
          style: AppTypography.bodyEmphasis.copyWith(
            color: AppColors.textPrimary,
          ),
        ),
        const SizedBox(height: AppSpacing.cardTextGap),
        Text(usageLine, textAlign: TextAlign.center, style: detail),
        if (ended != null) ...[
          const SizedBox(height: AppSpacing.cardTextGap),
          // Historical, not current data → the quieter chrome grey, never red.
          Text(
            'Subscription ended $ended',
            textAlign: TextAlign.center,
            style: AppTypography.caption.copyWith(
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ],
    ),
  );
}

/// The paid caption (price + renewal date). The plan word "Premium" lives in
/// the ring, so the caption does not repeat it.
Widget _paidCaption(UserProfile profile) {
  final renews = _formatDate(profile.subscriptionExpiresAt);
  final detail = AppTypography.caption.copyWith(color: AppColors.errorBody);
  return MergeSemantics(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(_kPriceLine, textAlign: TextAlign.center, style: detail),
        if (renews != null) ...[
          const SizedBox(height: AppSpacing.cardTextGap),
          Text('Renews $renews', textAlign: TextAlign.center, style: detail),
        ],
      ],
    ),
  );
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

/// The focal hero — a 180px ring (debrief gauge geometry) that sweeps in once on
/// entrance; the center number/word is static (the debrief composition). Reduce-
/// motion paints the final frame with no sweep.
class _PlanHero extends StatefulWidget {
  final double targetFraction;
  final Widget center;
  final Widget caption;
  final String semanticsLabel;

  const _PlanHero({
    required this.targetFraction,
    required this.center,
    required this.caption,
    required this.semanticsLabel,
  });

  @override
  State<_PlanHero> createState() => _PlanHeroState();
}

class _PlanHeroState extends State<_PlanHero>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  late final Animation<double> _sweep;
  bool _started = false;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(duration: _kSweepDuration, vsync: this);
    _sweep = CurvedAnimation(parent: _c, curve: Curves.easeOutCubic);
    // Reduce-motion read ONCE, context-free → deterministic in tests, no
    // re-fire on rotation/textScale/theme change.
    final reduceMotion = WidgetsBinding
        .instance.platformDispatcher.accessibilityFeatures.disableAnimations;
    if (reduceMotion) {
      _c.value = 1.0; // paint the final frame, no sweep
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !_started) {
          _started = true;
          _c.forward();
        }
      });
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Semantics(
            label: widget.semanticsLabel,
            child: SizedBox(
              width: _kHeroRingSize,
              height: _kHeroRingSize,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  ExcludeSemantics(
                    child: AnimatedBuilder(
                      animation: _sweep,
                      builder: (_, _) => CustomPaint(
                        size: const Size.square(_kHeroRingSize),
                        painter: _PlanGaugePainter(
                          fraction: widget.targetFraction * _sweep.value,
                        ),
                      ),
                    ),
                  ),
                  ExcludeSemantics(
                    child: SizedBox(
                      width: _kHeroInnerWidth,
                      child: widget.center,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: _kHeroCaptionGap),
          widget.caption,
        ],
      ),
    );
  }
}

/// The ring painter — debrief `_ScoreGaugePainter` geometry verbatim (270°
/// speedometer arc), but the value arc is ALWAYS `accent` (it encodes
/// quantity/membership, never tier/judgment — a colored status arc is banned).
class _PlanGaugePainter extends CustomPainter {
  final double fraction;

  const _PlanGaugePainter({required this.fraction});

  static const double _start = 3 * math.pi / 4;
  static const double _full = 3 * math.pi / 2;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = (Offset.zero & size).deflate(_kHeroRingStroke / 2);
    final track = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = _kHeroRingStroke
      ..strokeCap = StrokeCap.round
      ..color = AppColors.gaugeTrack;
    canvas.drawArc(rect, _start, _full, false, track);
    final f = fraction.clamp(0.0, 1.0);
    if (f > 0) {
      final value = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = _kHeroRingStroke
        ..strokeCap = StrokeCap.round
        ..color = AppColors.accent;
      canvas.drawArc(rect, _start, _full * f, false, value);
    }
  }

  @override
  bool shouldRepaint(_PlanGaugePainter oldDelegate) =>
      oldDelegate.fraction != fraction;
}

/// Loading placeholder — reserves the hero footprint (groove-only ring + two dim
/// bars) so nothing reflows when data lands. Never renders "Free plan".
class _HeroSkeleton extends StatelessWidget {
  const _HeroSkeleton();

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
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(
              width: _kHeroRingSize,
              height: _kHeroRingSize,
              child: CustomPaint(
                size: Size.square(_kHeroRingSize),
                painter: _PlanGaugePainter(fraction: 0),
              ),
            ),
            const SizedBox(height: _kHeroCaptionGap),
            bar(140, 18),
            const SizedBox(height: AppSpacing.cardTextGap + 3),
            bar(180, 14),
          ],
        ),
      ),
    );
  }
}

/// Asymmetric emphasis by tier (retention vs conversion). FREE "Subscribe" is
/// the loud accent FILL pill (the action we want). PAID "Manage subscription"
/// is a quiet NEUTRAL-OUTLINED pill — present + clearly tappable (Apple 3.1.1,
/// no dark pattern) but de-emphasized: accent stays fill-only (two-ink), never
/// a border/text. Both share the "Pick up"/"Try again" StadiumBorder geometry +
/// 64 height (`hangUpButtonSize`) so the primary action reads as THE action and
/// stops crowding the legal line.
class _PrimaryCta extends StatelessWidget {
  final String label;
  final bool isPaid;
  final VoidCallback? onPressed;
  const _PrimaryCta({
    required this.label,
    required this.isPaid,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: AppSpacing.hangUpButtonSize,
      child: isPaid
          ? OutlinedButton(
              onPressed: onPressed,
              style: OutlinedButton.styleFrom(
                backgroundColor: Colors.transparent,
                foregroundColor: AppColors.textPrimary,
                disabledForegroundColor: AppColors.textPrimary.withValues(
                  alpha: 0.4,
                ),
                // `side` set EXPLICITLY in both states so Material never
                // auto-recolors the border to a theme default (two-ink guard).
                side: BorderSide(
                  color: onPressed == null
                      ? AppColors.textSecondary.withValues(alpha: 0.4)
                      : AppColors.textSecondary,
                  width: 1,
                ),
                shape: const StadiumBorder(),
                textStyle: _kCtaTextStyle,
              ),
              child: Text(label),
            )
          : FilledButton(
              onPressed: onPressed,
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.accent,
                foregroundColor: AppColors.background,
                disabledBackgroundColor: AppColors.accent.withValues(
                  alpha: 0.4,
                ),
                disabledForegroundColor: AppColors.background,
                // Match the briefing "Pick up" pill (StadiumBorder).
                shape: const StadiumBorder(),
                textStyle: _kCtaTextStyle,
              ),
              child: Text(label),
            ),
    );
  }
}

/// Restore — a centered, intrinsic-width StadiumBorder text button: the ripple
/// hugs the label as a tidy pill (never a full-width slab, never glued left),
/// press feedback kept. Disabled (spinner) only while a restore is in flight.
class _RestoreRow extends StatelessWidget {
  final VoidCallback onPressed;
  final bool inFlight;

  const _RestoreRow({required this.onPressed, required this.inFlight});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: TextButton(
        onPressed: inFlight ? null : onPressed,
        style: TextButton.styleFrom(
          foregroundColor: AppColors.textSecondary,
          disabledForegroundColor: AppColors.textSecondary,
          minimumSize: const Size(0, AppSpacing.touchTargetComfortable),
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.base * 2),
          tapTargetSize: MaterialTapTargetSize.padded,
          shape: const StadiumBorder(),
          textStyle: AppTypography.caption,
        ),
        child: inFlight
            ? const SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: AppColors.textSecondary,
                ),
              )
            : const Text(_kRestore),
      ),
    );
  }
}

class _LegalFooter extends StatelessWidget {
  final TapGestureRecognizer termsRecognizer;
  final TapGestureRecognizer privacyRecognizer;

  const _LegalFooter({
    required this.termsRecognizer,
    required this.privacyRecognizer,
  });

  @override
  Widget build(BuildContext context) {
    final base = AppTypography.caption.copyWith(color: AppColors.textSecondary);
    final link = base.copyWith(decoration: TextDecoration.underline);
    // Story 8.3 — the auto-renewable disclosure lives at the POINT OF SALE (the
    // paywall), which retains it; a post-purchase status screen carries no
    // separate disclosure duty (Apple 3.1.2 / Google Play). Terms · Privacy
    // links are kept (hygiene). Tier-independent now.
    return Text.rich(
      TextSpan(
        style: base,
        children: [
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
