import 'dart:async';
import 'dart:convert';
import 'dart:developer' as dev;
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:livekit_client/livekit_client.dart';

import '../../../core/services/connectivity_service.dart';
import '../../../core/services/end_call_retry_service.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/call_colors.dart';
import '../../scenarios/character_catalog.dart';
import '../../scenarios/models/character_identity.dart';
import '../../scenarios/models/scenario.dart';
import '../../../core/api/api_client.dart';
import '../bloc/call_bloc.dart';
import '../bloc/call_event.dart';
import '../bloc/call_state.dart';
import '../models/call_session.dart';
import '../repositories/call_repository.dart';
import '../services/checkpoint_advanced_payload.dart';
import '../services/data_channel_handler.dart';
import '../services/env_warning_payload.dart';
import '../services/inbound_audio_stats_logger.dart';
import '../services/viseme_scheduler.dart';
import 'call_ended_notice_screen.dart';
import 'call_ended_screen.dart';
import 'scenario_backgrounds.dart';
import 'widgets/animated_calling_text.dart';
import 'widgets/character_avatar.dart';
import 'widgets/checkpoint_snapshot.dart';
import 'widgets/checkpoint_step_hud.dart';
import 'widgets/noisy_environment_banner.dart';
import 'widgets/rive_character_canvas.dart';

/// Story 6.3 — typed builder for `DataChannelHandler`. Production wires
/// `DataChannelHandler.new`; tests inject a counting / mock-returning
/// alternative through `CallScreen.debugHandlerBuilder` to assert the
/// "construct exactly once" + "dispose on tear-down" lifecycle contract.
///
/// Story 6.4 widened the signature with `onHangUpWarning`, `onCallEnd`,
/// and `onBotSpeakingEnded` so the handler can route server-driven
/// envelopes back to the screen / bloc.
///
/// Story 6.7 widened it again with `onCheckpointAdvanced` so the
/// `checkpoint_advanced` envelope (emitted on call connect AND on every
/// successful checkpoint advance) lands on the screen's
/// `_checkpointNotifier`.
typedef DataChannelHandlerBuilder =
    DataChannelHandler Function({
      required Room room,
      required void Function(String emotion, double intensity) onEmotion,
      required void Function(int secondsRemaining) onHangUpWarning,
      required void Function(String reason, Map<String, dynamic> data)
      onCallEnd,
      required void Function() onBotSpeakingEnded,
      required void Function(CheckpointAdvancedPayload payload)
      onCheckpointAdvanced,
      required void Function(EnvWarningPayload payload) onEnvWarning,
    });

// Layout constants — mirrored from `IncomingCallScreen` so the outgoing
// dial state matches the onboarding incoming-call screen visually (per
// Walid feedback, Story 6.2 redesign of `CallConnecting`).
const double _kCallNameSize = 38.0;
const double _kCallRoleSize = 16.0;
const double _kCallStatusSize = 24.0;
const double _kAvatarDiameter = 166.0;
const double _kScreenHorizontalPadding = 30.0;
const double _kScreenTopPadding = 60.0;
const double _kScreenBottomPadding = 70.0;

// Story 6.11 — vertical offset (below the SafeArea top inset) at which the
// noisy-environment banner sits, so it clears the checkpoint HUD's solid
// top band (status bar + a single line of step text + padding ≈ 50 px).
const double _kNoisyBannerTopOffset = 64.0;

/// Full-screen call surface for Story 6.1 + Story 6.2.
///
/// Detached from `go_router` (pushed via `Navigator.of(context, rootNavigator:
/// true)`) per ADR 003 §Tier 1. Story 6.1 owns the call lifecycle plumbing
/// (Room → CallBloc → root-Navigator pop). Story 6.2 layers the in-call
/// render on top of `CallConnected`: scenario background → gaussian blur →
/// full-body Rive canvas with the in-canvas hang-up button. Visemes and
/// emotion data-channel wiring land in Story 6.3.
///
/// `CallConnecting` clones the `IncomingCallScreen` layout (name + role +
/// circular avatar + "Calling..." dots + single hang-up button) so the
/// onboarding incoming-call surface and the outgoing dial surface share
/// the same visual language.
/// Story 6.13 follow-up (2026-05-28) — maps a LiveKit `ConnectionQuality`
/// to "should we warn the user their link is degraded?". `poor` and `lost`
/// are the degraded states (NetEq jitter adaptation → the stuttering /
/// skipping audio diagnosed as pure 5G network jitter, see deferred-work
/// item 1). `unknown` (pre-measurement, at connect) is NOT treated as weak
/// to avoid a spurious banner on every call start. Pure + top-level so the
/// decision is unit-testable without pumping the call screen.
bool isWeakConnectionQuality(ConnectionQuality quality) =>
    quality == ConnectionQuality.poor || quality == ConnectionQuality.lost;

class CallScreen extends StatefulWidget {
  final Scenario scenario;
  final CallSession callSession;

  /// Optional injection seam for tests. Production callers pass nothing —
  /// `CallScreen` constructs `Room()` once in `initState` and forwards it to
  /// `CallBloc`. Tests pass a `MockRoom`.
  final Room? room;

  /// Test seam (Story 6.2 AC9). When non-null, locks `_canvasInFallback`
  /// to this value and ignores the `RiveCharacterCanvas.onFallback`
  /// callback. Production callers pass nothing — the real fallback signal
  /// from the Rive canvas drives the UI. Tests use `false` to assert the
  /// "Rive working" branch (no Flutter hang-up button) and `true` to
  /// assert the fallback branch (Flutter hang-up button rendered).
  @visibleForTesting
  final bool? debugCanvasFallback;

