// Story 7.2 — Call Ended overlay (call-ended-screen-design.md).
//
// Non-interactive emotional transition screen shown for 3-10 s after a
// debrief-eligible call end (`user_hung_up`, `survived`, non-gifted
// `character_hung_up`, non-gifted `inappropriate_content`). Serves two
// purposes at once: an emotional pause before the feedback, and a latency
// mask over the server-side debrief generation (`GET /debriefs/{id}` is
// polled during the hold; the exit crossfade only fires when BOTH the
// minimum hold elapsed AND the debrief settled — whichever is later, hard
// capped at 10 s).
//
// The notice-path reasons (`network_lost`, `noisy_environment`,
// gifted-short-calls) never reach this screen — they keep
// `CallEndedNoticeScreen` (Decision C).
//
// The three displayed values arrive with ZERO extra network calls:
//   - % — client-computed `floor(passed/total*100)` from the checkpoint
//     snapshot captured at call end (Decision B; equals the Story 7.3
//     debrief formula — NOT the envelope's `survival_pct`).
//   - duration — `EndCallResult.durationSec` threaded through `CallEnded`
//     (Decision D).
//   - theatrical phrase — server-authored `scenario.endPhrases` delivered
//     with the scenario list payload (Decision A; content-is-server-side).

import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/router.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/call_colors.dart';
import '../../debrief/views/debrief_screen.dart';
import '../../scenarios/character_catalog.dart';
import '../../scenarios/models/scenario.dart';
import '../repositories/call_repository.dart';
import 'widgets/character_avatar.dart';

// Layout constants — identity zone mirrors `IncomingCallScreen` /
// `CallScreen.CallConnecting` (design: "same specs as Story 2.2").
const double _kNameSize = 38.0;
const double _kRoleSize = 16.0;
const double _kAvatarDiameter = 120.0;
const double _kBarHeight = 8.0;
const double _kBarHorizontalPadding = 20.0;
const double _kPhraseHorizontalPadding = 42.0;

/// Maps a `call_end` reason to the `end_phrases` variant key (AC-C6):
/// `survived` → grudging success, `user_hung_up` → the voluntary-exit
/// copy, everything else in-scope (`character_hung_up` /
/// `inappropriate_content`) → the failure copy.
@visibleForTesting
String callEndedPhraseVariant(String endReason) {
  switch (endReason) {
    case 'survived':
      return 'survived';
    case 'user_hung_up':
      return 'voluntary';
    default:
      return 'hung_up';
  }
}

/// Client-side survival percentage — `floor(passed/total*100)` clamped to
/// 0-100, with `total == 0 → 0` (design P-8: valid state, track-only bar).
/// Matches the Story 7.3 debrief formula so overlay % == debrief %.
@visibleForTesting
int computeSurvivalPct({required int passed, required int total}) {
  if (total <= 0) return 0;
  return ((passed * 100) ~/ total).clamp(0, 100);
}

/// `MM:SS` with leading zeros ("02:47", "00:00"); `H:MM:SS` only over an
/// hour ("1:02:15") — AC-C7 / design format rules.
@visibleForTesting
String formatCallDuration(int seconds) {
  final clamped = seconds < 0 ? 0 : seconds;
  final hours = clamped ~/ 3600;
  final minutes = (clamped % 3600) ~/ 60;
  final secs = clamped % 60;
  String two(int v) => v.toString().padLeft(2, '0');
  if (hours > 0) return '$hours:${two(minutes)}:${two(secs)}';
  return '${two(minutes)}:${two(secs)}';
}

/// Natural-speech duration for the announcement ("2 minutes 47 seconds"),
/// not the raw "02:47" (design — screen reader section).
@visibleForTesting
String spokenCallDuration(int seconds) {
  final clamped = seconds < 0 ? 0 : seconds;
  final hours = clamped ~/ 3600;
  final minutes = (clamped % 3600) ~/ 60;
  final secs = clamped % 60;
  final parts = <String>[
    if (hours > 0) '$hours ${hours == 1 ? 'hour' : 'hours'}',
    if (minutes > 0) '$minutes ${minutes == 1 ? 'minute' : 'minutes'}',
    '$secs ${secs == 1 ? 'second' : 'seconds'}',
  ];
  return parts.join(' ');
}

/// P-5 — combined live-region announcement including the explicit outcome
/// word so screen-reader users get the result without color. Degraded mode
/// (unknown `riveCharacter` → catalog miss → empty role, e.g. a
/// server-added scenario on an older app build): announce the bare name
/// rather than a dangling "Name, .".
@visibleForTesting
String callEndedAnnouncement({
  required String name,
  required String role,
  required int durationSec,
  required int pct,
  required bool success,
  required String? phrase,
}) {
  final outcome = success ? 'survived' : 'failed';
  final spoken = spokenCallDuration(durationSec);
  final phraseTail = phrase != null ? ' $phrase.' : '';
  final identity = role.isEmpty ? name : '$name, $role';
  return '$identity. Call Ended. Duration: $spoken. '
      'Achievement: $pct percent — $outcome.$phraseTail';
}

