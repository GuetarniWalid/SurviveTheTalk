import 'dart:async';
import 'dart:developer' as dev;

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:livekit_client/livekit_client.dart';

import '../../../core/services/connectivity_service.dart';
import '../../../core/services/end_call_retry_service.dart';
import '../../scenarios/models/scenario.dart';
import '../models/call_session.dart';
import '../models/end_call_result.dart';
import '../repositories/call_repository.dart';
import 'call_event.dart';
import 'call_state.dart';

class CallBloc extends Bloc<CallEvent, CallState> {
  final CallSession _session;
  // ignore: unused_field
  final Scenario _scenario;
  final Room _room;
  final CallRepository _callRepository;
  final ConnectivityService _connectivityService;
  final EndCallRetryService? _endCallRetryService;

  /// Exposes the cancel function returned by `room.events.on<...>` so we can
  /// unsubscribe in `close()` and avoid leaking a listener after the bloc
  /// is gone.
  CancelListenFunc? _disconnectCancel;

  /// True once `_onHangUpPressed` started — guards against the
  /// `RoomDisconnectedEvent` callback (asynchronously emitted via the
  /// LiveKit event bus when `room.disconnect()` runs) re-entering the
  /// disconnect path and emitting CallError on top of CallEnded.
  bool _hangingUp = false;

  /// True once the LiveKit `connect()` + mic-publish completed successfully.
  /// Guards `_onRoomDisconnected` against firing for the synchronous
  /// `RoomDisconnectedEvent` that LiveKit emits internally during a *failed*
  /// connect — without this, `_onCallStarted`'s catch arm and the listener
  /// would each emit `CallError`, racing.
  bool _connected = false;

  /// True after `room.disconnect()` has been awaited at least once. Stops
  /// `close()` from issuing a redundant second disconnect (the LiveKit Room
  /// handles a double-disconnect gracefully but it surfaces as a noisy log).
  bool _roomDisconnected = false;

  /// True once a server-driven `RemoteCallEnded` has been processed. Read
  /// by `_onRoomDisconnected` + the LiveKit listener so the follow-on
  /// `RoomDisconnectedEvent` from Pipecat's safety `EndFrame` does NOT
  /// surface `CallError('Connection lost.')` over a clean character-
  /// driven hang-up (Story 6.4 AC5). Also gates `_onPlaybackDrained`
  /// so mid-call user silence doesn't tear the room down.
  bool _remoteEndPending = false;

  /// Safety bound on the "remote-end-pending" window. If
  /// `VisemeScheduler.onSilenceConfirmed` never fires after a
  /// `RemoteCallEnded` (native channel detached, analyzer crashed,
  /// PCM stream wedged), force a `PlaybackDrained` after 10 s so the
  /// room is never wedged in a half-ended state. 10 s comfortably
  /// covers any natural exit-line duration on slow cellular.
  Timer? _remoteEndDrainTimer;

  /// Story 6.4 — small delay between the client-confirmed playback
  /// drain and the actual `_room.disconnect()` call. Covers the
  /// Android `AudioTrack` hardware buffer (~50-200 ms) that the
  /// VisemeScheduler's PCM-stream silence detector can't see. Without
  /// it, the very tail of the bot's exit line gets cut when
  /// `disconnect()` tears down the audio track.
  ///
  /// Constructor-injectable so tests can pass `Duration.zero` to
  /// keep their assertions fast.
  final Duration _playbackDrainBuffer;

  /// Story 6.5 Déviation #27 — bounded wait for the `/end` POST
  /// response before emitting `CallEnded` with gift info. 1 s in prod
  /// covers ~99% of POST roundtrips; `Duration.zero` in tests
  /// short-circuits the wait so existing widget tests that don't mock
  /// `CallRepository` don't hang on an unresolvable POST.
  final Duration _endCallResultTimeout;

  /// Story 6.5 review (P4) — once any exit path has fired the
  /// `POST /calls/{id}/end` request, this flag short-circuits all
  /// subsequent paths. The server endpoint IS idempotent (safe to
  /// double-POST), but a duplicate request is wasteful and obscures
  /// the canonical reason in operator logs (e.g. a 2nd POST with
  /// `network_lost` after a clean `character_hung_up`). The 3 exit
  /// paths converge here, so a single boolean suffices — no event
  /// ordering reasoning required.
  bool _endPostFired = false;

