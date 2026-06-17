sealed class ScenariosEvent {
  const ScenariosEvent();
}

final class LoadScenariosEvent extends ScenariosEvent {
  const LoadScenariosEvent();
}

/// Story 8.2 (D1) — silent re-fetch of `/scenarios` after a call returns, so
/// `CallUsage.callsRemaining` is fresh at the START of the next call (the FR29
/// debrief-paywall trigger reads it). Unlike [LoadScenariosEvent] it does NOT
/// emit [ScenariosLoading] (no full-screen spinner flash after every call) and
/// does NOT flip to [ScenariosError] on failure (a background refresh must not
/// error-screen the user mid-session) — it only swaps in a fresh
/// [ScenariosLoaded] on success, preserving the list State (and the Story 7.4
/// `_initiatedThisSession` mark). Knowingly reverses the 7.4 "no in-session
/// refetch" for usage accuracy; the briefing gate stays correct because the
/// refreshed `attempts` is server-fresh too.
final class RefreshScenariosEvent extends ScenariosEvent {
  const RefreshScenariosEvent();
}
