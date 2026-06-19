import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api/api_client.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/legal_links_row.dart';
import '../../subscription/bloc/subscription_bloc.dart';
import '../../subscription/bloc/subscription_event.dart';
import '../../subscription/bloc/subscription_state.dart';
import '../../subscription/repositories/subscription_repository.dart';
import '../../subscription/services/in_app_purchase_service.dart';

/// The invisible-tier paywall (Story 8.2, built to paywall-screen-design.md).
///
/// A light (`#F0F0F0`) modal bottom sheet shown at moments of maximum intent
/// (paid-scenario call, BottomOverlayCard, or the FR29 debrief peak). Four
/// states drive off [SubscriptionState]: Default / Loading / Success / Error.
///
/// Resolves to `true` when a purchase (or a genuine restore) completed — the
/// caller reloads `/scenarios` so the fresh `paid` tier re-flows (the Story 8.1
/// G2 contract); `false`/`null` on any dismiss. The purchase plumbing
/// ([SubscriptionBloc] / [InAppPurchaseService] / `POST /subscription/verify`)
/// is reused unchanged from Story 8.1 — this story adds no new billing logic
/// beyond the D2 restore affordance.
class PaywallSheet {
  const PaywallSheet._();

  /// Sheet top-corner radius (paywall-screen-design.md — 2× the 8px base unit;
  /// Decision D4, a declared deviation from the placeholder's BOC-lineage 42).
  static const double _topRadius = 16.0;

  /// Test seam — when set, [show] builds the sheet's bloc from this instead of
  /// the production wiring (which touches the real store plugin). Production
  /// leaves it null; covers every internal call site (the 3 entry points + the
  /// CALL_LIMIT_REACHED handler) without per-call plumbing.
  @visibleForTesting
  static SubscriptionBloc Function()? debugBlocBuilder;

  /// Test seam — inject the legal-links launcher (assert the Privacy / Terms
  /// URLs without the real url_launcher plugin). Read directly by [_OfferView].
  @visibleForTesting
  static Future<bool> Function(Uri, {LaunchMode mode})? debugLaunch;

  static SubscriptionBloc _buildBloc() {
    final override = debugBlocBuilder;
    if (override != null) return override();
    return SubscriptionBloc(
      repository: SubscriptionRepository(ApiClient()),
      iapService: InAppPurchaseService(),
    );
  }

  /// Open the sheet. Resolves to `true` when a purchase/restore completed, else
  /// `false` (dismissed / failed / cancelled).
  static Future<bool> show(BuildContext context) async {
    final result = await showModalBottomSheet<bool>(
      context: context,
      backgroundColor: AppColors.textPrimary,
      // Tall content (~552px) overflows iPhone-SE — `isScrollControlled` lets
      // the sheet hug content and the inner `SingleChildScrollView` scrolls on
      // small phones (design "iPhone SE mitigation").
      isScrollControlled: true,
      isDismissible: true,
      enableDrag: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(_topRadius)),
      ),
      builder: (_) => BlocProvider<SubscriptionBloc>(
        create: (_) => _buildBloc(),
        child: const _PaywallSheetBody(),
      ),
    );
    return result ?? false;
  }
}

// ---- Copy deck (paywall-screen-design.md → §2, verbatim) ----
const String _kTitle = 'Speak English for real';
const String _kSubtitle = "Practice with characters who won't go easy on you.";
const String _kPriceAmount = '\$1.99';
const String _kPricePeriod = 'per week';
const List<String> _kBenefits = <String>[
  'All scenarios unlocked.',
  'Daily calls. Daily progress.',
  'Know exactly what you\'re doing wrong',
];
const String _kCta = "Let's go";
const String _kLegal = 'Auto-renewable. 3 calls per day. Cancel anytime.';
const String _kSuccessTitle = "You're in";
const String _kError = 'Something went wrong. Try again.';
// Story 8.3 (F17) — store purchase pending external approval (Ask to Buy / SCA).
const String _kPendingApproval = 'Waiting for approval. You can close this.';
// Story 8.3 (2026-06-18 pivot) — Restore lives on the paywall, in the slot the
// "Not now" dismiss button used to occupy. The sheet still dismisses via swipe /
// scrim / system back (PopScope), so a dedicated dismiss button is redundant. A
// free-SEEN returning payer (reinstall / new device) lands HERE — not on the
// paid-only Manage drawer — so this is the correct Apple 3.1.1 "visible restore"
// home. A genuine restore re-delivers like a purchase (→ Purchased → "You're
// in"); an empty one surfaces a neutral "Nothing to restore." (never a fake
// success — Story 8.2 F16).
const String _kRestore = 'Restore purchases';
const String _kNothingToRestore = 'Nothing to restore.';