  /// Story 6.3 test seam. Production passes nothing; the screen falls back
  /// to `DataChannelHandler.new`. Tests pass a builder that records
  /// construction count and returns a mock handler — used to assert the
  /// "construct once on first CallConnected" + "dispose on unmount"
  /// lifecycle contract.
  @visibleForTesting
  final DataChannelHandlerBuilder? debugHandlerBuilder;

  const CallScreen({
    super.key,
    required this.scenario,
    required this.callSession,
    this.room,
    this.debugCanvasFallback,
    this.debugHandlerBuilder,
    this.debugPlaybackDrainBuffer,
    this.debugEndCallResultTimeout,
    this.callRepository,
    this.connectivityService,
    this.endCallRetryService,
  });

  /// Story 6.4 test seam. When non-null, overrides the bloc's
  /// `playbackDrainBuffer` (default 500 ms in production). Tests pass
  /// `Duration.zero` so `PlaybackDrained` → disconnect happens
  /// synchronously inside the test's 50 ms wait window.
  @visibleForTesting
  final Duration? debugPlaybackDrainBuffer;

  /// Story 6.5 Déviation #27 test seam. When non-null, overrides the
  /// bloc's `endCallResultTimeout` (default 1 s in production). Tests
  /// that don't mock `CallRepository` get an unresolvable POST future
  /// in `_pendingEndCalls`; the bloc would otherwise hang up to 1 s
  /// waiting for the response, blowing past the typical 50 ms pump
  /// window. Setting `Duration.zero` makes `_awaitEndCallResult`
  /// return immediately with whatever's already cached (typically
  /// null in those tests).
  @visibleForTesting
  final Duration? debugEndCallResultTimeout;

  /// Story 6.5 — optional injection seam for the repository that drives
  /// `POST /calls/{id}/end`. Production callers pass nothing —
  /// `CallScreen` builds `CallRepository(ApiClient())` once in `initState`
  /// and forwards it to `CallBloc`. Tests pass a `MockCallRepository`.
  /// Mirrors how `scenario_list_screen.dart` exposes the same seam for
  /// `initiateCall` (Story 6.1).
  @visibleForTesting
  final CallRepository? callRepository;

  /// Story 6.5 review (post-deploy E2E) — optional injection seam for the
  /// connectivity monitor that fires `RoomDisconnected` on mid-call
  /// airplane-mode toggle. Production callers pass nothing — `CallScreen`
  /// builds `ConnectivityService()` (which wraps `Connectivity()`) once
  /// in `initState`. Tests pass a `MockConnectivityService` whose
  /// `onConnectivityLost` stream they control.
  @visibleForTesting
  final ConnectivityService? connectivityService;

  /// Story 6.5 Option B (post-deploy fix) — optional injection seam for
  /// the persistent retry queue that holds `/end` POSTs which failed
  /// while offline. Production callers pass the app-level singleton
  /// from `bootstrap()` (the same instance also drains the queue on
  /// connectivity-regain via its own listener). Tests pass a
  /// `MockEndCallRetryService` to assert the bloc queues failed
  /// requests rather than dropping them.
  @visibleForTesting
  final EndCallRetryService? endCallRetryService;

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  late final Room _room;
  late final CallRepository _callRepository;
  late final ConnectivityService _connectivityService;
  EndCallRetryService? _endCallRetryService;

  /// Set true once `BlocProvider<CallBloc>` runs `create` — the bloc takes
  /// ownership of the Room from that point and `close()` will disconnect.
  /// While false (e.g. an exception aborted the route before the first
  /// `build()`), `dispose` is the only place the Room can be cleaned up.
  bool _blocCreated = false;

  /// Mirrors `RiveCharacterCanvas`'s fallback signal so we know whether to
  /// overlay the Flutter `_buildHangUpButton` (AC7). True only when Rive
  /// native is unavailable — production happy path keeps this false.
  bool _canvasInFallback = false;

  bool _backgroundPrecached = false;

  /// Idempotency guard — `BlocConsumer.listener` may fire on the same
  /// `CallEnded` more than once (e.g. const-equality dedup gotcha #4 + a
  /// transient rebuild). Track that the post-frame `maybePop` is already
  /// scheduled so we never queue two pops.
  bool _popScheduled = false;

  /// Story 6.3 — `GlobalKey` seam between `CallScreen` and the Rive canvas.
  /// `_dataChannelHandler` invokes `setEmotion` / `setVisemeId` through
  /// `_canvasKey.currentState?` so a missing canvas (rebuild between
  /// envelopes, fallback mode where the State exists but the cached
  /// enums are null) becomes a silent no-op instead of an exception.
  final GlobalKey<RiveCharacterCanvasState> _canvasKey =
      GlobalKey<RiveCharacterCanvasState>();

  /// Story 6.3 — owned by the screen, constructed on first `CallConnected`,
  /// disposed in `dispose()` BEFORE `super.dispose()`. The bloc owns the
  /// `Room` lifecycle; this handler is a non-lifecycle subscriber.
  DataChannelHandler? _dataChannelHandler;

  /// Story 6.3b — sister object to `_dataChannelHandler`. Subscribes to
  /// the native `AudioClockChannel` EventChannel and forwards each
  /// platform-generated viseme onto the Rive canvas. Same lifecycle as
  /// the handler.
  VisemeScheduler? _visemeScheduler;

  /// Story 6.14 AC1 — dev-only diagnostic. Logs the inbound (remote)
  /// audio receiver stats (jitter, jitterBufferDelay, concealedSamples)
  /// so the receiver-side time-stretch ("voix rallongée") can be measured
  /// before/after the jitter-buffer fix. Same non-lifecycle subscriber
  /// contract as `_dataChannelHandler`; inert when `kLogInboundAudioStats`
  /// is false.
  InboundAudioStatsLogger? _inboundAudioStatsLogger;

