# Story 9.1: Build Local Cache with sqflite for Scenarios and Debriefs

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want my scenario list and past debrief reports stored on my device,
so that I can browse scenarios and review my feedback even without internet.

## Context & Scope (read first)

This is the **first story of Epic 9 (Offline Access & Data Sync)** and is **Flutter-client-only** — **zero server changes**. The two read endpoints it caches already exist and are unchanged:

- `GET /scenarios` → `{data: [...scenario objects...], meta: {...usage...}}` (consumed by `Scenario.fromJson` + `CallUsage.fromMeta`).
- `GET /debriefs/{call_id}` → `{data: {...debrief object...}}` (consumed by `Debrief.tryParse`).

The job is a **read-through local cache** that makes the hub and past debriefs render offline from last-known data, then refresh silently when online. Story 9.2 ("Automatic Data Sync on Network Availability") builds on this — keep the sync trigger surface clean so 9.2 can extend it.

⚠️ **Three scope decisions are flagged at the end of this file under "Decisions Needing Walid's Confirmation" — read them before coding.** The most important: the "tap the report icon → debrief" path is **currently a placeholder** (`router.dart:188` renders `DebriefPlaceholderScreen`), so satisfying the offline-debrief AC requires wiring that route to the cache. Do not start the debrief half until Decision 3 is confirmed.

## Acceptance Criteria

> Source: `_bmad-output/planning-artifacts/epics.md` §"Story 9.1". The criteria below **correct two stale assumptions in the epic's prose** (per-scenario `difficulty` no longer exists — removed in Story 6.28; progression arrives embedded, not as a separate table). See Decisions 1 & 2.

1. **(FR32 — offline scenario list)** When the app fetches scenarios from `GET /scenarios`, the full scenario list **and** its `meta` usage block are written to the local sqflite cache. When the app is opened **offline**, the scenario list (hub) renders from the local cache with last-known data — including each scenario's last-known progression (`best_score`, `attempts`) and the last-known call-budget — instead of the network-error screen.

2. **(FR33 — offline debriefs)** When a debrief is received from `GET /debriefs/{call_id}` (which today happens at the end of a call, in `CallEndedScreen`), it is stored locally in sqflite, keyed so it can be retrieved by the scenario it belongs to. All past debrief reports for which a debrief was cached are accessible **offline** by tapping the report icon on a scenario card.

3. **(Local-first render)** When the hub renders, it loads from the local cache **first** (instant render if a cache exists), then refreshes from `GET /scenarios` in the background **if** network is available. A successful refresh updates both the on-screen list and the cache. A failed refresh while a cache exists is **silent** — the user keeps seeing last-known data, never the error screen.

4. **(Cache schema mirrors the live data model)** The local sqflite database persists: (a) the scenario list as parse-ready records keyed by scenario `id`, preserving server order; (b) the `/scenarios` `meta`/usage block; (c) debriefs keyed by `call_id` with their owning `scenario_id`. The persisted shapes round-trip cleanly through the existing `Scenario.fromJson` / `CallUsage.fromMeta` / `Debrief.tryParse` parsers (see Decision 1 for why we store parse-ready JSON, not normalized typed columns).

5. **(No regressions)** Online behaviour is unchanged on the happy path: a fresh fetch still produces the identical hub and the identical post-call debrief. The `flutter analyze` gate stays clean and `flutter test` stays fully green, including every pre-existing test.

6. **(Graceful cache-miss)** Tapping the report icon for a scenario whose debrief was **not** cached (e.g. attempted before this story shipped, or completed on another device) shows an empathetic "no saved report / reconnect to load" state — never a crash, a raw error, or an infinite spinner. When online, that path may fetch + cache the debrief if a `call_id` is resolvable; when offline with no cache, it bounces to the empathetic state.

## Tasks / Subtasks