// ---- Screen-reader announcements (design → Accessibility) ----
const String _kPriceSemantics = 'One dollar ninety-nine per week';
const String _kProcessingSemantics = 'Processing, please wait';
const String _kSuccessSemantics = "Subscription confirmed. You're in.";

// ---- Local layout / timing constants ----
const double _kHandleWidth = 40.0;
const double _kHandleHeight = 4.0;
// Story 8.3 (2026-06-18) — the primary CTA is the prominent action; height
// raised 48 → 64 (the app's big-CTA size, `hangUpButtonSize` / briefing "Pick
// up") so it reads as THE action above the small Restore line.
const double _kCtaHeight = 64.0;
// Fixed height for the Restore slot so the tappable "Restore purchases" button
// and the non-tappable "Nothing to restore." info line occupy the SAME space —
// the empty-state swap never reflows the CTA / legal below it.
const double _kRestoreSlotHeight = 48.0;
const double _kSpinnerSize = 24.0;
const double _kBenefitIconSize = 20.0;
const double _kBenefitIconGap = 12.0;
const double _kSuccessCheckSize = 48.0;

/// Success hold before auto-dismiss (design State 3) — 1.5s, extended to 5s
/// when a screen reader is active so the live-region announcement completes.
const Duration _kSuccessHold = Duration(milliseconds: 1500);
const Duration _kSuccessHoldAccessible = Duration(seconds: 5);
const Duration _kCrossfade = Duration(milliseconds: 200);

// Price hero — screen-specific 36px Bold (`paywall-price`); a local const per
// the 7.4/7.5 precedent (no new AppTypography token for a one-screen size).
const TextStyle _kPriceStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 36,
  fontWeight: FontWeight.w700,
);

// CTA label — Inter 14 SemiBold (`button-label`, NOT the 12px system label).
const TextStyle _kCtaTextStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 14,
  fontWeight: FontWeight.w600,
);

class _PaywallSheetBody extends StatefulWidget {
  const _PaywallSheetBody();

  @override
  State<_PaywallSheetBody> createState() => _PaywallSheetBodyState();
}

class _PaywallSheetBodyState extends State<_PaywallSheetBody> {
  Timer? _successTimer;
  bool _popped = false;

  @override
  void dispose() {
    _successTimer?.cancel();
    super.dispose();
  }

