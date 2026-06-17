import 'dart:async';

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
  ///
  /// Story 8.2 (code-review D2): a custom [_PaywallRoute] rather than
  /// `showModalBottomSheet`, because the design (States 2 & 3) requires every
  /// manual dismiss path — swipe, scrim tap, system back — DISABLED during
  /// Loading and the success hold, then re-enabled in Default/Error.
  /// `showModalBottomSheet` bakes `enableDrag`/`isDismissible` in at call time
  /// (its drag-dismiss calls `Navigator.pop` directly, bypassing `PopScope`),
  /// so it cannot toggle by state. The custom route draws its own scrim + drag,
  /// both gated on the live [SubscriptionState], so dismissibility tracks state.
  static Future<bool> show(BuildContext context) async {
    final result = await Navigator.of(context).push<bool>(
      _PaywallRoute(buildBloc: _buildBloc),
    );
    return result ?? false;
  }
}

/// A state is dismissible (swipe / scrim / back allowed) EXCEPT while a
/// purchase/restore is in flight ([SubscriptionLoading]) or during the
/// post-purchase hold ([SubscriptionPurchased]) — design States 2 & 3 disable
/// every manual dismiss path then, so the user can't interrupt the store
/// round-trip or the post-purchase tier-flip reload.
bool _isDismissibleState(SubscriptionState state) =>
    state is! SubscriptionLoading && state is! SubscriptionPurchased;

/// Custom modal route for the paywall (see [PaywallSheet.show] for the why).
/// Translucent + slide-up, with a self-drawn scrim so the scrim tap, the
/// drag-down and the system-back can all be gated on the live
/// [SubscriptionState] via [_isDismissibleState].
class _PaywallRoute extends PopupRoute<bool> {
  _PaywallRoute({required this.buildBloc});

  final SubscriptionBloc Function() buildBloc;

  @override
  Color? get barrierColor => null; // the layout draws its own (reactive) scrim
  @override
  bool get barrierDismissible => false; // dismissal is gated on the bloc state
  @override
  String? get barrierLabel => null;
  @override
  bool get opaque => false;
  @override
  Duration get transitionDuration => const Duration(milliseconds: 250);
  @override
  Duration get reverseTransitionDuration => const Duration(milliseconds: 200);

  @override
  Widget buildPage(
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
  ) {
    return BlocProvider<SubscriptionBloc>(
      create: (_) => buildBloc(),
      child: const _PaywallModalLayout(),
    );
  }
}

/// Scrim + bottom-anchored slide-up sheet. A single [BlocBuilder] computes
/// dismissibility per state change and gates BOTH the scrim tap and the
/// drag-down, so the design's State 2/3 "no manual dismiss during
/// Loading/Success" holds without per-gesture re-checks.
class _PaywallModalLayout extends StatelessWidget {
  const _PaywallModalLayout();

  @override
  Widget build(BuildContext context) {
    final animation = ModalRoute.of(context)!.animation!;
    return BlocBuilder<SubscriptionBloc, SubscriptionState>(
      builder: (context, state) {
        final dismissible = _isDismissibleState(state);
        return Stack(
          children: [
            // Scrim — fades with the route animation; absorbs all taps
            // (`opaque`), but only DISMISSES when the state allows it.
            Positioned.fill(
              child: FadeTransition(
                opacity: animation,
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: dismissible
                      ? () => Navigator.of(context).pop(false)
                      : null,
                  child: const ColoredBox(color: Colors.black54),
                ),
              ),
            ),
            // Sheet — slides up from the bottom; drag-down + system-back are
            // gated on `dismissible` inside [_PaywallSheetSurface].
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: SlideTransition(
                position: animation.drive(
                  Tween<Offset>(
                    begin: const Offset(0, 1),
                    end: Offset.zero,
                  ).chain(CurveTween(curve: Curves.easeOutCubic)),
                ),
                child: _PaywallSheetSurface(dismissible: dismissible),
              ),
            ),
          ],
        );
      },
    );
  }
}

/// The light sheet surface (radius [PaywallSheet._topRadius], `#F0F0F0`)
/// wrapping the scrolling content. Owns the drag-down-to-dismiss and the
/// system-back [PopScope], both gated on [dismissible] so they no-op during
/// Loading/Success.
class _PaywallSheetSurface extends StatelessWidget {
  final bool dismissible;

  const _PaywallSheetSurface({required this.dismissible});

  @override
  Widget build(BuildContext context) {
    // Cap the sheet so tall content scrolls on small phones (the old
    // `isScrollControlled` "iPhone SE mitigation") instead of overflowing.
    final maxHeight = MediaQuery.sizeOf(context).height * 0.92;
    // The drag-down-to-dismiss lives on the pinned handle INSIDE
    // `_PaywallSheetBody` (so it never fights the content's scroll); here we own
    // only the system-back `PopScope` (gated on `dismissible`) and the surface.
    return PopScope(
      canPop: dismissible,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: maxHeight),
        child: const Material(
          color: AppColors.textPrimary,
          clipBehavior: Clip.antiAlias,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.vertical(
              top: Radius.circular(PaywallSheet._topRadius),
            ),
          ),
          child: _PaywallSheetBody(),
        ),
      ),
    );
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
const String _kDismiss = 'Not now';
const String _kRestore = 'Restore purchases';
const String _kLegal = 'Auto-renewable. 3 calls per day. Cancel anytime.';
const String _kSuccessTitle = "You're in";
const String _kError = 'Something went wrong. Try again.';
const String _kNothingToRestore = 'Nothing to restore.';

