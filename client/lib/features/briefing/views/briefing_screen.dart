// Story 7.4 — Pre-scenario briefing screen, "The Handler's Brief"
// (Decision E, Walid-validated 2026-06-12).
//
// The screen masquerades as the phone's own incoming-call card — the
// briefing IS part of the fiction. One left alignment rail for everything;
// nothing centered; zero boxes, cards, icons, or dividers in the body (the
// 8px-inside / 32px-between spacing ratio does all grouping). With three
// short server strings the screen may look "empty" on tall displays — that
// restraint is the design, not unfinished work.
//
// Pure render + confirm surface: pops `true` from the CTA, `false` from the
// back arrow; the hub (`scenario_list_screen.dart`) owns the whole
// call-initiation chain (content warning → POST → CallScreen). No bloc
// (CallEndedScreen / DebriefScreen precedent): state is the pop-once guard
// plus the scroll-metrics flag driving the conditional footer hairline.

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../scenarios/models/scenario.dart';

// COPY LINT (Story 7.4 design pass, Walid-validated 2026-06-12). Banned on
// this screen: exclamation marks, question marks, praise ("Good luck",
// "You've got this"), emoji, "don't worry", tips, urgency cues, episode
// numbering. Voice lives ONLY in the kicker + stakes line; everything else
// is flat data. App-owned word budget: 23.
const String _kKicker = 'INCOMING CALL';
const String _kFactLine = 'Live voice call · English only · No script';
const String _kLabelSituation = 'THE SITUATION';
const String _kLabelExpect = 'WHAT TO EXPECT';
const String _kLabelSayThis = 'SAY THIS';
const String _kStakesLine = 'They can hang up on you. So can you.';
const String _kCtaLabel = 'Pick up';
const String _kBackSemanticLabel = 'Back to scenarios';

// Layout constants ("The Handler's Brief" §Layout spec) — local consts per
// the DebriefScreen precedent; no AppSpacing additions.
const double _kAvatarSize = 72.0;
const double _kArrowIconSize = 24.0;
// IconButton centers its 24px glyph inside the 44px target — pull the
// button left by the internal padding so the GLYPH sits on the 20px rail.
const double _kArrowOpticalInset =
    (AppSpacing.minTouchTarget - _kArrowIconSize) / 2;
const double _kTopBarGap = 16.0;
const double _kHeroGap = 16.0;
const double _kLockupGap = 8.0;
const double _kTriadTopGap = 40.0;
const double _kSectionGap = 32.0;
const double _kSectionInsideGap = 8.0;
const double _kFooterStakesGap = 12.0;
const double _kCtaMinHeight = 48.0;
const double _kCtaIconSize = 24.0;
const double _kCtaIconGap = 10.0;

// The four composed Inter styles (§Layout spec) — defined once; zero new
// AppTypography tokens (the _DifficultyHubLine / content-warning-sheet
// precedent). Two-ink discipline: text is ONLY textPrimary (title + the 3
// server strings) or textSecondary (all chrome).
const TextStyle _eyebrowStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 12,
  fontWeight: FontWeight.w500,
  letterSpacing: 1.0,
  color: AppColors.textSecondary,
);
const TextStyle _titleStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 24,
  fontWeight: FontWeight.w700,
  height: 1.2,
  color: AppColors.textPrimary,
);
const TextStyle _bodyStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 16,
  fontWeight: FontWeight.w400,
  height: 1.5,
  color: AppColors.textPrimary,
);
// w500 variant of _bodyStyle — the vocabulary block's ONLY emphasis
// (weight + last position; no box, no chips).
const TextStyle _vocabularyStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 16,
  fontWeight: FontWeight.w500,
  height: 1.5,
  color: AppColors.textPrimary,
);
const TextStyle _captionStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 13,
  fontWeight: FontWeight.w400,
  color: AppColors.textSecondary,
);
// Italic variant of _captionStyle for the stakes line.
const TextStyle _stakesStyle = TextStyle(
  fontFamily: AppTypography.fontFamily,
  fontSize: 13,
  fontWeight: FontWeight.w400,
  fontStyle: FontStyle.italic,
  color: AppColors.textSecondary,
);

