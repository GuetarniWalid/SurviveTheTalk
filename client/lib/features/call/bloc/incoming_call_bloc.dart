import 'package:flutter/foundation.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/onboarding/consent_storage.dart';
import '../../../core/onboarding/vibration_service.dart';
import '../repositories/call_repository.dart';
import 'incoming_call_event.dart';
import 'incoming_call_state.dart';

class IncomingCallBloc extends Bloc<IncomingCallEvent, IncomingCallState> {
  final CallRepository _callRepository;
  final ConsentStorage _consentStorage;
  final VibrationService _vibrationService;

  IncomingCallBloc({
    required CallRepository callRepository,
    required ConsentStorage consentStorage,
    required VibrationService vibrationService,
  })  : _callRepository = callRepository,
        _consentStorage = consentStorage,
        _vibrationService = vibrationService,
        super(const IncomingCallRinging()) {
    on<AcceptCallEvent>(_onAccept);
    on<DeclineCallEvent>(_onDecline);
  }

  /// Exposed so the incoming-call screen can fire `startRingPattern()` from
  /// its first-frame callback. Starting the ring is a side-effect of the
  /// widget mounting, not a user event, so it lives outside the bloc's
  /// event graph — but the bloc still owns the service instance so the
  /// stop-on-every-transition and stop-on-close guarantees are centralised.
  VibrationService get vibrationService => _vibrationService;

  Future<void> _onAccept(
    AcceptCallEvent event,
    Emitter<IncomingCallState> emit,
  ) async {
    // Drop duplicate accepts: a second tap (error-banner retry + button tap,
    // or fast double-tap) while the first request is in flight must not
    // spawn a second bot + DB row.
    if (state is IncomingCallAccepting || state is IncomingCallConnected) {
      return;
    }

    // Stop the ring as soon as the user commits to answering, even if the
    // network call then fails — a silent "Connecting…" is far less jarring
    // than a vibrating phone that refuses to pick up.
    await _vibrationService.stop();
    if (emit.isDone) return;
    emit(const IncomingCallAccepting());
    try {
      final session = await _callRepository.initiateCall(
        scenarioId: 'waiter_easy_01',
      );
      // Storage failure must not cancel a successful call: the bot is
      // already running on the server, so we surface Connected regardless
      // and let the next launch re-show the incoming-call screen if the
      // flag never landed (acceptable degraded mode).
      await _tryPersistFirstCallShown();
      if (emit.isDone) return;
      emit(IncomingCallConnected(session));
    } on ApiException catch (e) {
      // Treat error identically to Decline from a gating perspective: AC5
      // says first-call-shown is set once the user has SEEN the screen,
      // regardless of outcome. Without this the user loops on the ring
      // forever when the server is unreachable.
      await _tryPersistFirstCallShown();
      if (emit.isDone) return;
      emit(IncomingCallError(e.message));
    } catch (_) {
      await _tryPersistFirstCallShown();
      if (emit.isDone) return;
      emit(const IncomingCallError('Call setup failed.'));
    }
  }

  Future<void> _onDecline(
    DeclineCallEvent event,
    Emitter<IncomingCallState> emit,
  ) async {
    await _vibrationService.stop();
    await _tryPersistFirstCallShown();
    if (emit.isDone) return;
    emit(const IncomingCallDeclined());
  }

  Future<void> _tryPersistFirstCallShown() async {
    try {
      await _consentStorage.saveFirstCallShown();
    } catch (e, stack) {
      debugPrint('saveFirstCallShown failed: $e\n$stack');
    }
  }

  @override
  Future<void> close() async {
    // Defensive: widget may be disposed mid-ring (e.g. user backgrounds the
    // app without tapping either button). Without this the device keeps
    // vibrating after the screen is gone.
    await _vibrationService.stop();
    return super.close();
  }
}
