// Story 7.5 — Debrief screen v2 (debrief-screen-design.md §v2.0, Walid-validated
// 2026-06-15). Direction B "Rapport structuré — riche au clic, sobre au premier
// regard": an arc-gauge scorecard hero, a checkpoint breakdown that explains the
// %, and cards that reveal depth on tap (a DARK detail sheet for errors) or copy
// a server-authored practice prompt (areas only).
//
// The StatefulWidget host + BS-7 fallback machinery is UNCHANGED from v1 (Story
// 7.3): the payload is pre-fetched by the Call Ended overlay (zero network on the
// happy path); a null payload + non-null callId enters the text-only
// "Analyzing your conversation..." resume-poll (1 s cadence, 30 s budget), then a
// quiet "Debrief unavailable" terminal state. Never a crash, never error chrome,
// never a retry button (AC7/AC10 — polling IS the retry).
//
// A v1 payload (debrief_version 1, no v2 lists) renders without crashing — every
// v2 section is empty-gated and areas fall back to areasToWorkOn (AC2).
//
// No bloc (declared deviation from the design doc's file table) — screen-local
// state is tiny (3 phases, two timers), mirroring the reviewed CallEndedScreen.

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_toast.dart';
import '../../call/repositories/call_repository.dart';
import '../models/debrief.dart';

// COPY LINT (Story 7.5 debrief v2 — clinical charter; inherits the 7.4
// "Handler's Brief" rulebook, Walid-validated). BANNED on this screen AND its
// sheet, everywhere: exclamation marks; question marks in CHROME; praise /
// congratulation ("Great", "Well done", "Nice"); emoji; "tips" framing; urgency.
// Voice is the APP's, clinical-frank. A2/B1 parseable under mild post-call
// stress: present tense, second person, no idioms in chrome. Durations are
// APPROXIMATE and carry the '~'. Server strings (error/correction/context/
// explanation/examples/idiom/area/evidence/practice_prompt/phrasing/framing/
// inappropriate_behavior + checkpoint hints) render VERBATIM and are not counted.

// --- App-owned chrome strings ---
const String _kSurvivalRateLabel = 'Survival Rate';
const String _kHdrCheckpoints = 'CHECKPOINTS';
const String _kHdrErrors = 'LANGUAGE ERRORS';
const String _kHdrHesitations = 'HESITATIONS';
const String _kHdrIdioms = 'IDIOMS & SLANG';
const String _kHdrBetterPhrasing = 'SAID MORE NATURALLY';
const String _kHdrAbout = 'ABOUT THIS CALL';
const String _kHdrAreas = 'AREAS TO WORK ON';
const String _kEyebrowFocusFirst = 'FOCUS FIRST';
const String _kSheetEyebrowExamples = 'EXAMPLES';
const String _kLblCorrectForm = 'Correct form:';
const String _kLblYouSaid = 'You said:';
const String _kLblMoreNatural = 'More natural:';
const String _kLblPause = 'Pause';
const String _kHesFreezeNote = 'The character had to speak first.';
const String _kCopyButtonLabel = 'Copy practice';
const String _kCopiedConfirm = 'Copied';
const String _kDetailHint = 'Show detail';
const String _kBackSemantics = 'Back to scenarios';
const String _kLoading = 'Analyzing your conversation...';
const String _kUnavailable = 'Debrief unavailable for this call.';

// Layout constants (local consts per the Story 7.2/7.3 precedent).
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
const double _kImprovementGap = 4.0;
const double _kBottomPadding = 40.0;
const double _kAboutBorderWidth = 4.0;
const double _kFramingExtraHorizontalPadding = 20.0;

// Gauge (hero) — a self-contained, screenshot-worthy unit (AC8).
const double _kGaugeSize = 180.0;
// Narrower than the ring's clear bore so the % scales DOWN a touch (Walid
// 2026-06-15: the number was a hair too big / too close to the arc).
const double _kGaugeInnerWidth = 100.0;
const double _kGaugeStroke = 12.0;
// The %→label gap inside the ring. The % itself carries height:1.0 so its line
// box has no extra leading — without that the label drifted too far below.
const double _kGaugeLabelGap = 4.0;

