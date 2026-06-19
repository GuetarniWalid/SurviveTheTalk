# Story 9.2: Build Automatic Data Sync on Network Availability

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want my data to sync automatically when I get an internet connection,
so that I always see up-to-date scenarios and my progress is preserved across devices.

## Context & Scope (read first)

This is the **second (final) story of Epic 9 (Offline Access & Data Sync)** and is **Flutter-client-only** — **zero server changes** (no endpoint, no migration, no deploy). It builds directly on Story 9.1's read-through cache.

**The honest scope: most of this story's epic ACs are ALREADY satisfied by shipped code. One behavior is genuinely new.**

What already works (do NOT rebuild — verify + regression-test only):

| Epic-9.2 AC | Already delivered by | Mechanism |
|---|---|---|
| App launches with network → pulls latest scenarios + progression, updates cache | **Story 9.1** | `LoadScenariosEvent` = cache-first render → background `GET /scenarios` → `writeScenarios()` write-through ([scenarios_bloc.dart:36-107](client/lib/features/scenarios/bloc/scenarios_bloc.dart)) |
| New server scenarios appear in the cache + list | **Story 9.1** | Any successful fetch replaces the whole list and rewrites `cached_scenarios` transactionally |
| User completed a call on THIS device → cache updated simultaneously, no separate sync | **Story 8.2 + 9.1** | `RefreshScenariosEvent` (silent post-call refresh) now write-throughs to cache ([scenarios_bloc.dart:120-148](client/lib/features/scenarios/bloc/scenarios_bloc.dart)) |
| Sync causes no UI jank / no visible loading | **Story 8.2** | `RefreshScenariosEvent` emits no `ScenariosLoading` and no `ScenariosError`; only swaps a fresh `ScenariosLoaded` on success |

**The ONE genuinely new behavior — the whole point of this story:**

> When the device transitions **offline → online while the app is already running** (e.g. airplane mode toggled off while the hub shows cached data), the scenario list must refresh **automatically**, without an app relaunch and without the user tapping "Try again."

Story 9.1 deliberately left this seam open and named it: *"Connectivity awareness already exists — `ConnectivityService` exposes `onConnectivityRegained` … 9.2 will hook `onConnectivityRegained` to trigger background sync — leave that seam for 9.2."* ([9-1 Dev Notes](_bmad-output/implementation-artifacts/9-1-build-local-cache-with-sqflite-for-scenarios-and-debriefs.md)). Today **nothing** listens to `onConnectivityRegained` for the scenario list — only `EndCallRetryService` consumes it (to drain `/end` POSTs). This story adds that one wire and regression-guards everything above.