  /// Story 6.5 review (P3) — track in-flight `_endCallSilently`
  /// futures so `close()` can await them before tearing down the
  /// bloc. Without this, the fire-and-forget POST can outlive
  /// `bloc.close()` (the screen pops on `CallEnded` → `BlocProvider`
  /// disposes the bloc → repository call resolves on a disposed
  /// state). The set holds at most one future in practice (we POST
  /// once per call thanks to `_endPostFired`) but the set shape is
  /// future-proof if that contract ever loosens.
  final Set<Future<EndCallResult?>> _pendingEndCalls =
      <Future<EndCallResult?>>{};

  /// Story 6.5 Déviation #27 — captured at the first `_fireEndCall`
  /// call so every subsequent CallEnded emission site (e.g.
  /// `_onPlaybackDrained` firing after a `_onRemoteCallEnded` POST)
  /// can pass the canonical reason into the state. The "first wins"
  /// semantics matches `_endPostFired` — the POST is fired once with
  /// one reason; the state always carries that same reason.
  String? _lastEndReason;

  /// Story 6.5 Déviation #27 — server-confirmed gift outcome. `null`
  /// until the POST resolves (queued during airplane mode, or 1 s
  /// emission-site timeout fired). Read by emission sites to populate
  /// `CallEnded.wasGifted` / `CallEnded.giftsRemainingToday`.
  EndCallResult? _endCallResult;

  /// Story 6.5 Déviation #27 — bounded wait for the POST to resolve so
  /// `CallEnded` carries gift info when emitted. 1 s upper bound keeps
  /// the tap-to-pop latency tolerable on a slow server. Past the
  /// timeout, the result is null and the post-call screen falls back
  /// to hedged copy ("we'll confirm next time"). Tests can override
  /// `_endCallResultTimeout` via the constructor to `Duration.zero`
  /// so existing CallScreen widget tests that don't mock the repo
  /// (and therefore have an unresolvable POST in flight) don't
  /// stall on the 1 s deadline.
  Future<EndCallResult?> _awaitEndCallResult() async {
    if (_endCallResult != null) return _endCallResult;
    if (_pendingEndCalls.isEmpty) return null;
    if (_endCallResultTimeout == Duration.zero) return null;
    try {
      final results = await Future.wait(_pendingEndCalls).timeout(
        _endCallResultTimeout,
        onTimeout: () => const <EndCallResult?>[],
      );
      for (final r in results) {
        if (r != null) return r;
      }
    } catch (_) {
      // _endCallSilently swallows its own errors; this catch is
      // belt-and-braces against Future.wait surfacing something
      // unexpected during teardown races.
    }
    return _endCallResult;
  }

  /// Story 6.5 review (post-deploy E2E) — `connectivity_plus`
  /// subscription. Fires `RoomDisconnected` the moment the device
  /// goes offline (airplane mode toggle, cellular drop, WiFi router
  /// unplugged). Cancelled in `close()`.
  ///
  /// Why this exists in addition to the existing LiveKit
  /// `RoomDisconnectedEvent` listener: the LiveKit SDK does NOT
  /// detect connection loss while the device's radio is off — the
  /// OS silently buffers TCP/UDP sends that never reach the network,
  /// keepalive heartbeats never fire (they were never sent), and
  /// `RoomDisconnectedEvent` only fires once the SDK's internal
  /// retry budget is exhausted (several minutes in practice). Live
  /// VPS smoke test 2026-05-13 measured 7 m 12 s between the
  /// server-side participant-disconnect and the client's `/end` POST
  /// landing — the user was stuck on the call screen the entire time.
  /// Monitoring connectivity at the OS layer makes the disconnect
  /// reactive instead of timeout-driven.
  StreamSubscription<bool>? _connectivitySub;

