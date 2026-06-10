# Story 7.2: Build Call Ended Overlay Transition

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to see a dramatic "Call Ended" screen for a few seconds after the call before the debrief appears,
so that the emotional weight of what just happened settles before I receive detailed feedback.

This is a **client + small-server** story. The Flutter app builds the post-call **Call Ended overlay** (identity, duration, %, theatrical phrase, 3–10 s latency-masking hold, auto-fade to debrief). The server gains ONE new per-scenario field — `end_phrases` (the theatrical phrases) — delivered in the scenario payload the app **already downloads**, because **all user-facing content lives on the server, never hardcoded in the app** (Walid 2026-06-09 — see Decision A). Story 7.1 (debrief backend) is **live**; Story 7.3 (the real debrief screen) ships later and replaces the current `DebriefPlaceholderScreen`.

---

## ⚠️ Source-Document Drift — READ FIRST

The design doc [`call-ended-screen-design.md`](../planning-artifacts/call-ended-screen-design.md) (2026-04-01) predates Epic 6 and Story 7.1. Its layout/typography/variant/timing/a11y specs are authoritative — **follow them**. But three *data-flow* assumptions are stale; use THIS:

| Stale source statement | Current truth (use THIS) | Evidence |
|---|---|---|
| "The theatrical phrase comes from the server as part of the `call_end` payload" | No phrase exists server-side yet (scenarios carry only **spoken** `exit_lines`). → **ADD a per-scenario `end_phrases` field** (server), delivered in the **scenario list payload** the app already loads. Per the project rule that **all content is server-side** ([[content-must-be-server-side]]), it is NOT hardcoded in the app. | [server/pipeline/scenarios/the-waiter.yaml:191] (`exit_lines` only); [server/models/schemas.py:141 `ScenarioListItem`] |
| "The percentage is the `survival_pct` field from the `call_end` payload — same value as the debrief" | The live envelope's `survival_pct` uses a DIFFERENT formula (patience-meter ratio for hung-up) AND is absent on `user_hung_up`. → **Compute `floor(checkpoints_passed/total*100)` client-side** from the checkpoint snapshot — matches the 7.3 debrief formula. | [server/pipeline/patience_tracker.py:1327-1333] vs [server/pipeline/debrief_assembly.py `compute_survival_pct`] |
| Variant reasons are `{character_hung_up, user_hung_up, survived, network_lost}` | The live reason set is **6**: adds `inappropriate_content` (→ failure variant) and `noisy_environment` (→ stays on the existing notice screen, NOT the overlay). `network_lost`/`noisy_environment`/gifted-short-calls keep `CallEndedNoticeScreen`. | [server/models/schemas.py `EndCallIn`]; [client .../call_screen.dart:734-743] |

**Net:** the overlay's three values — **%** (client-computed from checkpoints), **duration** (`EndCallResult.durationSec`, already captured), **phrase** (server `end_phrases` in the scenario the app already holds) — are all available at call-end **without any extra network call**.

---

## Decisions

> Decision A is RESOLVED to server-side (Walid 2026-06-09). B–E are pinned by the drift analysis + existing code. F sets the scope boundary against the bigger content migration.

### Decision A — Theatrical phrases live on the SERVER (RESOLVED).
**All user-facing content must be server-driven, never baked into the app** (Walid 2026-06-09, [[content-must-be-server-side]]): Walid edits content often (user complaints) and adds scenarios **daily** — an app release per content change is untenable. So the phrases are a new per-scenario `end_phrases` field, authored in the scenario YAML, stored in the `scenarios` table (JSON-in-TEXT), and **exposed in `ScenarioListItem`** so the app receives them with the scenario list it already loads — instantly available at call-end for every reason (incl. `user_hung_up`/no-envelope cases). Editing a phrase later = a server edit, **no app update**. *(This replaces the earlier client-side-map idea, which violated the content-server rule.)*

### Decision B — Percentage = **client-computed `floor(passed/total*100)`**, not the envelope.
Compute from the checkpoint snapshot captured at end ([call_screen.dart:620-660]); equals the 7.3 debrief formula → overlay % == debrief %. Do **not** read `data['survival_pct']` from the `call_end` envelope (different formula + absent on `user_hung_up`).

### Decision C — Overlay scope = the current `maybePop()` branch only.
The existing code already names this story: [call_screen.dart:722-723] and [call_ended_notice_screen.dart:14-17]. The overlay **replaces the `else`/`maybePop()` branch** for the debrief-eligible reasons (`user_hung_up`, `survived`, non-gifted `character_hung_up`, non-gifted `inappropriate_content`). The `showsNotice` branch (`network_lost`, `noisy_environment`, gifted-short-calls) **keeps `CallEndedNoticeScreen` unchanged**. **No neutral/network overlay variant** (design IG-4 superseded by the shipped notice screen).

### Decision D — Duration = `EndCallResult.durationSec`.
Server-computed at `POST /calls/{id}/end`; already captured client-side in `_endCallResult`. Thread it (plus `callId`) into the `CallEnded` state.

### Decision E — Transition handoff to the debrief = imperative `pushReplacement`, payload forwarded.
The overlay fetches the debrief during the hold, then `pushReplacement`es to the debrief screen (currently `DebriefPlaceholderScreen`), forwarding the fetched payload. Same imperative `Navigator.of(context, rootNavigator: true).pushReplacement(MaterialPageRoute(...))` the notice screen uses ([call_screen.dart:746-756]).