✅ **Both open design decisions were CONFIRMED by Walid on 2026-06-19 — see "Decisions (CONFIRMED)" at the end. They are LOCKED; do not re-litigate.** Headline: (D1) **connectivity-regain is the ONLY new trigger** — no app-foreground-resume trigger; (D2) sync is **fully silent** — no spinner, no toast, no offline badge (this also closes 9.1's leftover "saved data affordance" question: **the answer is no badge**).

## Acceptance Criteria

> Source: `_bmad-output/planning-artifacts/epics.md` §"Story 9.2" + NFR20 (`prd.md` "Data sync reliability — Eventually consistent within 60s"). Reworded to separate the **already-delivered** guarantees (now regression-locked) from the **new** connectivity-regain behavior.

1. **(FR34 — new: auto-sync on connectivity regain)** When the device transitions from offline to online **while the app is running and the scenario hub is active** (its `ScenariosBloc` is alive), the hub automatically re-fetches `GET /scenarios` and updates both the on-screen list and the local cache — with **no app relaunch and no user tap**. This holds whether the hub is currently showing cached data (`ScenariosLoaded(fromCache: true)`), fresh data, OR the offline error screen (`ScenariosError` from a no-cache cold-launch offline): in every case a regain silently recovers to a fresh `ScenariosLoaded`.

2. **(FR34 — app-launch sync, regression-locked from 9.1)** When the app launches with network connectivity, it pulls the latest scenario list and embedded user progression from `GET /scenarios` and updates the local sqflite cache. (Already delivered by `LoadScenariosEvent`'s cache-first → background-refresh path; this story must not regress it.)

3. **(New server scenarios appear, regression-locked)** When scenarios are added on the server (weekly content drops post-MVP), the next successful sync (launch OR regain) writes them into `cached_scenarios` and the hub renders them. (Any successful fetch rewrites the full list transactionally — no per-scenario diffing needed.)

4. **(Same-device progression, regression-locked from 8.2 + 9.1)** When the user completes a call on this device, progression is already sent to the server during the call flow and the post-call `RefreshScenariosEvent` write-throughs the fresh `/scenarios` to the cache — so no separate sync is needed for data originating on this device. This story must not regress it.

5. **(NFR20 — eventual consistency)** When the app has network access, local data converges to server data well within 60 seconds of app launch (covered by AC2) **and** within seconds of a mid-session connectivity regain (covered by AC1). The trigger fires promptly on the regain event; wall-clock convergence is bounded by a single `/scenarios` round-trip.

6. **(No jank / no visible loading — D2 fully silent)** The regain sync runs through the existing silent `RefreshScenariosEvent` path: **no `ScenariosLoading` spinner, no error-screen flip on failure, no toast, no offline badge.** While browsing the hub, the list updates in place if fresh data arrives; a failed regain refresh is swallowed and the user keeps seeing last-known data. No flicker, no duplicate concurrent fetch.

7. **(No regressions / gates green)** `flutter analyze` stays clean and `flutter test` stays fully green, including every pre-existing test. The new `connectivityService` constructor param on `ScenariosBloc` is **optional and null-tolerant** (mirrors `cacheStore`) so existing bloc tests and the router fallback compile unchanged.

## Tasks / Subtasks

- [ ] **Task 1 — Inject `ConnectivityService` into `ScenariosBloc` + subscribe to regain (AC: #1, #6, #7)**
  - [ ] Add an **OPTIONAL named** constructor param: `ScenariosBloc(this._repository, {ScenarioCacheStore? cacheStore, ConnectivityService? connectivityService})`. Store it; do **not** make it required (a required param would force every existing bloc test + the router fallback to construct a `ConnectivityService` — keep the null-tolerant, optional-with-test-default pattern already used for `cacheStore` / `difficultyStorage` / `purchaseSyncService`).
  - [ ] In the constructor body, after registering the two existing handlers, subscribe to regain and re-dispatch the **existing** silent refresh:
    ```dart
    _regainSub = connectivityService?.onConnectivityRegained.listen((_) {
      add(const RefreshScenariosEvent());
    });
    ```
    Store the subscription in a `StreamSubscription<void>? _regainSub;` field. **Reuse `RefreshScenariosEvent` — do NOT invent a new event/state.** Its semantics are exactly what AC1/AC6 need: no `ScenariosLoading`, no `ScenariosError` flip, write-through to cache on success, swallow on failure. (See Decision D3.)
  - [ ] Override `close()` to cancel the subscription **before** `super.close()`, so no `RefreshScenariosEvent` is ever `add()`-ed after the bloc closes (post-close `add()` throws `StateError`). Mirror `EndCallRetryService.dispose()`'s `_regainSub?.cancel()` idiom:
    ```dart
    @override
    Future<void> close() {
      _regainSub?.cancel();
      return super.close();
    }
    ```
  - [ ] **Do NOT touch `_onLoad` / `_onRefresh` logic.** The existing `_loadInFlight` guard already serializes a regain-triggered refresh against a concurrent foreground load or post-call refresh (M1 / F3 fixes from 9.1) — a regain landing mid-fetch is dropped, not stacked. From `ScenariosError` (cold-launch-offline, no cache), `_onRefresh`'s guard (`_loadInFlight || state is ScenariosLoading`) is false, so it proceeds and recovers to `ScenariosLoaded` on success (AC1's error-screen self-heal). Verify this path in tests rather than adding new branching.

- [ ] **Task 2 — Thread `ConnectivityService` to the PRODUCTION inline bloc (AC: #1, #7)**
  - [ ] **CRITICAL — same trap as 9.1's cache-store wiring.** `App.scenariosBloc` is **null in production**; the real hub bloc is the **inline** `ScenariosBloc(ScenariosRepository(ApiClient()), cacheStore: scenarioCacheStore)..add(const LoadScenariosEvent())` at [router.dart:132-141](client/lib/app/router.dart). If you only wire an injected/`.value` path, the offline-regain feature silently no-ops in prod while every injected-bloc test stays green.
  - [ ] `bootstrap()` already constructs the app-lifetime `ConnectivityService` at [main.dart:117](client/lib/main.dart) (`final connectivityService = ConnectivityService();`, currently passed only to `EndCallRetryService.attach`). **Reuse that same instance** — pass it into `App(...)`. Do not construct a second one (it would be a second broadcast subscriber, harmless but wasteful and confusing).
  - [ ] Add `final ConnectivityService? connectivityService;` to `App` (optional, with the other bootstrap-owned services) and forward it through `AppRouter.createRouter(...)`.
  - [ ] In `createRouter`, add an optional `ConnectivityService? connectivityService` param (nullable, same rationale as `scenarioCacheStore`) and pass it into the inline bloc: `ScenariosBloc(ScenariosRepository(ApiClient()), cacheStore: scenarioCacheStore, connectivityService: connectivityService)`. Also pass it to the injected `.value` branch's bloc if/when one is supplied (the `App.scenariosBloc` test path constructs its own bloc, so that path injects its own `ConnectivityService` in tests — no change needed to the `.value` wrapper itself).
  - [ ] Sharing one `ConnectivityService` across `EndCallRetryService` **and** `ScenariosBloc` is safe: `onConnectivityChanged` is a `connectivity_plus` broadcast stream, and `onConnectivityRegained` returns a fresh per-call closure (independent `hasBeenOffline` state per subscriber). [Source: [connectivity_service.dart:77-90](client/lib/core/services/connectivity_service.dart).]

- [ ] **Task 3 — Tests (AC: #1, #4, #6, #7)**
  - [ ] **Retrofit the existing bloc suite to stay green.** Task 1 adds the `connectivityService` param. The existing `buildBloc()` helper ([scenarios_bloc_test.dart:89](client/test/features/scenarios/bloc/scenarios_bloc_test.dart)) passes none → `connectivityService` is null → no subscription → every pre-existing `[Loading, ...]` / Refresh expectation is unchanged. Confirm the full suite passes with the param added.
  - [ ] **New regain group** (`bloc_test` + `mocktail`). Add `class MockConnectivityService extends Mock implements ConnectivityService {}` (mirrors [end_call_retry_service_test.dart:15](client/test/core/services/end_call_retry_service_test.dart)). Drive a controllable regain stream:
    - Helper: a `StreamController<void> regain` (non-broadcast is fine — the bloc subscribes once); `when(() => mockConn.onConnectivityRegained).thenAnswer((_) => regain.stream);` Build the bloc with `connectivityService: mockConn`. `tearDown` closes the controller.
    - (a) **Regain from a cache-shown state triggers a silent refresh:** seed a `ScenariosLoaded`, `regain.add(null)`, expect a single fresh `ScenariosLoaded` (no `ScenariosLoading`, no `ScenariosError`), and `verify(() => mockRepo.fetchScenarios()).called(...)` + `verify(() => mockStore.writeScenarios(any())).called(1)` (write-through).
    - (b) **Regain recovers from the offline error screen:** put the bloc in `ScenariosError` (no-cache + failed load), then `regain.add(null)` with the repo now succeeding → expect `[ScenariosLoaded(fresh)]`, no intermediate `ScenariosLoading`. (AC1 self-heal.)
    - (c) **Failed regain refresh stays silent:** in `ScenariosLoaded`, `regain.add(null)` with the repo throwing `ApiException` → expect **no** new emission (state unchanged, no `ScenariosError`). (AC6.)
    - (d) **Regain refresh is dropped while a load is in flight:** start a `LoadScenariosEvent` with a delayed repo, fire `regain.add(null)` during the window → assert `fetchScenarios()` is called exactly once (the `_loadInFlight` guard holds). (Reuses the M1/F3 invariant.)
    - (e) **`close()` cancels the subscription:** after `bloc.close()`, `regain.add(null)` must NOT throw and must NOT call the repo (no post-close `add()`).
  - [ ] Use the existing `registerFallbackValue(const LoadScenariosEvent())` (already in `setUpAll`); no new fallback needed (`RefreshScenariosEvent` is const-constructed in the bloc, not passed through a mock).
  - [ ] **Do NOT inject a real `ConnectivityService` that hits `connectivity_plus`** in unit tests — mock it (the platform channel would fail in the VM runner, same class of trap as sqflite Gotcha A). A real `Connectivity()` is only exercised on-device.
  - [ ] (Optional, low-value) A wiring test that `createRouter(..., connectivityService: mockConn)` builds the inline hub bloc with the service — but the production wire is one line and a regression yields a visible "hub doesn't auto-refresh on regain" smoke-gate failure, so a full `createRouter` widget test may be judged too fragile (mirror 9.1's L2 defer rationale). Dev's call; document if skipped.
  - [ ] `flutter analyze` clean + full `flutter test` green.

## Dev Notes

### Architecture & patterns to follow (do NOT reinvent)
- **Connectivity-regain is an EXISTING, proven seam.** `ConnectivityService.onConnectivityRegained` is already correct and battle-tested (it powers `EndCallRetryService`'s queue drain). It emits **only on a true offline→online transition** — a `wifi → mobile` transport hop is NOT a regain, and the first event on an app that starts online is suppressed (stateful `hasBeenOffline` filter). So the bloc will not get a spurious refresh at boot; the normal boot path is `LoadScenariosEvent` only. [Source: [connectivity_service.dart:56-95](client/lib/core/services/connectivity_service.dart).]
- **The consumer pattern is `EndCallRetryService`** — subscribe to `onConnectivityRegained` in a long-lived object, fire a fire-and-forget action on each event, cancel the subscription on teardown. `ScenariosBloc` is the natural owner here (it owns the refresh logic + state), so the subscription lives on the bloc and dies in `close()` — no separate service needed. [Source: [end_call_retry_service.dart:56-65,147-150](client/lib/core/services/end_call_retry_service.dart).]
- **Reuse `RefreshScenariosEvent`, don't add a new event.** It is *literally* "the silent background refresh" event (Story 8.2): no spinner, no error flip, write-through to cache (9.1). A regain sync wants exactly those semantics. Adding a parallel `SyncScenariosEvent` would duplicate `_onRefresh` for zero behavioral gain. [Source: [scenarios_event.dart:9-21](client/lib/features/scenarios/bloc/scenarios_event.dart), [scenarios_bloc.dart:120-148](client/lib/features/scenarios/bloc/scenarios_bloc.dart).]
- **bootstrap() + thread-through DI** is the only DI mechanism (no service locator). The `ConnectivityService` is already bootstrap-owned; thread it App → `createRouter` → inline bloc exactly as 9.1 threaded `scenarioCacheStore`. [Source: [main.dart:117-122](client/lib/main.dart), [app.dart](client/lib/app/app.dart), [router.dart:47-141](client/lib/app/router.dart); `client/CLAUDE.md` §"Architecture patterns".]

### Why NOT an app-lifetime sync service (rejected design — do not build)
The obvious mirror of `EndCallRetryService` would be a bootstrap-owned `ScenarioSyncService`. **It does not fit**, because there is **no app-lifetime handle to the production `ScenariosBloc`**: that bloc is **route-scoped, created inline** via `BlocProvider(create:)` in the root route ([router.dart:132-141](client/lib/app/router.dart)), and `App.scenariosBloc` is `null` in prod by deliberate 9.1 design. A standalone service would have to either (a) promote the hub bloc to an app singleton (a real refactor that reverses 9.1's structure), or (b) write to the cache directly and force the hub to reload (more code, a new race). Putting the subscription **on the bloc** keeps the trigger co-located with the refresh it triggers, ties the subscription lifecycle to the bloc's, and is unit-testable with a fake stream. This is the same reasoning 9.1 used to keep the cache read-through "behind the bloc, not in the widgets."

### What is already true (regression targets, not build targets)
- App-launch sync (AC2), new-scenarios-appear (AC3), same-device post-call cache update (AC4), and no-jank silent refresh (AC6's machinery) are all **already shipped**. Your job for these is a green `flutter test` proving they still hold after the wiring change — not new feature code. The 9.1 bloc tests already cover cache-first load + write-through; the 8.2 tests cover the silent post-call refresh. Don't duplicate them; just keep them green.

### ⚠️ Gotchas (each is a real trap)
- **Gotcha A — post-`close()` `add()` throws.** A regain event arriving after the bloc closes would call `add(RefreshScenariosEvent())` on a closed bloc → `StateError`. Cancel `_regainSub` in `close()` **before** `super.close()`. Test case (e) guards this.
- **Gotcha B — `connectivity_plus` in `flutter test`.** A real `ConnectivityService` touches the `connectivity_plus` platform channel → fails in the VM runner. **Always mock** `ConnectivityService` in unit tests (same class of trap as sqflite Gotcha A in 9.1). [Source: `client/CLAUDE.md` §1 reflex generalized.]
- **Gotcha C — don't widen the silent-refresh into a visible one.** D2 is "fully silent." Do not add a `ScenariosLoading` emit, a toast, or an offline badge on the regain path. The list swaps in place via the fresh `ScenariosLoaded` (its `fromCache:false` differs by value from the cached emit, so `BlocBuilder` won't dedup it — 9.1 Gotcha C). [Source: [scenarios_state.dart:17-38](client/lib/features/scenarios/bloc/scenarios_state.dart).]
- **Gotcha D — sealed events + `registerFallbackValue`.** `ScenariosEvent` is sealed; tests already register `const LoadScenariosEvent()` as the fallback. No `Fake extends` (won't compile). [Source: `client/CLAUDE.md` §2.]
- **Gotcha E — lints block CI** (`prefer_const_constructors` on `const RefreshScenariosEvent()`, `verifyNever` not `verify(...).called(0)`). Run `flutter analyze` to zero before committing. [Source: `client/CLAUDE.md` §9.]

### Previous Story Intelligence (Story 9.1 — done 2026-06-19)
- 9.1 shipped the read-through cache and **explicitly reserved `onConnectivityRegained` for this story** — the seam is intentional, not incidental.
- 9.1's hard-won lesson, repeated here: **the production hub bloc is the router's inline fallback**, not `App.scenariosBloc` (null in prod). Wire the inline constructor or the feature silently no-ops. (9.1 spent a CRITICAL task callout on this; same trap applies to `connectivityService`.)
- 9.1's review added the `_loadInFlight` guard in **both** `_onLoad` and `_onRefresh` (M1 + F3). That guard is exactly what makes a regain-triggered `RefreshScenariosEvent` safe against a concurrent load/refresh — you inherit it for free; do not weaken it.
- 9.1's auth-reset cache wipe ([app.dart:143-147](client/lib/app/app.dart), keyed on `AuthBloc → AuthInitial`) is unrelated to sync but proves the App-level subscription/cancel idiom you'll mirror for `_cacheWipeSub` ↔ `_regainSub`.
- The cross-user privacy invariant (9.1 F1) is **out of scope** for 9.2 — you are not changing what's cached or when it's wiped, only adding a refresh trigger. Don't touch the wipe wiring.

### Git Intelligence (recent commits)
- `4d941a0` / `13e6c54` / `bfba430` / `88bb516` / `3437fb7` — the full Story 9.1 lifecycle (spec → dev → adversarial hardening → review fixes → done). All on `main`. The 9.1 diff is the canonical reference for: the optional-null-tolerant constructor param pattern (`cacheStore`), the inline-bloc wiring in `router.dart`, and the bloc-test retrofit (mocked store, default-null read). Mirror those shapes for `connectivityService`.

### Project Structure Notes
- **No new files.** This story edits four existing lib files and one test file:
  - `client/lib/features/scenarios/bloc/scenarios_bloc.dart` (constructor param + subscription + `close()` override)
  - `client/lib/main.dart` (pass the existing `connectivityService` into `App`)
  - `client/lib/app/app.dart` (accept + forward `connectivityService`)
  - `client/lib/app/router.dart` (param + feed inline bloc)
  - `client/test/features/scenarios/bloc/scenarios_bloc_test.dart` (mock + regain group)
- No server, DB, migration, or deploy footprint — the server **Smoke Test Gate is intentionally omitted** (client-only story; the offline/regain behavior is only honestly testable on-device with airplane mode).

### Manual on-device validation (Pixel 9 — client story, no server gate)
Airplane-mode toggling is the only honest test of regain sync. The behaviors that MUST be device-validated:
1. **Mid-session regain (the money moment):** open the hub online, turn **airplane mode ON** (hub keeps showing cached data — 9.1), then turn **airplane mode OFF** while still on the hub → the list refreshes **on its own**, no tap, no spinner, no relaunch. If a new scenario was added server-side, it appears.
2. **No-cache cold-launch-offline self-heal:** (fresh install or post-logout, cache empty) launch with airplane mode ON → empathetic error screen; turn airplane mode OFF → hub appears on its own (no "Try again" tap needed).
3. **No double-fetch / no jank:** toggling airplane off does not flash a spinner, jank the list, or fire a visible loop; the swap is silent.
4. **No spurious refresh on a transport hop:** switching wifi↔mobile (both online) does NOT trigger a visible reload (the regain filter suppresses it).
5. **Regression — post-call same-device update still works:** complete a call, return to hub → budget/progression are fresh (8.2 path unchanged).

A ready-to-run device script will be handed to Walid at smoke-gate time per the project rule.

### References
- [Source: `_bmad-output/planning-artifacts/epics.md`#Story-9.2] — the five epic ACs (app-launch sync, new scenarios, same-device update, NFR20 60s, no-jank).
- [Source: `_bmad-output/planning-artifacts/prd.md` "Data sync reliability"] — NFR20: "Eventually consistent within 60s … Local-first with background sync."
- [Source: `_bmad-output/planning-artifacts/architecture.md`#Data-Architecture] — "Sync pattern: pull from API at launch → store locally → display from cache" (lines 253-255); "Pull-based sync at app launch" (line 1032); offline-first separation (line 71).
- [Source: [client/lib/core/services/connectivity_service.dart](client/lib/core/services/connectivity_service.dart)] — `onConnectivityRegained` semantics (true-transition only, first-online suppressed, per-subscriber state).
- [Source: [client/lib/core/services/end_call_retry_service.dart](client/lib/core/services/end_call_retry_service.dart)] — the canonical `onConnectivityRegained` consumer (subscribe / fire-and-forget / cancel) to mirror.
- [Source: [client/lib/features/scenarios/bloc/scenarios_bloc.dart](client/lib/features/scenarios/bloc/scenarios_bloc.dart) + [scenarios_event.dart](client/lib/features/scenarios/bloc/scenarios_event.dart)] — `RefreshScenariosEvent` (the silent refresh to reuse), `_loadInFlight` guard, write-through.
- [Source: [client/lib/app/router.dart:132-141](client/lib/app/router.dart) + [main.dart:117-151](client/lib/main.dart) + [app.dart](client/lib/app/app.dart)] — the inline production hub bloc + the bootstrap→App→router threading path to mirror.
- [Source: `_bmad-output/implementation-artifacts/9-1-build-local-cache-with-sqflite-for-scenarios-and-debriefs.md`] — previous story: cache, write-through, the inline-bloc wiring trap, `_loadInFlight`, the reserved regain seam.
- [Source: `client/CLAUDE.md`] — Flutter gotchas (mock platform-channel services in tests, sealed-event fallback, BlocBuilder dedup, lint traps).

## Decisions (CONFIRMED — Walid 2026-06-19)

> Both LOCKED. The dev agent implements them as stated and must NOT re-open or "optimize" them.

**D1 — Connectivity-regain is the ONLY new sync trigger; no app-foreground-resume trigger. → CONFIRMED.**
Wire `ScenariosBloc` to `ConnectivityService.onConnectivityRegained` only. App-launch sync is already covered by 9.1's cache-first `LoadScenariosEvent`; mid-session offline→online is covered by the new regain hook. We deliberately do **not** add a `didChangeAppLifecycleState(resumed)` refresh trigger for the hub (the way `EndCallRetryService` has one). **Known, accepted trade-off:** the 9.1 code comment notes `connectivity_plus` on Android can occasionally miss a regain transition after a brief background trip (notification-shade airplane toggle, app-switch to verify net) — in that rare case the hub won't auto-refresh until the next launch or the next real regain event. Accepted for MVP; if it bites in practice, a foreground-resume trigger is the documented follow-up (it would need the hub screen to observe lifecycle, since the prod bloc isn't app-lifetime). This is surfaced now, not discovered later.

**D2 — Sync is fully silent: no spinner, no toast, no offline badge. → CONFIRMED.**
The regain refresh runs through `RefreshScenariosEvent` (no `ScenariosLoading`, no `ScenariosError` flip). On success the list swaps in place; on failure it's swallowed and last-known data stays. **No visible chrome of any kind** is added — and this also **closes Story 9.1's open "saved data affordance" question: the answer is NO badge / no offline indicator.** Matches the epic AC ("the sync does not cause UI jank or visible loading") and the Handler's-Brief "zero furniture" rule. The `fromCache` flag added in 9.1 stays an internal value-differentiator (so `BlocBuilder` doesn't dedup the fresh emit) — it drives no UI.

**D3 — Reuse `RefreshScenariosEvent`; no new event or state. → CONFIRMED (implementation default).**
The regain trigger dispatches the existing silent `RefreshScenariosEvent`. No `SyncScenariosEvent`, no new `ScenariosState`. Rationale: identical semantics (silent, write-through, swallow-on-failure), zero behavioral gain from a parallel event, and it keeps `_onRefresh` the single silent-refresh code path (one place to reason about the `_loadInFlight` race).

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed — comprehensive developer guide created.

### File List

## Change Log

| Date | Change |
| --- | --- |
| 2026-06-19 | Story 9.2 created (create-story). Scope clarified: 4 of 5 epic ACs already delivered by 9.1/8.2 (regression-locked); the one new behavior is connectivity-regain → silent hub refresh via the seam 9.1 reserved. Decisions D1 (regain-only, no app-resume trigger) + D2 (fully silent, no offline badge — closes 9.1's open badge question) + D3 (reuse `RefreshScenariosEvent`) CONFIRMED by Walid. Status `backlog → ready-for-dev`. |