  /// Story 6.4 — gates the upstream `playback_idle` publish + the
  /// bloc's `PlaybackDrained` dispatch. The naive
  /// `VisemeScheduler.onSilenceConfirmed` fires on EVERY 600 ms
  /// silence window, including intra-sentence Cartesia pauses in a
  /// multi-sentence bot turn. Without this gate, those pauses would
  /// be mis-classified as "bot turn over" and the silence ladder
  /// would start mid-greeting.
  ///
  /// Set to true on receiving `bot_speaking_ended` (server signal
  /// that the current bot turn's outbound audio buffer drained).
  /// Cleared by the next `onSilenceConfirmed` (which IS the post-
  /// turn silence — user's speaker actually drained).
  ///
  /// The bloc's `PlaybackDrained` safety timer (10 s after
  /// `RemoteCallEnded`) covers the case where this gate never arms
  /// during the hang-up sequence (e.g. the envelope is lost).
  bool _awaitingPlaybackIdle = false;

  /// Story 6.7 — UI-only state for the checkpoint stepper HUD. Null
  /// until the FIRST `checkpoint_advanced` envelope arrives (server
  /// emits one with index=0 from `on_first_participant_joined` AFTER
  /// the greeting `TTSSpeakFrame`). Non-null thereafter for the rest
  /// of the call.
  ///
  /// Lives on the State (NOT the bloc) because:
  ///   - bloc state is the *call lifecycle* (connecting / connected /
  ///     error / ended) — checkpoint progression is *mid-call UI*
  ///     and would force every BlocConsumer.builder to rebuild on
  ///     every advance (including the expensive Rive character canvas).
  ///   - Precedent: `_canvasInFallback` (Story 6.2), `_awaitingPlaybackIdle`
  ///     (Story 6.4) — both UI-only flags on the State.
  ///   - Scoped ValueNotifier means only the stepper subtree
  ///     ValueListenableBuilder rebuilds (Phase 2).
  final ValueNotifier<CheckpointSnapshot?> _checkpointNotifier =
      ValueNotifier<CheckpointSnapshot?>(null);

  /// Story 6.7 — exposed under `@visibleForTesting` so the Phase 1
  /// integration tests can drill in and assert "envelope arrives →
  /// notifier value updated correctly" + "call_end reconciles" without
  /// needing to pump the full Rive subtree (which AC8 dictates is
  /// covered by widget tests on the stepper canvas itself).
  @visibleForTesting
  ValueNotifier<CheckpointSnapshot?> get checkpointNotifierForTest =>
      _checkpointNotifier;

  /// Story 6.11 — UI-only state for the noisy-environment banner. Null
  /// until the (at-most-one-per-call) `env_warning` envelope arrives;
  /// non-null thereafter through the character's exit line, until the
  /// route transition to `CallEndedNoticeScreen` replaces the screen.
  /// Same UI-only-on-the-State pattern as `_checkpointNotifier` (Story
  /// 6.7) and `_weakConnectionNotifier` (Story 6.13) — only the banner
  /// subtree rebuilds, never the Rive canvas.
  final ValueNotifier<EnvWarningPayload?> _envWarningNotifier =
      ValueNotifier<EnvWarningPayload?>(null);

  @visibleForTesting
  ValueNotifier<EnvWarningPayload?> get envWarningNotifierForTest =>
      _envWarningNotifier;

  /// Story 6.13 follow-up — UI-only flag, true while the LOCAL
  /// participant's LiveKit `ConnectionQuality` is poor/lost. Drives a
  /// "weak connection" banner so the user understands the audio stutter
  /// is their network (a marginal-5G NetEq artifact, see deferred-work
  /// item 1), not an app bug — we can't fix the link, but we can set
  /// expectations + deflect blame. UI-only on the State like
  /// `_checkpointNotifier`; only the banner subtree rebuilds.
  final ValueNotifier<bool> _weakConnectionNotifier = ValueNotifier<bool>(
    false,
  );

  /// Cancels the LiveKit connection-quality listener on dispose.
  CancelListenFunc? _qualityCancel;

  /// On recovery (quality back to good/excellent) we hold the banner for
  /// this long before hiding, so a brief quality bounce doesn't flicker
  /// the banner off then back on.
  static const Duration _kWeakConnectionLinger = Duration(seconds: 4);
  Timer? _weakConnectionHideTimer;

  /// User-facing banner copy. Attributes the stutter to the connection
  /// (deflects blame from the app) without being preachy. Adjust /
  /// localise here.
  static const String _kWeakConnectionMessage =
      'Weak connection · audio may stutter';

  @visibleForTesting
  ValueNotifier<bool> get weakConnectionNotifierForTest =>
      _weakConnectionNotifier;

  @override
  void initState() {
    super.initState();
    _room = widget.room ?? Room();
    // Story 6.13 follow-up — surface a "weak connection" banner when the
    // LOCAL participant's LiveKit ConnectionQuality degrades. LiveKit
    // derives quality from RTT + packet loss + jitter (the same jitter
    // that makes Tina's voice stutter on a marginal 5G link). Only the
    // LOCAL participant's quality reflects the USER's connection — the
    // agent runs from the datacenter and is always good, so its quality
    // is irrelevant here. Events arrive after connect; subscribing now is
    // safe (no events fire pre-connect). Listener cancelled in dispose().
    _qualityCancel = _room.events.on<ParticipantConnectionQualityUpdatedEvent>((
      event,
    ) {
      if (event.participant is! LocalParticipant) return;
      if (!mounted) return;
      if (isWeakConnectionQuality(event.connectionQuality)) {
        _weakConnectionHideTimer?.cancel();
        _weakConnectionHideTimer = null;
        _weakConnectionNotifier.value = true;
      } else {
        // Recovered — linger before hiding to avoid a flicker on a brief
        // good/poor bounce.
        _weakConnectionHideTimer?.cancel();
        _weakConnectionHideTimer = Timer(_kWeakConnectionLinger, () {
          if (mounted) _weakConnectionNotifier.value = false;
        });
      }
    });
    _callRepository = widget.callRepository ?? CallRepository(ApiClient());
    _connectivityService = widget.connectivityService ?? ConnectivityService();
    // Story 6.5 Option B — read the app-level singleton via
    // RepositoryProvider when no explicit injection. Tests that
    // construct CallScreen outside an App-shell either pass an
    // explicit service or accept the null case (the bloc handles a
    // null service gracefully — failed POSTs fall back to the
    // janitor sweep backstop for cap-counter recovery).
    _endCallRetryService =
        widget.endCallRetryService ?? _tryReadEndCallRetryService(context);
    _canvasInFallback = widget.debugCanvasFallback ?? false;
  }