  /// Read-only access to the underlying LiveKit Room for non-lifecycle
  /// subscriptions (e.g. `DataChannelHandler` listening to
  /// `DataReceivedEvent`). The bloc remains the single owner of the
  /// Room's connect/disconnect lifecycle. DO NOT call `disconnect()` on
  /// this Room from outside the bloc — emit a `HangUpPressed` event
  /// instead so the lifecycle guards (`_hangingUp`, `_roomDisconnected`)
  /// stay coherent.
  Room get room => _room;

  CallBloc({
    required CallSession session,
    required Scenario scenario,
    required Room room,
    required CallRepository callRepository,
    ConnectivityService? connectivityService,
    EndCallRetryService? endCallRetryService,
    Duration playbackDrainBuffer = const Duration(milliseconds: 500),
    Duration endCallResultTimeout = const Duration(seconds: 1),
  }) : _session = session,
       _scenario = scenario,
       _room = room,
       _callRepository = callRepository,
       _connectivityService = connectivityService ?? ConnectivityService(),
       _endCallRetryService = endCallRetryService,
       _playbackDrainBuffer = playbackDrainBuffer,
       _endCallResultTimeout = endCallResultTimeout,
       super(const CallConnecting()) {
    on<CallStarted>(_onCallStarted);
    on<HangUpPressed>(_onHangUpPressed);
    on<RoomDisconnected>(_onRoomDisconnected);
    on<RemoteCallEnded>(_onRemoteCallEnded);
    on<PlaybackDrained>(_onPlaybackDrained);

    _disconnectCancel = _room.events.on<RoomDisconnectedEvent>((_) {
      if (_hangingUp) return;
      // Skip the synchronous-during-connect-failure case: `_onCallStarted`'s
      // own catch arm owns the CallError emission for that path, otherwise
      // the listener would race it with a second `[CallError, CallEnded]`.
      if (!_connected) return;
      // Story 6.4 — the server-driven hang-up sequence ends with a
      // pipecat EndFrame → LiveKit room teardown → this listener fires.
      // The `_remoteEndPending` flag short-circuits the path so the
      // already-emitted `CallEnded` isn't overwritten by `CallError`.
      // Mirror LiveKit's internal disconnected state into our flag so a
      // follow-on `PlaybackDrained` (10 s safety timer, or the natural
      // VisemeScheduler signal) doesn't try to disconnect an already-
      // disconnected room — a wasted call that surfaces as a noisy log.
      if (_remoteEndPending) {
        _roomDisconnected = true;
        return;
      }
      add(const RoomDisconnected());
    });

    // Story 6.5 review (post-deploy E2E) — proactive connectivity
    // monitor. Fires `RoomDisconnected` the moment the OS reports
    // total connectivity loss, so airplane-mode-mid-call doesn't
    // hang the user on the call screen waiting for LiveKit's
    // (multi-minute) timeout. The handler short-circuits if the
    // call hasn't connected yet (the dial-screen has its own
    // failure path) or is already shutting down.
    _connectivitySub = _connectivityService.onConnectivityLost.listen((lost) {
      if (!lost) return;
      if (_hangingUp || !_connected || _remoteEndPending) return;
      if (_endPostFired) return;
      dev.log(
        'connectivity_lost — dispatching RoomDisconnected',
        name: 'CallBloc',
      );
      add(const RoomDisconnected());
    });
  }

