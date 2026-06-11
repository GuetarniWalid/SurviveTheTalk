// Story 7.3 — Debrief screen (debrief-screen-design.md).
//
// Renders the debrief payload pre-fetched by the Call Ended overlay
// (Story 7.2) — the happy path makes ZERO network calls: the payload
// arrives through the constructor and the route's 900 ms fade owns the
// entry animation (this screen adds none).
//
// The only network code is the BS-7 fallback (call-ended-screen-design.md
// lines 515-527): entered with a null payload + non-null callId, the
// screen shows the text-only "Analyzing your conversation..." state and
// resumes polling `GET /debriefs/{call_id}` every ~1 s, bounded by a 30 s
// budget (7.1 reality: a permanently-failed generation returns
// DEBRIEF_NOT_READY forever). Budget exhausted / null callId / structural
// parse failure / terminal ApiException → quiet "Debrief unavailable"
// state. Never a crash, never error chrome (AC10), never a retry button
// (AC7 — polling IS the retry).
//
// No bloc (declared deviation from the design doc's file table): the
// state here is screen-local and tiny (3 phases, two timers) and the
// reviewed sibling `CallEndedScreen` established the exact pattern —
// StatefulWidget + injected `CallRepository` + constructor timing seams.

import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../call/repositories/call_repository.dart';
import '../models/debrief.dart';

// Layout constants (debrief-screen-design.md) — local consts per the
// Story 7.2 precedent; no AppSpacing additions required.
const double _kArrowInset = 8.0;
const double _kArrowIconSize = 24.0;
const double _kHeroTopGap = 30.0;
const double _kHeroTightGap = 8.0;
const double _kHeroIdentityGap = 16.0;
const double _kSectionGap = 24.0;
const double _kCountLineGap = 4.0;
const double _kCardGap = 12.0;
const double _kCardPadding = 16.0;
const double _kCardRadius = 12.0;
const double _kCardLabelGap = 4.0;
const double _kCardBlockGap = 12.0;
const double _kIdiomMeaningGap = 8.0;
const double _kAreaItemGap = 8.0;
const double _kImprovementGap = 4.0;
const double _kBottomPadding = 40.0;
const double _kAboutBorderWidth = 4.0;

// Encouraging framing sits in a 40px-padded text column (narrower for
// readability) — 20px comes from the screen padding, this adds the rest.
const double _kFramingExtraHorizontalPadding = 20.0;

/// "Attempt #N" with the "· Previous best: X%" segment only when a
/// previous best exists (design: no "Previous best: 0%" clutter on the
/// first attempt).
@visibleForTesting
String debriefAttemptLine({
  required int attemptNumber,
  required int? previousBest,
}) {
  final base = 'Attempt #$attemptNumber';
  if (previousBest == null) return base;
  return '$base · Previous best: $previousBest%';
}

/// Count line under the "Language Errors" header.
@visibleForTesting
String errorCountLine(int count) {
  if (count == 0) return 'No errors flagged';
  if (count == 1) return '1 error flagged';
  return '$count errors flagged';
}

/// Count line under the "Hesitation Analysis" header.
@visibleForTesting
String hesitationCountLine(int count) {
  if (count == 0) return 'No hesitations flagged';
  if (count == 1) return '1 moment flagged';
  return '$count moments flagged';
}

/// "You said:" card label, with the dedup badge once an error repeats
/// (content-strategy Q8: "(×N)" only when count >= 2).
@visibleForTesting
String errorYouSaidLabel(int count) =>
    count >= 2 ? 'You said (×$count):' : 'You said:';

/// Screen state machine (story Task 3.1).
enum _DebriefPhase { content, loading, unavailable }

class DebriefScreen extends StatefulWidget {
  /// Canonical BS-7 polling cadence/budget — tests shrink these through
  /// the constructor seams so the loop runs inside a pumped window.
  static const Duration kPollInterval = Duration(seconds: 1);
  static const Duration kPollBudget = Duration(seconds: 30);

  /// Debrief payload pre-fetched by the Call Ended overlay. Null when the
  /// overlay's 10 s cap fired first, the callId was unknown, or its fetch
  /// failed terminally — the BS-7 fallback then takes over.
  final Map<String, dynamic>? payload;

  /// Call-session id for the resume-poll. Null disables polling entirely
  /// (nothing to fetch with → "unavailable").
  final int? callId;

  final CallRepository callRepository;

  final Duration pollInterval;
  final Duration pollBudget;

  const DebriefScreen({
    super.key,
    required this.payload,
    required this.callId,
    required this.callRepository,
    this.pollInterval = kPollInterval,
    this.pollBudget = kPollBudget,
  });

  @override
  State<DebriefScreen> createState() => _DebriefScreenState();
}