// Checkpoint breakdown — flat on-rail list, no card.
const double _kCheckpointRowGap = 12.0;
const double _kCheckpointMarkerSize = 18.0;
const double _kCheckpointMarkerGap = 8.0;
const double _kCheckpointMarkerBorder = 1.5;
const double _kCheckpointGlyphSize = 12.0;
const double _kEyebrowGap = 8.0;

// Tap-for-detail + copy affordances.
const double _kChevronSize = 22.0;
const double _kChevronGap = 8.0;
const double _kCopyButtonTopGap = 12.0;
const double _kCopyIconSize = 16.0;
const double _kCopyIconGap = 6.0;
const double _kCopyButtonVPad = 8.0;

// Dark detail sheet — matched to the report (Walid 2026-06-15: dark, NOT the
// light content-warning/difficulty sheet). Reuses the showModalBottomSheet
// plumbing + drag-handle, themed onto the elevated card surface.
const double _kSheetRadius = 42.0;
const double _kSheetHPad = 36.0;
const double _kSheetTopPad = 24.0;
const double _kSheetBottomPad = 36.0;
const double _kSheetHandleGap = 24.0;
const double _kSheetBlockGap = 16.0;
const double _kSheetExampleGap = 8.0;
const double _kDragHandleWidth = 40.0;
const double _kDragHandleHeight = 4.0;

const double _kEyebrowLetterSpacing = 1.0;

/// Hero gauge color (Walid 2026-06-15): red at/below 40% (below the survival
/// threshold), amber 41-99% (survived, not perfect), green at 100%.
@visibleForTesting
Color scoreColor(int survivalPct) {
  if (survivalPct >= 100) return AppColors.statusCompleted;
  if (survivalPct > 40) return AppColors.warning;
  return AppColors.destructive;
}

/// "Attempt #N" with the "· Previous best: X%" segment only when a previous
/// best exists (no "Previous best: 0%" clutter on the first attempt).
@visibleForTesting
String debriefAttemptLine({
  required int attemptNumber,
  required int? previousBest,
}) {
  final base = 'Attempt #$attemptNumber';
  if (previousBest == null) return base;
  return '$base · Previous best: $previousBest%';
}

/// Count line under "Language Errors".
@visibleForTesting
String errorCountLine(int count) {
  if (count == 0) return 'No errors flagged';
  if (count == 1) return '1 error flagged';
  return '$count errors flagged';
}

/// Count line under "Hesitations".
@visibleForTesting
String hesitationCountLine(int count) {
  if (count == 0) return 'No hesitations flagged';
  if (count == 1) return '1 moment flagged';
  return '$count moments flagged';
}

/// Summary line under "Checkpoints" — the factual decomposition of the %.
@visibleForTesting
String checkpointCountLine(int met, int total) => '$met of $total reached';

/// "You said:" card label, with the dedup badge once an error repeats
/// (content-strategy Q8: "(×N)" only when count >= 2).
@visibleForTesting
String errorYouSaidLabel(int count) =>
    count >= 2 ? 'You said (×$count):' : 'You said:';

/// Surface duration label — ALWAYS approximate ("~Ns"); the measurement is an
/// estimate, never a stopwatch (Story 7.5 C5).
@visibleForTesting
String hesitationDurationLabel(double sec) => '~${sec.round()}s';

/// Per-checkpoint a11y phrase (state in words, not glyph/color).
@visibleForTesting
String checkpointSemantics(bool met, String hint) =>
    met ? 'Reached: $hint' : 'Not reached: $hint';

/// Screen state machine (Story 7.3 Task 3.1) — unchanged.
enum _DebriefPhase { content, loading, unavailable }

class DebriefScreen extends StatefulWidget {
  /// Canonical BS-7 polling cadence/budget — tests shrink these through the
  /// constructor seams so the loop runs inside a pumped window.
  static const Duration kPollInterval = Duration(seconds: 1);
  static const Duration kPollBudget = Duration(seconds: 30);