  Future<void> _onCallStarted(
    CallStarted event,
    Emitter<CallState> emit,
  ) async {
    final stopwatch = Stopwatch()..start();
    // `Future.sync` traps a synchronous throw from `connect()` (e.g. mocked
    // failure in tests, or an SDK precondition assertion) into an async
    // failure so the surrounding try/catch is the single failure-handling
    // surface.
    final connectFuture = Future<void>.sync(
      () => _room.connect(_session.livekitUrl, _session.token),
    );
    try {
      await connectFuture.timeout(
        const Duration(seconds: 5),
        onTimeout: () => throw TimeoutException('LiveKit connect timed out'),
      );
    } on TimeoutException {
      // Schedule a fire-and-forget disconnect for the case where the
      // underlying connect resolves AFTER the timeout — Future.timeout
      // can't cancel its target, so without this we leak a half-connected
      // Room (zombie participant on the LiveKit server).
      _scheduleZombieDisconnect(connectFuture);
      // Story 6.5 review (P1, P2): connect-failure leaves the server-
      // side `'pending'` row inserted by /calls/initiate orphaned. The
      // listener at `_disconnectCancel` guards `if (!_connected)
      // return;` (correctly — it would race this catch arm if it
      // didn't), so this catch is the only place the cleanup POST can
      // fire. The janitor's 1 h sweep is the eventual-consistency
      // backstop; this POST unsticks the cap counter immediately.
      unawaited(_fireEndCall(reason: 'network_lost'));
      if (emit.isDone) return;
      emit(const CallError("Couldn't connect to the call."));
      emit(await _buildCallEnded());
      return;
    } catch (_) {
      _scheduleZombieDisconnect(connectFuture);
      // Same rationale as the TimeoutException arm above. Any failure
      // mode that prevents `_connected = true` from running must fire
      // the cleanup POST here, since the disconnect listener will
      // early-return on `!_connected` and skip the POST otherwise.
      unawaited(_fireEndCall(reason: 'network_lost'));
      if (emit.isDone) return;
      emit(const CallError("Couldn't connect to the call."));
      emit(await _buildCallEnded());
      return;
    }

    // Minimum 1-s "Connecting…" display per incoming-call-screen-design.md:409.
    // Mic publish is held until AFTER the visual hold so the user is not
    // already publishing audio while the dots are still on screen.
    final remaining = 1000 - stopwatch.elapsedMilliseconds;
    if (remaining > 0) {
      await Future<void>.delayed(Duration(milliseconds: remaining));
    }
    if (emit.isDone) return;
    try {
      await _room.localParticipant?.setMicrophoneEnabled(true);
    } catch (_) {
      // Story 6.5 review (P1): mic-enable failure is a connect-side
      // failure — `_connected` is still false at this point so the
      // listener guard would skip the POST. Fire it here so the cap
      // counter unsticks.
      unawaited(_fireEndCall(reason: 'network_lost'));
      if (emit.isDone) return;
      emit(const CallError("Couldn't connect to the call."));
      emit(await _buildCallEnded());
      return;
    }
    _connected = true;
    if (emit.isDone) return;
    emit(const CallConnected());
  }

  void _scheduleZombieDisconnect(Future<void> connectFuture) {
    connectFuture
        .then((_) async {
          // Connect resolved post-timeout. Drop the orphan room.
          if (_roomDisconnected) return;
          _roomDisconnected = true;
          try {
            await _room.disconnect();
          } catch (_) {}
        })
        .catchError((_) {
          // Connect resolved post-timeout with a failure — nothing to clean
          // up. Swallow to keep the future from surfacing as an unhandled
          // zone error.
        });
  }

  Future<void> _onHangUpPressed(
    HangUpPressed event,
    Emitter<CallState> emit,
  ) async {
    _hangingUp = true;
    // User-initiated hang-up takes over from any pending remote-end:
    // clear the 10 s safety timer so it can't fire a stale
    // `PlaybackDrained` after the bloc has already emitted CallEnded
    // (which would cause a double-emit, or — worse — fire on a closed
    // bloc if the screen unmounts before the timer's deadline).
    _remoteEndDrainTimer?.cancel();
    _remoteEndDrainTimer = null;
    _remoteEndPending = false;
    if (!_roomDisconnected) {
      _roomDisconnected = true;
      try {
        await _room.disconnect();
      } catch (_) {
        // disconnect() rarely throws, but if it does the user has already
        // committed to leaving — surface CallEnded anyway rather than wedge
        // the screen.
      }
    }
    // Story 6.5 — fire-and-forget POST /calls/{id}/end so the server
    // can flip status → completed and free the cap slot. The user is
    // already leaving the call; we never block the UI on the round-trip
    // and we never surface a server-side failure to the user.
    unawaited(_fireEndCall(reason: 'user_hung_up'));
    if (emit.isDone) return;
    emit(await _buildCallEnded());
  }