class _DebriefScreenState extends State<DebriefScreen> {
  late _DebriefPhase _phase;
  Debrief? _debrief;
  Timer? _pollTimer;
  Timer? _budgetTimer;

  @override
  void initState() {
    super.initState();
    if (widget.payload != null) {
      // Happy path — zero network. A provided-but-broken payload is
      // terminal (re-fetching would return the same bytes).
      final parsed = Debrief.tryParse(widget.payload);
      _debrief = parsed;
      _phase = parsed != null
          ? _DebriefPhase.content
          : _DebriefPhase.unavailable;
    } else if (widget.callId != null) {
      // BS-7 — the overlay handed off before the debrief settled.
      _phase = _DebriefPhase.loading;
      _budgetTimer = Timer(widget.pollBudget, _onBudgetExhausted);
      unawaited(_attemptFetch());
    } else {
      _phase = _DebriefPhase.unavailable;
    }
  }

  Future<void> _attemptFetch() async {
    final callId = widget.callId;
    if (callId == null) return; // loading is only entered with an id
    try {
      final payload = await widget.callRepository.fetchDebrief(callId: callId);
      if (!mounted || _phase != _DebriefPhase.loading) return;
      _settle(Debrief.tryParse(payload));
      // Broad catch mirrors CallEndedScreen._attemptFetch: a post-call
      // fetch failure must never crash or surface error chrome — anything
      // that isn't "still generating" lands on the quiet terminal state.
      // ignore: avoid_catches_without_on_clauses
    } catch (e) {
      if (!mounted || _phase != _DebriefPhase.loading) return;
      if (e is ApiException && e.code == 'DEBRIEF_NOT_READY') {
        // Still generating — re-arm; the 30 s budget bounds the loop.
        _pollTimer = Timer(widget.pollInterval, () {
          unawaited(_attemptFetch());
        });
        return;
      }
      _settle(null);
    }
  }

  /// Terminal transition out of `loading` — content when the payload
  /// parses, unavailable otherwise.
  void _settle(Debrief? parsed) {
    _budgetTimer?.cancel();
    _budgetTimer = null;
    setState(() {
      _debrief = parsed;
      _phase = parsed != null
          ? _DebriefPhase.content
          : _DebriefPhase.unavailable;
    });
  }

  void _onBudgetExhausted() {
    if (!mounted || _phase != _DebriefPhase.loading) return;
    _pollTimer?.cancel();
    _pollTimer = null;
    setState(() => _phase = _DebriefPhase.unavailable);
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _budgetTimer?.cancel();
    _budgetTimer = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // No PopScope — system back must work (CallEndedScreen's P-4 rule
    // does NOT apply here); the stack is [scenario list shell, debrief].
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        // BS-7 — a late-arriving payload fades the content in over the
        // loading text (300 ms, easeOut). The initial child renders
        // without animation, so the constructor-payload path adds no
        // entry effect on top of the route's fade.
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 300),
          switchInCurve: Curves.easeOut,
          child: _buildPhase(),
        ),
      ),
    );
  }

  Widget _buildPhase() {
    switch (_phase) {
      case _DebriefPhase.content:
        return _DebriefContent(
          key: const ValueKey('debrief-content'),
          debrief: _debrief!,
        );
      case _DebriefPhase.loading:
        // Text only — explicitly NOT a spinner (BS-7).
        return _DebriefMessage(
          key: const ValueKey('debrief-loading'),
          message: 'Analyzing your conversation...',
          style: AppTypography.body.copyWith(color: AppColors.textSecondary),
        );
      case _DebriefPhase.unavailable:
        return _DebriefMessage(
          key: const ValueKey('debrief-unavailable'),
          message: 'Debrief unavailable for this call.',
          style: AppTypography.caption.copyWith(
            color: AppColors.textSecondary,
          ),
        );
    }
  }
}

/// Back arrow — sole exit (AC7). Lives inside the scroll view on the
/// content state (resolved design Q1: it scrolls with content).
class _BackArrow extends StatelessWidget {
  const _BackArrow();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: _kArrowInset, left: _kArrowInset),
      child: Align(
        alignment: Alignment.topLeft,
        child: Semantics(
          button: true,
          label: 'Back to scenarios',
          child: SizedBox(
            width: AppSpacing.minTouchTarget,
            height: AppSpacing.minTouchTarget,
            child: IconButton(
              padding: EdgeInsets.zero,
              iconSize: _kArrowIconSize,
              color: AppColors.textPrimary,
              icon: const Icon(Icons.arrow_back_ios_new),
              // Root-navigator imperative route (pushed by the overlay's
              // pushReplacement) — Navigator.pop, NOT go_router's
              // context.pop().
              onPressed: () => Navigator.of(context).pop(),
            ),
          ),
        ),
      ),
    );
  }
}