/// "The Handler's Brief" — replaces `BriefingPlaceholderScreen`.
///
/// Pushed (with the full [Scenario] in `state.extra`) from BOTH hub
/// entries — the first-attempt call-icon gate and the whole-card browse
/// tap — and always pops a `bool`: `true` from the CTA ("Pick up"),
/// `false`/null from the back arrow or a system back.
class BriefingScreen extends StatefulWidget {
  final Scenario scenario;

  const BriefingScreen({super.key, required this.scenario});

  @override
  State<BriefingScreen> createState() => _BriefingScreenState();
}

class _BriefingScreenState extends State<BriefingScreen> {
  final ScrollController _scrollController = ScrollController();

  /// Pop-once guard shared by the CTA and the back arrow — a double-tap's
  /// second pop would dismiss the HUB underneath (AC-C7).
  bool _popped = false;

  /// True while body content actually extends beneath the pinned footer —
  /// the only state the hairline is allowed to render in.
  bool _showHairline = false;

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  /// Tracks `maxScrollExtent > 0` across layout/metrics changes (first
  /// build, rotation, text-scale change) — ScrollMetricsNotification fires
  /// on all of them, not just user scrolling. The setState is deferred to
  /// post-frame because metrics notifications can arrive during layout.
  bool _onScrollMetrics(ScrollMetricsNotification notification) {
    final shouldShow = notification.metrics.maxScrollExtent > 0;
    if (shouldShow != _showHairline) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && shouldShow != _showHairline) {
          setState(() => _showHairline = shouldShow);
        }
      });
    }
    return false;
  }

  void _onBack() {
    if (_popped) return;
    // canPop covers the normal `push` entry from the hub; the `go(root)`
    // fallback covers stack-less entries (kept from the placeholder).
    if (context.canPop()) {
      _popped = true;
      context.pop(false);
    } else {
      context.go(AppRoutes.root);
    }
  }

  void _onPickUp() {
    if (_popped) return;
    if (context.canPop()) {
      _popped = true;
      context.pop(true);
    } else {
      // No caller awaits the bool on a stack-less entry — bounce home.
      context.go(AppRoutes.root);
    }
  }

  /// Visibility predicate ONLY — the rendered string stays the raw server
  /// value (guardrail: no string operations on any server field).
  String? _renderable(String? value) =>
      (value != null && value.trim().isNotEmpty) ? value : null;

  @override
  Widget build(BuildContext context) {
    final scenario = widget.scenario;
    final situationText = _renderable(scenario.briefing?['context']);
    final expectText = _renderable(scenario.briefing?['expect']);
    final vocabularyText = _renderable(scenario.briefing?['vocabulary']);
    // Fixed order: THE SITUATION → WHAT TO EXPECT → SAY THIS (vocabulary
    // last = nearest the CTA = freshest in working memory at tap). A
    // null/empty value drops its section entirely — no bare eyebrow.
    final sections = <Widget>[
      if (situationText != null)
        _BriefingSection(label: _kLabelSituation, body: situationText),
      if (expectText != null)
        _BriefingSection(label: _kLabelExpect, body: expectText),
      if (vocabularyText != null)
        _BriefingSection(
          label: _kLabelSayThis,
          body: vocabularyText,
          emphasizeBody: true,
        ),
    ];

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        // The footer owns the bottom inset (content-warning-sheet pattern)
        // so its background extends to the screen edge.
        bottom: false,
        child: Column(
          children: [
            Expanded(
              child: NotificationListener<ScrollMetricsNotification>(
                onNotification: _onScrollMetrics,
                child: SingleChildScrollView(
                  controller: _scrollController,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Padding(
                        padding: const EdgeInsets.only(
                          left:
                              AppSpacing.screenHorizontal - _kArrowOpticalInset,
                        ),
                        child: Semantics(
                          button: true,
                          label: _kBackSemanticLabel,
                          child: SizedBox(
                            width: AppSpacing.minTouchTarget,
                            height: AppSpacing.minTouchTarget,
                            child: IconButton(
                              padding: EdgeInsets.zero,
                              iconSize: _kArrowIconSize,
                              color: AppColors.textPrimary,
                              icon: const Icon(Icons.arrow_back),
                              onPressed: _onBack,
                            ),
                          ),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.screenHorizontal,
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const SizedBox(height: _kTopBarGap),
                            _HeroAvatar(scenario: scenario),
                            const SizedBox(height: _kHeroGap),
                            const Text(_kKicker, style: _eyebrowStyle),
                            const SizedBox(height: _kLockupGap),
                            Semantics(
                              header: true,
                              child: Text(
                                scenario.title,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: _titleStyle,
                              ),
                            ),
                            const SizedBox(height: _kLockupGap),
                            const Text(_kFactLine, style: _captionStyle),
                            if (sections.isNotEmpty) ...[
                              const SizedBox(height: _kTriadTopGap),
                              for (var i = 0; i < sections.length; i++) ...[
                                if (i > 0)
                                  const SizedBox(height: _kSectionGap),
                                sections[i],
                              ],
                            ],
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            _ThresholdFooter(
              showHairline: _showHairline,
              onPickUp: _onPickUp,
            ),
          ],
        ),
      ),
    );
  }
}

/// 72px circle character photo — the ONLY pictorial element on screen.
/// Non-interactive; falls back to the flat `avatarBg` circle when the
/// thumbnail asset is missing (`scenario_card.dart:_Avatar` precedent).
class _HeroAvatar extends StatelessWidget {
  final Scenario scenario;

  const _HeroAvatar({required this.scenario});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      image: true,
      label: '${scenario.title}, photo',
      child: ClipOval(
        child: Container(
          width: _kAvatarSize,
          height: _kAvatarSize,
          color: AppColors.avatarBg,
          child: Image.asset(
            'assets/images/characters/${scenario.riveCharacter}.jpg',
            width: _kAvatarSize,
            height: _kAvatarSize,
            fit: BoxFit.cover,
            errorBuilder: (_, _, _) => const SizedBox.shrink(),
          ),
        ),
      ),
    );
  }
}