  Future<void> _onRoomDisconnected(
    RoomDisconnected event,
    Emitter<CallState> emit,
  ) async {
    if (_hangingUp) return;
    // Story 6.4 — character-driven end: the server's safety EndFrame
    // (8 s after `call_end`) tears down the room. We may not have
    // received our local `PlaybackDrained` yet — emit CallEnded
    // directly (clean end, not Connection lost). The POST already
    // fired from `_onRemoteCallEnded`; we don't re-POST here.
    if (_remoteEndPending) {
      _remoteEndDrainTimer?.cancel();
      _remoteEndDrainTimer = null;
      _roomDisconnected = true;
      if (emit.isDone) return;
      emit(await _buildCallEnded());
      return;
    }
    // Story 6.5 — mid-call network drop: fire-and-forget POST so the
    // server's cap counter eventually unsticks. This is the ONE path
    // that POSTs AND emits CallError — the visible UX is "Call cut →
    // back to scenario list"; the POST is silent telemetry/cleanup.
    unawaited(_fireEndCall(reason: 'network_lost'));
    if (emit.isDone) return;
    emit(const CallError('Connection lost.'));
    _roomDisconnected = true;
    if (emit.isDone) return;
    emit(await _buildCallEnded());
  }

  Future<void> _onRemoteCallEnded(
    RemoteCallEnded event,
    Emitter<CallState> emit,
  ) async {
    if (_remoteEndPending) return;
    _remoteEndPending = true;
    // Story 6.5 — fire-and-forget POST so the server flips status →
    // completed as soon as the server-driven end is acknowledged.
    // Doing this here (rather than waiting for `_onPlaybackDrained`)
    // means the cap counter frees up the moment the bot decides to
    // hang up, not 5-10 s later when the audio fully drains.
    //
    // Story 6.5 review (P5): `DataChannelHandler` defaults a malformed
    // `call_end` envelope's `reason` to the string `'unknown'` so the
    // bloc still treats the event as a clean end. But the server's
    // `EndCallIn.reason` is a strict `Literal` — `'unknown'` would
    // 422 silently (fire-and-forget swallows it), leaving the cap
    // counter stuck for 1 h until the janitor sweep. Coerce here so
    // the canonical character-hung-up reason lands on the wire.
    final reason = event.reason == 'unknown'
        ? 'character_hung_up'
        : event.reason;
    unawaited(_fireEndCall(reason: reason));
    // Do NOT disconnect the room here — the server's TTS exit line is
    // still streaming and the local jitter buffer / Opus decoder still
    // has up to ~1.5 s of audio to play. Disconnecting now cuts the
    // last sentence mid-word.
    //
    // The drain signal comes from `VisemeScheduler.onSilenceConfirmed`
    // (which rides the same PCM stream that drives lip-sync, via
    // `AudioClockChannel`) → `PlaybackDrained` event → disconnect.
    //
    // Safety: if the silence signal never fires (native detach, crash,
    // wedged stream), force-end after 10 s so the bloc isn't stuck
    // forever in remote-end-pending.
    _remoteEndDrainTimer?.cancel();
    _remoteEndDrainTimer = Timer(const Duration(seconds: 10), () {
      add(const PlaybackDrained());
    });
  }

  Future<void> _onPlaybackDrained(
    PlaybackDrained event,
    Emitter<CallState> emit,
  ) async {
    // Gate on `_remoteEndPending` — VisemeScheduler fires this
    // callback on every silence window, including mid-call gaps
    // between user turns. Only the post-`RemoteCallEnded` firing
    // should end the call.
    if (!_remoteEndPending) return;
    _remoteEndDrainTimer?.cancel();
    _remoteEndDrainTimer = null;

    // The VisemeScheduler's `onSilenceConfirmed` fires when the PCM
    // STREAM BEING SENT to the speaker has been silent for the
    // confirmation window. The Android AudioTrack hardware buffer
    // (~50-200 ms) is still playing the last real audio samples at
    // that moment — calling `_room.disconnect()` immediately would
    // tear down the audio track and cut the very tail of the bot's
    // exit line ("...Goodbye." → "...Goodb").
    //
    // 500 ms covers the worst-case hardware buffer + speaker latency
    // on Android without being perceptibly long.
    if (_playbackDrainBuffer > Duration.zero) {
      await Future<void>.delayed(_playbackDrainBuffer);
    }

    // Re-check emit.isDone after the await — `HangUpPressed` could
    // have raced past us during the drain delay and already emitted
    // CallEnded (the bloc serializes handlers but Bloc's framework
    // can mark emit.isDone during teardown).
    if (emit.isDone) return;

    if (!_roomDisconnected) {
      _roomDisconnected = true;
      try {
        await _room.disconnect();
      } catch (_) {
        // Same posture as `_onHangUpPressed`: the user has already
        // committed to leaving (the server hung up); surface CallEnded
        // regardless rather than wedge the screen.
      }
    }
    // Story 6.5 — POST fired earlier from `_onRemoteCallEnded` with the
    // server-supplied reason. Re-POSTing here is redundant (the server
    // endpoint is idempotent but the extra request is wasteful).
    if (emit.isDone) return;
    emit(await _buildCallEnded());
  }