  /// Debrief payload pre-fetched by the Call Ended overlay. Null when the
  /// overlay's 10 s cap fired first, the callId was unknown, or its fetch
  /// failed terminally — the BS-7 fallback then takes over.
  final Map<String, dynamic>? payload;

  /// Call-session id for the resume-poll. Null disables polling.
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
      final parsed = Debrief.tryParse(widget.payload);
      _debrief = parsed;
      _phase = parsed != null
          ? _DebriefPhase.content
          : _DebriefPhase.unavailable;
    } else if (widget.callId != null) {
      _phase = _DebriefPhase.loading;
      _budgetTimer = Timer(widget.pollBudget, _onBudgetExhausted);
      unawaited(_attemptFetch());
    } else {
      _phase = _DebriefPhase.unavailable;
    }
  }

  Future<void> _attemptFetch() async {
    final callId = widget.callId;
    if (callId == null) return;
    try {
      final payload = await widget.callRepository.fetchDebrief(callId: callId);
      if (!mounted || _phase == _DebriefPhase.content) return;
      _settle(Debrief.tryParse(payload));
      // ignore: avoid_catches_without_on_clauses
    } catch (e) {
      if (!mounted || _phase != _DebriefPhase.loading) return;
      if (e is ApiException && e.code == 'DEBRIEF_NOT_READY') {
        _pollTimer = Timer(widget.pollInterval, () {
          unawaited(_attemptFetch());
        });
        return;
      }
      _settle(null);
    }
  }

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
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
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
        return _DebriefMessage(
          key: const ValueKey('debrief-loading'),
          message: _kLoading,
          style: AppTypography.body.copyWith(color: AppColors.textSecondary),
        );
      case _DebriefPhase.unavailable:
        return _DebriefMessage(
          key: const ValueKey('debrief-unavailable'),
          message: _kUnavailable,
          style: AppTypography.caption.copyWith(color: AppColors.textSecondary),
        );
    }
  }
}

/// Back arrow — sole exit (AC7). Scrolls with content on the content state.
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
          label: _kBackSemantics,
          child: SizedBox(
            width: AppSpacing.minTouchTarget,
            height: AppSpacing.minTouchTarget,
            child: IconButton(
              padding: EdgeInsets.zero,
              iconSize: _kArrowIconSize,
              color: AppColors.textPrimary,
              icon: const Icon(Icons.arrow_back_ios_new),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ),
        ),
      ),
    );
  }
}

/// Loading / unavailable layout — back arrow + centered message. No spinner,
/// no retry, no snackbars.
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

/// Full v2 debrief layout — single scroll, sections 24px apart on one left rail.
class _DebriefContent extends StatelessWidget {
  final Debrief debrief;

  const _DebriefContent({super.key, required this.debrief});