  /// On a confirmed purchase, hold the "You're in" state for 1.5s (5s with a
  /// screen reader) then auto-dismiss with `true` — the bool the caller awaits
  /// to trigger its `/scenarios` reload (G2). Guarded so a rebuild can't queue
  /// a second pop.
  void _startSuccessHold(BuildContext context) {
    if (_successTimer != null) return;
    final accessible = MediaQuery.of(context).accessibleNavigation;
    final hold = accessible ? _kSuccessHoldAccessible : _kSuccessHold;
    _successTimer = Timer(hold, () {
      if (!mounted || _popped) return;
      _popped = true;
      Navigator.of(context).pop(true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return BlocConsumer<SubscriptionBloc, SubscriptionState>(
      listener: (context, state) {
        if (state is SubscriptionPurchased) _startSuccessHold(context);
      },
      builder: (context, state) {
        final isSuccess = state is SubscriptionPurchased;
        final isLoading = state is SubscriptionLoading;
        // PopScope blocks system back during the in-flight purchase and the
        // success hold; in Default/Error, system back is a clean dismiss (the
        // sheet pops with no result → `show` returns false). AC8 / design
        // back-button table. (Native swipe/scrim stay enabled —
        // `showModalBottomSheet`'s `enableDrag`/`isDismissible` are static;
        // PopScope is the contracted dismiss block. Story 8.3 dropped the
        // explicit "Not now" button — these three dismiss paths replace it.)
        return PopScope(
          canPop: !(isLoading || isSuccess),
          child: SingleChildScrollView(
            child: SafeArea(
              top: false,
              child: Padding(
                padding: EdgeInsets.fromLTRB(20, 8, 20, 20 + bottomInset),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const _DragHandle(),
                    const SizedBox(height: 32),
                    AnimatedSwitcher(
                      duration: _kCrossfade,
                      child: isSuccess
                          ? const _SuccessView(key: ValueKey('paywall-success'))
                          : _OfferView(
                              key: const ValueKey('paywall-offer'),
                              state: state,
                              onSubscribe: () => context
                                  .read<SubscriptionBloc>()
                                  .add(const SubscribePressed()),
                              onRestore: () => context
                                  .read<SubscriptionBloc>()
                                  .add(const RestorePressed()),
                            ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// Material 3 drag indicator — a visual "swipe to dismiss" affordance.
class _DragHandle extends StatelessWidget {
  const _DragHandle();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: _kHandleWidth,
      height: _kHandleHeight,
      decoration: BoxDecoration(
        color: AppColors.overlaySubtitle,
        borderRadius: BorderRadius.circular(_kHandleHeight / 2),
      ),
    );
  }
}

/// The offer surface — Default / Loading / Error all render here (only the CTA
/// + the inline caption change). Success swaps to [_SuccessView].
class _OfferView extends StatelessWidget {
  final SubscriptionState state;
  final VoidCallback onSubscribe;
  final VoidCallback onRestore;

  const _OfferView({
    super.key,
    required this.state,
    required this.onSubscribe,
    required this.onRestore,
  });

  @override
  Widget build(BuildContext context) {
    final loading = state is SubscriptionLoading;
    final failed = state is SubscriptionFailed;
    // Story 8.3 (F17) — pending external approval: actions are inert (no
    // double-buy) but the sheet stays dismissible ("You can close this.").
    final pending = state is SubscriptionPendingApproval;
    // Story 8.3 — a "Restore purchases" tap that found no entitlement (F16):
    // a neutral caption, never a fake success.
    final restoreEmpty = state is SubscriptionRestoreEmpty;
    final actionsDisabled = loading || pending;
    final secondary = AppTypography.body.copyWith(
      color: AppColors.overlaySubtitle,
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          _kTitle,
          textAlign: TextAlign.center,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppTypography.headline.copyWith(color: AppColors.background),
        ),
        const SizedBox(height: 24),
        Text(
          _kSubtitle,
          textAlign: TextAlign.center,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: secondary,
        ),
        const SizedBox(height: 32),
        // Price hero — read naturally by screen readers ("one dollar
        // ninety-nine per week"), not "$1.99".
        Semantics(
          label: _kPriceSemantics,
          excludeSemantics: true,
          child: Column(
            children: [
              Text(
                _kPriceAmount,
                textAlign: TextAlign.center,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: _kPriceStyle.copyWith(color: AppColors.background),
              ),
              Text(_kPricePeriod, textAlign: TextAlign.center, style: secondary),
            ],
          ),
        ),
        const SizedBox(height: 32),
        for (var i = 0; i < _kBenefits.length; i++) ...[
          if (i > 0) const SizedBox(height: 8),
          _BenefitRow(text: _kBenefits[i]),
        ],
        const SizedBox(height: 32),
        // Story 8.3 (2026-06-18) — Restore sits ABOVE the primary CTA as a
        // small, quiet line. On an empty restore it becomes a NON-tappable info
        // line ("Nothing to restore.") of the SAME fixed height, so the swap
        // never reflows the CTA / legal below. Reopening the sheet (swipe /
        // scrim) builds a fresh bloc → it resets to a tappable "Restore
        // purchases".
        _RestoreControl(
          restoreEmpty: restoreEmpty,
          disabled: actionsDisabled,
          onRestore: onRestore,
        ),
        const SizedBox(height: 12),
        _CtaButton(
          loading: loading,
          onPressed: actionsDisabled ? null : onSubscribe,
        ),
        if (failed) ...[
          const SizedBox(height: 8),
          Semantics(
            liveRegion: true,
            child: Text(
              _kError,
              textAlign: TextAlign.center,
              style: AppTypography.caption.copyWith(
                color: AppColors.paywallError,
              ),
            ),
          ),
        ],
        if (pending) ...[
          const SizedBox(height: 8),
          Semantics(
            liveRegion: true,
            child: Text(
              _kPendingApproval,
              textAlign: TextAlign.center,
              style: AppTypography.caption.copyWith(
                color: AppColors.overlaySubtitle,
              ),
            ),
          ),
        ],
        const SizedBox(height: 24),
        Text(
          _kLegal,
          textAlign: TextAlign.center,
          style: AppTypography.caption.copyWith(
            color: AppColors.overlaySubtitle,
          ),
        ),
        const SizedBox(height: 12),
        // Story 10.1 (AC6) — Privacy Policy + Terms of Use links, required in the
        // binary for auto-renewable subscriptions (Apple Guideline 3.1.2). Quiet
        // underlined caption links, two-ink with the legal caption above.
        LegalLinksRow(
          color: AppColors.overlaySubtitle,
          launch: PaywallSheet.debugLaunch,
        ),
      ],
    );
  }
}

/// Accent check + benefit text. The checkmark is decorative (`ExcludeSemantics`
/// — the text carries the meaning), which is what justifies its sub-3:1
/// accent-on-light contrast under WCAG SC 1.4.11 (design Accessibility note).
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

/// Story 8.3 — the Restore affordance: a SMALL, quiet line ABOVE the CTA. Both
/// renderings share one fixed height ([_kRestoreSlotHeight]) so swapping between
/// them never reflows the CTA / legal below:
///  - normal: a tappable caption-sized "Restore purchases" text button (greyed +
///    inert while a purchase/restore is in flight or pending — no double-fire);
///  - empty-restore (F16): a NON-tappable "Nothing to restore." info line (no
///    fake success). It is no longer a button — to retry, reopen the sheet
///    (a fresh bloc resets it to the tappable "Restore purchases").
class _RestoreControl extends StatelessWidget {
  final bool restoreEmpty;
  final bool disabled;
  final VoidCallback onRestore;

  const _RestoreControl({
    required this.restoreEmpty,
    required this.disabled,
    required this.onRestore,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: _kRestoreSlotHeight,
      child: Center(
        child: restoreEmpty
            ? Semantics(
                liveRegion: true,
                child: Text(
                  _kNothingToRestore,
                  textAlign: TextAlign.center,
                  style: AppTypography.caption.copyWith(
                    color: AppColors.overlaySubtitle,
                  ),
                ),
              )
            : TextButton(
                onPressed: disabled ? null : onRestore,
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.overlaySubtitle,
                  disabledForegroundColor: AppColors.overlaySubtitle.withValues(
                    alpha: 0.4,
                  ),
                  minimumSize: const Size(0, _kRestoreSlotHeight),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  textStyle: AppTypography.caption,
                ),
                child: const Text(_kRestore),
              ),
      ),
    );
  }
}

/// The accent CTA — "Let's go", or a centered spinner while a purchase/restore
/// is in flight. Disabled (non-tappable) during loading + success.
class _CtaButton extends StatelessWidget {
  final bool loading;
  final VoidCallback? onPressed;

  const _CtaButton({required this.loading, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: _kCtaHeight,
      child: FilledButton(
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.accent,
          foregroundColor: AppColors.background,
          disabledBackgroundColor: AppColors.accent,
          disabledForegroundColor: AppColors.background,
          // Story 8.3 — match the briefing "Pick up" pill (StadiumBorder).
          shape: const StadiumBorder(),
          textStyle: _kCtaTextStyle,
        ),
        child: loading
            ? Semantics(
                liveRegion: true,
                label: _kProcessingSemantics,
                child: const SizedBox(
                  height: _kSpinnerSize,
                  width: _kSpinnerSize,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: AppColors.background,
                  ),
                ),
              )
            : const Text(_kCta),
      ),
    );
  }
}

/// Post-purchase confirmation — "You're in" + an accent check, held briefly by
/// the parent before auto-dismiss. A live-region container so a screen reader
/// announces the confirmation.
class _SuccessView extends StatelessWidget {
  const _SuccessView({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      liveRegion: true,
      label: _kSuccessSemantics,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            _kSuccessTitle,
            textAlign: TextAlign.center,
            style: AppTypography.headline.copyWith(color: AppColors.background),
          ),
          const SizedBox(height: 24),
          const ExcludeSemantics(
            child: Icon(
              Icons.check_circle,
              size: _kSuccessCheckSize,
              color: AppColors.accent,
            ),
          ),
        ],
      ),
    );
  }
}