  /// Story 6.5 review (P4) — single converging entry-point for the
  /// `POST /calls/{id}/end` fire-and-forget. Guards against duplicate
  /// POSTs from the 3 exit paths (`HangUpPressed`,
  /// `RoomDisconnected`, `RemoteCallEnded`) racing against each other.
  /// The server endpoint IS idempotent, but a duplicate request is
  /// wasteful and obscures the canonical reason in operator logs.
  ///
  /// Also tracks the in-flight future in `_pendingEndCalls` so
  /// `close()` can await it before the bloc tears down — without
  /// this, the POST can outlive the bloc when the screen pops on
  /// `CallEnded`, with the repository resolving on a disposed state.
  ///
  /// **Calling convention** — callers always wrap this in
  /// `unawaited(_fireEndCall(...))`; the returned Future is not
  /// consumed directly at the call-site. The gift fields are read
  /// later by `_buildCallEnded` via `_awaitEndCallResult()`, which
  /// awaits the captured `_endCallResult` field (populated by the
  /// `.then` continuation below). This keeps the exit-path handlers
  /// fully synchronous and the gift-fields propagation entirely
  /// inside the bloc.
  ///
  /// Story 6.5 Déviation #27 — the Future return type is kept so the
  /// `_pendingEndCalls` book-keeping and dedup branch can both yield
  /// a Future of the same shape. On the dedup short-circuit, returns
  /// a resolved Future of the captured `_endCallResult` (which may
  /// be null if the first POST has not resolved yet — in that case
  /// `_awaitEndCallResult` re-awaits via the in-flight future in
  /// `_pendingEndCalls`).
  Future<EndCallResult?> _fireEndCall({required String reason}) {
    if (_endPostFired) {
      // Already fired by an earlier exit-path handler; return the
      // last captured result (may be null if the first POST hasn't
      // resolved yet — the caller's `_awaitEndCallResult` will pick
      // up the in-flight future from `_pendingEndCalls` instead).
      return Future<EndCallResult?>.value(_endCallResult);
    }
    _endPostFired = true;
    _lastEndReason = reason;
    final future = _endCallSilently(reason: reason);
    _pendingEndCalls.add(future);
    // Capture the resolved result so subsequent CallEnded emissions
    // can pick it up without re-awaiting the future (e.g.
    // `_onPlaybackDrained` firing seconds after `_onRemoteCallEnded`).
    // `.then` always runs even when the future returns null.
    future.then((result) {
      if (result != null) _endCallResult = result;
    });
    // Future.whenComplete fires for both success and error paths,
    // so the set always drains.
    future.whenComplete(() => _pendingEndCalls.remove(future));
    return future;
  }

