import '../models/call_usage.dart';
import '../models/scenario.dart';

sealed class ScenariosState {
  const ScenariosState();
}

final class ScenariosInitial extends ScenariosState {
  const ScenariosInitial();
}

// Deliberately non-const so successive loading emissions are distinct
// instances; BlocListener/BlocBuilder dedupe equal const instances and would
// silently skip a retry that re-enters Loading. Mirrors `auth_state.dart`.
final class ScenariosLoading extends ScenariosState {}

final class ScenariosLoaded extends ScenariosState {
  final List<Scenario> scenarios;
  final CallUsage usage;

  /// Named parameters chosen over positional so future widening (e.g.
  /// `lastSyncedAt` in Story 9.x cache work, or per-scenario lock state)
  /// doesn't shift call sites. Mirrors the pattern Story 5.2 retro flagged
  /// as a velocity multiplier.
  const ScenariosLoaded({required this.scenarios, required this.usage});
}

final class ScenariosError extends ScenariosState {
  /// One of: 'NETWORK_ERROR', 'SERVER_ERROR', 'MALFORMED_RESPONSE',
  /// 'UNKNOWN_ERROR'. Copy lives in the view, keyed by this code — the
  /// bloc no longer ferries user-facing strings.
  final String code;

  /// `0` on the first failure; increments by `1` each subsequent
  /// consecutive failure; resets to `0` on any `ScenariosLoaded` emission.
  /// Drives the repeat-failure copy variant in `_ErrorView`.
  final int retryCount;

  const ScenariosError({required this.code, required this.retryCount});
}
