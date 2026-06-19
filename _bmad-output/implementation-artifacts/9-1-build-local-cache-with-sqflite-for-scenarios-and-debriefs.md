# Story 9.1: Build Local Cache with sqflite for Scenarios and Debriefs

Status: review

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

✅ **All three scope decisions were CONFIRMED by Walid on 2026-06-19 — see "Decisions (CONFIRMED)" at the end of this file. They are LOCKED; do not re-litigate them.** Key confirmed point: the "tap the report icon → debrief" path is **currently a placeholder** (`router.dart:188` renders `DebriefPlaceholderScreen`); 9.1 **does** include wiring that route to the cache (**cache-only** resolution — no new server endpoint — see Decision 3). Proceed with the full story, debrief half included.

## Acceptance Criteria

> Source: `_bmad-output/planning-artifacts/epics.md` §"Story 9.1". The criteria below **correct two stale assumptions in the epic's prose** (per-scenario `difficulty` no longer exists — removed in Story 6.28; progression arrives embedded, not as a separate table). See Decisions 1 & 2.

1. **(FR32 — offline scenario list)** When the app fetches scenarios from `GET /scenarios`, the full scenario list **and** its `meta` usage block are written to the local sqflite cache. When the app is opened **offline**, the scenario list (hub) renders from the local cache with last-known data — including each scenario's last-known progression (`best_score`, `attempts`) and the last-known call-budget — instead of the network-error screen. On auth reset (a 401 or sign-out) the entire local cache is cleared, so no cached data leaks to a different user who signs in on the same device (see Task 6b).

2. **(FR33 — offline debriefs)** When a debrief is received from `GET /debriefs/{call_id}` (which today happens at the end of a call, in `CallEndedScreen`), it is stored locally in sqflite, keyed so it can be retrieved by the scenario it belongs to. All past debrief reports for which a debrief was cached are accessible **offline** by tapping the report icon on a scenario card. Because debriefs are cache-only (never re-fetched) and quote the user's own spoken transcript, the cache MUST be cleared on auth reset (Task 6b) so one user never sees another's debrief on a shared device.

3. **(Local-first render)** When the hub renders, it loads from the local cache **first** (instant render if a cache exists), then refreshes from `GET /scenarios` in the background **if** network is available. A successful refresh updates both the on-screen list and the cache. A failed refresh while a cache exists is **silent** — the user keeps seeing last-known data, never the error screen.

4. **(Cache schema mirrors the live data model)** The local sqflite database persists: (a) the scenario list as parse-ready records keyed by scenario `id`, preserving server order; (b) the `/scenarios` `meta`/usage block; (c) debriefs keyed by `call_id` with their owning `scenario_id`. The persisted shapes round-trip cleanly through the existing `Scenario.fromJson` / `CallUsage.fromMeta` / `Debrief.tryParse` parsers (see Decision 1 for why we store parse-ready JSON, not normalized typed columns).

5. **(No regressions)** Online behaviour is unchanged on the happy path: a fresh fetch still produces the identical hub and the identical post-call debrief. The `flutter analyze` gate stays clean and `flutter test` stays fully green, including every pre-existing test.

6. **(Graceful cache-miss)** Tapping the report icon for a scenario whose debrief was **not** cached (e.g. attempted before this story shipped, or completed on another device) shows an empathetic "no saved report / reconnect to load" state — never a crash, a raw error, or an infinite spinner. Per the confirmed cache-only resolution (Decision 3), this state is shown whether on- or offline; 9.1 does **not** attempt a server lookup to backfill a missing debrief.

## Tasks / Subtasks

