import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../core/api/api_exception.dart';
import '../../../core/local_cache/scenario_cache_store.dart';
import '../repositories/scenarios_fetch_result.dart';
import '../repositories/scenarios_repository.dart';
import 'scenarios_event.dart';
import 'scenarios_state.dart';

class ScenariosBloc extends Bloc<ScenariosEvent, ScenariosState> {
  final ScenariosRepository _repository;

  /// Story 9.1 — optional offline cache. Null-tolerant on purpose: when null
  /// (no store wired, e.g. existing bloc tests / a future flavor without the
  /// DB) every cache read/write is skipped and the bloc keeps today's
  /// network-only behaviour. Mirrors the optional-with-test-default pattern
  /// already used for `difficultyStorage` / `purchaseSyncService`.
  final ScenarioCacheStore? _cacheStore;

  /// In-flight guard, independent of the emitted state. The cache-first path
  /// (Story 9.1) emits `ScenariosLoaded` (NOT `ScenariosLoading`) for the whole
  /// network window, so the old `state is ScenariosLoading` check alone would
  /// let a re-entrant `LoadScenariosEvent` (the bloc's default transformer is
  /// concurrent) start a SECOND parallel `/scenarios` fetch — re-introducing the
  /// exact out-of-order `usage` overwrite the guard exists to prevent. This flag
  /// restores the pre-9.1 single-fetch invariant on the cache-hit branch too.
  bool _loadInFlight = false;

  ScenariosBloc(this._repository, {ScenarioCacheStore? cacheStore})
    : _cacheStore = cacheStore,
      super(const ScenariosInitial()) {
    on<LoadScenariosEvent>(_onLoad);
    on<RefreshScenariosEvent>(_onRefresh);
  }

  Future<void> _onLoad(
    LoadScenariosEvent event,
    Emitter<ScenariosState> emit,
  ) async {
    // Drop spam taps on "Try again" / re-entrant loads while a fetch is already
    // in flight — otherwise we stack N parallel Dio requests whose responses can
    // land out of order. `_loadInFlight` covers the cache-hit branch (state stays
    // Loaded, not Loading); the `state is ScenariosLoading` check is kept for the
    // no-cache branch and mirrors `IncomingCallBloc._onAccept`.
    if (_loadInFlight || state is ScenariosLoading) return;
    _loadInFlight = true;
    try {
      // Capture the next retry index BEFORE Loading clobbers the previous
      // ScenariosError state. Resets to 0 on any non-error prior state, so a
      // successful Loaded → fresh failure starts at 0 again.
      final previous = state;
      final nextRetryCount =
          previous is ScenariosError ? previous.retryCount + 1 : 0;

      // Story 9.1 — cache-first: render last-known data instantly when a cache
      // exists, then refresh from the network below. A null cache (empty,
      // corrupt, or no store wired) falls through to the Loading→fetch path.
      var shownFromCache = false;
      final cacheStore = _cacheStore;
      if (cacheStore != null) {
        final cached = await cacheStore.readScenarios();
        if (cached != null) {
          shownFromCache = true;
          emit(
            ScenariosLoaded(
              scenarios: cached.scenarios,
              usage: cached.usage,
              fromCache: true,
            ),
          );
        }
      }

      if (!shownFromCache) emit(ScenariosLoading());

      try {
        final result = await _repository.fetchScenarios();
        await _writeCacheSafely(result);
        emit(ScenariosLoaded(scenarios: result.scenarios, usage: result.usage));
      } on ApiException catch (e) {
        // Story 9.1 — a failed refresh while a cache is already on screen is
        // SILENT (keep last-known data, never the error screen). Only
        // error-screen when there was no cache to fall back to.
        if (shownFromCache) return;
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
        if (shownFromCache) return;
        emit(
          ScenariosError(
            code: 'MALFORMED_RESPONSE',
            retryCount: nextRetryCount,
          ),
        );
      }
    } finally {
      _loadInFlight = false;
    }
  }

  /// Story 8.2 (D1) — silent background refresh after a call returns. No
  /// `ScenariosLoading` (so the list never flashes to a spinner mid-session)
  /// and no `ScenariosError` flip (a failed background refresh keeps the
  /// current view rather than error-screening the user). Only a successful
  /// fetch swaps in a fresh `ScenariosLoaded` — which, because the widget type
  /// at that tree position is unchanged, preserves the list State (the 7.4
  /// `_initiatedThisSession` mark) while updating `usage`/`scenarios`. Skips
  /// while a foreground load is in flight so it can't race it.
  ///
  /// Story 9.1 — a successful refresh also writes through to the cache, keeping
  /// the offline copy progression-fresh after every call.
  Future<void> _onRefresh(
    RefreshScenariosEvent event,
    Emitter<ScenariosState> emit,
  ) async {
    // Skip while a foreground load is in flight — its cache-hit branch keeps the
    // state at Loaded (not Loading), so without `_loadInFlight` a refresh could
    // race a concurrent fetch (Story 9.1).
    if (_loadInFlight || state is ScenariosLoading) return;
    try {
      final result = await _repository.fetchScenarios();
      await _writeCacheSafely(result);
      emit(ScenariosLoaded(scenarios: result.scenarios, usage: result.usage));
    } catch (_) {
      // Background refresh — swallow any failure and keep the current state.
      // Stale usage for one more call beats an error screen after a call.
    }
  }

  /// Persists a freshly-fetched result to the cache. A cache-write failure must
  /// NEVER downgrade a successful fetch (the user still sees fresh data), so
  /// any error here is swallowed.
  Future<void> _writeCacheSafely(ScenariosFetchResult result) async {
    final cacheStore = _cacheStore;
    if (cacheStore == null) return;
    try {
      await cacheStore.writeScenarios(result);
      // ignore: avoid_catches_without_on_clauses
    } catch (_) {
      // Swallow — a successful fetch must not error out on a cache-write fault.
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