class CallEndedScreen extends StatefulWidget {
  /// Canonical hold/transition timings (call-ended-screen-design.md).
  static const Duration kEntryDuration = Duration(milliseconds: 1000);
  static const Duration kMinHold = Duration(seconds: 3);

  /// P-6 — extended minimum when a screen reader is active so the live
  /// region announcement completes before the exit transition.
  static const Duration kMinHoldAccessible = Duration(seconds: 5);
  static const Duration kMaxHold = Duration(seconds: 10);
  static const Duration kPollInterval = Duration(seconds: 1);
  static const Duration kExitTransition = Duration(milliseconds: 900);

  final Scenario scenario;

  /// One of the overlay-eligible reasons (`user_hung_up`, `survived`,
  /// `character_hung_up`, `inappropriate_content`).
  final String endReason;

  /// Server-computed duration (`EndCallResult.durationSec`). Null when the
  /// `/end` POST hadn't resolved (queued retry) — rendered as "00:00".
  final int? durationSec;

  /// Call-session id for `GET /debriefs/{callId}`. Null skips the fetch
  /// (the hold then runs on the minimum timer alone).
  final int? callId;

  /// Checkpoint snapshot captured at push time (Decision B).
  final int checkpointsPassed;
  final int totalCheckpoints;

  final CallRepository callRepository;

  /// Timing seams — production uses the canonical constants; tests shrink
  /// them so the hold logic runs inside a pumped test window.
  final Duration entryDuration;
  final Duration minHold;
  final Duration minHoldAccessible;
  final Duration maxHold;
  final Duration pollInterval;

  /// Test seam — replaces the debrief route pushed on exit. Receives the
  /// fetched debrief payload (null when the fetch failed terminally or
  /// the 10 s cap fired first).
  @visibleForTesting
  final Route<void> Function(Map<String, dynamic>? payload)?
  debugDebriefRouteBuilder;

  const CallEndedScreen({
    super.key,
    required this.scenario,
    required this.endReason,
    required this.durationSec,
    required this.callId,
    required this.checkpointsPassed,
    required this.totalCheckpoints,
    required this.callRepository,
    this.entryDuration = kEntryDuration,
    this.minHold = kMinHold,
    this.minHoldAccessible = kMinHoldAccessible,
    this.maxHold = kMaxHold,
    this.pollInterval = kPollInterval,
    this.debugDebriefRouteBuilder,
  });

  /// Entry route (AC-C10): 1000 ms total — the dark backdrop fades in over
  /// the call screen during the first 500 ms (`easeIn`; visually the call
  /// screen fading out into the shared `#1E1F23`), a brief dark beat at the
  /// midpoint, then the overlay content fades in over the last 500 ms
  /// (`easeOut`). On exit (the debrief route pushed on top), this screen
  /// fades out over the first 600 ms of the 900 ms window via
  /// `secondaryAnimation` — the design's 300 ms crossfade overlap.
  static Route<void> route({
    required Scenario scenario,
    required String endReason,
    required int? durationSec,
    required int? callId,
    required int checkpointsPassed,
    required int totalCheckpoints,
    required CallRepository callRepository,
  }) {
    return PageRouteBuilder<void>(
      transitionDuration: kEntryDuration,
      pageBuilder: (_, _, _) => CallEndedScreen(
        scenario: scenario,
        endReason: endReason,
        durationSec: durationSec,
        callId: callId,
        checkpointsPassed: checkpointsPassed,
        totalCheckpoints: totalCheckpoints,
        callRepository: callRepository,
      ),
      transitionsBuilder: (_, animation, secondaryAnimation, child) {
        final backdrop = CurvedAnimation(
          parent: animation,
          curve: const Interval(0.0, 0.5, curve: Curves.easeIn),
        );
        final content = CurvedAnimation(
          parent: animation,
          curve: const Interval(0.5, 1.0, curve: Curves.easeOut),
        );
        final exitFade = Tween<double>(begin: 1.0, end: 0.0).animate(
          CurvedAnimation(
            parent: secondaryAnimation,
            curve: const Interval(0.0, 2 / 3, curve: Curves.easeIn),
          ),
        );
        return FadeTransition(
          opacity: exitFade,
          child: Stack(
            fit: StackFit.expand,
            children: [
              FadeTransition(
                opacity: backdrop,
                child: const ColoredBox(color: AppColors.background),
              ),
              FadeTransition(opacity: content, child: child),
            ],
          ),
        );
      },
    );
  }