  /// Story 6.5 — fire-and-forget POST /calls/{id}/end.
  ///
  /// Every exit path (user hang-up, network drop, character hang-up)
  /// funnels through `_fireEndCall` → here so the server can flip
  /// `status` → `'completed'` and free the cap slot. Failures are
  /// logged via `dart:developer` (NEVER surfaced to the UI per
  /// CLAUDE.md Gotcha #10): the user has already committed to leaving,
  /// and a flaky server must not break the hang-up UX. The server-side
  /// janitor sweep is the eventually-consistent backstop for any POST
  /// that never reaches the server.
  ///
  /// Story 6.5 review (P18): the log line includes the exception
  /// runtimeType and (if available) an `ApiException.code`, but
  /// deliberately NOT the raw `$e.toString()` — that could include a
  /// `DioException`'s response body, which on a misconfigured 500 from
  /// a future endpoint version might leak user email / JWT / scenario
  /// content through Android logcat (snoopable by other apps with
  /// `READ_LOGS` on older devices and by some crash-reporting SDKs).
  Future<EndCallResult?> _endCallSilently({required String reason}) async {
    try {
      return await _callRepository.endCall(
        callId: _session.callId,
        reason: reason,
      );
    } catch (e, stack) {
      final code = _safeApiCode(e);
      dev.log(
        'endCall failed reason=$reason type=${e.runtimeType}'
        '${code != null ? ' code=$code' : ''} — queueing for retry',
        name: 'CallBloc',
        stackTrace: stack,
      );
      // Story 6.5 Option B (post-deploy fix) — persist the failed
      // POST so `EndCallRetryService` can replay it on the next
      // connectivity-regain event OR at the next app boot. The
      // janitor sweep is the final backstop for any entry that
      // somehow never drains (storage write failed AND app never
      // reopens). The service itself swallows storage errors so
      // this await is safe even on a broken keychain.
      final retryService = _endCallRetryService;
      if (retryService != null) {
        await retryService.queue(callId: _session.callId, reason: reason);
      }
      return null;
    }
  }

  /// Story 6.5 Déviation #27 — single builder for the terminal
  /// `CallEnded` state. Awaits the in-flight POST (up to 1 s) so the
  /// emitted state carries `wasGifted` + `giftsRemainingToday` when
  /// the server has responded. On timeout / no-POST-fired the fields
  /// stay null and the post-call notice screen falls back to hedged
  /// copy. The `endReason` field always carries `_lastEndReason` set
  /// by `_fireEndCall` — the listener uses it to route to the right
  /// notice variant (e.g. always show "Connexion perdue" screen on
  /// `network_lost`, regardless of gift outcome).
  Future<CallEnded> _buildCallEnded() async {
    final result = await _awaitEndCallResult();
    return CallEnded(
      endReason: _lastEndReason,
      wasGifted: result?.wasGifted,
      giftsRemainingToday: result?.giftsRemainingToday,
      // Story 7.2 — the Call Ended overlay renders the server-computed
      // duration and fetches the debrief by call id during its hold.
      durationSec: result?.durationSec,
      callId: _session.callId,
    );
  }

  /// Best-effort extraction of `ApiException.code` without coupling
  /// `call_bloc.dart` to `ApiException` directly (the bloc layer is
  /// transport-agnostic). Uses dynamic dispatch so a `noSuchMethod`
  /// is the only side-effect on a non-API error type, which we
  /// swallow.
  String? _safeApiCode(Object e) {
    try {
      final dynamic dyn = e;
      final code = dyn.code;
      return code is String ? code : null;
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> close() async {
    _remoteEndDrainTimer?.cancel();
    _remoteEndDrainTimer = null;
    // Story 6.5 review (post-deploy E2E) — cancel the connectivity
    // subscription FIRST so a late connectivity-lost event during
    // teardown can't enqueue a `RoomDisconnected` on a closing bloc.
    await _connectivitySub?.cancel();
    _connectivitySub = null;
    final cancel = _disconnectCancel;
    _disconnectCancel = null;
    if (cancel != null) {
      await cancel();
    }
    if (!_roomDisconnected) {
      _roomDisconnected = true;
      try {
        await _room.disconnect();
      } catch (_) {}
    }
    // Story 6.5 review (P3): wait for any in-flight end-call POST
    // before tearing the bloc down. Bounded by a 2 s timeout so a
    // server hang cannot block the screen pop indefinitely — the
    // janitor's 1 h sweep is the eventual-consistency backstop.
    if (_pendingEndCalls.isNotEmpty) {
      try {
        await Future.wait(_pendingEndCalls).timeout(
          const Duration(seconds: 2),
          onTimeout: () => <EndCallResult?>[],
        );
      } catch (_) {
        // _endCallSilently already swallows its own errors; this
        // catch is belt-and-braces against Future.wait surfacing
        // a different failure mode during teardown.
      }
    }
    return super.close();
  }
}
