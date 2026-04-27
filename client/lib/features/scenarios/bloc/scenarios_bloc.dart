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
    // Drop spam taps on "Tap to retry" while a fetch is already in flight —
    // otherwise we stack N parallel Dio requests whose responses can land
    // out of order. Mirrors the guard in `IncomingCallBloc._onAccept`.
    if (state is ScenariosLoading) return;
    emit(ScenariosLoading());
    try {
      final scenarios = await _repository.fetchScenarios();
      emit(ScenariosLoaded(scenarios));
    } on ApiException catch (e) {
      emit(ScenariosError(e.message));
    } catch (_) {
      // TypeError / FormatException / etc. from a malformed payload
      // (Scenario.fromJson cast failure, missing 'data' key, wrong types).
      // Without this catch the exception escapes the bloc and the UI
      // hangs forever in ScenariosLoading. Swallow the type info — the
      // user only needs an actionable message.
      emit(
        const ScenariosError('Unexpected response. Please try again.'),
      );
    }
  }
}