  @override
  State<CallEndedScreen> createState() => _CallEndedScreenState();
}

class _CallEndedScreenState extends State<CallEndedScreen> {
  Timer? _minHoldTimer;
  Timer? _capTimer;
  Timer? _pollTimer;
  bool _timersStarted = false;
  bool _minHoldElapsed = false;

  /// True once the debrief fetch settled — payload received OR terminal
  /// failure (anything but `DEBRIEF_NOT_READY`). Either way the hold can
  /// end; the overlay never shows error chrome (UX-DR6).
  bool _debriefSettled = false;
  Map<String, dynamic>? _debriefPayload;
  bool _exited = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_timersStarted) return;
    _timersStarted = true;
    // Hold timing starts when the screen is fully visible (entry fade
    // complete), per the design's entry sequence — hence the entryDuration
    // offset on both deadlines.
    final accessible = MediaQuery.of(context).accessibleNavigation;
    final minHold = accessible ? widget.minHoldAccessible : widget.minHold;
    _minHoldTimer = Timer(widget.entryDuration + minHold, () {
      _minHoldElapsed = true;
      _maybeExit();
    });
    // Hard cap — transition even if the debrief never settled (the debrief
    // screen owns the >10 s loading fallback, design BS-7).
    _capTimer = Timer(widget.entryDuration + widget.maxHold, _exit);
    unawaited(_attemptFetch());
  }

  Future<void> _attemptFetch() async {
    final callId = widget.callId;
    if (callId == null) {
      // Degraded state (no id to fetch with) — nothing will ever resolve;
      // exit on the minimum hold alone.
      _debriefSettled = true;
      return;
    }
    try {
      final payload = await widget.callRepository.fetchDebrief(callId: callId);
      if (!mounted || _exited) return;
      _debriefPayload = payload;
      _debriefSettled = true;
      // Broad catch is deliberate: the overlay must never surface an error
      // (UX-DR6) and a post-call fetch failure must never crash the exit
      // flow — anything that isn't "still generating" is terminal and the
      // debrief screen simply receives no payload. `_maybeExit` stays
      // OUTSIDE the try so a navigation failure is never swallowed here.
      // ignore: avoid_catches_without_on_clauses
    } catch (e) {
      if (!mounted || _exited) return;
      if (e is ApiException && e.code == 'DEBRIEF_NOT_READY') {
        // Still generating — poll until ready or the 10 s cap fires.
        _pollTimer = Timer(widget.pollInterval, () {
          unawaited(_attemptFetch());
        });
        return;
      }
      _debriefSettled = true;
    }
    _maybeExit();
  }

  /// AC-C9 — exit on the LAST of (min hold elapsed, debrief settled).
  void _maybeExit() {
    if (_minHoldElapsed && _debriefSettled) _exit();
  }

  void _exit() {
    if (_exited || !mounted) return;
    _exited = true;
    _cancelTimers();
    final route =
        widget.debugDebriefRouteBuilder?.call(_debriefPayload) ??
        _debriefRoute();
    // Forward-only (UX-DR10): back stack ends [scenario-list, debrief].
    Navigator.of(context).pushReplacement(route);
  }

  /// AC-C11 / Decision E — the real debrief route (Story 7.3). The
  /// payload + callId + repository ride the constructor; the payload ALSO
  /// stays on `RouteSettings.arguments` (the Decision-F handoff contract
  /// this story's tests assert). Fade-in over 300-900 ms of the 900 ms
  /// window — overlapping this screen's 0-600 ms fade-out for the
  /// design's 300 ms crossfade.
  Route<void> _debriefRoute() {
    return PageRouteBuilder<void>(
      settings: RouteSettings(
        name: AppRoutes.debrief,
        arguments: _debriefPayload,
      ),
      transitionDuration: CallEndedScreen.kExitTransition,
      pageBuilder: (_, _, _) => DebriefScreen(
        payload: _debriefPayload,
        callId: widget.callId,
        callRepository: widget.callRepository,
      ),
      transitionsBuilder: (_, animation, _, child) => FadeTransition(
        opacity: CurvedAnimation(
          parent: animation,
          curve: const Interval(1 / 3, 1.0, curve: Curves.easeOut),
        ),
        child: child,
      ),
    );
  }

  void _cancelTimers() {
    _minHoldTimer?.cancel();
    _minHoldTimer = null;
    _capTimer?.cancel();
    _capTimer = null;
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  @override
  void dispose() {
    _cancelTimers();
    super.dispose();
  }

  /// Phrase for the reason's variant; null/empty → hide the element
  /// entirely (design P-7 — never render "null" or a placeholder).
  String? get _phrase {
    final raw =
        widget.scenario.endPhrases?[callEndedPhraseVariant(widget.endReason)];
    if (raw == null) return null;
    final trimmed = raw.trim();
    return trimmed.isEmpty ? null : trimmed;
  }

  @override
  Widget build(BuildContext context) {
    final identity = kCharacterCatalog[widget.scenario.riveCharacter];
    final name = identity?.name ?? widget.scenario.title;
    final role = identity?.role ?? '';
    final pct = computeSurvivalPct(
      passed: widget.checkpointsPassed,
      total: widget.totalCheckpoints,
    );
    final success = widget.endReason == 'survived';
    final variantColor = success ? AppColors.accent : AppColors.destructive;
    final phrase = _phrase;

    return PopScope(
      // P-4 — the call is over; there is no screen to go back to. The only
      // exit is the automatic forward transition to the debrief.
      canPop: false,
      child: Scaffold(
        backgroundColor: AppColors.background,
        body: Semantics(
          liveRegion: true,
          container: true,
          label: callEndedAnnouncement(
            name: name,
            role: role,
            durationSec: widget.durationSec ?? 0,
            pct: pct,
            success: success,
            phrase: phrase,
          ),
          child: SafeArea(
            // Story 5.4 overflow pattern (mirrors `_buildDialSurface` on
            // the sibling call screen): the Spacer-driven Column fills tall
            // viewports and gracefully scrolls on small phones at large
            // text scales instead of overflowing.
            child: LayoutBuilder(
              builder: (context, constraints) {
                return SingleChildScrollView(
                  child: ConstrainedBox(
                    constraints: BoxConstraints(
                      minHeight: constraints.maxHeight,
                    ),
                    child: IntrinsicHeight(
                      child: Column(
                        children: [
                          const SizedBox(height: 40),
                          // Identity zone — same specs as the incoming-call
                          // screen.
                          Text(
                            name,
                            textAlign: TextAlign.center,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontFamily: 'Inter',
                              fontSize: _kNameSize,
                              fontWeight: FontWeight.w400,
                              color: AppColors.textPrimary,
                              height: 46 / 38,
                            ),
                          ),
                          // Degraded mode (catalog miss): skip the empty
                          // role line instead of rendering a blank 19px row.
                          if (role.isNotEmpty)
                            Text(
                              role,
                              textAlign: TextAlign.center,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontFamily: 'Inter',
                                fontSize: _kRoleSize,
                                fontWeight: FontWeight.w400,
                                color: CallColors.secondary,
                                height: 19 / 16,
                              ),
                            ),
                          const SizedBox(height: 12),
                          Text(
                            formatCallDuration(widget.durationSec ?? 0),
                            textAlign: TextAlign.center,
                            maxLines: 1,
                            style: AppTypography.callEndedDuration.copyWith(
                              color: AppColors.textPrimary,
                            ),
                          ),
                          // Status zone — avatar + understated "Call Ended".
                          const Spacer(),
                          CharacterAvatar(
                            character: widget.scenario.riveCharacter,
                            size: _kAvatarDiameter,
                          ),
                          const SizedBox(height: 16),
                          Text(
                            'Call Ended',
                            textAlign: TextAlign.center,
                            style: AppTypography.callEndedLabel.copyWith(
                              color: AppColors.textPrimary,
                            ),
                          ),
                          const Spacer(),
                          // Result zone — variant-colored % + bar + phrase.
                          Text(
                            '$pct%',
                            textAlign: TextAlign.center,
                            style: AppTypography.callEndedPercent.copyWith(
                              color: variantColor,
                            ),
                          ),
                          const SizedBox(height: 10),
                          Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: _kBarHorizontalPadding,
                            ),
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(
                                _kBarHeight / 2,
                              ),
                              child: LinearProgressIndicator(
                                value: pct / 100,
                                minHeight: _kBarHeight,
                                // Track #414143 vs the avatar's #38383A
                                // circle — LOCKED 2026-06-09 (story Dev
                                // Notes "Avatar vs track color"); no new
                                // token, no inline hex.
                                backgroundColor: AppColors.avatarBg,
                                color: variantColor,
                              ),
                            ),
                          ),
                          if (phrase != null)
                            Padding(
                              padding: const EdgeInsets.only(
                                left: _kPhraseHorizontalPadding,
                                right: _kPhraseHorizontalPadding,
                                top: 16,
                              ),
                              child: Text(
                                phrase,
                                textAlign: TextAlign.center,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: AppTypography.callEndedPhrase.copyWith(
                                  color: variantColor,
                                  height: 1.4,
                                ),
                              ),
                            ),
                          const SizedBox(height: 50),
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}