  @override
  Widget build(BuildContext context) {
    final d = debrief;
    final mutedCaption = AppTypography.caption.copyWith(
      color: AppColors.textSecondary,
    );
    final framing = d.encouragingFraming;
    final about = d.inappropriateBehavior;
    final metCount = d.checkpoints.where((c) => c.met).length;

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
                // HERO — the self-contained scorecard (AC8). Centered as a unit.
                const SizedBox(height: _kHeroTopGap),
                _ScoreGauge(survivalPct: d.survivalPct),
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
                  overflow: TextOverflow.ellipsis,
                  style: mutedCaption,
                ),
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
                // CHECKPOINTS (B7) — the "why this score?" factual layer leads.
                if (d.checkpoints.isNotEmpty) ...[
                  const SizedBox(height: _kSectionGap),
                  const _SectionHeader(_kHdrCheckpoints),
                  const SizedBox(height: _kCountLineGap),
                  Text(
                    checkpointCountLine(metCount, d.checkpoints.length),
                    style: mutedCaption,
                  ),
                  for (final cp in d.checkpoints) ...[
                    const SizedBox(height: _kCheckpointRowGap),
                    _CheckpointRow(checkpoint: cp),
                  ],
                ],
                // LANGUAGE ERRORS — always visible (count line).
                const SizedBox(height: _kSectionGap),
                const _SectionHeader(_kHdrErrors),
                const SizedBox(height: _kCountLineGap),
                Text(errorCountLine(d.errors.length), style: mutedCaption),
                for (final error in d.errors) ...[
                  const SizedBox(height: _kCardGap),
                  _ErrorCard(error: error),
                ],
                // HESITATIONS — always visible (count line).
                const SizedBox(height: _kSectionGap),
                const _SectionHeader(_kHdrHesitations),
                const SizedBox(height: _kCountLineGap),
                Text(
                  hesitationCountLine(d.hesitations.length),
                  style: mutedCaption,
                ),
                for (final hesitation in d.hesitations) ...[
                  const SizedBox(height: _kCardGap),
                  _HesitationCard(hesitation: hesitation),
                ],
                // IDIOMS & SLANG — absence IS the design (no empty state).
                if (d.idioms.isNotEmpty) ...[
                  const SizedBox(height: _kSectionGap),
                  const _SectionHeader(_kHdrIdioms),
                  for (final idiom in d.idioms) ...[
                    const SizedBox(height: _kCardGap),
                    _IdiomCard(idiom: idiom),
                  ],
                ],
                // SAID MORE NATURALLY (B2) — hidden when empty (often is).
                if (d.betterPhrasings.isNotEmpty) ...[
                  const SizedBox(height: _kSectionGap),
                  const _SectionHeader(_kHdrBetterPhrasing),
                  for (final phrasing in d.betterPhrasings) ...[
                    const SizedBox(height: _kCardGap),
                    _BetterPhrasingCard(phrasing: phrasing),
                  ],
                ],
                // ABOUT THIS CALL (FR37) — hidden when null.
                if (about != null) ...[
                  const SizedBox(height: _kSectionGap),
                  const _SectionHeader(_kHdrAbout),
                  const SizedBox(height: _kCardGap),
                  _AboutThisCallCard(explanation: about),
                ],
                // AREAS TO WORK ON — rich v2 cards when present; v1 fallback to
                // the flat title list otherwise (AC2).
                if (d.areas.isNotEmpty) ...[
                  const SizedBox(height: _kSectionGap),
                  const _SectionHeader(_kHdrAreas),
                  for (final area in d.areas) ...[
                    const SizedBox(height: _kCardGap),
                    _AreaCard(area: area),
                  ],
                ] else if (d.areasToWorkOn.isNotEmpty) ...[
                  const SizedBox(height: _kSectionGap),
                  const _SectionHeader(_kHdrAreas),
                  const SizedBox(height: _kCardGap),
                  _AreasFallbackCard(areas: d.areasToWorkOn),
                ],
                const SizedBox(height: _kBottomPadding),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// The arc-gauge scorecard hero — a 270° two-arc ring with the % centered
/// inside. Pure-Flutter CustomPainter (HUD-is-Flutter ruling), no animation
/// (the route's 900 ms fade owns entry).
class _ScoreGauge extends StatelessWidget {
  final int survivalPct;

  const _ScoreGauge({required this.survivalPct});