/// Loading / unavailable layout — back arrow at top, centered message
/// where content would appear. No spinner, no retry, no snackbars.
class _DebriefMessage extends StatelessWidget {
  final String message;
  final TextStyle style;

  const _DebriefMessage({
    super.key,
    required this.message,
    required this.style,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _BackArrow(),
        Expanded(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.screenHorizontal,
              ),
              child: Text(message, textAlign: TextAlign.center, style: style),
            ),
          ),
        ),
      ],
    );
  }
}

/// Full debrief layout — single scroll, sections 24px apart.
class _DebriefContent extends StatelessWidget {
  final Debrief debrief;

  const _DebriefContent({super.key, required this.debrief});

  @override
  Widget build(BuildContext context) {
    final d = debrief;
    final heroColor = d.survivalPct == 100
        ? AppColors.statusCompleted
        : AppColors.destructive;
    final mutedCaption = AppTypography.caption.copyWith(
      color: AppColors.textSecondary,
    );
    final framing = d.encouragingFraming;
    final about = d.inappropriateBehavior;

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _BackArrow(),
          Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.screenHorizontal,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SizedBox(height: _kHeroTopGap),
                // Hero — the self-contained screenshot block (AC8).
                Text(
                  '${d.survivalPct}%',
                  textAlign: TextAlign.center,
                  maxLines: 1,
                  semanticsLabel: '${d.survivalPct} percent survival rate',
                  style: AppTypography.display.copyWith(color: heroColor),
                ),
                const SizedBox(height: _kHeroTightGap),
                Text(
                  'Survival Rate',
                  textAlign: TextAlign.center,
                  style: mutedCaption,
                ),
                const SizedBox(height: _kHeroIdentityGap),
                Text(
                  '${d.characterName} — ${d.scenarioTitle}',
                  textAlign: TextAlign.center,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTypography.headline.copyWith(
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: _kHeroTightGap),
                Text(
                  debriefAttemptLine(
                    attemptNumber: d.attemptNumber,
                    previousBest: d.previousBest,
                  ),
                  textAlign: TextAlign.center,
                  maxLines: 1,
                  style: mutedCaption,
                ),
                // Encouraging framing (FR15b) — keyed on field presence,
                // never on survival_pct; server strings render VERBATIM
                // (copy is server-owned).
                if (framing != null) ...[
                  const SizedBox(height: _kSectionGap),
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: _kFramingExtraHorizontalPadding,
                    ),
                    child: Column(
                      children: [
                        Text(
                          framing.proximity,
                          textAlign: TextAlign.center,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: AppTypography.body.copyWith(
                            color: AppColors.accent,
                          ),
                        ),
                        if (framing.improvement != null) ...[
                          const SizedBox(height: _kImprovementGap),
                          Text(
                            framing.improvement!,
                            textAlign: TextAlign.center,
                            style: mutedCaption,
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
                // Language Errors (FR10) — always visible.
                const SizedBox(height: _kSectionGap),
                const _SectionHeader('Language Errors'),
                const SizedBox(height: _kCountLineGap),
                Text(errorCountLine(d.errors.length), style: mutedCaption),
                for (final error in d.errors) ...[
                  const SizedBox(height: _kCardGap),
                  _ErrorCard(error: error),
                ],
                // Hesitation Analysis (FR12) — always visible.
                const SizedBox(height: _kSectionGap),
                const _SectionHeader('Hesitation Analysis'),
                const SizedBox(height: _kCountLineGap),
                Text(
                  hesitationCountLine(d.hesitations.length),
                  style: mutedCaption,
                ),
                for (final hesitation in d.hesitations) ...[
                  const SizedBox(height: _kCardGap),
                  _HesitationCard(hesitation: hesitation),
                ],
                // Idioms & Slang (FR13) — absence of the section IS the
                // design: no header, no "No idioms encountered".
                if (d.idioms.isNotEmpty) ...[
                  const SizedBox(height: _kSectionGap),
                  const _SectionHeader('Idioms & Slang'),
                  for (final idiom in d.idioms) ...[
                    const SizedBox(height: _kCardGap),
                    _IdiomCard(idiom: idiom),
                  ],
                ],
                // About This Call (FR37 / AC9) — hidden when null.
                if (about != null) ...[
                  const SizedBox(height: _kSectionGap),
                  const _SectionHeader('About This Call'),
                  const SizedBox(height: _kCardGap),
                  _AboutThisCallCard(explanation: about),
                ],
                // Areas to Work On — always; server clamps to <= 3.
                const SizedBox(height: _kSectionGap),
                const _SectionHeader('Areas to Work On'),
                const SizedBox(height: _kCardGap),
                _AreasCard(areas: d.areasToWorkOn),
                const SizedBox(height: _kBottomPadding),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;

  const _SectionHeader(this.title);

  @override
  Widget build(BuildContext context) {
    return Semantics(
      header: true,
      child: Text(
        title,
        style: AppTypography.headline.copyWith(color: AppColors.textPrimary),
      ),
    );
  }
}

/// Shared card chrome — avatar-bg, 12px radius, 16px padding.
class _DebriefCard extends StatelessWidget {
  final Widget child;

  const _DebriefCard({required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(_kCardPadding),
      decoration: const BoxDecoration(
        color: AppColors.avatarBg,
        borderRadius: BorderRadius.all(Radius.circular(_kCardRadius)),
      ),
      child: child,
    );
  }
}

class _ErrorCard extends StatelessWidget {
  final DebriefError error;

  const _ErrorCard({required this.error});

  @override
  Widget build(BuildContext context) {
    final labelStyle = AppTypography.sectionTitle.copyWith(
      color: AppColors.textSecondary,
    );
    return _DebriefCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(errorYouSaidLabel(error.count), style: labelStyle),
          const SizedBox(height: _kCardLabelGap),
          Text(
            error.userSaid,
            style: AppTypography.body.copyWith(color: AppColors.textPrimary),
          ),
          const SizedBox(height: _kCardBlockGap),
          Text('Correct form:', style: labelStyle),
          const SizedBox(height: _kCardLabelGap),
          // Accent marks the learnable content (AC2).
          Text(
            error.correction,
            style: AppTypography.bodyEmphasis.copyWith(
              color: AppColors.accent,
            ),
          ),
          const SizedBox(height: _kCardBlockGap),
          Text(
            error.context,
            style: AppTypography.caption.copyWith(
              color: AppColors.textSecondary,
              fontStyle: FontStyle.italic,
            ),
          ),
        ],
      ),
    );
  }
}

class _HesitationCard extends StatelessWidget {
  final DebriefHesitation hesitation;

  const _HesitationCard({required this.hesitation});

  @override
  Widget build(BuildContext context) {
    return _DebriefCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Pause',
            style: AppTypography.sectionTitle.copyWith(
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: _kCardLabelGap),
          Text(
            '${hesitation.durationSec.toStringAsFixed(1)} seconds',
            style: AppTypography.debriefDuration.copyWith(
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(height: _kCardBlockGap),
          Text(
            '"${hesitation.context}"',
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: AppTypography.body.copyWith(
              color: AppColors.textSecondary,
              fontStyle: FontStyle.italic,
            ),
          ),
        ],
      ),
    );
  }
}

class _IdiomCard extends StatelessWidget {
  final DebriefIdiom idiom;

  const _IdiomCard({required this.idiom});

  @override
  Widget build(BuildContext context) {
    return _DebriefCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            "'${idiom.expression}'",
            style: AppTypography.bodyEmphasis.copyWith(
              color: AppColors.accent,
            ),
          ),
          const SizedBox(height: _kIdiomMeaningGap),
          Text(
            idiom.meaning,
            style: AppTypography.body.copyWith(color: AppColors.textPrimary),
          ),
          const SizedBox(height: _kCardBlockGap),
          Text(
            '"${idiom.context}"',
            style: AppTypography.caption.copyWith(
              color: AppColors.textSecondary,
              fontStyle: FontStyle.italic,
            ),
          ),
        ],
      ),
    );
  }
}