- [ ] **Task 1 — Add dependencies (AC: #1, #2, #4)**
  - [ ] `cd client && flutter pub add sqflite path_provider` (resolves current stable — sqflite ^2.4.x / path_provider ^2.1.x as of 2026-06). Add **`sqflite_common_ffi`** to **dev_dependencies** (`flutter pub add --dev sqflite_common_ffi`) — required to run DB code under `flutter test` (see Gotcha A).
  - [ ] Verify `flutter pub get` resolves with the existing SDK constraint (`sdk: ^3.11.0`).

- [ ] **Task 2 — Build the local database layer (AC: #4)**
  - [ ] Create `client/lib/core/local_cache/app_database.dart`: a single owner of the sqflite `Database` instance. `open()` resolves the DB path via `path_provider` (`getApplicationDocumentsDirectory()`), opens at `version: 1`, and creates tables in `onCreate`. **Make the factory + path injectable** (`open({DatabaseFactory? factory, String? path})`) so tests pass `databaseFactoryFfi` + `inMemoryDatabasePath` without touching platform channels (Gotcha A/B).
  - [ ] Schema (version 1) — store parse-ready JSON, not normalized columns (Decision 1):
    - `cached_scenarios(id TEXT PRIMARY KEY, position INTEGER NOT NULL, json TEXT NOT NULL, updated_at INTEGER NOT NULL)`
    - `cache_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` — holds the `/scenarios` `meta` JSON (key `scenarios_usage`) and the last-sync timestamp (key `scenarios_synced_at`).
    - `cached_debriefs(call_id INTEGER PRIMARY KEY, scenario_id TEXT NOT NULL, debrief_json TEXT NOT NULL, created_at INTEGER NOT NULL)` + `CREATE INDEX idx_debriefs_scenario ON cached_debriefs(scenario_id)`.
  - [ ] Leave an explicit `onUpgrade` switch (empty for v1) so 9.2 / future stories can add migrations without reopening this file blind.

- [ ] **Task 3 — Scenario cache store + cache-first Bloc load (AC: #1, #3, #5)**
  - [ ] Create `client/lib/core/local_cache/scenario_cache_store.dart` wrapping `AppDatabase`: `Future<ScenariosFetchResult?> readScenarios()` (returns null on empty cache; reads rows ordered by `position`, rebuilds `Scenario.fromJson` per row + `CallUsage.fromMeta` from `cache_meta`); `Future<void> writeScenarios(ScenariosFetchResult)` (transactional: clear + reinsert rows in order, upsert `cache_meta`). Reuse the existing `ScenariosFetchResult` wrapper — do not invent a new DTO.
  - [ ] Modify `client/lib/features/scenarios/bloc/scenarios_bloc.dart` to take the `ScenarioCacheStore` (constructor injection, alongside the existing `ScenariosRepository`). On `LoadScenariosEvent`: read cache → if present, emit `ScenariosLoaded(fromCache: true)` immediately; else emit `ScenariosLoading`. Then attempt the network fetch → on success, `writeScenarios()` + emit fresh `ScenariosLoaded`; on `ApiException` → **if a cache was already shown, stay silent (no error emit)**; **if no cache, emit `ScenariosError`** preserving the existing error-classification + `retryCount` logic.
  - [ ] On `RefreshScenariosEvent` (the silent post-call refresh, Story 8.2): on success, `writeScenarios()` + emit; on failure stay silent (unchanged). This keeps the cache progression-fresh after every call.
  - [ ] Add an optional `bool fromCache` (default `false`) to `ScenariosLoaded` in `scenarios_state.dart` — used only so the UI *could* show a subtle "saved data" affordance; do not break existing equality/tests. (Surfacing an offline badge in the UI is optional polish — confirm with Walid before adding visible chrome.)

- [ ] **Task 4 — Debrief cache store + capture at fetch (AC: #2, #6)** — *gated on Decision 3*
  - [ ] Create `client/lib/core/local_cache/debrief_cache_store.dart`: `Future<void> write({required int callId, required String scenarioId, required Map<String,dynamic> payload})`; `Future<Map<String,dynamic>?> readLatestForScenario(String scenarioId)` (most recent by `created_at`); `Future<Map<String,dynamic>?> readByCallId(int callId)`.
  - [ ] Write-on-fetch: in `client/lib/features/call/views/call_ended_screen.dart`, after `widget.callRepository.fetchDebrief(callId:)` succeeds, persist the payload via the injected store keyed by `widget.scenario.id` + `callId`. The scenario + callId are both already in scope here (`CallEndedScreen.route(scenario:..., callId:...)`). Thread the store through `CallEndedScreen.route(...)` (and from `call_screen.dart:959` where the route is built) — fire-and-forget, never block the transition, never throw into the UI.
  - [ ] Also persist in the `DebriefScreen` polling path if a fetch lands there (so a late-arriving debrief is still cached).

- [ ] **Task 5 — Wire the report-icon route to the cache (AC: #2, #6)** — *gated on Decision 3*
  - [ ] Replace the `'${AppRoutes.debrief}/:scenarioId'` placeholder in `client/lib/app/router.dart:184-192`: resolve the cached debrief for `scenarioId` via `DebriefCacheStore.readLatestForScenario`, then render the **real** `DebriefScreen(payload: cached, callId: cachedCallId, callRepository: ...)`. On cache-miss + offline → empathetic "no saved report" state (reuse `EmpatheticErrorScreen`, like `NoNetworkScreen`); on cache-miss + online → attempt fetch (needs a resolvable `call_id` — see Decision 3 open question) then cache.
  - [ ] Keep `DebriefScreen` back-compat: it already accepts `payload` + `callId` + `callRepository` and renders v1 & v2 payloads defensively (`Debrief.tryParse`). Do not alter its parsing contract.

- [ ] **Task 6 — DI wiring in bootstrap (AC: #1, #2, #5)**
  - [ ] In `client/lib/main.dart` `bootstrap()`: `await AppDatabase.open()` once (parallel with the existing `preload()` calls), construct the two stores, and thread them into `App(...)` → `router.dart` → `ScenariosBloc` and the call/debrief route, following the established "open in bootstrap, pass via constructor" pattern (same shape as `ConnectivityService` / `EndCallRetryService`). Do **not** introduce `get_it` — the app uses constructor injection + `context.read()` only.
  - [ ] Update `client/lib/app/app.dart` to accept + forward the stores (optional params with test defaults, mirroring how `endCallRetryService` / `purchaseSyncService` are threaded).

- [ ] **Task 7 — Tests (AC: #1–#6)**
  - [ ] Store unit tests using `sqflite_common_ffi` (`sqfliteFfiInit(); databaseFactory = databaseFactoryFfi;` in `setUp`, open at `inMemoryDatabasePath`): round-trip scenarios (order preserved, `Scenario.fromJson` rebuild equals the input model field-for-field), meta round-trip, debrief round-trip + `readLatestForScenario` returns the newest.
  - [ ] `ScenariosBloc` tests (bloc_test + mocktail): (a) cache-hit then successful refresh → `[Loaded(fromCache:true), Loaded(fresh)]`; (b) cache-hit + network `ApiException` → `[Loaded(fromCache:true)]` only, **no** `ScenariosError`; (c) no cache + network failure → `[Loading, ScenariosError]` (existing behaviour preserved); (d) refresh writes through to the store. Use `registerFallbackValue` with a concrete event (sealed-class rule).
  - [ ] Widget test: report-icon tap → cached debrief renders the real `DebriefScreen`; cache-miss offline → empathetic state, no crash.
  - [ ] `flutter analyze` clean + full `flutter test` green.

## Dev Notes

### Architecture & patterns to follow (do NOT reinvent)
- **`bootstrap()` + thread-through DI** is the project's only DI mechanism — no service locator. Open the DB in `bootstrap()` (it's async, like the `preload()` caches) and pass the stores down. [Source: `client/CLAUDE.md` §"Architecture patterns"; `client/lib/main.dart` `bootstrap()`.]
- **Read-through cache lives behind the existing Bloc, not in the widgets.** `ScenariosBloc` already has the right two events (`LoadScenariosEvent` foreground, `RefreshScenariosEvent` silent) and the `ScenariosFetchResult` wrapper — extend them, don't replace. [Source: `client/lib/features/scenarios/bloc/`, `repositories/scenarios_fetch_result.dart`.]
- **Existing local-persistence pattern** is `flutter_secure_storage` wrappers with `preload()`/in-memory cache (`TokenStorage`, `ConsentStorage`, `EndCallRetryStorage`). sqflite is the right tool **only** because the data is list/relational and larger than single-key blobs — keep secrets (JWT) in secure storage, not sqflite. [Source: `client/lib/core/auth/token_storage.dart`, `core/services/end_call_retry_storage.dart`.]
- **Connectivity awareness already exists** — `ConnectivityService` exposes `onConnectivityLost` / `onConnectivityRegained` streams, wired in `bootstrap()`. Story 9.1 does **not** need to add connectivity plumbing: cache-first load is connectivity-agnostic (it just tries the network and tolerates failure). 9.2 will hook `onConnectivityRegained` to trigger background sync — leave that seam for 9.2. [Source: `client/lib/core/services/connectivity_service.dart`.]

### Exact data shapes (cache must round-trip these)
- **Scenario model** (`client/lib/features/scenarios/models/scenario.dart`): fields `id` (String), `title`, `isFree` (`is_free`), `riveCharacter` (`rive_character`), `languageFocus` (`language_focus` List<String>), `contentWarning` (`content_warning`, nullable), `bestScore` (`best_score`, nullable int), `attempts` (int, default 0), `tagline` (**derived client-side** from `kScenarioTaglines[id]`, NOT in JSON), `endPhrases` (`end_phrases`, Map), `briefing` (Map: vocabulary/context/expect). **There is NO `difficulty` field** (removed in Story 6.28 — difficulty is global-only). `fromJson` exists; **`toJson` does NOT** — so cache the **raw server JSON object** (`data[i]`), not a re-serialized model. [Source: model file; `project_difficulty_global_only`.]
- **Usage / meta** (`call_usage.dart` `CallUsage.fromMeta`): `meta` carries `tier`, `calls_remaining`, `calls_per_period`, `period`. Cache the raw `meta` map.
- **Debrief model** (`client/lib/features/debrief/models/debrief.dart`): `Debrief.tryParse(Map)` is fully defensive (4 strict hero scalars → null-on-fail; arrays default `[]`; v1/v2 back-compat). Cache the raw `data` map from `GET /debriefs/{call_id}`; the schema authority is `_bmad-output/planning-artifacts/debrief-content-strategy.md`. Do not re-model it.

### Cache-write choke points (where the data already flows)
- Scenarios: `ScenariosRepository.fetchScenarios()` → returns `ScenariosFetchResult` → write here (in the Bloc, after success).
- Debriefs: `CallEndedScreen` `_fetch...` calls `callRepository.fetchDebrief(callId:)` and holds `widget.scenario` — this is the single place a debrief is fetched in normal flow; write the cache here. The route is built at `call_screen.dart:959` (`CallEndedScreen.route(scenario: widget.scenario, callId: state.callId, ...)`). [Source: `call_ended_screen.dart`, `call_screen.dart`.]

### ⚠️ Gotchas (each one is a real trap)
- **Gotcha A — sqflite does NOT work in `flutter test` by default.** The default plugin uses Android/iOS platform channels → `MissingPluginException` in the VM test runner. Every DB-touching test MUST: add `sqflite_common_ffi` (dev dep), call `sqfliteFfiInit()` and set `databaseFactory = databaseFactoryFfi` in `setUp`, and open with `inMemoryDatabasePath`. This is the sqflite analogue of the existing `FlutterSecureStorage.setMockInitialValues({})` reflex. [Source: `client/CLAUDE.md` §1.]
- **Gotcha B — `path_provider` also uses platform channels.** `getApplicationDocumentsDirectory()` throws in tests. That's why `AppDatabase.open()` must accept an injectable factory + path — tests bypass `path_provider` entirely via ffi + in-memory.
- **Gotcha C — `BlocListener` dedup on same `const` state.** If you add `fromCache` to `ScenariosLoaded`, ensure the cache-emit and the fresh-emit are **not equal** instances or a listener may drop the fresh one. (`fromCache:true` vs default `false` already differentiates them.) [Source: `client/CLAUDE.md` §4.]
- **Gotcha D — `pumpAndSettle` hangs on the debrief screen's polling/spinner.** Use explicit `pump(Duration(...))` in widget tests. [Source: `client/CLAUDE.md` §3.]
- **Gotcha E — token-color lint.** No hex literals outside `lib/core/theme/`; reuse `AppColors` for any new offline-state UI. [Source: `client/CLAUDE.md` §6.]
- **Gotcha F — lints block CI** (`prefer_const_constructors`, sealed-class `const`, `verifyNever` not `verify(...).called(0)`). Run `flutter analyze` to zero before committing. [Source: `client/CLAUDE.md` §9.]

### Privacy note (not a blocker, flag for awareness)
Debrief content is derived from the user's spoken transcript (it quotes their language mistakes). Server-side, the transcript is deliberately **never persisted** (Story 7.1 D1). Caching debrief bodies in plaintext sqflite is standard for an app-private DB (covered by OS full-disk encryption on modern Android/iOS) — acceptable for MVP, but worth a one-line mention to Walid. If he wants it encrypted, `sqflite_sqlcipher` is the drop-in, but that's a deliberate scope-add, not assumed here.

### Manual on-device validation (Pixel 9 — this is a client story, no server gate)
This story has **no server/DB/deploy footprint**, so the server Smoke Test Gate is intentionally omitted. The behaviour that MUST be device-validated (airplane mode is the only honest test of offline render):
1. Online: open hub, complete a call to generate + cache a debrief, then re-open that scenario's debrief via the report icon (online) — renders.
2. **Airplane mode ON, kill + relaunch app:** hub renders from cache (last-known scenarios, progression, budget) — **not** the no-network error screen.
3. Airplane mode ON: tap the report icon on the just-completed scenario — its debrief renders from cache.
4. Airplane mode ON: tap the report icon on a scenario with no cached debrief — empathetic "no saved report" state, no crash/spinner.
5. Airplane mode OFF: hub silently refreshes; no flicker/jank, no duplicate fetch loop.

A ready-to-run device script will be handed to Walid at smoke-gate time per the project rule.

### Project Structure Notes
- New directory `client/lib/core/local_cache/` (`app_database.dart`, `scenario_cache_store.dart`, `debrief_cache_store.dart`) — matches the `core/` placement the architecture prescribes for the local DB (`core/api/`, `core/auth/`, `core/services/` siblings). [Source: `architecture.md` MVP Project Structure §`core/`.]
- No new feature directories — extends `features/scenarios` (bloc/state) and `features/debrief` (route wiring) only.
- Mirror tests under `client/test/core/local_cache/`, `client/test/features/scenarios/`, `client/test/features/debrief/`.

### References
- [Source: `_bmad-output/planning-artifacts/epics.md`#Story-9.1] — ACs (corrected for difficulty removal + embedded progression).
- [Source: `_bmad-output/planning-artifacts/architecture.md`#MVP-Project-Structure] — `sqflite` local DB choice, `core/` placement, "load from local cache first then refresh" local-first principle (lines 339, 71, 1009).
- [Source: `_bmad-output/planning-artifacts/debrief-content-strategy.md`] — `debrief_json` schema authority.
- [Source: `client/lib/features/scenarios/` + `core/api/api_client.dart`] — `/scenarios` envelope, `Scenario`/`CallUsage` models, `ScenariosBloc` events/states.
- [Source: `client/lib/features/debrief/models/debrief.dart` + `features/call/views/call_ended_screen.dart` + `api/routes_debriefs.py`] — `GET /debriefs/{call_id}` contract, `Debrief.tryParse`, the call-end fetch choke point.
- [Source: `client/CLAUDE.md`] — Flutter gotchas (sqflite tests, secure-storage mock, BlocListener dedup, lint traps).
- Latest dependency versions confirmed current on [pub.dev/packages/sqflite](https://pub.dev/packages/sqflite) — prefer `flutter pub add` to resolve the exact stable pin.

## Decisions Needing Walid's Confirmation

> These are genuine forks the dev agent should NOT silently resolve. Recommended answer is given first; confirm or override before the relevant task.

**Decision 1 — Store parse-ready JSON blobs, not normalized typed columns. (Recommended: YES)**
The epic prose lists columns `(id, title, difficulty, is_free, briefing_text, content_warning)`. That list is **stale**: per-scenario `difficulty` was removed (Story 6.28), `tagline` is derived client-side, and `briefing`/`end_phrases` are richer maps. Storing each scenario's **raw server JSON** keyed by `id` (+ `position`) round-trips through the existing `Scenario.fromJson` with zero field drift, auto-absorbs future server-added fields (content is server-driven by design), and keeps the app a "dumb renderer." Recommendation: store JSON blobs. Override only if you specifically want queryable typed columns (more code, brittle, no current consumer needs SQL filtering).

**Decision 2 — Fold `user_progress` into the cached scenario row; no separate progress table. (Recommended: YES)**
Progression (`best_score`, `attempts`) arrives **embedded** in the `/scenarios` response, not from a separate endpoint, and there is no device-local write path that would populate a standalone `user_progress` table independently. A separate table would duplicate data with nothing to keep it in sync. Recommendation: keep progression inside the cached scenario JSON. (Revisit if a future story writes progression locally before sync.)

**Decision 3 — Complete the report-icon → debrief route as part of 9.1. (Recommended: YES, but confirm the scope-add)**
The offline-debrief AC ("accessible by tapping the report icon") **cannot be met today** because `'/debrief/:scenarioId'` renders `DebriefPlaceholderScreen` (router.dart:188) — the real debrief is only ever shown post-call, by `call_id`. To deliver the AC, 9.1 must (a) cache each debrief keyed by `scenario_id`, and (b) replace that placeholder route with a cache-first real `DebriefScreen`. This is a small but real scope-add (it finishes a deferred Epic-7 wiring). **Open sub-question:** for a scenario with NO cached debrief but the user is **online**, there is no "latest debrief for a scenario" server endpoint — only `GET /debriefs/{call_id}`, and the client has no stored `scenario_id → call_id` map for past calls. Options: (i) cache-only (report icon shows the debrief only if it was cached when the call ended — simplest, recommended for MVP); (ii) add a server `GET /scenarios/{id}/latest-debrief` endpoint (defer to a server story / 9.2). Recommendation: **(i) cache-only for 9.1** — the report icon shows a saved report when one exists, else the empathetic state. Confirm before building Tasks 4–5. If Walid prefers to keep 9.1 strictly to the cache layer and split the route wiring into its own story, say so and AC #2/#6 move with it.

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
