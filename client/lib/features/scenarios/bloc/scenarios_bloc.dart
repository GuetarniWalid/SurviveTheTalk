import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../core/api/api_exception.dart';
import '../repositories/scenarios_repository.dart';
import 'scenarios_event.dart';
import 'scenarios_state.dart';

class ScenariosBloc extends Bloc<ScenariosEvent, ScenariosState> {
  final ScenariosRepository _repository;

  ScenariosBloc(this._repository) : super(const ScenariosInitial()) {
    on<LoadScenariosEvent>(_onLoad);
  }

  Future<void> _onLoad(
    LoadScenariosEvent event,
    Emitter<ScenariosState> emit,
  ) async {
    // Drop spam taps on "Try again" while a fetch is already in flight —
    // otherwise we stack N parallel Dio requests whose responses can land
    // out of order. Mirrors the guard in `IncomingCallBloc._onAccept`.
    if (state is ScenariosLoading) return;

    // Capture the next retry index BEFORE Loading clobbers the previous
    // ScenariosError state. Resets to 0 on any non-error prior state, so a
    // successful Loaded → fresh failure starts at 0 again.
    final previous = state;
    final nextRetryCount =
        previous is ScenariosError ? previous.retryCount + 1 : 0;

    emit(ScenariosLoading());
    try {
      final result = await _repository.fetchScenarios();
      emit(ScenariosLoaded(scenarios: result.scenarios, usage: result.usage));
    } on ApiException catch (e) {
      emit(
        ScenariosError(
          code: _classifyApiException(e),
          retryCount: nextRetryCount,
        ),
      );
    } catch (_) {
      // TypeError / FormatException / etc. from a malformed payload
      // (Scenario.fromJson cast failure, missing 'data' key, wrong types).
      // Without this catch the exception escapes the bloc and the UI
      // hangs forever in ScenariosLoading.
      emit(
        ScenariosError(
          code: 'MALFORMED_RESPONSE',
          retryCount: nextRetryCount,
        ),
      );
    }
  }

  /// Maps an `ApiException` to the canonical 4-class error code the view
  /// consumes. Routing (in priority order):
  ///   - `code == 'NETWORK_ERROR'`                          → NETWORK_ERROR
  ///   - `statusCode in [500, 600)` OR `code == 'SERVER_ERROR'` → SERVER_ERROR
  ///   - anything else (incl. 4xx, server-defined codes)    → UNKNOWN_ERROR
  ///
  /// Status-code routing was added 2026-04-29 (Story 5.5 review, decision 6)
  /// to fix the dead-code heuristic — backend codes never start with '5', so
  /// the previous `code.startsWith('5')` branch never fired in production.
  /// `'SERVER_ERROR'` literal kept as a defensive case for any future server
  /// surface that emits the canonical string code without a 5xx HTTP status.
  static String _classifyApiException(ApiException e) {
    if (e.code == 'NETWORK_ERROR') return 'NETWORK_ERROR';
    final status = e.statusCode;
    if ((status != null && status >= 500 && status < 600) ||
        e.code == 'SERVER_ERROR') {
      return 'SERVER_ERROR';
    }
    return 'UNKNOWN_ERROR';
  }
}