/// FR37 card — avatar-bg with the 4px destructive left stripe.
/// BoxDecoration can't combine a non-uniform border with a borderRadius,
/// so the rounded corners come from a ClipRRect around the striped box.
class _AboutThisCallCard extends StatelessWidget {
  final String explanation;

  const _AboutThisCallCard({required this.explanation});

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: const BorderRadius.all(Radius.circular(_kCardRadius)),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(_kCardPadding),
        decoration: const BoxDecoration(
          color: AppColors.avatarBg,
          border: Border(
            left: BorderSide(
              color: AppColors.destructive,
              width: _kAboutBorderWidth,
            ),
          ),
        ),
        child: Text(
          explanation,
          maxLines: 5,
          overflow: TextOverflow.ellipsis,
          style: AppTypography.body.copyWith(color: AppColors.textPrimary),
        ),
      ),
    );
  }
}

/// Single card, numbered study list (numbers imply priority — no accent
/// colors, no bullets).
class _AreasCard extends StatelessWidget {
  final List<String> areas;

  const _AreasCard({required this.areas});

  @override
  Widget build(BuildContext context) {
    return _DebriefCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < areas.length; i++) ...[
            if (i > 0) const SizedBox(height: _kAreaItemGap),
            Text(
              '${i + 1}. ${areas[i]}',
              style: AppTypography.body.copyWith(color: AppColors.textPrimary),
            ),
          ],
        ],
      ),
    );
  }
}