  /// Best-effort lookup of the app-level retry service. Returns null
  /// when no `RepositoryProvider<EndCallRetryService>` ancestor exists
  /// (e.g. widget-test environments that pump `CallScreen` standalone).
  /// Wrapped in try/catch because `context.read` throws on a missing
  /// ancestor, and we prefer a null fall-back to a crash on the dial
  /// surface.
  EndCallRetryService? _tryReadEndCallRetryService(BuildContext context) {
    try {
      return context.read<EndCallRetryService>();
    } catch (_) {
      return null;
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Saves the first-frame disk read on the CallConnected layer-1 image
    // (AC8 recommendation). Runs once.
    if (!_backgroundPrecached) {
      _backgroundPrecached = true;
      final path = kScenarioBackgrounds[widget.scenario.riveCharacter];
      if (path != null) {
        precacheImage(AssetImage(path), context);
      }
    }
  }

  /// Fire-and-forget `{"type":"playback_idle"}` upstream to Pipecat
  /// via LiveKit's reliable data channel. `bot.py`'s
  /// `on_data_received` event handler routes it to
  /// `PatienceTracker.handle_playback_idle()`, which starts the
  /// silence ladder from the user's perceived end-of-bot-speech
  /// (instead of the server's outbound flush, which fired ~1 s
  /// ahead due to WebRTC jitter buffering).
  ///
  /// `reliable: true` so SCTP retransmits a dropped packet — losing
  /// this signal would mean the silence ladder never starts for that
  /// turn until the next bot utterance ends.
  void _publishPlaybackIdle(Room room) {
    final participant = room.localParticipant;
    if (participant == null) {
      // Room is mid-teardown or pre-connect — the bloc's safety
      // timer (10 s after `RemoteCallEnded`) covers this case. Log
      // so a regression that wedges `localParticipant=null` during
      // a healthy call surfaces in the diagnostic tail.
      dev.log(
        'CallScreen: publishData(playback_idle) skipped — '
        'localParticipant is null',
        name: 'call.uplink',
        level: 700,
      );
      return;
    }
    final bytes = utf8.encode(jsonEncode({'type': 'playback_idle'}));
    // Belt-and-braces: `publishData` returns a Future but a guard-rail
    // assertion (room disconnected, codec mismatch) could throw
    // synchronously. `.catchError` only catches async failures, so a
    // sync throw would escape as an unhandled future error. Wrap the
    // call so both modes route through the same diagnostic.
    try {
      unawaited(
        participant.publishData(bytes, reliable: true).catchError((Object e) {
          // The data channel can throw during teardown (room
          // disconnecting). The bloc's safety timer covers the
          // case where the server never receives this signal.
          dev.log(
            'CallScreen: publishData(playback_idle) failed: $e',
            name: 'call.uplink',
            level: 700,
          );
        }),
      );
    } catch (e) {
      dev.log(
        'CallScreen: publishData(playback_idle) threw sync: $e',
        name: 'call.uplink',
        level: 700,
      );
    }
  }

  @override
  void dispose() {
    // Story 6.3 — fire-and-forget the data-channel cancel. `?.dispose()`
    // is null-safe for the CallError-during-connect path where
    // `CallConnected` never fired. Order matters: dispose owned objects
    // first, then call super.
    final handler = _dataChannelHandler;
    _dataChannelHandler = null;
    if (handler != null) {
      unawaited(handler.dispose());
    }
    final scheduler = _visemeScheduler;
    _visemeScheduler = null;
    if (scheduler != null) {
      unawaited(scheduler.dispose());
    }
    // Story 6.14 — tear down the inbound-audio diagnostic.
    final statsLogger = _inboundAudioStatsLogger;
    _inboundAudioStatsLogger = null;
    if (statsLogger != null) {
      unawaited(statsLogger.dispose());
    }
    // Story 6.7 — dispose the checkpoint notifier BEFORE super.dispose()
    // so any rebuild-during-teardown can't read a disposed ValueNotifier
    // (would throw on `.value` access).
    _checkpointNotifier.dispose();
    // Story 6.11 — same teardown ordering for the noisy-environment
    // banner notifier.
    _envWarningNotifier.dispose();
    // Story 6.13 follow-up — tear down the connection-quality listener +
    // linger timer before disposing the notifier so neither can fire on a
    // disposed ValueNotifier during teardown.
    _qualityCancel?.call();
    _qualityCancel = null;
    _weakConnectionHideTimer?.cancel();
    _weakConnectionHideTimer = null;
    _weakConnectionNotifier.dispose();
    if (!_blocCreated) {
      // Safety net: the bloc never ran, so `CallBloc.close()` will not.
      // Drop the Room ourselves so we don't leak background timers (TTLMap
      // cleanup, SignalClient connect timer) or a half-open WebRTC peer.
      unawaited(_room.disconnect());
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return BlocProvider<CallBloc>(
      create: (_) {
        _blocCreated = true;
        return CallBloc(
          session: widget.callSession,
          scenario: widget.scenario,
          room: _room,
          callRepository: _callRepository,
          connectivityService: _connectivityService,
          endCallRetryService: _endCallRetryService,
          playbackDrainBuffer:
              widget.debugPlaybackDrainBuffer ??
              const Duration(milliseconds: 500),
          endCallResultTimeout:
              widget.debugEndCallResultTimeout ?? const Duration(seconds: 1),
        )..add(const CallStarted());
      },
      child: BlocConsumer<CallBloc, CallState>(
        listenWhen: (previous, current) =>
            current is CallEnded ||
            (previous is! CallConnected && current is CallConnected),
        listener: (context, state) {
          // Story 6.3 — wire the data-channel handler exactly once on the
          // first transition into CallConnected. The `??=` + the
          // `prev is! CallConnected && next is CallConnected` listenWhen
          // filter together guarantee single-construction even if the
          // bloc replays CallConnected via a later state path.
          if (state is CallConnected && _dataChannelHandler == null) {
            final room = context.read<CallBloc>().room;
            // Story 6.3b — VisemeScheduler subscribes to the native
            // EventChannel (`AudioClockChannel.kt`) and applies each
            // viseme arriving from the audio thread directly on the
            // Rive canvas. No data-channel involvement.
            //
            // Story 6.4 — the same PCM stream that drives lip-sync
            // also serves as the "speaker is silent now" signal that
            // tells the bloc when the server's exit-line audio has
            // actually finished playing locally. Naive callback that
            // fires on EVERY silence window; the bloc gates on its
            // own `_remoteEndPending` flag (mid-call gaps are ignored
            // there).
            _visemeScheduler = VisemeScheduler(
              applyViseme: (id) => _canvasKey.currentState?.setVisemeId(id),
              onSilenceConfirmed: () {
                if (!context.mounted) return;
                // The silence-confirmed callback fires on EVERY 600 ms
                // silence window — including intra-utterance Cartesia
                // pauses in a multi-sentence bot turn. Gate on
                // `_awaitingPlaybackIdle` so we only act on the silence
                // window that comes AFTER `bot_speaking_ended` (i.e.
                // the actual end-of-turn silence).
                //
                // Two consumers gated by the same flag:
                //
                // 1. Server-side `PatienceTracker` — publish
                //    `playback_idle` upstream so the silence ladder
                //    counts from the user's ear, not the server's
                //    outbox.
                //
                // 2. Bloc's hang-up drain (`PlaybackDrained`) — let
                //    the bloc disconnect the room only after the
                //    exit-line audio has actually finished playing.
                //
                // The upstream publish is fire-and-forget; loss is
                // tolerable (SCTP retransmits on the data channel,
                // and the bloc's 10 s safety timer covers the rare
                // case where the message never lands).
                if (!_awaitingPlaybackIdle) return;
                _awaitingPlaybackIdle = false;
                _publishPlaybackIdle(room);
                context.read<CallBloc>().add(const PlaybackDrained());
              },
            );
            // Story 6.14 AC1 — start the inbound-audio jitter diagnostic
            // on the same connect transition. Inert unless
            // `kLogInboundAudioStats` is true.
            _inboundAudioStatsLogger = InboundAudioStatsLogger(room)..start();
            final handlerBuilder =
                widget.debugHandlerBuilder ?? DataChannelHandler.new;
            _dataChannelHandler = handlerBuilder(
              room: room,
              // Intensity (the `_` in onEmotion) is received but not yet
              // consumed; future hook for emotion-blend. Documented as
              // a deliberate ignore so reviewers don't flag dead args.
              onEmotion: (emotion, _) =>
                  _canvasKey.currentState?.setEmotion(emotion),
              // Story 6.4 — `hang_up_warning` has no in-call UI surface
              // (UX-DR6: zero text on screen during calls). Reserved as
              // a hook for a future debrief-transition story. The
              // deliberate no-op is the production behaviour.
              onHangUpWarning: (_) {},
              // Story 6.4 — server-driven hang-up reaches the bloc as
              // `RemoteCallEnded`; the bloc handles room teardown and
              // emits CallEnded, which the BlocConsumer.listener above
              // pops back to /scenarios.
              //
              // Story 6.7 Deviation #2 — BEFORE dispatching the bloc
              // event, reconcile the HUD UP to the server-authoritative
              // met state. Closes the "cancel-mid-flight envelope-lost
              // race" (Story 6.6 deferred-work line 406): if N
              // `checkpoint_advanced` pushes succeeded but the final one
              // was cancelled by the pipeline shutdown, the local met count
              // would lag the server.
              //
              // Story 6.20 AC3 — prefer the REAL met SET when the server
              // sends `goals_met_indices`, so a future debrief can't
              // mislabel WHICH goals were met when they flipped out of
              // order. Fall back to the count-based `[0..passed)`
              // reconstruction only when the field is absent (pre-6.20
              // server, rolling deploy). Either way only walk UP — union
              // with the current set so the reconcile never SHRINKS what
              // the HUD already showed. `justFlippedIndex: null` so no
              // completion animation fires on the reconcile.
              onCallEnd: (reason, data) {
                if (!context.mounted) return;
                final total = data['total_checkpoints'];
                final current = _checkpointNotifier.value;
                if (total is num && current != null) {
                  final ti = total.toInt();
                  if (ti > 0) {
                    // Build the server-authoritative met set: prefer the
                    // real index set, else the count-based fallback.
                    final List<int> serverMet;
                    final rawSet = data['goals_met_indices'];
                    if (rawSet is List) {
                      final seen = <int>{};
                      for (final e in rawSet) {
                        if (e is num) {
                          final i = e.toInt();
                          if (i >= 0 && i < ti) seen.add(i);
                        }
                      }
                      serverMet = seen.toList();
                    } else {
                      final passed = data['checkpoints_passed'];
                      final pi = passed is num ? passed.toInt() : 0;
                      final clamped = pi < 0 ? 0 : (pi > ti ? ti : pi);
                      serverMet = [for (var i = 0; i < clamped; i++) i];
                    }
                    // Walk UP only: union with what the HUD already shows so
                    // a (theoretically) smaller server set never erases a
                    // locally-rendered tick.
                    final union = {...current.metIndices, ...serverMet}.toList()
                      ..sort();
                    if (union.length > current.metCount) {
                      _checkpointNotifier.value = CheckpointSnapshot(
                        hints: current.hints,
                        metIndices: union,
                        total: ti,
                        justFlippedIndex: null,
                      );
                    }
                  }
                }
                context.read<CallBloc>().add(RemoteCallEnded(reason, data));
              },
              // Story 6.4 — server signals end-of-bot-turn (outbound
              // audio drained). Arms the `_awaitingPlaybackIdle` gate
              // so the NEXT confirmed silence (user's speaker drained)
              // publishes `playback_idle` upstream. The data-channel
              // SCTP message arrives at the client well BEFORE the
              // tail audio is decoded + played, so the gate is set in
              // time for the post-utterance silence.
              onBotSpeakingEnded: () {
                _awaitingPlaybackIdle = true;
              },
              // Story 6.7 / 6.10 — `checkpoint_advanced` envelope (emitted
              // on call connect with zero goals met AND once per goal flip)
              // updates the UI-only HUD state. Story 6.10 UI refonte: the
              // HUD is a Flutter widget showing ONE step at a time. We pass
              // the full `hints` + met set so it animates locally, plus
              // `justFlippedIndex` (the goal that just flipped this turn, or
              // null on the initial state) to drive the completion
              // animation. `index` is the just-flipped goal's index, so it
              // marks a real flip only when it's actually in the met set.
              onCheckpointAdvanced: (payload) {
                if (!context.mounted) return;
                final met = payload.goalsMetIndices;
                final flipped = met.contains(payload.index)
                    ? payload.index
                    : null;
                _checkpointNotifier.value = CheckpointSnapshot(
                  hints: payload.hints,
                  metIndices: met,
                  total: payload.total,
                  justFlippedIndex: flipped,
                );
              },
              // Story 6.11 — parasitic background voice detected. Surface
              // the banner so the user sees WHY the character is about to
              // cut the call. The server-driven `call_end{reason:
              // noisy_environment}` follows shortly after this (the
              // PatienceTracker exit-line sequence), routing through
              // `onCallEnd` → `RemoteCallEnded` like any other character
              // hang-up. The banner stays up until the route transition.
              onEnvWarning: (payload) {
                if (!context.mounted) return;
                _envWarningNotifier.value = payload;
              },
            );
          }

          if (state is! CallEnded) return;
          if (_popScheduled) return;
          _popScheduled = true;
          // Story 6.5 Déviation #27 — pick the post-call route based on
          // (endReason, wasGifted). Three buckets:
          //
          //   1. `network_lost` (any gift outcome): the user needs to
          //      see "you lost connection, here's what happened to your
          //      quota". ALWAYS push the notice screen.
          //   2. `character_hung_up` / `inappropriate_content` AND
          //      `wasGifted=true`: the short-call gift screen.
          //   3. Everything else (`user_hung_up`, `survived`,
          //      non-gifted character/inappropriate >= 30 s): the
          //      Story 7.2 Call Ended overlay (identity + duration + %
          //      + theatrical phrase, 3-10 s hold masking the debrief
          //      fetch, auto-crossfade to the debrief).
          //
          // Defer to post-frame so the builder rebuilds with `canPop:
          // true` BEFORE the pop / pushReplacement is attempted —
          // otherwise the still-mounted `PopScope(canPop: false)` of
          // the previous frame intercepts navigation.
          //
          // `rootNavigator: true` mirrors the push contract documented
          // on the `CallScreen` dartdoc (ADR 003 §Tier 1).
          final endReason = state.endReason;
          final wasGifted = state.wasGifted;
          final showsNotice =
              endReason == 'network_lost' ||
              // Story 6.11 — parasitic-voice cut is ALWAYS gifted + always
              // shows the notice (no-quota-burn path, same UX as
              // network_lost): the user needs to know it was their
              // environment and that the slot was refunded.
              endReason == 'noisy_environment' ||
              ((endReason == 'character_hung_up' ||
                      endReason == 'inappropriate_content') &&
                  wasGifted == true);
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!context.mounted) return;
            final nav = Navigator.of(context, rootNavigator: true);
            if (showsNotice && endReason != null) {
              nav.pushReplacement(
                MaterialPageRoute<void>(
                  builder: (_) => CallEndedNoticeScreen(
                    endReason: endReason,
                    wasGifted: wasGifted,
                    giftsRemainingToday: state.giftsRemainingToday,
                  ),
                ),
              );
            } else if (endReason != null) {
              // Story 7.2 — Call Ended overlay for the debrief-eligible
              // reasons. Metrics are captured AT PUSH TIME: the % comes
              // from the HUD's reconciled checkpoint snapshot (Decision B
              // — the server-authoritative met set after the call_end
              // reconcile above, NOT the envelope's survival_pct, which
              // uses a different formula and is absent on user_hung_up);
              // duration + callId ride the CallEnded state (Decision D).
              final snapshot = _checkpointNotifier.value;
              nav.pushReplacement(
                CallEndedScreen.route(
                  scenario: widget.scenario,
                  endReason: endReason,
                  durationSec: state.durationSec,
                  callId: state.callId,
                  checkpointsPassed: snapshot?.metCount ?? 0,
                  totalCheckpoints: snapshot?.total ?? 0,
                  callRepository: _callRepository,
                ),
              );
            } else {
              // `endReason == null` cannot happen on the bloc's normal
              // exit paths (every one sets `_lastEndReason` before
              // emitting CallEnded) — fall back to the plain pop rather
              // than render an overlay with an unknown variant.
              nav.maybePop();
            }
          });
        },
        builder: (context, state) {
          // PopScope blocks system back-press during connecting/connected
          // /errored (ADR 003 §Tier 1) but MUST allow pop once the call
          // has ended, otherwise the listener's programmatic
          // Navigator.maybePop() is also blocked. CallError is
          // intentionally treated like an in-call state — the user must
          // confirm the exit via the on-screen "End call" button so a
          // stray back-gesture doesn't drop them out of an error they
          // haven't seen yet.
          return PopScope(
            canPop: state is CallEnded,
            child: Scaffold(
              backgroundColor: AppColors.background,
              body: _buildBody(context, state),
            ),
          );
        },
      ),
    );
  }

  Widget _buildBody(BuildContext context, CallState state) {
    if (state is CallConnected) {
      return _buildConnected(context);
    }
    if (state is CallError) {
      return _buildErrorBody(context, state.reason);
    }
    // CallConnecting (initial) and CallEnded (transient terminal state
    // before pop) both fall through to the dial surface. CallEnded only
    // renders for a single frame before the post-frame `maybePop` runs.
    return _buildDialSurface(context);
  }

  /// Outgoing dial surface — clones `IncomingCallScreen`'s visual structure
  /// (name + role on top, circular avatar at center, "Calling..." dots,
  /// single hang-up button at the bottom). Reads identity from
  /// `kCharacterCatalog`.
  ///
  /// Wrapped in `LayoutBuilder + SingleChildScrollView + IntrinsicHeight`
  /// (Story 5.4 pattern) so the natural Spacer-driven layout fills tall
  /// viewports while gracefully scrolling on small phones at large text
  /// scalers (320×480 + 1.5× safety net).
  Widget _buildDialSurface(BuildContext context) {
    final identity = kCharacterCatalog[widget.scenario.riveCharacter];
    assert(
      identity != null,
      'No character identity registered for riveCharacter '
      '"${widget.scenario.riveCharacter}". Add an entry to '
      'kCharacterCatalog.',
    );
    return SafeArea(
      child: LayoutBuilder(
        builder: (context, constraints) {
          return SingleChildScrollView(
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: IntrinsicHeight(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(
                    _kScreenHorizontalPadding,
                    _kScreenTopPadding,
                    _kScreenHorizontalPadding,
                    _kScreenBottomPadding,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _buildIdentityHeader(identity),
                      const Spacer(),
                      _buildAvatarBlock(),
                      const Spacer(),
                      Center(child: _buildHangUpButton(context)),
                    ],
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildIdentityHeader(CharacterIdentity? identity) {
    if (identity == null) {
      return const SizedBox.shrink();
    }
    return Column(
      children: [
        Text(
          identity.name,
          textAlign: TextAlign.center,
          style: const TextStyle(
            fontFamily: 'Inter',
            fontSize: _kCallNameSize,
            fontWeight: FontWeight.w400,
            color: AppColors.textPrimary,
            height: 46 / 38,
          ),
        ),
        Text(
          identity.role,
          textAlign: TextAlign.center,
          style: const TextStyle(
            fontFamily: 'Inter',
            fontSize: _kCallRoleSize,
            fontWeight: FontWeight.w400,
            color: CallColors.secondary,
            height: 19 / 16,
          ),
        ),
      ],
    );
  }

  Widget _buildAvatarBlock() {
    return Column(
      children: [
        CharacterAvatar(
          character: widget.scenario.riveCharacter,
          size: _kAvatarDiameter,
        ),
        const SizedBox(height: 12),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: AnimatedCallingText(
            style: TextStyle(
              fontFamily: 'Inter',
              fontSize: _kCallStatusSize,
              fontWeight: FontWeight.w400,
              color: CallColors.secondary,
              height: 29 / 24,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildErrorBody(BuildContext context, String reason) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          _kScreenHorizontalPadding,
          _kScreenTopPadding,
          _kScreenHorizontalPadding,
          _kScreenBottomPadding,
        ),
        child: Column(
          children: [
            const Spacer(),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 32),
              child: Text(
                reason,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'Inter',
                  fontSize: 16,
                  fontWeight: FontWeight.w500,
                  color: AppColors.destructive,
                ),
              ),
            ),
            const Spacer(),
            Center(child: _buildHangUpButton(context)),
          ],
        ),
      ),
    );
  }

  Widget _buildConnected(BuildContext context) {
    final backgroundPath = kScenarioBackgrounds[widget.scenario.riveCharacter];
    assert(
      backgroundPath != null,
      'No scenario background registered for riveCharacter '
      '"${widget.scenario.riveCharacter}". Add an entry to '
      'kScenarioBackgrounds or update the scenario.',
    );
    return Stack(
      fit: StackFit.expand,
      children: [
        // Layer 1 — scenario background image.
        if (backgroundPath != null)
          Image.asset(
            backgroundPath,
            fit: BoxFit.cover,
            errorBuilder: (_, _, _) => Container(color: AppColors.background),
          )
        else
          Container(color: AppColors.background),
        // Layer 2 — gaussian blur. SizedBox.expand gives BackdropFilter a
        // child to clip against; without one the filter is a no-op. Sigma 3
        // is intentional (depth-of-field), see project memory
        // `project_call_screen_blur_sigma_3.md`.
        BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 3, sigmaY: 3),
          child: const SizedBox.expand(),
        ),
        // Layer 3 — full-screen Rive canvas (character + in-canvas hang-up
        // button). The Semantics wrapper applies to ONLY this layer (per
        // AC6: "wired on the Rive canvas region for screen readers"),
        // not the entire Stack. On fallback it renders a solid
        // AppColors.background and we overlay the Flutter hang-up button
        // so the user retains an exit affordance.
        Positioned.fill(
          child: Semantics(
            button: true,
            label: 'End call',
            child: RiveCharacterCanvas(
              key: _canvasKey,
              character: widget.scenario.riveCharacter,
              onHangUp: () =>
                  context.read<CallBloc>().add(const HangUpPressed()),
              onFallback: () {
                if (widget.debugCanvasFallback != null) return;
                if (mounted) setState(() => _canvasInFallback = true);
              },
            ),
          ),
        ),
        // Story 6.11 — noisy-environment banner. Top-anchored inside
        // SafeArea with a top offset that clears the checkpoint HUD's
        // solid band (the HUD pins to the absolute top; this sits just
        // below it, per AC7 "above the character, below the stepper").
        // Placed BEFORE the HUD layer so the HUD z-paints above it if they
        // ever overlap. IgnorePointer so taps reach the character / in-
        // canvas hang-up button. Renders SizedBox.shrink when no warning
        // is active (null notifier value).
        Positioned.fill(
          child: IgnorePointer(
            ignoring: true,
            child: SafeArea(
              child: Align(
                alignment: Alignment.topCenter,
                child: Padding(
                  padding: const EdgeInsets.only(top: _kNoisyBannerTopOffset),
                  child: ValueListenableBuilder<EnvWarningPayload?>(
                    valueListenable: _envWarningNotifier,
                    builder: (context, payload, _) =>
                        NoisyEnvironmentBanner(payload: payload),
                  ),
                ),
              ),
            ),
          ),
        ),
        // Layer 4 — Checkpoint HUD (Story 6.10 UI refonte). A single
        // Flutter widget overlaid on the character: a dark gradient box
        // pinned to the ABSOLUTE top of the screen showing ONLY the
        // current step (inline check + text), animating per goal flip.
        // The Rive `.riv` no longer renders checkpoints. NO SafeArea here
        // (Walid 2026-05-28: the box must start at the very top, behind
        // the status bar); the widget consumes `MediaQuery.padding.top`
        // internally so the text still clears the status bar inside the
        // solid band. `IgnorePointer` lets taps fall through to the
        // character canvas. Renders `SizedBox.shrink()` when there's
        // nothing to show (null snapshot / all done).
        Positioned.fill(
          child: IgnorePointer(
            ignoring: true,
            child: Align(
              alignment: Alignment.topCenter,
              child: ValueListenableBuilder<CheckpointSnapshot?>(
                valueListenable: _checkpointNotifier,
                builder: (context, snap, _) =>
                    CheckpointStepHud(snapshot: snap),
              ),
            ),
          ),
        ),
        // Story 6.13 follow-up — weak-connection indicator (bottom scrim).
        // Renders only while the local participant's LiveKit quality is
        // poor/lost (debounced via `_weakConnectionNotifier`). It slides up
        // + fades in from the bottom; a background-coloured gradient fades
        // to transparent so it reads as part of the scene, not a hard
        // banner. Anchored low — clear of the checkpoint stepper at the
        // top — with the content lifted above the in-canvas hang-up button.
        // IgnorePointer so taps fall through to the hang-up.
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: IgnorePointer(
            ignoring: true,
            child: ValueListenableBuilder<bool>(
              valueListenable: _weakConnectionNotifier,
              builder: (context, weak, _) => AnimatedSlide(
                offset: weak ? Offset.zero : const Offset(0, 1),
                duration: const Duration(milliseconds: 320),
                curve: Curves.easeOutCubic,
                child: AnimatedOpacity(
                  opacity: weak ? 1 : 0,
                  duration: const Duration(milliseconds: 320),
                  curve: Curves.easeOut,
                  child: _buildWeakConnectionIndicator(context),
                ),
              ),
            ),
          ),
        ),
        if (_canvasInFallback)
          Positioned.fill(
            child: SafeArea(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 40),
                  child: _buildHangUpButton(context),
                ),
              ),
            ),
          ),
      ],
    );
  }

  /// Story 6.13 follow-up — the "weak connection" indicator (bottom scrim).
  /// A vertical gradient in the app background colour, opaque in the MIDDLE
  /// (behind the icon + text, for legibility over the bright scene) and
  /// fading to transparent at BOTH the top (so it blends into the scene)
  /// and the bottom (so the in-canvas hang-up button below stays clear,
  /// never dimmed). Content is vertically centred in the panel, which is
  /// bottom-anchored but sits ABOVE the hang-up button. A prominent
  /// wifi-off glyph reads "network problem" at a glance. Sizes are
  /// screen-height fractions so it scales across devices and is trivial to
  /// nudge here. Decorative, so `Semantics(liveRegion)` announces it
  /// without trapping focus.
  Widget _buildWeakConnectionIndicator(BuildContext context) {
    final screenHeight = MediaQuery.of(context).size.height;
    return Semantics(
      liveRegion: true,
      label: _kWeakConnectionMessage,
      child: Container(
        width: double.infinity,
        height: screenHeight * 0.42,
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              AppColors.background.withValues(alpha: 0.0),
              AppColors.background.withValues(alpha: 0.92),
              AppColors.background.withValues(alpha: 0.0),
            ],
            stops: const [0.0, 0.5, 1.0],
          ),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.wifi_off_rounded,
              color: AppColors.textPrimary,
              size: 32,
            ),
            const SizedBox(height: 10),
            Text(
              'Weak connection',
              textAlign: TextAlign.center,
              style: AppTypography.bodyEmphasis.copyWith(
                color: AppColors.textPrimary,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              'Audio may stutter',
              textAlign: TextAlign.center,
              style: AppTypography.caption.copyWith(
                color: AppColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHangUpButton(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Hang up',
      child: Material(
        color: CallColors.decline,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: () => context.read<CallBloc>().add(const HangUpPressed()),
          child: const SizedBox(
            width: 60,
            height: 60,
            child: Icon(Icons.call_end, color: AppColors.textPrimary, size: 28),
          ),
        ),
      ),
    );
  }
}