- [x] **Task 1 — Add dependencies (AC: #1, #2, #4)**
  - [x] `cd client && flutter pub add sqflite path_provider` (resolves current stable — sqflite ^2.4.x / path_provider ^2.1.x as of 2026-06). Add **`sqflite_common_ffi`** to **dev_dependencies** (`flutter pub add --dev sqflite_common_ffi`) — required to run DB code under `flutter test` (see Gotcha A).
  - [x] Verify `flutter pub get` resolves with the existing SDK constraint (`sdk: ^3.11.0`).

- [x] **Task 2 — Build the local database layer (AC: #1, #2, #4)**
  - [x] Create `client/lib/core/local_cache/app_database.dart`: a single owner of the sqflite `Database` instance. `open()` resolves the DB path via `path_provider` (`getApplicationDocumentsDirectory()`), opens at `version: 1`, and creates tables in `onCreate`. **Make the factory + path injectable** (`open({DatabaseFactory? factory, String? path})`) so tests pass `databaseFactoryFfi` + `inMemoryDatabasePath` without touching platform channels (Gotcha A/B).
  - [x] Schema (version 1) — store parse-ready JSON, not normalized columns (Decision 1):
    - `cached_scenarios(id TEXT PRIMARY KEY, position INTEGER NOT NULL, json TEXT NOT NULL, updated_at INTEGER NOT NULL)`
    - `cache_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` — holds the `/scenarios` `meta` JSON (key `scenarios_usage`) and the last-sync timestamp (key `scenarios_synced_at`).
    - `cached_debriefs(call_id INTEGER PRIMARY KEY, scenario_id TEXT NOT NULL, debrief_json TEXT NOT NULL, created_at INTEGER NOT NULL)` + `CREATE INDEX idx_debriefs_scenario ON cached_debriefs(scenario_id)`.
  - [x] Add `Future<void> clearAll()` — deletes every row from all three tables in one transaction (used by Task 6b on auth reset). Leave an explicit `onUpgrade` switch (empty for v1) so 9.2 / future stories can add migrations without reopening this file blind.

- [x] **Task 3 — Scenario cache store + cache-first Bloc load (AC: #1, #3, #5)**
  - [x] **Thread the raw JSON to the write path (REQUIRED — read this first).** `Scenario` has `fromJson` but **NO `toJson`**, `CallUsage` has `fromMeta` but **NO `toMeta`**, and `tagline` is derived client-side from `kScenarioTaglines[id]` (absent from the server JSON). So the cache CANNOT reconstruct the raw maps from the parsed models — **never re-serialize a `Scenario`/`CallUsage` by hand** (lossy; drops `tagline` and any future server field; defeats Decision 1). **Extend the EXISTING `ScenariosFetchResult`** (`repositories/scenarios_fetch_result.dart`) — this is extending the wrapper, NOT inventing a new DTO — to also carry the raw maps: add `final List<Map<String, dynamic>> rawScenarios;` (the raw `data` list, server order preserved) and `final Map<String, dynamic> rawMeta;` (the raw `meta` map). Populate them in `ScenariosRepository.fetchScenarios()` (`scenarios_repository.dart:14-21`, which today parses `data`/`meta` and **discards** the raw maps) and update its const constructor + any call sites/tests.
  - [x] Create `client/lib/core/local_cache/scenario_cache_store.dart` wrapping `AppDatabase`:
    - `Future<ScenariosFetchResult?> readScenarios()` — returns null on an **empty cache OR any parse/format failure** of the cached rows/meta. It MUST wrap the row-by-row `Scenario.fromJson` rebuild and the `CallUsage.fromMeta` call in a try/catch: if any cached row or the `meta` blob throws (e.g. a `TypeError` from an unchecked cast, or the `FormatException` from `CallUsage.fromMeta`'s `calls_per_period <= 0` guard — both real after a schema change between app versions or a partially-written row), treat it as a **cache-miss** and return `null` so the Bloc falls through to the network path. Never let a corrupt cached row crash the cache-first render. Reads rows ordered by `position`; rebuilds via `Scenario.fromJson(json)` per row + `CallUsage.fromMeta(rawMeta)`; also carry the same raw maps back so the returned `ScenariosFetchResult` stays self-consistent.
    - `Future<void> writeScenarios(ScenariosFetchResult result)` — transactional: clear `cached_scenarios` then reinsert each `result.rawScenarios[i]` as the `json` column (keyed by `result.scenarios[i].id`, `position = i`), and upsert `result.rawMeta` into `cache_meta` (key `scenarios_usage`). Write the RAW maps — never a re-serialized model.
  - [x] Modify `client/lib/features/scenarios/bloc/scenarios_bloc.dart` to take the `ScenarioCacheStore` as an **OPTIONAL named constructor param**: `ScenariosBloc(this._repository, {ScenarioCacheStore? cacheStore})`. Make the cache path **null-tolerant** — when `cacheStore == null`, skip every cache read/write and fall back to today's network-only behaviour (this is what keeps the existing `scenarios_bloc_test.dart` `buildBloc()` and the router fallback compiling/green; mirrors the optional-with-test-default pattern already used for `difficultyStorage`/`purchaseSyncService`). On `LoadScenariosEvent`: read cache → if non-null, emit `ScenariosLoaded(fromCache: true)` immediately; else emit `ScenariosLoading`. Then attempt the network fetch → on success, `writeScenarios()` + emit fresh `ScenariosLoaded`; on `ApiException` → **if a cache was already shown, stay silent (no error emit)**; **if no cache, emit `ScenariosError`** preserving the existing error-classification + `retryCount` logic (the existing `catch (_) → MALFORMED_RESPONSE` guard at `scenarios_bloc.dart:43-54` must remain — it stops the UI hanging in `ScenariosLoading`).
  - [x] On `RefreshScenariosEvent` (the silent post-call refresh, Story 8.2): on success, `writeScenarios()` + emit; on failure stay silent (unchanged). This keeps the cache progression-fresh after every call.
  - [x] Add an optional `bool fromCache` (default `false`) to `ScenariosLoaded` in `scenarios_state.dart` — used only so the UI *could* show a subtle "saved data" affordance; do not break existing equality/tests. (Surfacing an offline badge in the UI is optional polish — confirm with Walid before adding visible chrome.)

- [x] **Task 4 — Debrief cache store + capture at fetch (AC: #2, #6)** — *Decision 3 CONFIRMED (cache-only), proceed*
  - [x] Create `client/lib/core/local_cache/debrief_cache_store.dart`: `Future<void> write({required int callId, required String scenarioId, required Map<String,dynamic> payload})`; **`Future<({int callId, Map<String,dynamic> payload})?> readLatestForScenario(String scenarioId)`** (most recent by `created_at`, returning BOTH the row's `call_id` and its `debrief_json` — Task 5 needs the call_id); `Future<Map<String,dynamic>?> readByCallId(int callId)`.
  - [x] Write-on-fetch: in `client/lib/features/call/views/call_ended_screen.dart`, after `widget.callRepository.fetchDebrief(callId:)` succeeds, persist the payload via the injected store keyed by `widget.scenario.id` + `callId`. The scenario + callId are both already in scope here (`CallEndedScreen.route(scenario:..., callId:...)`). Thread the store through `CallEndedScreen.route(...)` (and from `call_screen.dart:959` where the route is built) — fire-and-forget, never block the transition, never throw into the UI. **This is the ONLY debrief write in 9.1.**
  - [x] **Do NOT cache from inside `DebriefScreen`'s own polling path** (`_attemptFetch`/`_settle`, `debrief_screen.dart:299-328`): that screen's constructor takes only `payload`/`callId`/`callRepository` — it has **no `scenario_id` in scope**, and `cached_debriefs.scenario_id` is `NOT NULL`, so a write from there is impossible without an out-of-scope constructor change. It is also redundant: `CallEndedScreen` (bullet above) already polls + fetches the late-arriving debrief at the same choke point with `widget.scenario` in scope, and the Task 5 route constructs `DebriefScreen` with a non-null `payload` so its internal poll never fires. Do not add a `scenarioId` param to `DebriefScreen`.

- [x] **Task 5 — Wire the report-icon route to the cache (AC: #2, #6)** — *Decision 3 CONFIRMED (cache-only), proceed*
  - [x] Replace the `'${AppRoutes.debrief}/:scenarioId'` placeholder in `client/lib/app/router.dart:184-192`: resolve the cached debrief for `scenarioId` via `DebriefCacheStore.readLatestForScenario(scenarioId)`. If non-null, render the **real** `DebriefScreen(payload: result.payload, callId: result.callId, callRepository: CallRepository(ApiClient()), presentPaywallOnLoad: false)`.
    - `callRepository` is a **required** constructor arg but is **unused on this cache-hit path** — a non-null `payload` makes `DebriefScreen.initState` render immediately and never poll (`debrief_screen.dart:259-264`). Construct `CallRepository(ApiClient())` **inline** exactly as the incoming-call route already does (`router.dart:176`; both classes are already imported). Do NOT add a new `CallRepository` field/DI thread to `createRouter`/`App` — only the two cache stores need threading (Task 6).
  - [x] **Cache-miss state (Decision 3 = no server backfill).** If `readLatestForScenario` returns null, render the empathetic "no saved report — reconnect to load" state whether on- or offline. Reuse `EmpatheticErrorScreen` exactly as `NoNetworkScreen` does (`no_network_screen.dart:30-42`): wrap it in `Scaffold(backgroundColor: AppColors.background, body: EmpatheticErrorScreen(...))`. The code table has **no** "no saved report" code, so deliver the copy via `titleOverride:` + `bodyOverride:` (pass any `code`, e.g. `'UNKNOWN_ERROR'`, just for the icon). The `onRetry` CTA is **required** but must NOT re-fetch (there is no backfill) — wire it to go back, mirroring the placeholder's existing idiom: `onRetry: () => context.canPop() ? context.pop() : context.go(AppRoutes.root)`, with `retryLabel: 'Back'`. Keep the title/body strings within the copy lint (no exclamation/praise/emoji — Gotcha E) and surface them to Walid for sign-off.
  - [x] Keep `DebriefScreen` back-compat: it already renders v1 & v2 payloads defensively (`Debrief.tryParse`). Do not alter its parsing contract.

- [x] **Task 6 — DI wiring in bootstrap (AC: #1, #2, #5)**
  - [x] In `client/lib/main.dart` `bootstrap()`: `await AppDatabase.open()` once (parallel with the existing `preload()` calls), construct the `ScenarioCacheStore` + `DebriefCacheStore`, and thread them into `App(...)` → `AppRouter.createRouter(...)`, following the established "open in bootstrap, pass via constructor" pattern (same shape as `ConnectivityService` / `EndCallRetryService`). Do **not** introduce `get_it` — the app uses constructor injection + `context.read()` only.
  - [x] **CRITICAL — `ScenariosBloc` has TWO construction sites; the PRODUCTION one is the router's inline fallback, not bootstrap.** `bootstrap()` does NOT build/pass a `ScenariosBloc`, so `App.scenariosBloc` is `null` in prod and the root route runs the **inline** `ScenariosBloc(ScenariosRepository(ApiClient()))..add(const LoadScenariosEvent())` at `client/lib/app/router.dart:118-121` (the `.value` branch at 112-117 is test-only). You MUST inject the `ScenarioCacheStore` into **that inline constructor too**: add a required `ScenarioCacheStore` param to `AppRouter.createRouter(...)`, pass it `App` → `createRouter`, and feed it into BOTH the inline `ScenariosBloc(ScenariosRepository(ApiClient()), cacheStore: store)` at line 120 AND any injected `.value` bloc. If you only wire the bootstrap/`.value` path, the production inline bloc gets no cache store and the entire offline feature silently no-ops while all injected-bloc tests stay green.
  - [x] Update `client/lib/app/app.dart` to accept + forward the stores (optional params with test defaults, mirroring how `endCallRetryService` / `purchaseSyncService` are threaded), and pass the `DebriefCacheStore` to the debrief route (Task 5) and the call route (Task 4 write).

- [x] **Task 6b — Clear the cache on auth reset / logout (AC: #1, #2 — privacy)**
  - [x] The ONLY auth-reset path is `AuthInterceptor.globalHandler` (`client/lib/app/app.dart`, ~lines 134-178): it calls `_tokenStorage.deleteToken()` and dispatches `ResetAuthEvent` — nothing clears app data today. Inside that handler, also call `await <appDatabase>.clearAll();` (best-effort, wrapped in try/catch like the token delete — the bloc reset stays the load-bearing step). Thread the `AppDatabase` (or a `clear()` on each store) into `App` so the handler can reach it.
  - [x] **Why this is mandatory, not polish:** the sqflite DB lives at `getApplicationDocumentsDirectory()` (app-wide, not per-user) and auth is email/code, so after a 401 reset a DIFFERENT user can sign in on the same device. Without the clear, the new user sees the previous user's cached progression + call-budget until a network refresh, and — because debriefs are cache-only (Decision 3, never refreshed) and keyed by `scenario_id` — sees the previous user's **debrief**, which quotes their spoken transcript/mistakes, **indefinitely**.
  - [x] Test: a store/bloc test asserting the cache is empty after `clearAll()` (no scenario rows, no meta, no debriefs).

- [x] **Task 7 — Tests (AC: #1–#6)**
  - [x] Store unit tests using `sqflite_common_ffi` (`sqfliteFfiInit(); databaseFactory = databaseFactoryFfi;` in `setUp`, open at `inMemoryDatabasePath`):
    - Scenario round-trip (order preserved). **Do NOT use `expect(rebuilt, original)`** — `Scenario` has no `==`/Equatable (identity equality only; documented at `scenario_list_screen.dart:135-136`), and Dart Maps/Lists have no value `==` either. Assert scalar fields directly (`id`, `title`, `isFree`, `riveCharacter`, `contentWarning`, `bestScore`, `attempts`, `tagline`) and collection fields (`languageFocus`, `endPhrases`, `briefing`) with `listEquals`/`mapEquals` (or `DeepCollectionEquality().equals`).
    - Meta round-trip; debrief round-trip + `readLatestForScenario` returns the newest (and its call_id).
    - **Corrupt-row case:** insert a row whose `json`/`meta` fails to parse, assert `readScenarios()` returns `null` (does NOT throw).
    - `clearAll()` empties all three tables.
  - [x] `ScenariosBloc` tests (bloc_test + mocktail): (a) cache-hit then successful refresh → `[Loaded(fromCache:true), Loaded(fresh)]`; (b) cache-hit + network `ApiException` → `[Loaded(fromCache:true)]` only, **no** `ScenariosError`; (c) no cache + network failure → `[Loading, ScenariosError]` (existing behaviour preserved); (d) refresh writes through to the store. Use `registerFallbackValue` with a concrete event (sealed-class rule).
    - **Retrofit the existing suite:** Task 3 adds the `cacheStore` param, so the existing `buildBloc()` helper (`scenarios_bloc_test.dart:67`) and every pre-existing test MUST inject a **mocked** `ScenarioCacheStore` whose `readScenarios()` is stubbed to return `null` (empty cache). With a null/empty cache the bloc must emit `ScenariosLoading` first (not `Loaded(fromCache:true)`), so all existing `[Loading, ...]` and Refresh expectations stay valid. **Never inject a real `ScenarioCacheStore`/`AppDatabase` into bloc tests** — that hits sqflite → `MissingPluginException` (Gotcha A).
  - [x] Widget test: report-icon tap → cached debrief renders the real `DebriefScreen`; cache-miss → empathetic state, no crash.
  - [x] `flutter analyze` clean + full `flutter test` green.

## Dev Notes

### Architecture & patterns to follow (do NOT reinvent)
- **`bootstrap()` + thread-through DI** is the project's only DI mechanism — no service locator. Open the DB in `bootstrap()` (it's async, like the `preload()` caches) and pass the stores down. [Source: `client/CLAUDE.md` §"Architecture patterns"; `client/lib/main.dart` `bootstrap()`.]
- **Read-through cache lives behind the existing Bloc, not in the widgets.** `ScenariosBloc` already has the right two events (`LoadScenariosEvent` foreground, `RefreshScenariosEvent` silent) and the `ScenariosFetchResult` wrapper. **Extend** the wrapper (add `rawScenarios`/`rawMeta` — Task 3) rather than replace it; `ScenariosRepository.fetchScenarios()` currently parses then **discards** the raw `data`/`meta`, so it must be changed to retain them (the parsed models have no `toJson`/`toMeta`). [Source: `client/lib/features/scenarios/bloc/`, `repositories/scenarios_fetch_result.dart`, `repositories/scenarios_repository.dart`.]
- **Existing local-persistence pattern** is `flutter_secure_storage` wrappers with `preload()`/in-memory cache (`TokenStorage`, `ConsentStorage`, `EndCallRetryStorage`). sqflite is the right tool **only** because the data is list/relational and larger than single-key blobs — keep secrets (JWT) in secure storage, not sqflite. [Source: `client/lib/core/auth/token_storage.dart`, `core/services/end_call_retry_storage.dart`.]
- **Connectivity awareness already exists** — `ConnectivityService` exposes `onConnectivityLost` / `onConnectivityRegained` streams, wired in `bootstrap()`. Story 9.1 does **not** need to add connectivity plumbing: cache-first load is connectivity-agnostic (it just tries the network and tolerates failure). 9.2 will hook `onConnectivityRegained` to trigger background sync — leave that seam for 9.2. [Source: `client/lib/core/services/connectivity_service.dart`.]

### Exact data shapes (cache must round-trip these)
- **Scenario model** (`client/lib/features/scenarios/models/scenario.dart`): fields `id` (String), `title`, `isFree` (`is_free`), `riveCharacter` (`rive_character`), `languageFocus` (`language_focus` List<String>), `contentWarning` (`content_warning`, nullable), `bestScore` (`best_score`, nullable int), `attempts` (int, default 0), `tagline` (**derived client-side** from `kScenarioTaglines[id]`, NOT in JSON), `endPhrases` (`end_phrases`, Map), `briefing` (Map: vocabulary/context/expect). **There is NO `difficulty` field** (removed in Story 6.28 — difficulty is global-only). `fromJson` exists; **`toJson` does NOT**, and there is no `==`/Equatable (identity equality only). So cache the **raw server JSON object** (`data[i]`), not a re-serialized model. [Source: model file; `project_difficulty_global_only`.]
- **Usage / meta** (`call_usage.dart` `CallUsage.fromMeta`): `meta` carries `tier`, `calls_remaining`, `calls_per_period`, `period`. `fromMeta` throws `FormatException` if `calls_per_period <= 0` and does unchecked casts (so a stale cached meta from an older app build can throw — handle as cache-miss, Task 3). No `toMeta`/`toJson` — cache the raw `meta` map.
- **Debrief model** (`client/lib/features/debrief/models/debrief.dart`): `Debrief.tryParse(Map)` is fully defensive (4 strict hero scalars → null-on-fail; arrays default `[]`; v1/v2 back-compat). Cache the raw `data` map from `GET /debriefs/{call_id}`; the schema authority is `_bmad-output/planning-artifacts/debrief-content-strategy.md`. Do not re-model it.

### Cache-write choke points (where the data already flows)
- Scenarios: `ScenariosRepository.fetchScenarios()` now also carries `rawScenarios`/`rawMeta` on the extended `ScenariosFetchResult` (Task 3) → write THOSE (the raw JSON) here, in the Bloc, after success — never a re-serialized model.
- Debriefs: `CallEndedScreen` `_fetch...` calls `callRepository.fetchDebrief(callId:)` and holds `widget.scenario` — this is the single place a debrief is fetched/written in 9.1. The route is built at `call_screen.dart:959` (`CallEndedScreen.route(scenario: widget.scenario, callId: state.callId, ...)`). [Source: `call_ended_screen.dart`, `call_screen.dart`.]

### ⚠️ Gotchas (each one is a real trap)
- **Gotcha A — sqflite does NOT work in `flutter test` by default.** The default plugin uses Android/iOS platform channels → `MissingPluginException` in the VM test runner. Every DB-touching test MUST: add `sqflite_common_ffi` (dev dep), call `sqfliteFfiInit()` and set `databaseFactory = databaseFactoryFfi` in `setUp`, and open with `inMemoryDatabasePath`. This is the direct analogue of the `FlutterSecureStorage.setMockInitialValues({})` test reflex in `client/CLAUDE.md` §1 (that section is about secure-storage, not sqflite — there is no sqflite section yet; follow the ffi pattern here).
- **Gotcha B — `path_provider` also uses platform channels.** `getApplicationDocumentsDirectory()` throws in tests. That's why `AppDatabase.open()` must accept an injectable factory + path — tests bypass `path_provider` entirely via ffi + in-memory.
- **Gotcha C — `BlocListener` dedup on same `const` state.** If you add `fromCache` to `ScenariosLoaded`, ensure the cache-emit and the fresh-emit are **not equal** instances or a listener may drop the fresh one. (`fromCache:true` vs default `false` already differentiates them; note `ScenariosLoaded` has no Equatable, so emissions differ by identity anyway.) [Source: `client/CLAUDE.md` §4.]
- **Gotcha D — `pumpAndSettle` hangs on the debrief screen's polling/spinner.** Use explicit `pump(Duration(...))` in widget tests. [Source: `client/CLAUDE.md` §3.]
- **Gotcha E — token-color lint.** No hex literals outside `lib/core/theme/`; reuse `AppColors` for any new offline-state UI. [Source: `client/CLAUDE.md` §6.]
- **Gotcha F — lints block CI** (`prefer_const_constructors`, sealed-class `const`, `verifyNever` not `verify(...).called(0)`). Run `flutter analyze` to zero before committing. [Source: `client/CLAUDE.md` §9.]

### Privacy note
Debrief content is derived from the user's spoken transcript (it quotes their language mistakes). Server-side, the transcript is deliberately **never persisted** (Story 7.1 D1). Caching debrief bodies in plaintext sqflite is standard for an app-private DB (covered by OS full-disk encryption on modern Android/iOS) — acceptable for MVP. The cross-user concern (a second account on the same device) is handled by **Task 6b** (clear cache on auth reset). If Walid later wants at-rest encryption, `sqflite_sqlcipher` is the drop-in — a deliberate future scope-add, not assumed here.

### Manual on-device validation (Pixel 9 — this is a client story, no server gate)
This story has **no server/DB/deploy footprint**, so the server Smoke Test Gate is intentionally omitted. The behaviour that MUST be device-validated (airplane mode is the only honest test of offline render):
1. Online: open hub, complete a call to generate + cache a debrief, then re-open that scenario's debrief via the report icon (online) — renders.
2. **Airplane mode ON, kill + relaunch app:** hub renders from cache (last-known scenarios, progression, budget) — **not** the no-network error screen.
3. Airplane mode ON: tap the report icon on the just-completed scenario — its debrief renders from cache.
4. Airplane mode ON: tap the report icon on a scenario with no cached debrief — empathetic "no saved report" state, no crash/spinner.
5. Airplane mode OFF: hub silently refreshes; no flicker/jank, no duplicate fetch loop.
6. Sign out (or trigger a 401), sign in as a different account: the previous account's scenarios/progression/debriefs are GONE (cache cleared — Task 6b).

A ready-to-run device script will be handed to Walid at smoke-gate time per the project rule.

### Project Structure Notes
- New directory `client/lib/core/local_cache/` (`app_database.dart`, `scenario_cache_store.dart`, `debrief_cache_store.dart`) — matches the `core/` placement the architecture prescribes for the local DB (`core/api/`, `core/auth/`, `core/services/` siblings). [Source: `architecture.md` MVP Project Structure §`core/`.]
- No new feature directories — extends `features/scenarios` (bloc/state/repository) and `features/debrief` (route wiring) only.
- Mirror tests under `client/test/core/local_cache/`, `client/test/features/scenarios/`, `client/test/features/debrief/`.

### References
- [Source: `_bmad-output/planning-artifacts/epics.md`#Story-9.1] — ACs (corrected for difficulty removal + embedded progression).
- [Source: `_bmad-output/planning-artifacts/architecture.md`#MVP-Project-Structure] — `sqflite` local DB choice, `core/` placement, "load from local cache first then refresh" local-first principle (lines 339, 71, 1009).
- [Source: `_bmad-output/planning-artifacts/debrief-content-strategy.md`] — `debrief_json` schema authority.
- [Source: `client/lib/features/scenarios/` + `core/api/api_client.dart`] — `/scenarios` envelope, `Scenario`/`CallUsage` models, `ScenariosFetchResult`, `ScenariosRepository`, `ScenariosBloc` events/states.
- [Source: `client/lib/features/debrief/models/debrief.dart` + `features/call/views/call_ended_screen.dart` + `features/call/views/no_network_screen.dart` + `features/scenarios/views/widgets/empathetic_error_screen.dart` + `api/routes_debriefs.py`] — `GET /debriefs/{call_id}` contract, `Debrief.tryParse`, the call-end fetch choke point, the empathetic-error pattern.
- [Source: `client/lib/app/app.dart` (AuthInterceptor.globalHandler) + `features/auth/bloc/auth_bloc.dart`] — the 401/reset path Task 6b hooks into.
- [Source: `client/CLAUDE.md`] — Flutter gotchas (sqflite tests, secure-storage mock, BlocListener dedup, lint traps).
- Latest dependency versions confirmed current on [pub.dev/packages/sqflite](https://pub.dev/packages/sqflite) — prefer `flutter pub add` to resolve the exact stable pin.

## Decisions (CONFIRMED — Walid 2026-06-19)

> All three are LOCKED. The dev agent must implement them as stated and must NOT re-open or "optimize" them.

**Decision 1 — Store parse-ready JSON blobs, not normalized typed columns. → CONFIRMED.**
Store each scenario's **raw server JSON** (the `data[i]` object) keyed by `id` (+ `position` for order), the `meta` block as JSON in `cache_meta`, and each debrief's raw `data` map. The epic prose's column list `(id, title, difficulty, is_free, briefing_text, content_warning)` is **stale and must NOT be used**: per-scenario `difficulty` was removed (Story 6.28), `tagline` is derived client-side, and `briefing`/`end_phrases` are richer maps. JSON blobs round-trip through the existing `Scenario.fromJson` / `CallUsage.fromMeta` / `Debrief.tryParse` with zero field drift and auto-absorb future server-added fields (content is server-driven by design). Do **not** create queryable typed columns. **Implementation consequence (see Task 3):** because `Scenario`/`CallUsage` have no `toJson`/`toMeta`, the raw maps must be threaded from `ScenariosRepository.fetchScenarios()` to the cache via an extended `ScenariosFetchResult` — never re-serialized from the parsed models.

**Decision 2 — Fold progression into the cached scenario row; no separate `user_progress` table. → CONFIRMED.**
Progression (`best_score`, `attempts`) arrives **embedded** in the `/scenarios` response, not a separate endpoint, and nothing writes progression locally before sync. The cached scenario JSON already carries it. Do **not** create a separate `user_progress` table.

**Decision 3 — Complete the report-icon → debrief route in 9.1, cache-only resolution. → CONFIRMED (scope-add accepted).**
The offline-debrief AC cannot be met today because `'/debrief/:scenarioId'` renders `DebriefPlaceholderScreen` (router.dart:188); the real debrief is only ever shown post-call, by `call_id`. 9.1 **does** (a) cache each debrief at the call-end fetch keyed by `scenario_id` + `call_id` (Task 4), and (b) replace that placeholder route with a real cache-backed `DebriefScreen` (Task 5). **Cache-only resolution is confirmed:** a report is viewable from the report icon ONLY if it was cached at call-end. On cache-miss (on- or offline) → empathetic "no saved report" state. **Out of scope for 9.1:** any new server endpoint (e.g. `GET /scenarios/{id}/latest-debrief`) and any `scenario_id → call_id` backfill fetch. (A server-backed "fetch any past debrief by scenario" could be a future story if ever wanted — not now.)

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Code `/bmad-dev-story`, 2026-06-19)

### Debug Log References

- `flutter analyze` → **No issues found!**
- `flutter test` (full suite) → **All 661 tests passed** (+22 net new: 2 app_database, 7 scenario_cache_store, 5 debrief_cache_store, 3 cached_debrief_screen, 5 bloc cache-first).
- `flutter pub add` resolved `sqflite ^2.4.2+1` + `path_provider ^2.1.6` (direct) + `sqflite_common_ffi ^2.4.0+3` (dev) under the existing `sdk: ^3.11.0`.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Spec hardened by an adversarial multi-agent review (4 lenses + per-finding verification against the live codebase) before hand-off: raw-JSON threading via extended `ScenariosFetchResult`, cache-clear on auth reset (Task 6b), optional/null-tolerant Bloc cache param, `readLatestForScenario` returning the call_id, parse-failure tolerance, the two `ScenariosBloc` construction sites, and the `EmpatheticErrorScreen` reuse contract.
- **Implemented all 8 tasks (1–7 + 6b).** Read-through cache lives behind `ScenariosBloc` (cache-first emit → silent network refresh → write-through); debrief cached once at the call-end fetch (`CallEndedScreen`, fire-and-forget) and resolved on the report-icon route by a new `CachedDebriefScreen`. Auth-reset wipe (`AuthInterceptor.globalHandler`) clears the whole DB.
- **Deviation 1 — cache-store params on `createRouter` are NULLABLE, not "required" as Task 6 worded it.** `app.dart` cannot synchronously default a DB-backed store (`AppDatabase.open()` is async) and the many App-constructing widget tests pass none; a required param would force every one to stand up sqflite → `MissingPluginException` (Gotcha A). Threaded as `ScenarioCacheStore?` / `DebriefCacheStore?` instead; the bloc + the debrief route are both null-tolerant. The CRITICAL intent — feed the **PRODUCTION inline** `ScenariosBloc` at `router.dart`, not just the test-only `.value` path — is fully honored (the inline `ScenariosBloc(ScenariosRepository(ApiClient()), cacheStore: scenarioCacheStore)` gets the store).
- **Deviation 2 — write-on-fetch stores keyed by `raw['id']`, equivalent to `result.scenarios[i].id`.** `Scenario.fromJson` reads `json['id']`, so the two are identical; reading the id straight from the raw map is self-contained and removes any index-zip risk.
- **Deviation 3 — deleted the now-dead `debrief_placeholder_screen.dart`.** Decision 3 replaces its route with the real cache-backed screen; nothing else imported it (verified), so the file is dead code and was removed rather than left orphaned.
- **`fromCache` flag added to `ScenariosLoaded` (Task 3 last bullet).** Differentiates the cache emit from the fresh emit by value (Gotcha C) so a listener never dedups the refresh. **No visible UI affordance was added** — the story says surfacing an offline badge is optional polish to confirm with Walid first. Open question for Walid: do you want a subtle "saved data" indicator on the hub when `fromCache: true`, or leave it invisible?
- **Cache-miss copy needs Walid sign-off (Task 5).** The "no saved report" state shows title `"No saved report yet."` + body `"Reports are saved on your device after you finish a call online. Reconnect and complete this scenario to see its report here."` (within the Handler's-Brief copy lint — no exclamation/praise/emoji). CTA = `Back` (no re-fetch, cache-only).
- **`bootstrap()` opens the DB fail-soft** (mirrors the `RiveNative.init()` pattern): on an open failure the app runs network-only rather than crashing on boot.
- **No server/DB/deploy footprint** — client-only story, server Smoke Test Gate intentionally omitted. The on-device validation (airplane-mode offline render + cross-user cache wipe) is the Pixel 9 gate, script to be handed to Walid at smoke-gate time.

### File List

**New (lib):**
- `client/lib/core/local_cache/app_database.dart`
- `client/lib/core/local_cache/scenario_cache_store.dart`
- `client/lib/core/local_cache/debrief_cache_store.dart`
- `client/lib/features/debrief/views/cached_debrief_screen.dart`

**Modified (lib):**
- `client/pubspec.yaml` (+ `sqflite`, `path_provider`; dev `sqflite_common_ffi`)
- `client/lib/features/scenarios/repositories/scenarios_fetch_result.dart` (+ `rawScenarios`/`rawMeta`)
- `client/lib/features/scenarios/repositories/scenarios_repository.dart` (retain raw maps)
- `client/lib/features/scenarios/bloc/scenarios_bloc.dart` (cache-first load + write-through, null-tolerant `cacheStore`)
- `client/lib/features/scenarios/bloc/scenarios_state.dart` (`ScenariosLoaded.fromCache`)
- `client/lib/features/scenarios/views/scenario_list_screen.dart` (thread `debriefCacheStore` → `CallScreen`)
- `client/lib/features/call/views/call_ended_screen.dart` (cache-write on debrief fetch)
- `client/lib/features/call/views/call_screen.dart` (forward `debriefCacheStore` to the overlay route)
- `client/lib/app/router.dart` (cache-store params; cache-backed debrief route; feed inline bloc)
- `client/lib/app/app.dart` (accept/forward stores; clear cache on auth reset — Task 6b)
- `client/lib/main.dart` (open `AppDatabase` in `bootstrap()`, construct stores, pass to `App`)

**Deleted (lib):**
- `client/lib/features/debrief/views/debrief_placeholder_screen.dart` (dead after Decision 3)

**New (test):**
- `client/test/core/local_cache/app_database_test.dart`
- `client/test/core/local_cache/scenario_cache_store_test.dart`
- `client/test/core/local_cache/debrief_cache_store_test.dart`
- `client/test/features/debrief/views/cached_debrief_screen_test.dart`

**Modified (test):**
- `client/test/features/scenarios/bloc/scenarios_bloc_test.dart` (mocked `ScenarioCacheStore` retrofit + cache-first group)
- `client/test/features/scenarios/repositories/scenarios_repository_test.dart` (raw-map assertions)

## Change Log

| Date | Change |
| --- | --- |
| 2026-06-19 | Story 9.1 dev-story complete — offline sqflite cache for scenarios + debriefs (cache-first hub load, silent refresh + write-through, cache-only report-icon route, auth-reset wipe). 4 new lib files + 11 modified + 1 deleted; 6 test files (4 new). `flutter analyze` clean, `flutter test` 661 green (+22). Status `in-progress → review`. |