// ---- Screen-reader announcements (design → Accessibility) ----
const String _kPriceSemantics = 'One dollar ninety-nine per week';
const String _kProcessingSemantics = 'Processing, please wait';
const String _kSuccessSemantics = "Subscription confirmed. You're in.";

// ---- Local layout / timing constants ----
const double _kHandleWidth = 40.0;
const double _kHandleHeight = 4.0;
const double _kCtaHeight = 48.0;
const double _kCtaRadius = 12.0;
const double _kSpinnerSize = 24.0;
const double _kBenefitIconSize = 20.0;
const double _kBenefitIconGap = 12.0;
const double _kSuccessCheckSize = 48.0;

/// Success hold before auto-dismiss (design State 3) — 1.5s, extended to 5s
/// when a screen reader is active so the live-region announcement completes.
const Duration _kSuccessHold = Duration(milliseconds: 1500);
const Duration _kSuccessHoldAccessible = Duration(seconds: 5);
const Duration _kCrossfade = Duration(milliseconds: 200);

// Downward fling velocity (px/s) past which a drag dismisses the sheet — only
// honored when the state is dismissible (Default/Error). Story 8.2 (D2).
const double _kDismissFlingVelocity = 700.0;

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
    // The sheet surface, scrim, drag-down and system-back `PopScope` all live
    // in the parent `_PaywallModalLayout`/`_PaywallSheetSurface` (Story 8.2 D2 —
    // dismissibility is gated there on the live state). This widget is just the
    // scrolling content + the success-hold side-effect.
    return BlocConsumer<SubscriptionBloc, SubscriptionState>(
      listener: (context, state) {
        if (state is SubscriptionPurchased) _startSuccessHold(context);
      },
      builder: (context, state) {
        final isSuccess = state is SubscriptionPurchased;
        final dismissible = _isDismissibleState(state);
        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Pinned drag handle, OUTSIDE the scroll view so its vertical drag
            // never fights the content's scroll. A downward fling dismisses —
            // but only when the state allows it (Default/Error). Full-width hit
            // band so the grab is easy.
            GestureDetector(
              key: const Key('paywall-drag-handle'),
              behavior: HitTestBehavior.opaque,
              onVerticalDragEnd: dismissible
                  ? (details) {
                      if ((details.primaryVelocity ?? 0) >
                          _kDismissFlingVelocity) {
                        Navigator.of(context).pop(false);
                      }
                    }
                  : null,
              child: const SizedBox(
                width: double.infinity,
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Center(child: _DragHandle()),
                ),
              ),
            ),
            Flexible(
              child: SingleChildScrollView(
                child: SafeArea(
                  top: false,
                  child: Padding(
                    padding: EdgeInsets.fromLTRB(20, 20, 20, 20 + bottomInset),
                    child: AnimatedSwitcher(
                      duration: _kCrossfade,
                      child: isSuccess
                          ? const _SuccessView(
                              key: ValueKey('paywall-success'),
                            )
                          : _OfferView(
                              key: const ValueKey('paywall-offer'),
                              state: state,
                              onSubscribe: () => context
                                  .read<SubscriptionBloc>()
                                  .add(const SubscribePressed()),
                              onRestore: () => context
                                  .read<SubscriptionBloc>()
                                  .add(const RestorePressed()),
                              onDismiss: () =>
                                  Navigator.of(context).pop(false),
                            ),
                    ),
                  ),
                ),
              ),
            ),
          ],
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
  final VoidCallback onDismiss;

  const _OfferView({
    super.key,
    required this.state,
    required this.onSubscribe,
    required this.onRestore,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    final loading = state is SubscriptionLoading;
    final failed = state is SubscriptionFailed;
    final restoreEmpty = state is SubscriptionRestoreEmpty;
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
        _CtaButton(loading: loading, onPressed: loading ? null : onSubscribe),
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
        if (restoreEmpty) ...[
          const SizedBox(height: 8),
          Semantics(
            liveRegion: true,
            child: Text(
              _kNothingToRestore,
              textAlign: TextAlign.center,
              style: AppTypography.caption.copyWith(
                color: AppColors.overlaySubtitle,
              ),
            ),
          ),
        ],
        const SizedBox(height: 16),
        TextButton(
          onPressed: loading ? null : onDismiss,
          style: TextButton.styleFrom(
            foregroundColor: AppColors.overlaySubtitle,
            disabledForegroundColor:
                AppColors.overlaySubtitle.withValues(alpha: 0.4),
            minimumSize: const Size.fromHeight(48),
            textStyle: AppTypography.body,
          ),
          child: const Text(_kDismiss),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: loading ? null : onRestore,
          style: TextButton.styleFrom(
            foregroundColor: AppColors.overlaySubtitle,
            disabledForegroundColor:
                AppColors.overlaySubtitle.withValues(alpha: 0.4),
            minimumSize: const Size.fromHeight(48),
            textStyle: AppTypography.caption,
          ),
          child: const Text(_kRestore),
        ),
        const SizedBox(height: 24),
        Text(
          _kLegal,
          textAlign: TextAlign.center,
          style: AppTypography.caption.copyWith(
            color: AppColors.overlaySubtitle,
          ),
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
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(_kCtaRadius),
          ),
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