  @override
  Widget build(BuildContext context) {
    final color = scoreColor(survivalPct);
    return Center(
      child: Semantics(
        label: '$survivalPct percent survival rate',
        child: SizedBox(
          width: _kGaugeSize,
          height: _kGaugeSize,
          child: Stack(
            alignment: Alignment.center,
            children: [
              ExcludeSemantics(
                child: CustomPaint(
                  size: const Size.square(_kGaugeSize),
                  painter: _ScoreGaugePainter(
                    fraction: survivalPct / 100.0,
                    color: color,
                  ),
                ),
              ),
              ExcludeSemantics(
                child: SizedBox(
                  width: _kGaugeInnerWidth,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Text(
                          '$survivalPct%',
                          maxLines: 1,
                          // height:1.0 — collapse the font's default leading so
                          // the label sits snug under the number, and the
                          // number+label pair centres in the ring.
                          style: AppTypography.display.copyWith(
                            color: color,
                            height: 1.0,
                          ),
                        ),
                      ),
                      const SizedBox(height: _kGaugeLabelGap),
                      Text(
                        _kSurvivalRateLabel,
                        textAlign: TextAlign.center,
                        style: AppTypography.caption.copyWith(
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ScoreGaugePainter extends CustomPainter {
  final double fraction;
  final Color color;

  const _ScoreGaugePainter({required this.fraction, required this.color});

  // A "speedometer" sweep: a 270° arc opening at the bottom, starting at 135°
  // (lower-left) clockwise.
  static const double _start = 3 * math.pi / 4;
  static const double _full = 3 * math.pi / 2;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = (Offset.zero & size).deflate(_kGaugeStroke / 2);
    final track = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = _kGaugeStroke
      ..strokeCap = StrokeCap.round
      ..color = AppColors.gaugeTrack;
    canvas.drawArc(rect, _start, _full, false, track);
    final f = fraction.clamp(0.0, 1.0);
    if (f > 0) {
      final value = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = _kGaugeStroke
        ..strokeCap = StrokeCap.round
        ..color = color;
      canvas.drawArc(rect, _start, _full * f, false, value);
    }
  }

  @override
  bool shouldRepaint(_ScoreGaugePainter oldDelegate) =>
      oldDelegate.fraction != fraction || oldDelegate.color != color;
}

/// Section eyebrow — 12/500 UPPERCASE, +1.0 tracking, textSecondary (Handler's
/// Brief). Keeps the class name + Semantics(header:true) so call sites are
/// unchanged from v1.
class _SectionHeader extends StatelessWidget {
  final String title;

  const _SectionHeader(this.title);

  @override
  Widget build(BuildContext context) {
    return Semantics(
      header: true,
      child: Text(
        title,
        style: AppTypography.label.copyWith(
          color: AppColors.textSecondary,
          letterSpacing: _kEyebrowLetterSpacing,
        ),
      ),
    );
  }
}

/// One met/missed beat row — flat on the rail (no card). The state marker is the
/// ONLY place accent is earned in the body, and only as a FILL (two-ink rule).
class _CheckpointRow extends StatelessWidget {
  final DebriefCheckpoint checkpoint;

  const _CheckpointRow({required this.checkpoint});

  @override
  Widget build(BuildContext context) {
    final met = checkpoint.met;
    return Semantics(
      label: checkpointSemantics(met, checkpoint.hint),
      excludeSemantics: true,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _CheckpointMarker(met: met),
          const SizedBox(width: _kCheckpointMarkerGap),
          Expanded(
            child: Text(
              checkpoint.hint,
              style: AppTypography.body.copyWith(
                color: met ? AppColors.textPrimary : AppColors.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CheckpointMarker extends StatelessWidget {
  final bool met;

  const _CheckpointMarker({required this.met});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: _kCheckpointMarkerSize,
      height: _kCheckpointMarkerSize,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: met ? AppColors.accent : Colors.transparent,
        border: met
            ? null
            : Border.all(
                color: AppColors.avatarBg,
                width: _kCheckpointMarkerBorder,
              ),
      ),
      child: Icon(
        met ? Icons.check : Icons.remove,
        size: _kCheckpointGlyphSize,
        // Accent is a FILL; the glyph sits in the background ink (met) — never
        // accent-as-icon-color floating on the dark surface.
        color: met ? AppColors.background : AppColors.textSecondary,
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

/// Error card — brief on the surface (context), depth on tap (rule + examples)
/// in a DARK sheet. A chevron appears ONLY when there IS depth (honest
/// affordance). NO copy button (Walid 2026-06-15: copy is areas-only).
class _ErrorCard extends StatelessWidget {
  final DebriefError error;

  const _ErrorCard({required this.error});

  bool get _hasDepth =>
      (error.explanation != null && error.explanation!.isNotEmpty) ||
      error.examples.isNotEmpty;

  @override
  Widget build(BuildContext context) {
    final labelStyle = AppTypography.sectionTitle.copyWith(
      color: AppColors.textSecondary,
    );
    final card = _DebriefCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(errorYouSaidLabel(error.count), style: labelStyle),
                const SizedBox(height: _kCardLabelGap),
                Text(
                  error.userSaid,
                  style: AppTypography.body.copyWith(
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: _kCardBlockGap),
                Text(_kLblCorrectForm, style: labelStyle),
                const SizedBox(height: _kCardLabelGap),
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
          ),
          if (_hasDepth) ...[
            const SizedBox(width: _kChevronGap),
            const Icon(
              Icons.chevron_right,
              color: AppColors.textSecondary,
              size: _kChevronSize,
            ),
          ],
        ],
      ),
    );
    if (!_hasDepth) return card;
    return Semantics(
      button: true,
      hint: _kDetailHint,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => showErrorDetailSheet(context, error),
        child: card,
      ),
    );
  }
}

/// Opens the DARK error-detail sheet (rule + examples). Read-only,
/// fire-and-forget. Reuses the showModalBottomSheet plumbing; themed dark.
Future<void> showErrorDetailSheet(BuildContext context, DebriefError error) {
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    isDismissible: true,
    enableDrag: true,
    builder: (_) => _ErrorDetailSheet(error: error),
  );
}

class _ErrorDetailSheet extends StatelessWidget {
  final DebriefError error;

  const _ErrorDetailSheet({required this.error});

  @override
  Widget build(BuildContext context) {
    final labelStyle = AppTypography.sectionTitle.copyWith(
      color: AppColors.textSecondary,
    );
    final explanation = error.explanation;
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: AppColors.avatarBg,
        borderRadius: BorderRadius.vertical(top: Radius.circular(_kSheetRadius)),
      ),
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          _kSheetHPad,
          _kSheetTopPad,
          _kSheetHPad,
          _kSheetBottomPad + MediaQuery.viewPaddingOf(context).bottom,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Center(child: _DragHandle()),
              const SizedBox(height: _kSheetHandleGap),
              Text(_kLblYouSaid, style: labelStyle),
              const SizedBox(height: _kCardLabelGap),
              Text(
                error.userSaid,
                style: AppTypography.body.copyWith(
                  color: AppColors.textPrimary,
                ),
              ),
              const SizedBox(height: _kSheetBlockGap),
              Text(_kLblCorrectForm, style: labelStyle),
              const SizedBox(height: _kCardLabelGap),
              Text(
                error.correction,
                style: AppTypography.headline.copyWith(color: AppColors.accent),
              ),
              if (explanation != null && explanation.isNotEmpty) ...[
                const SizedBox(height: _kSheetBlockGap),
                Text(
                  explanation,
                  style: AppTypography.body.copyWith(
                    color: AppColors.textPrimary,
                  ),
                ),
              ],
              if (error.examples.isNotEmpty) ...[
                const SizedBox(height: _kSheetBlockGap),
                Semantics(
                  header: true,
                  child: Text(
                    _kSheetEyebrowExamples,
                    style: AppTypography.label.copyWith(
                      color: AppColors.textSecondary,
                      letterSpacing: _kEyebrowLetterSpacing,
                    ),
                  ),
                ),
                for (final example in error.examples) ...[
                  const SizedBox(height: _kSheetExampleGap),
                  Text(
                    '· $example',
                    style: AppTypography.body.copyWith(
                      color: AppColors.textPrimary,
                    ),
                  ),
                ],
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _DragHandle extends StatelessWidget {
  const _DragHandle();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: _kDragHandleWidth,
      height: _kDragHandleHeight,
      decoration: BoxDecoration(
        color: AppColors.textSecondary,
        borderRadius: BorderRadius.circular(_kDragHandleHeight),
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
            _kLblPause,
            style: AppTypography.sectionTitle.copyWith(
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: _kCardLabelGap),
          Text(
            hesitationDurationLabel(hesitation.durationSec),
            semanticsLabel: 'about ${hesitation.durationSec.round()} seconds',
            style: AppTypography.debriefDuration.copyWith(
              color: AppColors.textPrimary,
            ),
          ),
          if (!hesitation.resolved) ...[
            const SizedBox(height: _kCardLabelGap),
            Text(
              _kHesFreezeNote,
              style: AppTypography.caption.copyWith(
                color: AppColors.textSecondary,
              ),
            ),
          ],
          if (hesitation.context.isNotEmpty) ...[
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
            style: AppTypography.bodyEmphasis.copyWith(color: AppColors.accent),
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

/// "Said more naturally" (B2) — a correct-but-clumsy line phrased better. The
/// suggestion uses bodyEmphasis WEIGHT, never accent (two-ink discipline: this
/// is not a correction).
class _BetterPhrasingCard extends StatelessWidget {
  final DebriefBetterPhrasing phrasing;

  const _BetterPhrasingCard({required this.phrasing});

  @override
  Widget build(BuildContext context) {
    final labelStyle = AppTypography.sectionTitle.copyWith(
      color: AppColors.textSecondary,
    );
    return _DebriefCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_kLblYouSaid, style: labelStyle),
          const SizedBox(height: _kCardLabelGap),
          Text(
            phrasing.original,
            style: AppTypography.body.copyWith(color: AppColors.textPrimary),
          ),
          const SizedBox(height: _kCardBlockGap),
          Text(_kLblMoreNatural, style: labelStyle),
          const SizedBox(height: _kCardLabelGap),
          Text(
            phrasing.suggestion,
            style: AppTypography.bodyEmphasis.copyWith(
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(height: _kCardBlockGap),
          Text(
            phrasing.reason,
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

/// Rich, actionable area card (D-a/B5/D-c): an optional "FOCUS FIRST" eyebrow on
/// #0, the title, the in-call evidence, and a COPY button for the server-authored
/// practice prompt.
class _AreaCard extends StatelessWidget {
  final DebriefArea area;

  const _AreaCard({required this.area});

  @override
  Widget build(BuildContext context) {
    return _DebriefCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (area.isFocus) ...[
            Semantics(
              header: true,
              child: Text(
                _kEyebrowFocusFirst,
                style: AppTypography.label.copyWith(
                  color: AppColors.textSecondary,
                  letterSpacing: _kEyebrowLetterSpacing,
                ),
              ),
            ),
            const SizedBox(height: _kEyebrowGap),
          ],
          Text(
            area.title,
            style: AppTypography.bodyEmphasis.copyWith(
              color: AppColors.textPrimary,
            ),
          ),
          if (area.evidence.isNotEmpty) ...[
            const SizedBox(height: _kCardLabelGap),
            Text(
              area.evidence,
              style: AppTypography.caption.copyWith(
                color: AppColors.textSecondary,
                fontStyle: FontStyle.italic,
              ),
            ),
          ],
          if (area.practicePrompt.isNotEmpty) ...[
            const SizedBox(height: _kCopyButtonTopGap),
            _CopyButton(payload: area.practicePrompt, topic: area.title),
          ],
        ],
      ),
    );
  }
}

/// Copy-a-practice-prompt button — writes the server prompt VERBATIM to the
/// clipboard and shows the informational "Copied" toast. textSecondary ink
/// (never accent: two-ink discipline). Learning action only (AC7-v2).
class _CopyButton extends StatelessWidget {
  final String payload;
  final String topic;

  const _CopyButton({required this.payload, required this.topic});

  void _onTap(BuildContext context) {
    unawaited(Clipboard.setData(ClipboardData(text: payload)));
    AppToast.show(context, message: _kCopiedConfirm, type: AppToastType.success);
  }

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Semantics(
        button: true,
        label: 'Copy practice prompt for $topic',
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => _onTap(context),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: _kCopyButtonVPad),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.content_copy,
                  size: _kCopyIconSize,
                  color: AppColors.textSecondary,
                ),
                const SizedBox(width: _kCopyIconGap),
                Text(
                  _kCopyButtonLabel,
                  style: AppTypography.label.copyWith(
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// v1 back-compat — a single card, numbered study list (numbers imply priority;
/// no accent, no copy). Rendered only when a v1 payload supplies the flat
/// areasToWorkOn list and the rich areas list is empty.
class _AreasFallbackCard extends StatelessWidget {
  final List<String> areas;

  const _AreasFallbackCard({required this.areas});

  @override
  Widget build(BuildContext context) {
    return _DebriefCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < areas.length; i++) ...[
            if (i > 0) const SizedBox(height: _kEyebrowGap),
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