/// One dossier section: eyebrow label → 8 → prose. The server string is
/// fed RAW into exactly one Text (no parsing — the authored quotation
/// marks ARE the chips). MergeSemantics reads label + body as one unit.
class _BriefingSection extends StatelessWidget {
  final String label;
  final String body;
  final bool emphasizeBody;

  const _BriefingSection({
    required this.label,
    required this.body,
    this.emphasizeBody = false,
  });

  @override
  Widget build(BuildContext context) {
    return MergeSemantics(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: _eyebrowStyle),
          const SizedBox(height: _kSectionInsideGap),
          Text(body, style: emphasizeBody ? _vocabularyStyle : _bodyStyle),
        ],
      ),
    );
  }
}

/// Pinned threshold footer: conditional 1px hairline (the single permitted
/// line on screen, visible ONLY while content scrolls beneath) → stakes
/// line (no maxLines clamp — at large text scale it wraps and the footer
/// grows; the body scrolls under it) → the locked CTA pill.
class _ThresholdFooter extends StatelessWidget {
  final bool showHairline;
  final VoidCallback onPickUp;

  const _ThresholdFooter({required this.showHairline, required this.onPickUp});

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    return ColoredBox(
      color: AppColors.background,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (showHairline)
            const SizedBox(
              key: ValueKey('briefing-footer-hairline'),
              height: 1,
              child: ColoredBox(color: AppColors.hairline),
            ),
          Padding(
            padding: EdgeInsets.fromLTRB(
              AppSpacing.screenHorizontal,
              12,
              AppSpacing.screenHorizontal,
              16 + bottomInset,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(_kStakesLine, style: _stakesStyle),
                const SizedBox(height: _kFooterStakesGap),
                ElevatedButton(
                  onPressed: onPickUp,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: AppColors.background,
                    minimumSize: const Size.fromHeight(_kCtaMinHeight),
                    shape: const StadiumBorder(),
                    elevation: 0,
                    textStyle: const TextStyle(
                      fontFamily: AppTypography.fontFamily,
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.phone_outlined, size: _kCtaIconSize),
                      SizedBox(width: _kCtaIconGap),
                      Text(_kCtaLabel),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