### Decision F — SCOPE BOUNDARY: only the NEW content (phrases) moves server-side in 7.2.
The character **name + role + avatar** stay sourced from `kCharacterCatalog` (client) for 7.2 — consistent with the sibling call screens (incoming-call, connecting) that also use it. Migrating ALL existing shared content (names/roles/avatars/taglines, and serving the Rive puppet/images so **new characters** need no app update) is a **separate, larger content-architecture effort** (its own ADR + story; generic-shared-body decided 2026-06-09). 7.2 does NOT touch it — it only adds the brand-new `end_phrases` content (which has no existing client home) directly server-side, the right way from the start.

---

## Acceptance Criteria

> Overlay-eligible reasons: `user_hung_up`, `survived`, non-gifted `character_hung_up`, non-gifted `inappropriate_content`. Out of scope (keep `CallEndedNoticeScreen`): `network_lost`, `noisy_environment`, gifted-short-calls.

### Server (deliver the phrases)

**AC-S1 — Migration 012 adds `end_phrases`.**
`server/db/migrations/012_scenarios_end_phrases.sql` runs `ALTER TABLE scenarios ADD COLUMN end_phrases TEXT;` (JSON object, **nullable** — legacy rows pre-date it; ADD-only, replays clean — mirrors 011's `ADD COLUMN scenario_title`). It keeps `tests/test_migrations.py` green against the current `tests/fixtures/prod_snapshot.sqlite` (ADD-only/nullable replays clean). The snapshot is refreshed (`python scripts/refresh_prod_snapshot.py`) + committed **right after deploy** — the refresh SSH-pulls live prod, which carries 012 only post-deploy (the documented 7.1/011 sequencing). (Next number is 012 — 011 is the latest on disk.)

**AC-S2 — All 6 scenario YAMLs carry `end_phrases`; the seeder threads it.**
Each `server/pipeline/scenarios/*.yaml` gets an `end_phrases:` block under `metadata:` with 3 string variants: `hung_up`, `voluntary`, `survived` (copy = the Walid-approved table in Dev Notes; the 2nd cop scenario gets its own). `seed_scenarios._row_from_yaml` adds an `end_phrases` key serialized via `json.dumps(meta.get("end_phrases"), ensure_ascii=False)` (NULL when absent), mirroring the `scenario_title` pattern ([seed_scenarios.py:71-76]). **`_UPSERT_SCENARIO_SQL` lives in [db/queries.py:292-335] (NOT `seed_scenarios.py`)** and lists every column explicitly — the new column must be added in **THREE** spots there: the `INSERT INTO scenarios (…)` column list, the `VALUES (:…)` params, AND the `ON CONFLICT(id) DO UPDATE SET … = excluded.end_phrases` clause. **Omitting the `DO UPDATE SET` line = `end_phrases` silently never re-seeds on an existing scenario** (the seeder is idempotent and runs every boot, so it always hits the UPDATE branch).

**AC-S3 — `end_phrases` is exposed in the client-facing scenario LIST payload.**
`ScenarioListItem` ([schemas.py:141-156]) gains `end_phrases: dict | None = None`, and `list_scenarios` ([routes_scenarios.py:57-110]) passes `end_phrases=_safe_json_load(row["end_phrases"], scenario_id=row["id"], column="end_phrases")`. **It MUST be on the LIST item, not detail-only** — the client carries the list `Scenario` into the call, so the overlay needs `end_phrases` at call-end **without a detail fetch** (unlike `exit_lines`, which is server-internal). `ScenarioDetail` inherits the field (and the `s.*` SELECT queries already pick up the new column — no SELECT change), but `get_scenario` builds `ScenarioDetail` with explicit kwargs and need NOT pass `end_phrases` — the detail payload simply nulls it, which is fine (the overlay reads the LIST item, never the detail).

**AC-S4 — Server gates green.**
`python -m ruff check .` + `python -m ruff format --check .` + `.venv/Scripts/python -m pytest` all pass, incl. `test_migrations.py` and the scenarios tests. +tests in **`tests/test_scenarios.py`** (the scenarios route/seeder/loader live there — there is **no** `test_routes_scenarios.py`) asserting `end_phrases` round-trips YAML→DB→`ScenarioListItem`: add `end_phrases` to the corrupt-JSON parametrize list (`test_scenarios.py:~209-217`, since it's a new JSON-in-TEXT column) + a list-item assertion (`~L101-122`).

### Client (render the overlay)

**AC-C1 — `Scenario` model parses `end_phrases`.**
`client/lib/features/scenarios/models/scenario.dart` gains `final Map<String, String>? endPhrases;`, parsed in `fromJson` from `json['end_phrases']` (null-safe: a server that omits it → `null`).

**AC-C2 — Call Ended overlay renders the design layout.**
A new `CallEndedScreen` (`client/lib/features/call/views/call_ended_screen.dart`) renders the three zones from the design doc: identity (name 38px, role 16px, duration 38px), status (120 px avatar + "Call Ended" 20px), result (% 24px, 8 px progress bar, phrase 24px italic, max 2 lines). Non-interactive; `PopScope(canPop: false)` blocks back during the hold.

**AC-C3 — Identity reused from `kCharacterCatalog` (Decision F).**
Name/role/avatar via `kCharacterCatalog[scenario.riveCharacter]` + the existing `CharacterAvatar` widget — same as the sibling call screens.

**AC-C4 — Percentage + bar = client-computed `floor(passed/total*100)`.**
From the checkpoint snapshot captured at call end (NOT the envelope's `survival_pct` — Decision B); clamp 0–100; `total==0 ⇒ 0%` track-only bar (design P-8). Equals the 7.3 debrief %.

**AC-C5 — Variant colors by reason.**
Failure red (`AppColors.destructive`) for `user_hung_up`/`character_hung_up`/`inappropriate_content`; success green (`AppColors.accent`) for `survived`. Identity/status zones color-constant. % shown for all in-scope reasons.

**AC-C6 — Theatrical phrase from `scenario.endPhrases` (server).**
Pick by reason → variant: `survived`→`survived`; `user_hung_up`→`voluntary`; `character_hung_up`/`inappropriate_content`→`hung_up`. A missing/null/empty phrase **hides the phrase element** (design P-7) — never render `"null"`/placeholder. (No client-side phrase map.)

**AC-C7 — Duration `MM:SS` / `H:MM:SS`.**
From `CallEnded.durationSec`: leading zeros (`02:47`, `00:00`), `H:MM:SS` only over 1 h. `00:00` valid (immediate disconnect).

**AC-C8 — Background debrief fetch masks latency.**
On entry, fetch `GET /debriefs/{callId}` (new `CallRepository.fetchDebrief`). `404 DEBRIEF_NOT_READY` → poll (~1 s) until ready or the 10 s cap; `200` → keep the payload. Concurrent with the hold; never blocks the UI / no in-overlay error chrome (UX-DR6).

**AC-C9 — Hold 3 s min / 10 s max, transition on the LAST condition.**
Min hold 3 s (5 s if a screen reader is active — `MediaQuery.accessibleNavigation`, design P-6). Exit when **both** min-hold elapsed AND debrief resolved (whichever later); hard cap 10 s. No overlay countdown/loader.

**AC-C10 — Entry + exit transitions per the design timing.**
Entry: call screen fade-out 500 ms `easeIn` → `#1E1F23` beat → overlay fade-in 500 ms `easeOut`. Exit: ~900 ms crossfade (600/600, 300 ms overlap) to the debrief. Pushed as `pushReplacement` (forward-only, UX-DR10).

**AC-C11 — Auto-transition, payload forwarded (Decision E).**
On the exit trigger, `pushReplacement` to the debrief route (`DebriefPlaceholderScreen` for now), forwarding the fetched payload; back stack ends `[scenario-list, debrief]`. No user action.

**AC-C12 — Nav wiring preserves the notice path.**
[call_screen.dart] listener: `showsNotice` branch unchanged; only the `else`/`maybePop` branch becomes the overlay push. Capture `checkpointsPassed`/`totalCheckpoints` from `_checkpointNotifier.value`, and `callId`/`durationSec`/`endReason`/`scenario` at push time → `CallEndedScreen` constructor. Thread `durationSec` + `callId` into `CallEnded` ([call_state.dart:41-51], populated in `_buildCallEnded` from `_awaitEndCallResult()` + `_session.callId`).

**AC-C13 — Tokens, a11y, client gates.**
No inline hex (theme-token test): reuse `AppColors`/`CallColors`; add the four call-ended typography styles to `AppTypography`. Screen-reader live-region on appear incl. the outcome word (design P-5). `flutter analyze` → "No issues found!" + `flutter test` → "All tests passed!" (full suites).

---

## Tasks / Subtasks

### Server
- [x] **Task 1 — Migration 012 + snapshot (AC-S1).** Write `012_scenarios_end_phrases.sql` (`ALTER TABLE scenarios ADD COLUMN end_phrases TEXT`); add `test_migrations.py::test_migration_012_*`; after deploy, `refresh_prod_snapshot.py` + commit the snapshot. *(Migration + test done; the snapshot refresh is the documented post-deploy step under Task 11 — the snapshot only carries 012 once prod does.)*
- [x] **Task 2 — YAML + seeder (AC-S2).** Add `end_phrases:{hung_up,voluntary,survived}` to all 6 `scenarios/*.yaml` — **copy verbatim from the Dev Notes table (all 6 sets locked, no choosing)**; add the `end_phrases` key to `seed_scenarios._row_from_yaml` (`json.dumps`, NULL when absent); add the column to `_UPSERT_SCENARIO_SQL` in **`db/queries.py`** in ALL THREE spots (INSERT column list, `VALUES` params, `ON CONFLICT … DO UPDATE SET`).
- [x] **Task 3 — Expose in `ScenarioListItem` (AC-S3).** Add `end_phrases: dict | None = None` to `ScenarioListItem` ([schemas.py:141-156]); pass `end_phrases=_safe_json_load(row["end_phrases"], scenario_id=row["id"], column="end_phrases")` in `list_scenarios`. (`ScenarioDetail` inherits the field; `get_scenario` may leave it unset → detail nulls it, fine.) +round-trip tests in `tests/test_scenarios.py`.
- [x] **Task 4 — Server gates (AC-S4).** `ruff` + `pytest` green incl. migration + scenarios tests. *(ruff check + format clean; full pytest 805 passed.)*

### Client
- [x] **Task 5 — `Scenario.endPhrases` (AC-C1).** Add the field + `fromJson` parse (null-safe). Update any `Scenario` test fixtures. *(Optional constructor param — zero fixture churn; 4 new model tests.)*
- [x] **Task 6 — Typography (AC-C2/C13).** Add `callEndedDuration` (38), `callEndedLabel` (20), `callEndedPercent` (24), `callEndedPhrase` (24 italic) to `AppTypography`. Progress-track color: reuse `AppColors.avatarBg` (#414143) for separation from the #38383A avatar — see Dev Notes §"Avatar vs track color".
- [x] **Task 7 — `CallEndedScreen` (AC-C2..C7, C10, C13).** 3-zone `Column` per the design's widget-mapping table; reuse `CharacterAvatar(size: 120)`; client-computed % (guard `total==0`); variant colors; phrase from `scenario.endPhrases` (hide if null); `MM:SS` formatter; `PopScope`; entry `FadeTransition`; `Semantics` live-region.
- [x] **Task 8 — Debrief fetch + hold/transition controller (AC-C8..C11).** `CallRepository.fetchDebrief(callId)` (`GET /debriefs/$callId`, unwrap `data`, map `DEBRIEF_NOT_READY`→poll-sentinel, other 404→terminal); 3 s/5 s min-hold timer + poll until ready or 10 s; exit crossfade `pushReplacement` to the debrief forwarding the payload; cancel timers/futures in `dispose`.
- [x] **Task 9 — State + nav wiring (AC-C12).** Extend `CallEnded` (+`durationSec`, +`callId`); populate in `_buildCallEnded`; replace the `else`/`maybePop` branch in [call_screen.dart] with the overlay push (capture metrics at push time); keep `showsNotice` byte-identical.
- [x] **Task 10 — Client tests + gates (AC-C13).** Widget tests (variants, %/bar incl. `total==0`, durations `00:00`/`02:47`/`1:02:15`, phrase hidden when null, `PopScope`); timing tests with fake clock/short `Duration`s (both-conditions, 10 s cap, screen-reader 5 s min); `fetchDebrief` mocktail tests; bloc test (`CallEnded` carries `durationSec`+`callId`). Force phone surface size; explicit `pump(Duration)` not `pumpAndSettle` (client/CLAUDE.md §3/§7). Run the **full** `flutter analyze` + `flutter test`. *(analyze "No issues found!"; full flutter test 448 passed.)*

### Deploy
- [ ] **Task 11 — Deploy + Smoke Gate.** Deploy (applies migration 012 → refresh+commit snapshot), then Walid's Pixel 9 gate below.

---

## Smoke Test Gate (Server / Deploy Story)

> Migration + a client-facing API field → this story deploys. Every unchecked box is a stop-ship for `in-progress → review`. Paste the actual command + output.

- [x] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test. _Proof:_ 2026-06-10 — CI run 27267831002 success; `/health` → `{"status":"ok","db":"ok","git_sha":"8e60ea05d173c5a02a3d475767d9c2fb6f8b8369"}`; `Active: active (running) since Wed 2026-06-10 09:49:51 UTC; Main PID: 1158183`.
- [x] **`GET /scenarios` returns `end_phrases`.** Production-like curl returns each scenario with an `end_phrases` object (`hung_up`/`voluntary`/`survived`).
  - _Command:_ JWT minted on VPS (`issue_token(1)`) + `curl -sS -H "Authorization: Bearer $JWT" http://127.0.0.1:8000/scenarios`
  - _Expected/Actual:_ 200 — ALL 6 items carry the full `end_phrases` object, byte-identical to the locked Dev Notes table (e.g. `waiter_easy_01 -> {"hung_up": "The waitress kicked you out", "voluntary": "You walked out", "survived": "You actually got your food"}`).
- [x] **DB column present + populated.** Read back prod DB (via venv stdlib): `scenarios.end_phrases` exists and holds the JSON for each scenario.
  - _Command:_ `/opt/survive-the-talk/current/server/.venv/bin/python -c 'import sqlite3; … SELECT id, end_phrases FROM scenarios'` → all 6 rows populated (cop_hard_01, girlfriend_medium_01, landlord_hard_01, mugger_medium_01, waiter_easy_01, cop_interrogation_01).
- [x] **DB backup taken BEFORE deploy (migration 012).** _Command:_ `ssh root@167.235.63.129 "sqlite3 /opt/survive-the-talk/data/db.sqlite \".backup '/opt/survive-the-talk/backups/db.pre-7.2-manual.sqlite'\""` _Proof:_ `db.pre-7.2-manual.sqlite` (184320 bytes, Jun 10 09:46 — BEFORE the 09:49 deploy) + the CI auto-backup `db.pre-8e60ea0.sqlite` from deploy-server.yml.
- [ ] **On-device: failure variant.** End a call (tap hang-up, or character hangs up ≥30 s). Overlay shows name/role/avatar, `MM:SS`, a **red** % + bar matching the in-call checkpoint progress, and the scenario's red **server** phrase; holds ≥3 s; fades to debrief.
- [ ] **On-device: success variant.** Complete a scenario → **green** 100% + the grudging "survived" phrase; auto-fades to debrief.
- [ ] **Latency masking.** Hold feels deliberate (no overlay spinner); debrief appears already-rendered after the crossfade.
- [ ] **Notice path intact.** `network_lost`/`noisy_environment`/very-short gifted call still shows `CallEndedNoticeScreen` (no regression).
- [x] **Server logs clean.** `journalctl -u pipecat.service -n 50 --since "5 min ago"` — no ERROR/Traceback for `/scenarios`. _Proof:_ 2026-06-10 09:55 — `journalctl --since '6 min ago' | grep -iE 'error|traceback|exception'` returned EMPTY (post-deploy boot + the verified `/scenarios` calls included in the window).

---

## Dev Notes

### Where the three displayed values come from

| Value | Source | How the overlay gets it |
|---|---|---|
| **Phrase** | NEW server field `scenarios.end_phrases` (JSON), exposed in `ScenarioListItem` → carried in the client `Scenario`. | `scenario.endPhrases[variant]` (variant from reason). Available at call-end with NO extra fetch. |
| **Percentage** | Client checkpoint snapshot, reconciled to the server-authoritative met set at end ([call_screen.dart:620-660]). `floor(passed/total*100)` == the 7.3 debrief formula. | Capture `_checkpointNotifier.value!.metCount`/`.total` in the listener; compute in the widget. NOT `data['survival_pct']`. |
| **Duration** | `EndCallResult.durationSec` (server-computed at `/end`); captured in `_endCallResult`. | Thread into `CallEnded` (Task 9). |

### Server plumbing — mirror `scenario_title`, but client-exposed (the one gotcha)

Adding `end_phrases` follows the Story 7.1 `scenario_title` path EXACTLY (migration ALTER → YAML metadata → `seed_scenarios._row_from_yaml` `json.dumps` → `_UPSERT_SCENARIO_SQL` **in `db/queries.py`** [add the column in 3 spots: INSERT cols, VALUES params, `ON CONFLICT DO UPDATE SET`] → `s.*` SELECT) — **except** `scenario_title` is server-internal (only in `DebriefOut`), whereas `end_phrases` MUST be on the client-facing **`ScenarioListItem`** (not detail-only). Put it on the LIST item because the client carries the list `Scenario` into the call; the overlay reads it at call-end without a `GET /scenarios/{id}` round-trip. `ScenarioDetail` inherits it for free. JSON-in-TEXT convention: store `{"hung_up":"…","voluntary":"…","survived":"…"}`; decode via `_safe_json_load`.

### Seed phrases (Walid-approved 2026-06-09 — author per scenario)

**ALL 6 sets LOCKED (Walid 2026-06-09)** — the dev seeds each scenario's YAML verbatim from this table; no proposing/choosing. Tone: short, 3rd person, sarcastic, never congratulatory; ≤50 chars ideal / 70 hard. (Walid may still tweak any string later — it's a server edit, no app update.)

| Scenario (character) | `hung_up` (failure) | `voluntary` (you quit) | `survived` (rare) |
|---|---|---|---|
| the-waiter (Waitress) | "The waitress kicked you out" | "You walked out" | "You actually got your food" |
| the-mugger (Mugger) | "The mugger gave up on you" | "You hung up first" | "The mugger walked away empty-handed" |
| the-girlfriend (Girlfriend) | "She hung up. Again." | "You ended the call" | "She's still on the line. Barely." |
| the-cop (Cop) | "The officer lost patience" | "You hung up on the officer" | "The officer let you off" |
| the-landlord (Landlord) | "The landlord hung up on you" | "You hung up on him" | "The landlord backed down" |
| cop-interrogation-01 (Detective, "The 8:30 Alibi") | "The detective stopped believing you" | "You hung up on the detective" | "Your alibi held. Barely." |

### Reuse, don't reinvent (client)

- **Avatar:** `CharacterAvatar` ([widgets/character_avatar.dart]) at `size: 120`. Don't hand-roll a `CircleAvatar`.
- **Identity:** `kCharacterCatalog[scenario.riveCharacter]` → `CharacterIdentity{name, role, imageAsset}` (Decision F — stays client for 7.2).
- **Auth'd GET:** copy `CallRepository.endCall` ([call_repository.dart:43-53]) for `fetchDebrief`; `ApiClient` base `http://167.235.63.129`, Bearer interceptor.
- **Post-call nav:** copy the imperative `rootNavigator pushReplacement(MaterialPageRoute)` in a post-frame callback ([call_screen.dart:744-760]); `_popScheduled` guards double-push. Don't touch `CallEndedNoticeScreen` / the `showsNotice` predicate.

### Avatar vs track color (DECIDED 2026-06-09)

**LOCKED:** avatar circle = the shipped `CharacterAvatar` (`CallColors.avatarBackground` #38383A — continuity with the other call screens); progress-bar track = `AppColors.avatarBg` (#414143), which keeps it visually distinct from the avatar. No new token, no inline hex. (This swaps the design doc's literal #414143-avatar / #38383A-track assignment to preserve cross-screen avatar continuity; Walid may fine-tune at the on-device gate, but the dev implements exactly this.)

### Conventions / traps

- **Server:** migration must replay vs `prod_snapshot.sqlite` + refresh it (server/CLAUDE.md §2 / root CLAUDE.md); `_safe_json_load` for the JSON column; loguru-via-sink in tests (§3).
- **Client (client/CLAUDE.md):** no inline hex (§6); `pump(Duration)` not `pumpAndSettle` on continuous animations (§3); force phone surface (§7); mocktail `registerFallbackValue` concrete events (§2); no toast/snackbar on error (§10).
- **Commit cadence:** per the new rule (root CLAUDE.md → Commit Cadence), each stage is its OWN commit — no amend/squash/force-push.

### Project Structure Notes

- **New — server:** `db/migrations/012_scenarios_end_phrases.sql`; tests. **New — client:** `features/call/views/call_ended_screen.dart`; tests.
- **Edited — server:** `pipeline/scenarios/*.yaml` (6, +`end_phrases`), `db/seed_scenarios.py` (+`end_phrases` key in `_row_from_yaml`), **`db/queries.py` (+`end_phrases` in `_UPSERT_SCENARIO_SQL` — 3 spots)**, `models/schemas.py` (+`end_phrases` on `ScenarioListItem`), `api/routes_scenarios.py` (`list_scenarios` passes it), `tests/test_scenarios.py` (+round-trip/corrupt-JSON), `tests/fixtures/prod_snapshot.sqlite` (refresh).
- **Edited — client:** `features/scenarios/models/scenario.dart` (+`endPhrases`), `features/call/bloc/call_state.dart` (+`durationSec`,+`callId`), `features/call/bloc/call_bloc.dart` (`_buildCallEnded`), `features/call/views/call_screen.dart` (overlay push), `features/call/repositories/call_repository.dart` (+`fetchDebrief`), `core/theme/app_typography.dart` (+4 styles).
- **Untouched (boundary, Decision F):** `kCharacterCatalog`/`kScenarioTaglines`, the Rive puppet, `DebriefPlaceholderScreen`, `CallEndedNoticeScreen`/`showsNotice`.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 7.2] — ACs (L1303-1329).
- [Source: _bmad-output/planning-artifacts/call-ended-screen-design.md] — **authoritative** layout/typography/variants/timing/a11y/widget-mapping/phrase tables.
- [Source: _bmad-output/implementation-artifacts/7-1-build-debrief-generation-backend.md] — `GET /debriefs/{call_id}` + `DEBRIEF_NOT_READY`/`CALL_NOT_FOUND`; `scenario_title` plumbing pattern (migration 011 + YAML + seeder).
- [Source: server/db/migrations/004_scenarios_and_user_progress.sql:5-27] — `scenarios` schema; [011_debriefs.sql:45] — `ALTER … ADD scenario_title` (mirror for 012).
- [Source: server/pipeline/scenarios/the-waiter.yaml:5-26,191-194] — `metadata` + `exit_lines`; [seed_scenarios.py:23-103, 71-76] — `_row_from_yaml`/`scenario_title`; [db/queries.py:292-335] `_UPSERT_SCENARIO_SQL`, [237-265] `s.*` queries.
- [Source: server/models/schemas.py:141-156] `ScenarioListItem` (add `end_phrases` HERE), [158-181] `ScenarioDetail`; [api/routes_scenarios.py:57-110] `list_scenarios`, [113-176] `get_scenario`; `_safe_json_load`.
- [Source: server/pipeline/patience_tracker.py:1327-1357] — envelope `survival_pct` = patience ratio (do NOT use); [pipeline/debrief_assembly.py] — the `floor(passed/total)` to match.
- [Source: client/lib/features/scenarios/models/scenario.dart:3-46] (+`endPhrases`); [character_catalog.dart:22-48]; [features/call/views/call_screen.dart:620-660,709-760]; [views/call_ended_notice_screen.dart:14-17]; [bloc/call_state.dart:41-51]; [bloc/call_bloc.dart:555,590]; [services/data_channel_handler.dart:107-127]; [repositories/call_repository.dart:43-53]; [widgets/character_avatar.dart]; [core/theme/app_colors.dart], [call_colors.dart:21,32], [app_typography.dart].
- [Source: client/CLAUDE.md] §1/§2/§3/§6/§7/§10; [server/CLAUDE.md] §2/§3; [project-root CLAUDE.md] — gates, Commit Cadence, migration-snapshot rule.
- Memory: [[content-must-be-server-side]] (the rule driving Decision A), [[commit-every-story-stage]].

## Dev Agent Record

### Agent Model Used

Claude Fable 5 (claude-fable-5) via /bmad-dev-story, 2026-06-10.

### Debug Log References

- Full server pytest: **805 passed** (was 801; +4 — `test_migration_012_scenarios_end_phrases`, `test_list_items_carry_end_phrases`, `test_list_end_phrases_matches_yaml_authoring`, `test_list_returns_500_on_corrupt_end_phrases_json`). `ruff check` + `ruff format --check` clean.
- Full flutter test: **448 passed** (was 420; +28 — 19 `call_ended_screen_test`, 4 `scenario_test` endPhrases, 2 `call_repository_test` fetchDebrief, 1 `call_bloc_test` durationSec/callId, 2 `call_screen_test` post-call navigation). `flutter analyze` "No issues found!".
- One real bug caught by the timing tests during dev: `_maybeExit()` (→ `pushReplacement`) initially sat INSIDE `_attemptFetch`'s broad `try` — a navigation failure would have been silently swallowed by the fetch catch. Moved outside the try (navigation errors now surface; fetch errors still settle silently per UX-DR6).

### Completion Notes List

- **Server** — `end_phrases` follows the `scenario_title` plumbing exactly (migration 012 ALTER ADD nullable TEXT → YAML `metadata.end_phrases` → `_row_from_yaml` conditional `json.dumps` → `_UPSERT_SCENARIO_SQL` in all 3 spots incl. `DO UPDATE SET` → `s.*` SELECT), except exposed on the client-facing **`ScenarioListItem`** via `_safe_json_load` (AC-S3). `ScenarioDetail` inherits the field and `get_scenario` leaves it None (the overlay reads the LIST item). All 6 YAMLs seeded verbatim from the locked phrase table.
- **Deviation #1 (test placement)** — AC-S4 asked to add `end_phrases` to the corrupt-JSON parametrize at `test_scenarios.py:~209`, but that parametrize hits the DETAIL route, which deliberately never decodes `end_phrases` — adding it there would assert a 500 the route correctly doesn't produce. Wrote a dedicated LIST-route corruption test instead (`test_list_returns_500_on_corrupt_end_phrases_json`), preserving the AC's intent (corrupt JSON-in-TEXT → 500 `SCENARIO_CORRUPT`).
- **Client model** — `Scenario.endPhrases` is an OPTIONAL constructor param (zero churn across existing fixtures) and `fromJson` parses defensively: non-string variant values are dropped rather than crashing the whole scenario-list parse (**Deviation #2** vs the codebase's usual strict `as` casts — a malformed phrase must never kill the list screen; the overlay treats a missing variant as "hide the phrase", same as null).
- **`CallEndedScreen`** — 3-zone layout per the design widget-mapping table; identity zone mirrors the incoming-call/connecting text styles; the 4 new `AppTypography` call-ended styles; `CharacterAvatar(size: 120)` (avatar #38383A via `CallColors.avatarBackground`) with progress track `AppColors.avatarBg` #414143 (the LOCKED swap); variant colors via `AppColors.destructive`/`accent`; `floor(passed/total*100)` clamped, `total==0 → 0%` track-only (P-8); `MM:SS`/`H:MM:SS` formatter; phrase hidden when null/empty (P-7); `PopScope(canPop:false)` (P-4); live-region `Semantics` with the explicit outcome word + natural-speech duration (P-5).
- **Entry/exit transitions (AC-C10)** — `CallEndedScreen.route()` is a 1000 ms `PageRouteBuilder`: backdrop fade-in over 0–500 ms `easeIn` (reads as the call screen fading into the shared `#1E1F23`), content fade-in 500–1000 ms `easeOut`; on exit the same route fades out over the first 600 ms of the debrief route's 900 ms window via `secondaryAnimation` while the debrief fades in over 300–900 ms — the design's 300 ms crossfade overlap.
- **Hold controller (AC-C8/C9)** — hold deadlines offset by `entryDuration` (timing starts at full visibility per the design); min hold 3 s (5 s when `MediaQuery.accessibleNavigation` — P-6); exit on the LAST of (min hold, debrief settled); hard cap 10 s. Debrief fetch: `DEBRIEF_NOT_READY` → cancellable 1 s poll `Timer` (NOT `Future.delayed` — uncancellable timers fail widget tests and leak); any other failure settles silently (UX-DR6, no error chrome). All timers cancelled in `dispose` and on exit. **Deviation #6** — the canonical timings are constructor params with canonical defaults (timing seams for deterministic tests).
- **Deviation #4 (payload forwarding)** — `DebriefPlaceholderScreen` is a Decision-F boundary (untouched) and takes no payload, so the fetched debrief rides `RouteSettings(name: AppRoutes.debrief, arguments: payload)` on the exit route + a `debugDebriefRouteBuilder` test seam observes it. Story 7.3's real screen consumes the forwarded payload from the route arguments.
- **Nav wiring (AC-C12)** — only the `else`/`maybePop` branch changed: debrief-eligible reasons push `CallEndedScreen.route(...)` with metrics captured at push time (`_checkpointNotifier.value` met-count/total — i.e. post-`call_end`-reconcile server-authoritative set — plus `state.durationSec`/`state.callId`); `showsNotice` branch byte-identical (regression-tested). **Deviation #5** — a null `endReason` (impossible on normal exit paths) falls back to the old plain `maybePop` rather than rendering an unknown-variant overlay.
- **Bloc/state** — `CallEnded` gains nullable `durationSec` + `callId`, populated in `_buildCallEnded` from the awaited `EndCallResult` + `_session.callId`. **Deviation #3** — a null `durationSec` (POST unresolved at emit, queued-retry edge) renders as "00:00" (the design's only zero-state; documented, rare).
- **Smoke-gate fix (2026-06-10, Walid's first device run) — the stale "Calling" surface no longer shows between the call and the overlay.** Pre-7.2, `_buildBody` let the `CallEnded` state fall through to the DIAL surface (name + avatar + "Calling" + hang-up button) — harmless then because the route popped on the very next frame, so it was never actually seen. The 7.2 overlay changed the geometry: its 1 s entry fade deliberately keeps the call-screen route visible UNDERNEATH (that's the design's "call screen fades out" beat), which promoted the stale fallback into a visible "second hang-up screen" (Walid: two hang-up screens before the debrief = one too many). Fix: `CallEnded` now renders a bare dark body (`SizedBox.shrink()` on the `AppColors.background` scaffold) so the sequence on device is in-call canvas → dark scene break → overlay content fade-in — exactly ONE hang-up screen, as the design intends. Locked by a regression test (`CallEnded renders a bare scene break — the dial surface never reappears beneath the overlay`). This also cleans the notice-path frames (`network_lost` etc. now break to dark instead of flashing "Calling" during the notice push). Client tests 448 → 449.

### File List

**New — server:** `server/db/migrations/012_scenarios_end_phrases.sql`
**Edited — server:** `server/pipeline/scenarios/the-waiter.yaml`, `server/pipeline/scenarios/the-mugger.yaml`, `server/pipeline/scenarios/the-girlfriend.yaml`, `server/pipeline/scenarios/the-cop.yaml`, `server/pipeline/scenarios/the-landlord.yaml`, `server/pipeline/scenarios/cop-interrogation-01.yaml` (+`metadata.end_phrases`), `server/db/seed_scenarios.py` (+`end_phrases` in `_row_from_yaml`), `server/db/queries.py` (+`end_phrases` in `_UPSERT_SCENARIO_SQL` × 3 spots), `server/models/schemas.py` (+`end_phrases` on `ScenarioListItem`), `server/api/routes_scenarios.py` (`list_scenarios` passes it), `server/tests/test_migrations.py` (+1 test), `server/tests/test_scenarios.py` (+3 tests)
**Pending (deploy step):** `server/tests/fixtures/prod_snapshot.sqlite` (refresh + commit right after deploy)
**New — client:** `client/lib/features/call/views/call_ended_screen.dart`, `client/test/features/call/views/call_ended_screen_test.dart` (19 tests)
**Edited — client:** `client/lib/features/scenarios/models/scenario.dart` (+`endPhrases`), `client/lib/core/theme/app_typography.dart` (+4 styles), `client/lib/features/call/repositories/call_repository.dart` (+`fetchDebrief`), `client/lib/features/call/bloc/call_state.dart` (`CallEnded` +`durationSec`+`callId`), `client/lib/features/call/bloc/call_bloc.dart` (`_buildCallEnded`), `client/lib/features/call/views/call_screen.dart` (overlay push branch), `client/test/features/scenarios/models/scenario_test.dart` (+4), `client/test/features/call/repositories/call_repository_test.dart` (+2), `client/test/features/call/bloc/call_bloc_test.dart` (+1), `client/test/features/call/views/call_screen_test.dart` (+2)

### Change Log

| Date | Change |
|---|---|
| 2026-06-09 | Story 7.2 drafted (`backlog` → `ready-for-dev`); client-only Call Ended overlay; phrases proposed client-side. |
| 2026-06-09 | **Revised: phrases moved SERVER-SIDE** per Walid's content-is-server-side rule ([[content-must-be-server-side]]). Now a client + small-server story: new per-scenario `end_phrases` field (migration 012 + YAML + seeder + `ScenarioListItem` exposure) delivered in the scenario list payload; client overlay reads `scenario.endPhrases`. Re-added the Smoke Test Gate (deploys). Scope boundary (Decision F): names/avatars/Rive stay client for 7.2; the full content migration is a separate ADR+story (generic-shared-body decided). |
| 2026-06-09 | **All open decisions LOCKED for the dev** (Walid: "make decisions now so the dev doesn't think"). Authored the 6th set of phrases (cop-interrogation-01 / "The 8:30 Alibi" — Detective). Fixed the avatar/track color (avatar #38383A via CharacterAvatar, track #414143). **Zero open decisions remain** — the spec is fully deterministic for `/bmad-dev-story`. |
| 2026-06-10 | **/bmad-dev-story COMPLETE (Tasks 1–10)** — `in-progress` → `review`. Server: migration 012 + 6 YAMLs seeded verbatim + seeder/upsert/ScenarioListItem plumbing (+4 tests, pytest 805). Client: `CallEndedScreen` (3-zone design layout, variant colors, client-computed %, server phrases, 3–10 s hold masking the polled debrief fetch, entry/exit crossfades, a11y live region), `Scenario.endPhrases`, 4 typography styles, `fetchDebrief`, `CallEnded` +`durationSec`/`callId`, overlay nav wiring with notice path untouched (+28 tests, flutter test 448, analyze clean). 7 deviations documented in Completion Notes (test placement, defensive parse, 00:00 null-duration, RouteSettings payload forwarding, null-reason fallback, timing seams, `_maybeExit` outside try). Task 11 (deploy + Pixel 9 smoke gate) remains. |
| 2026-06-10 | **Deployed + server smoke boxes verified** — CI 27267831002 success on `8e60ea0`; `/health` SHA match; migration 012 live; all 6 prod rows + `GET /scenarios` payload carry `end_phrases`; pre-deploy backup `db.pre-7.2-manual.sqlite`; logs clean. `prod_snapshot.sqlite` refreshed (carries 012, FK 0, integrity ok) + committed (`99be9cf`). |
| 2026-06-10 | **Smoke-gate fix — removed the stale "Calling" screen between call and overlay** (Walid's first Pixel 9 run: "deux écrans de raccrochement avant le debrief, c'est trop"). Root cause: `_buildBody`'s pre-7.2 fallback rendered the DIAL surface on `CallEnded` — invisible when the route popped instantly, plainly visible now through the overlay's 1 s entry fade. `CallEnded` now renders a bare dark scene break; +1 regression test (client 449). See Completion Notes §Smoke-gate fix. |
