import 'dart:async';

import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import 'checkpoint_snapshot.dart';

/// Story 6.10 UI refonte (2026-05-28) — Flutter-native checkpoint HUD,
/// overlaid on top of the Rive character. **Replaces** the old Rive
/// stepper-circles (`CheckpointStepperCanvas`) + the separate Flutter
/// hint bubble (`CheckpointHintBubble`). Per Walid (2026-05-28): the
/// Rive `.riv` no longer renders checkpoints — all of it is Flutter now.
///
/// Design (Walid's spec, 2026-05-28):
///   - A box pinned to the ABSOLUTE top of the screen (behind the status
///     bar — no SafeArea). Background = the dark app background
///     ([AppColors.background] #1E1F23): SOLID for the top 50% of the box
///     height, then a 100%→0% fade over the bottom 50% (gradient stops
///     0 / 0.5 / 1.0). The box is sized to exactly 2× its content (via an
///     invisible content mirror), so the text always sits in the solid
///     top band and the fade trails into the scene below.
///   - Inside, a single row: a **check** to the left + the CURRENT step's
///     text. Only ONE step is shown at a time (the next not-yet-done one).
///   - When that step is completed, the check animates from an outline to
///     a green ([AppColors.statusCompleted]) filled check, then the card
///     slides up + fades out and the NEXT step slides in.
///   - Out-of-order completion (a later goal met first): the active step
///     slides out, the just-completed step is shown briefly with its green
///     check, then it slides out and the active (still-pending) step
///     slides back in. The serialized animation chain shows every flip in
///     order even when several land back-to-back.
///
/// Data: driven entirely by [CheckpointSnapshot] (full `hints` list + met
/// set + `justFlippedIndex`), so every transition is computed locally with
/// no extra server round-trip.
///
/// Renders [SizedBox.shrink] when there is nothing to show (null snapshot,
/// no hints yet, or all objectives complete after the final animation).
/// Wrapped in `IgnorePointer` by the call screen so taps reach the
/// character canvas underneath.
class CheckpointStepHud extends StatefulWidget {
  final CheckpointSnapshot? snapshot;

  const CheckpointStepHud({super.key, required this.snapshot});

  @override
  State<CheckpointStepHud> createState() => _CheckpointStepHudState();
}

class _CheckpointStepHudState extends State<CheckpointStepHud> {
  static const Duration _switchDuration = Duration(milliseconds: 320);
  static const Duration _holdCompleted = Duration(milliseconds: 750);

  /// The step text currently rendered.
  String _text = '';

  /// Whether the rendered step shows a green (completed) check.
  bool _checked = false;

  /// Bumped on every visual frame so [AnimatedSwitcher] keys distinct
  /// instances and animates the slide between them.
  int _frameId = 0;

  /// Serializes animation work so back-to-back snapshot updates (e.g. two
  /// goals flipping in one turn) each play in order rather than clobbering.
  Future<void> _chain = Future<void>.value();

  /// Author-order indices whose completion animation has already played.
  /// Driving off the SET (not a met-count delta) is what makes
  /// two-goals-in-one-turn animate correctly: the server emits the same
  /// full `goals_met_indices` on each per-flip envelope, so we diff the
  /// incoming met set against this and animate every index we haven't yet.
  Set<int> _animatedMet = <int>{};

  /// The single in-flight hold/transition timer. Cancelled in [dispose] so
  /// the widget never leaves a pending timer behind (a teardown mid-
  /// animation would otherwise trip Flutter's `!timersPending` assert).
  Timer? _pendingTimer;

  @override
  void initState() {
    super.initState();
    _ingest(widget.snapshot, isFirst: true);
  }

  @override
  void dispose() {
    _pendingTimer?.cancel();
    _pendingTimer = null;
    super.dispose();
  }

  /// A cancellable delay. Replaces `Future.delayed` so the animation chain
  /// holds no timer the test framework (or a real route pop) can't reap.
  /// After [dispose] the returned future simply never completes — the
  /// chain stalls harmlessly because every continuation guards on `mounted`.
  Future<void> _wait(Duration d) {
    _pendingTimer?.cancel();
    final completer = Completer<void>();
    _pendingTimer = Timer(d, () {
      if (!completer.isCompleted) completer.complete();
    });
    return completer.future;
  }

  @override
  void didUpdateWidget(CheckpointStepHud oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.snapshot != widget.snapshot) {
      _ingest(widget.snapshot, isFirst: false);
    }
  }

  void _ingest(CheckpointSnapshot? snap, {required bool isFirst}) {
    if (snap == null || snap.hints.isEmpty) {
      _animatedMet = <int>{};
      _enqueue(() => _showFrame('', checked: false));
      return;
    }

    final activeText = snap.allMet ? '' : snap.activeHint; // '' when all met

    if (isFirst) {
      // First snapshot (mount / reconnect mid-call): never replay
      // completions for goals already met — just settle on the active step.
      _animatedMet = snap.metIndices.toSet();
      setState(() {
        _text = activeText;
        _checked = false;
      });
      return;
    }

    // Every met index we haven't animated yet is a NEW completion. Because
    // each per-flip envelope carries the SAME full met set, whichever
    // envelope we process first already lists all goals that flipped this
    // turn — so two-goals-in-one-turn animate one after the other (in
    // author order) instead of the second being swallowed.
    final newlyMet =
        snap.metIndices.where((i) => !_animatedMet.contains(i)).toList()..sort();
    if (newlyMet.isEmpty) {
      // Reconcile / no new flip → settle on the active step.
      _enqueue(() => _showFrame(activeText, checked: false));
      return;
    }
    _animatedMet.addAll(newlyMet);
    final completedTexts = [for (final i in newlyMet) snap.hintAt(i)];
    _enqueue(() => _playFlips(completedTexts, activeText));
  }

  void _enqueue(Future<void> Function() task) {
    _chain = _chain.then((_) async {
      if (!mounted) return;
      await task();
    });
  }

  /// Animate each newly-completed step in turn, then settle on the active
  /// (next-pending) step. Walid's spec (2026-05-28): every completed step
  /// SLIDES in already-checked, holds, then slides out as the next one
  /// slides in — a uniform rhythm. Even the step currently shown (the
  /// active one that just completed) slides (it refreshes in with its green
  /// check) rather than checking in place, so the motion is consistent:
  ///   slide-in greet✓ → slide-out / slide-in drink✓ → slide-out /
  ///   slide-in the next pending step.
  /// When several goals complete in one turn they play one after another,
  /// in author order.
  Future<void> _playFlips(List<String> completedTexts, String activeText) async {
    for (final text in completedTexts) {
      if (!mounted) return;
      if (text.isEmpty) continue;
      await _showFrame(text, checked: true);
      if (!mounted) return;
      await _wait(_holdCompleted);
      if (!mounted) return;
    }
    await _showFrame(activeText, checked: false);
  }

  /// Swap the rendered frame (new key → AnimatedSwitcher slides), then wait
  /// out the transition so the chain stays in lock-step with the visuals.
  Future<void> _showFrame(String text, {required bool checked}) async {
    if (!mounted) return;
    if (text == _text && checked == _checked) return;
    setState(() {
      _text = text;
      _checked = checked;
      _frameId++;
    });
    await _wait(_switchDuration);
  }

  @override
  Widget build(BuildContext context) {
    // Nothing to show (null/empty snapshot, or all objectives complete
    // after the final animation) → hide the whole HUD entirely.
    if (_text.isEmpty) return const SizedBox.shrink();

    // The box is pinned to the VERY top of the screen (behind the status
    // bar — no SafeArea); the content's own top padding clears the status
    // bar so the text still sits below it but inside the solid band.
    final topInset = MediaQuery.of(context).padding.top;
    final contentPadding = EdgeInsets.only(
      top: topInset + 14,
      left: 20,
      right: 20,
      bottom: 14,
    );

    // The visible content (animated between steps).
    final visibleContent = Padding(
      padding: contentPadding,
      child: AnimatedSwitcher(
        duration: _switchDuration,
        switchInCurve: Curves.easeOut,
        switchOutCurve: Curves.easeIn,
        transitionBuilder: (child, animation) {
          // Slide up + fade between steps.
          final slide = Tween<Offset>(
            begin: const Offset(0, 0.35),
            end: Offset.zero,
          ).animate(animation);
          return FadeTransition(
            opacity: animation,
            child: SlideTransition(position: slide, child: child),
          );
        },
        child: _StepRow(
          key: ValueKey<int>(_frameId),
          text: _text,
          checked: _checked,
        ),
      ),
    );

    // An INVISIBLE mirror of the same content directly below it. Because
    // it has the identical structure/text/padding, its height always
    // equals the visible content's height — so the Column is exactly 2×
    // the content tall. With the gradient solid over the top 50% and
    // fading over the bottom 50%, the text is GUARANTEED to live in the
    // 100%-opaque band, with the fade trailing into the scene below. No
    // measurement, no flash — it adapts to any line count automatically.
    final fadeTail = Opacity(
      opacity: 0,
      child: Padding(
        padding: contentPadding,
        child: _StepRow(text: _text, checked: _checked),
      ),
    );

    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        // Dark app-background (#1E1F23) — SOLID for the top half, then a
        // 100%→0% fade over the bottom half (stops 0 / 0.5 / 1.0). Tokens
        // only — `.withValues` keeps theme_tokens_test green.
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            AppColors.background,
            AppColors.background,
            AppColors.background.withValues(alpha: 0.0),
          ],
          stops: const [0.0, 0.5, 1.0],
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [visibleContent, fadeTail],
      ),
    );
  }
}

/// One rendered step: the inline check + the step text.
class _StepRow extends StatelessWidget {
  final String text;
  final bool checked;

  const _StepRow({super.key, required this.text, required this.checked});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.max,
      children: [
        _CheckIndicator(checked: checked),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            text,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontFamily: 'Inter',
              fontSize: 18,
              fontWeight: FontWeight.w600,
              height: 1.25,
              // Light text on the solid-dark top band → 13.5:1 contrast,
              // no shadow needed.
              color: AppColors.textPrimary,
            ),
          ),
        ),
      ],
    );
  }
}

/// The check: an outline circle while pending, a green filled check once
/// the step is completed. The cross-fade + scale pop signals "done".
class _CheckIndicator extends StatelessWidget {
  final bool checked;

  const _CheckIndicator({required this.checked});

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 260),
      transitionBuilder: (child, animation) =>
          ScaleTransition(scale: animation, child: child),
      child: checked
          ? Container(
              key: const ValueKey<String>('check-done'),
              width: 26,
              height: 26,
              decoration: const BoxDecoration(
                color: AppColors.statusCompleted,
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.check,
                size: 17,
                color: AppColors.textPrimary,
              ),
            )
          : Container(
              key: const ValueKey<String>('check-pending'),
              width: 26,
              height: 26,
              decoration: BoxDecoration(
                color: Colors.transparent,
                shape: BoxShape.circle,
                border: Border.all(color: AppColors.textPrimary, width: 2),
              ),
            ),
    );
  }
}
