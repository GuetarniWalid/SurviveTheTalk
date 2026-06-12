# Story 7.4: Build Pre-Scenario Briefing Display

Status: ready-for-dev

## ⚠️ Source-Document Drift — READ FIRST

| Stale statement (epics.md / architecture.md / UX spec) | Current truth (code wins) | Evidence |
|---|---|---|
| `briefing_text` column (architecture.md §scenarios table, epics.md AC "displays the scenario's `briefing_text`") | The column shipped in Story 5.1 as **`briefing`** — a JSON object `{vocabulary, context, expect}` stored as TEXT, `NOT NULL`. There is NO `briefing_text` column and none must be added. | `server/db/migrations/004_scenarios_and_user_progress.sql`, `server/db/seed_scenarios.py:126`, `server/pipeline/scenarios/the-waiter.yaml:222-225` |
| "section-title (14px SemiBold) for headers" (epic AC4 / ux-design-specification.md typography table) | The **shipped** debrief section-header pattern is `AppTypography.headline` (18/600) + `Semantics(header: true)` (`_SectionHeader`). Mirror the shipped pattern — the AC's intent is "established styles", and the established style is the code. | `client/lib/features/debrief/views/debrief_screen.dart:484-499` |
| "a briefing screen **or dialog**" (epic AC1) | The app already committed to a **screen**: route `/briefing/:scenarioId` + `BriefingPlaceholderScreen` ("Stub screen used until Story 7.4 ships the real pre-scenario briefing") + the ScenarioCard's whole-card tap with semantic hint "View briefing" already navigates there. This story replaces the placeholder; it does not introduce a dialog. | `client/lib/app/router.dart:192-200`, `client/lib/features/briefing/views/briefing_placeholder_screen.dart:9`, `client/lib/features/scenarios/views/widgets/scenario_card.dart:37-47` |
| No Figma frame exists for the briefing screen (checked `figma-export/.figma/` — no `*brief*` extract) | Layout below is derived from established tokens + shipped screen patterns. Walid iterates on-device post-implementation (this is the feature, not a defect — `feedback_mvp_iteration_strategy`). | — |

## Decisions (resolved defaults — follow unless Walid overrides before dev)

### Decision A — Briefing data rides the LIST payload (RESOLVED)
Expose the existing `scenarios.briefing` column on `GET /scenarios` list items, exactly like Story 7.2 did for `end_phrases`. **No migration** (column exists since 5.1, NOT NULL, all 6 YAMLs authored), **no extra fetch**, **no loading/error states on the briefing screen** — the data is already in the `Scenario` the hub holds. The alternative (client fetches `GET /scenarios/{id}` on open) is rejected: it adds a round-trip + spinner + error states, and the detail payload carries `base_prompt` + `checkpoints.success_criteria` — spoilers the client must not need. ADR-004 confirms briefings belong to the scenario payload the app already fetches. The SQL already does `SELECT s.*` — only the Pydantic model + route constructor change.

### Decision B — "First attempt" = server `attempts == 0` AND not initiated this session (RESOLVED)
`Scenario.attempts` (COALESCE'd to 0, already parsed client-side, already drives `isNotAttempted`) is the truth at list-load time. **But the hub list does NOT refetch after a call** (known staleness class — deferred-work `meta.calls_remaining` entry): after first call → debrief → back to hub, `attempts` still reads 0 and the briefing would re-trigger, violating epic AC3 on-device. Fix: an in-memory `Set<String> _initiatedThisSession` in `_ListState`, marked **after a successful `initiateCall` POST** (not on confirm — a failed POST means no call happened, re-showing the briefing is correct). Gate = `attempts == 0 && !_initiatedThisSession.contains(id) && hasBriefingContent`. No disk persistence — on app restart the server truth is fresh. Do NOT bolt a list-refresh onto this story (LoadScenariosEvent blanks the hub through `ScenariosLoading`; the staleness item stays deferred).

### Decision C — One screen, two entries, one confirm contract (RESOLVED)
`BriefingScreen` is pushed via the existing GoRoute from BOTH entries and always pops a `bool`:
- **Gate entry** (epic AC1): call-icon tap on a first-attempt scenario → push briefing → `true` continues the call chain, anything else aborts.
- **Browse entry** (existing card-tap affordance): whole-card tap → same screen, same CTA — confirming from browse ALSO starts the call (reading the briefing then having to go back and find the phone icon would be hostile).
Both handlers converge on a private `_startCall(scenario)` extracted from today's `_onCallTap` body (content-warning sheet → POST `/calls/initiate` → push `CallScreen` on the root navigator). The call-initiation orchestration NEVER moves into the briefing screen — the screen is a pure render + confirm surface, mirroring `showContentWarningSheet`'s await-a-bool contract.

### Decision D — Sequencing with the content warning (RESOLVED)
Briefing FIRST, content warning AFTER confirm, for first-timers on warned scenarios (mugger/cop/landlord): briefing screen → "Call" → "HEADS UP / Buckle up" sheet → "Pick up" → POST. The warning's UX decision record is LAW (re-appears every time, no "don't show again", `content-warning-dialog.md`) — the briefing never absorbs or replaces it. Returning users keep today's flow untouched: warning sheet (if any) → POST.

## Story

As a user,
I want to see a short situational briefing before attempting a scenario for the first time,
so that I know what to expect and can prepare key vocabulary.

## Acceptance Criteria

### Server

1. **AC-S1 — briefing on the list payload.** `GET /scenarios` list items each carry `briefing`: the decoded JSON object from the existing `scenarios.briefing` column (keys `vocabulary` / `context` / `expect`, string values). `GET /scenarios/{id}` (which already returns `briefing`) is unchanged. Field typed `dict | None` on `ScenarioListItem` (the `ScenarioDetail` override `briefing: dict` stays).
2. **AC-S2 — corruption posture.** A corrupt-JSON or wrong-shape `briefing` value on the list route produces the canonical 500 `{error: SCENARIO_CORRUPT}` envelope (same `_safe_json_load` + `ValidationError` net as `language_focus` / `end_phrases`), never a raw FastAPI default.
3. **AC-S3 — seeder fail-fast.** `seed_scenarios._row_from_yaml` validates the YAML `briefing` shape at boot (must be a dict with exactly the keys `vocabulary`, `context`, `expect`, each a string — **empty strings allowed**, several test fixtures use them) and raises `ValueError` naming the offending scenario id on violation. Mirrors the 7.2 review patch that added the same posture for `end_phrases`.

### Client

4. **AC-C1 — model parse.** `Scenario` gains `final Map<String, String>? briefing`, parsed defensively exactly like `endPhrases` (keep only string→string entries; absent / non-map → null; never throws). A `bool get hasBriefingContent` returns true iff at least one of the three values is a non-empty trimmed string.
5. **AC-C2 — real BriefingScreen.** `BriefingPlaceholderScreen` is replaced by `BriefingScreen` (StatefulWidget, no bloc — sole state is a pop-once guard). Dark theme (`AppColors.background`), back arrow top-left (pop `false`; `canPop ? pop : go(root)` fallback kept from the placeholder), scrollable body: character avatar (100px circle, `assets/images/characters/<riveCharacter>.jpg` with `errorBuilder` → flat `avatarBg` circle fallback), scenario title, then up to three sections — **Context**, **What to expect**, **Key phrases** — each `_SectionHeader`-style header (`headline` + `Semantics(header: true)`) over `body`-style text rendered **verbatim** from the briefing map (`context` / `expect` / `vocabulary` respectively — do NOT split the vocabulary string on commas, it is authored prose). A section whose value is null/empty/whitespace is hidden entirely (no bare header). Pinned bottom CTA: full-width accent `ElevatedButton` (StadiumBorder, `Icons.phone_outlined`, label **"Call"**, `Semantics` label `Call <title>`) that pops `true` exactly once.
6. **AC-C3 — route carries the Scenario.** The `/briefing/:scenarioId` GoRoute passes the full `Scenario` via `state.extra` (both entries push with `extra: scenario`) and gains a route-level `redirect` → `AppRoutes.root` when `extra` is not a `Scenario` (deep-link / refresh entry — graceful bounce, no fallback widget).
7. **AC-C4 — first-attempt gate (epic AC1).** Tapping the **call icon** on a scenario with `attempts == 0` that has briefing content and was not initiated this session pushes `BriefingScreen` BEFORE any call initiation — no `POST /calls/initiate` fires until the user confirms.
8. **AC-C5 — confirm proceeds normally (epic AC2).** Briefing pops `true` → the unchanged chain runs: content-warning sheet if `contentWarning != null` (Decision D order) → `POST /calls/initiate` (with global difficulty) → `CallScreen` pushed on the root navigator (connecting animation untouched). Pop `false`/back → hub, zero network calls.
9. **AC-C6 — skip for returning users (epic AC3).** `attempts > 0` OR already initiated this session OR no briefing content → call-icon tap runs the chain directly (content warning still shown when applicable), byte-identical to today's behavior.
10. **AC-C7 — browse entry.** Whole-card tap pushes the same screen with the same confirm contract (confirm from browse starts the call chain too). Double-tap on the card or the call icon never double-pushes the route, and double-tap on the CTA / back never double-pops (a second pop would dismiss the hub).
11. **AC-C8 — design-system + a11y compliance (epic AC4).** Zero new color tokens (theme_tokens_test stays green), zero new typography tokens (inline styles compose `AppTypography.fontFamily` like `_DifficultyHubLine` / the content-warning sheet where no token fits), ≥44px touch targets, `Semantics` on back/CTA/headers, no overflow at 320×568 with `textScaler` 1.5 (scrollable body absorbs growth; CTA stays reachable because it is pinned, not in-scroll).

## Tasks / Subtasks

- [ ] **Task 1 — Server: expose `briefing` on the list** (AC-S1, AC-S2)
  - [ ] 1.1 `models/schemas.py`: add `briefing: dict | None = None` to `ScenarioListItem`; update the class docstring (it currently documents briefing as detail-only).
  - [ ] 1.2 `api/routes_scenarios.py` list constructor: `briefing=_safe_json_load(row["briefing"], scenario_id=row["id"], column="briefing")` (the SQL already `SELECT s.*` — no query change).
  - [ ] 1.3 Tests (`tests/test_scenarios.py`): list items carry the 3-key briefing dict (seeded fixture); corrupt-JSON briefing → 500 SCENARIO_CORRUPT; valid-JSON-wrong-shape (e.g. `"[1,2]"`) → 500 SCENARIO_CORRUPT. Mirror the existing `end_phrases` test trio.
- [ ] **Task 2 — Server: seeder shape validation** (AC-S3)
  - [ ] 2.1 `db/seed_scenarios.py`: validate `doc["briefing"]` before the `json.dumps` at line 126 — dict, keys exactly `{vocabulary, context, expect}`, all values `str` (empty OK). `ValueError` messages name the scenario id, matching the `end_phrases` / `resolve_patience_config` convention.
  - [ ] 2.2 Tests: non-dict / missing key / extra key / non-string value each raise; confirm all 6 shipped YAMLs still seed (existing seed tests cover the happy path).
  - [ ] 2.3 Run `ruff check . && ruff format --check . && pytest` (in-sandbox, warmed — full suite, ~880+ expected green incl. `test_migrations`).
- [ ] **Task 3 — Client: model** (AC-C1)
  - [ ] 3.1 `scenario.dart`: `briefing` field + defensive `fromJson` parse (copy the `endPhrases` block shape) + `hasBriefingContent` getter + doc comment citing Story 7.4.
  - [ ] 3.2 Model tests: present / absent / non-map / mixed-type entries filtered / all-empty → `hasBriefingContent == false`.
- [ ] **Task 4 — Client: BriefingScreen + router** (AC-C2, AC-C3)
  - [ ] 4.1 Create `client/lib/features/briefing/views/briefing_screen.dart` per AC-C2 layout (local layout consts like DebriefScreen; reuse `AppSpacing.screenHorizontal`/`screenVerticalList`/`avatarLarge`; title inline 24/700 `fontFamily` style, `textPrimary`).
  - [ ] 4.2 `router.dart`: swap the briefing GoRoute to `BriefingScreen(scenario: state.extra! as Scenario)` + route-level `redirect` guarding non-`Scenario` extra → root. Keep `_fadePage`.
  - [ ] 4.3 Delete `briefing_placeholder_screen.dart` (+ its test file if one exists; fix any harness references — `scenario_list_screen_test.dart:129` stubs its own briefing route, verify it still compiles).
  - [ ] 4.4 Widget tests (`test/features/briefing/views/briefing_screen_test.dart`): renders avatar/title/3 sections; hides empty sections (waiter-style all-empty fixture → no headers); CTA pops `true`; back pops `false`; CTA double-tap pops once; 320×568 @ textScaler 1.5 no overflow; semantics (header flags, `Call <title>` button, back button).
- [ ] **Task 5 — Client: hub gate** (AC-C4..C7)
  - [ ] 5.1 `scenario_list_screen.dart`: extract `_startCall(BuildContext, Scenario)` from `_onCallTap` (content-warning → POST → push CallScreen — chain order untouched); add `_initiatedThisSession` set, marked right after `initiateCall` succeeds. **Flag choreography (precise — avoid a self-block):** BOTH handlers (`_onCallTap`, `_onCardTap`) start with `if (_initiating) return; setState(() => _initiating = true);`, run their flow (briefing await included — so double-taps can't double-push the route), and reset the flag in `finally`. `_startCall` itself contains NO `_initiating` check or set — it is only ever invoked with the flag already held by its caller.
  - [ ] 5.2 `_onCallTap`: gate per Decision B → `context.push<bool>('${AppRoutes.briefing}/${scenario.id}', extra: scenario)` → `ready != true → return` → `context.mounted` check → `_startCall`.
  - [ ] 5.3 `_onCardTap`: same push + same continuation (replaces the bare `context.push`).
  - [ ] 5.4 Widget tests (extend `scenario_list_screen_test.dart`, mock-router harness already exists): first-attempt call tap pushes briefing + NO POST before confirm; confirm → POST + CallScreen; confirm on warned scenario → warning sheet between briefing and POST; decline → no POST; `attempts > 0` → direct chain (no briefing); null/empty briefing → direct chain; session mark → second call tap after a successful initiate skips the briefing despite stale `attempts == 0`; card tap → briefing + confirm continues.
- [ ] **Task 6 — Gates, deploy, flip**
  - [ ] 6.1 `cd client && flutter analyze` → "No issues found!"; `flutter test` → all pass (489 existing + ~18 new — indicative).
  - [ ] 6.2 Server gates (Task 2.3) green.
  - [ ] 6.3 Deploy server to VPS (normal release flow — no migration, no .env change), `systemctl restart pipecat.service`, fill the Smoke Test Gate boxes below.
  - [ ] 6.4 Flip story + `sprint-status.yaml` → `review`; commit (one commit for the dev stage, list format, no Co-Authored-By).

## Smoke Test Gate (Server / Deploy Stories Only)

> Server slice = list-payload field only: no migration, no writes, no .env change. DB boxes are N/A with rationale.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_
- [ ] **Happy-path endpoint round-trip.** Every list item carries the 3-key briefing object.
  - _Command:_ `ssh root@167.235.63.129 'set -a; . /opt/survive-the-talk/.env; set +a; cd /opt/survive-the-talk/current/server && JWT=$(.venv/bin/python -c "from auth.jwt_service import issue_token; print(issue_token(1))") && curl -sS -H "Authorization: Bearer $JWT" http://localhost:8000/scenarios | .venv/bin/python -m json.tool | grep -A4 briefing | head -30'`
  - _Expected:_ 200; each `data[]` item has `"briefing": {"vocabulary": "...", "context": "...", "expect": "..."}`
  - _Actual:_
- [ ] **Error / unauth path produces the `{error}` envelope.**
  - _Command:_ `curl -sS http://167.235.63.129/scenarios`
  - _Expected:_ 401 + `{"error": {"code": "AUTH_UNAUTHORIZED", ...}}`
  - _Actual:_
- [ ] **DB side-effect verified.** N/A — read-only payload change; no rows written, no schema change.
- [ ] **DB backup taken BEFORE deploy.** N/A — no migration (the standard pre-deploy auto-backup in `deploy-server.yml` still runs).
- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 50 --since "5 min ago"` — no ERROR / Traceback for the requests above.
  - _Proof:_

## Pixel 9 Smoke Gate (on-device validation — owed before review → done)

**Agent prep (before Walid touches the phone — agent runs these, not Walid):**
1. Deploy the server slice; build + hand over the new APK (the old APK ignores `briefing` harmlessly — defensive parse — but only the new one shows the screen).
2. Reset first-attempt state for user_id=1 on TWO scenarios — The Waiter (no content warning) and The Mugger (has one). Back up the rows first, then delete them (restores `attempts=0` AND clears the hub stats line — expected):
   `ssh root@167.235.63.129` → `/opt/survive-the-talk/current/server/.venv/bin/python -c "import sqlite3; c=sqlite3.connect('/opt/survive-the-talk/data/db.sqlite'); rows=list(c.execute(\"SELECT * FROM user_progress WHERE user_id=1 AND scenario_id IN ('waiter_easy_01','mugger_medium_01')\")); print(rows); c.execute(\"DELETE FROM user_progress WHERE user_id=1 AND scenario_id IN ('waiter_easy_01','mugger_medium_01')\"); c.commit()"`
   (paste the printed backup rows into the gate record so they can be restored on request; verify the exact scenario ids against the DB first)
3. If the daily call quota is exhausted, apply the standard quota reset (backup → flip today's rows to `failed`).

**Ready-to-play script (responses approximate — live LLM; the briefing screen itself is deterministic):**

1. Open the app → hub. The Waiter card shows NO stats line (reset worked). Tap the **phone icon** on The Waiter.
   💰 **MONEY MOMENT #1:** instead of the call starting, the dark **briefing screen** fades in — waiter avatar + title + "Context" / "What to expect" / "Key phrases" sections + green **Call** button. No connecting screen, no audio.
2. Tap the **back arrow**. → Back on the hub, NO call started, quota untouched.
3. Tap the **phone icon** on The Waiter again → briefing appears again (still never attempted). Tap **Call**.
   → Normal call start (no content warning on the waiter): connecting → Tina answers. Say: **"Hi, I'd like to order the soup of the day."** → she responds in character. Then hang up (red button), let Call Ended → Debrief play out, back-arrow to the hub.
4. Tap the **phone icon** on The Waiter a third time.
   💰 **MONEY MOMENT #2:** the briefing does NOT appear — the call starts directly (session memory covers the stale list). Hang up immediately, back out to the hub.
5. Tap the waiter **card itself** (name/avatar area, not the phone icon).
   💰 **MONEY MOMENT #3:** the same briefing screen opens in browse mode — re-readable any time. Back-arrow out.
6. Tap the **phone icon** on The Mugger (reset + content-warned).
   💰 **MONEY MOMENT #4:** briefing first → tap **Call** → THEN the "HEADS UP / Buckle up" sheet slides up → tap **Not now** → hub, no call burned.
7. Kill the app completely, reopen → tap the **phone icon** on The Waiter: no briefing (server now reports attempts ≥ 1 — the restart path trusts the server). Hang up if it connects.

Gate boxes: ☐ #1 briefing-before-first-call ☐ #2 session skip ☐ #3 card-tap browse ☐ #4 briefing→warning order ☐ #7 server-truth after restart ☐ no crash / no layout overflow on the briefing screen.

## Dev Notes

### Context & flow map (exact, file:line)

Today's call-icon chain — `client/lib/features/scenarios/views/scenario_list_screen.dart`:
`ScenarioCard.onCallTap` (`:220`) → `_ListState._onCallTap` (`:257`): `_initiating` debounce (`:258`) → `showContentWarningSheet` if `contentWarning != null` (`:259-263`) → `CallRepository.initiateCall(scenarioId, difficulty)` (`:267-272`) → push `CallScreen` via **root** Navigator, `fullscreenDialog` (`:276-281`, ADR 003 §Tier 1) → error routing: `NETWORK_ERROR` → `NoNetworkScreen`, `CALL_LIMIT_REACHED` → `PaywallSheet.show`, default → red `AppToast` (`:282-308`).
Card tap: `_onCardTap` (`:320-322`) → `context.push('/briefing/<id>')` → `BriefingPlaceholderScreen`.
This story inserts the briefing gate at the TOP of `_onCallTap` and re-points `_onCardTap` at the same screen+confirm contract. Nothing else in the chain moves.

### Data contract

Server row → list item (new field in **bold**): `id, title, is_free, rive_character, language_focus, content_warning, best_score, attempts, end_phrases,` **`briefing`**.
Briefing object (authored YAML → `json.dumps` at seed → `_safe_json_load` at serve), e.g. the waiter (`server/pipeline/scenarios/the-waiter.yaml:222-225`):
```yaml
briefing:
  vocabulary: "\"I'd like...\", \"soup of the day\", \"grilled / fried\""
  context: "You're ordering food at a restaurant. The waitress is not in a good mood."
  expect: "The waitress is impatient — order clearly and don't take too long deciding."
```
Authoring rules (scenario-authoring-template.md §8): ≤3 vocabulary items, no checkpoint/exit-line spoilers, written in English, clinical register (not the character's voice). Section→key mapping: Context→`context`, What to expect→`expect`, Key phrases→`vocabulary`.

### Layout spec (default — Walid iterates on-device)

Dark `Scaffold` (`AppColors.background`), `SafeArea`, h-pad `AppSpacing.screenHorizontal` (20), v-pad `screenVerticalList` (30). Column: back-arrow row (placeholder's exact `canPop ? pop : go(root)` + `Semantics(button, 'Back to scenarios')`, ≥44px) → `Expanded(SingleChildScrollView(...))`: centered avatar `avatarLarge` (100, `ClipOval`, asset + `errorBuilder` fallback per `scenario_card.dart:_Avatar`) → title (inline `TextStyle(fontFamily: AppTypography.fontFamily, fontSize: 24, fontWeight: w700)`, `textPrimary`, centered) → sections (left-aligned: header `AppTypography.headline` + `Semantics(header: true)` / gap / `AppTypography.body` `textPrimary`, local `_kSectionGap`-style consts) → pinned bottom CTA outside the scroll: full-width `ElevatedButton` styled exactly like the content-warning "Pick up" (`content_warning_sheet.dart:241-267`: accent bg, `AppColors.background` fg, StadiumBorder, `Icons.phone_outlined` + 'Call', 14/700) with bottom safe-area padding. Copy ('Call', section header wording) is a soft default — flag changes to Walid, don't ask permission.

### What NOT to do (hard guardrails)

1. **NO migration, NO YAML edits.** The `briefing` column + all 6 authored briefings exist. Editing any YAML `briefing` content invalidates that scenario's calibration-ledger `scenario_hash` (briefing is hashed — `calibration_engine.py:1400`) and forces revalidation; content changes are out of scope.
2. **Do NOT fetch `GET /scenarios/{id}` from the client.** Spoiler-heavy payload (base_prompt, success_criteria) + needless round-trip. Decision A.
3. **Do NOT persist briefing-seen to storage.** No `shared_preferences`/sqflite exists in this app (flutter_secure_storage is onboarding/auth-scoped); local caching is Epic 9's. Server `attempts` + the in-memory session set are the whole mechanism.
4. **Do NOT touch the content-warning sheet** or weaken its every-time rule (`content-warning-dialog.md` is LAW). Sequence after the briefing, never merge.
5. **Do NOT move call initiation into BriefingScreen.** It stays a render+confirm surface popping a bool; `_ListState` owns the chain (test seams `callRepository`/`callScreenBuilder` depend on it).
6. **Do NOT add a bloc** to BriefingScreen (zero async state — CallEndedScreen/DebriefScreen precedent, and those at least had timers).
7. **Do NOT split/parse the vocabulary string** — render verbatim (authored prose with quotes/commas inside).
8. **Do NOT add color tokens or hex literals** outside `core/theme/` (theme_tokens_test scans `lib/`); compose inline TextStyles only where no token fits.
9. **Do NOT touch the debrief surface** (report-icon path, DebriefScreen, debrief payloads) — Story 7.5 owns the debrief overhaul; 7.4 must not collide.
10. **Do NOT reintroduce any per-scenario difficulty** coupling (global-only ruling, Story 6.28).

### Edge cases the review WILL probe (handle in dev, not in review)

- **Paywall/cap path:** briefing confirm → POST → 403 `CALL_LIMIT_REACHED` → PaywallSheet; session mark NOT set (initiate failed) so the briefing re-shows on the next tap — correct: no call ever started.
- **Double-tap classes:** card/icon double-push (widened `_initiating` span), CTA/back double-pop (pop-once guard — the second pop would dismiss the HUB).
- **`context.mounted` after every await** (`:262`/`:273` pattern), including after the briefing push resolves.
- **Empty-section rendering:** test fixtures use `briefing: {vocabulary: '', context: '', expect: ''}` — all-empty must mean NO gate and NO bare headers (7.3 review precedent: empty areas section hidden).
- **a11y:** textScaler 1.5 @ 320×568 overflow-free; decorative text excluded from semantics only where double-announce occurs (7.3 `ExcludeSemantics` patch precedent).
- **Old-APK back-compat:** old `Scenario.fromJson` ignores the new key (no strict keys) — server can deploy first, no coordination needed.

### Previous story intelligence (7.3 / 7.2)

- **7.3 (debrief screen):** StatefulWidget-no-bloc + constructor seams pattern validated; review flagged a11y overflow ellipsis, `ExcludeSemantics` on decorative captions, empty-array sections rendering bare headers, and untested route-handoff code — all four classes apply here (AC-C2/C8 + Task 5.4 cover them). Tests: 320×568 surface, explicit `pump(Duration)` (never `pumpAndSettle` — irrelevant here, no timers, but keep the habit), `FlutterSecureStorage.setMockInitialValues({})` in setUp, mocktail repos.
- **7.2 (end_phrases):** the canonical server-content-field recipe — but 7.4's is SMALLER: the column/seed/upsert plumbing already exists; only model+route+tests change. The 7.2 review added seeder fail-fast shape validation after the fact — Task 2 bakes it in up-front.
- **House format:** every commit per stage, list-format messages, no Co-Authored-By, sprint-status flip in the same commit as the stage.

### Git intelligence

Recent commits confirm the cadence and surfaces: `0c7d2fb` (7.3 review patches + done flip), `e7e2f0e` (7.3 dev — debrief screen + BS-7), `438d891` (7.3 spec). Untracked `.review-*.diff` files + `find.exe.stackdump` at repo root are review-agent artifacts — do not commit them with this story.

### Project structure notes

- New: `client/lib/features/briefing/views/briefing_screen.dart`, `client/test/features/briefing/views/briefing_screen_test.dart`.
- Modified: `client/lib/features/scenarios/models/scenario.dart`, `client/lib/features/scenarios/views/scenario_list_screen.dart`, `client/lib/app/router.dart`, `server/models/schemas.py`, `server/api/routes_scenarios.py`, `server/db/seed_scenarios.py`, `server/tests/test_scenarios.py` (+ seeder tests file), model/list-screen test files.
- Deleted: `client/lib/features/briefing/views/briefing_placeholder_screen.dart`.
- Test-count baseline: client 489, server 880 (post-7.3/6.28).

### References

- Epic AC source: `_bmad-output/planning-artifacts/epics.md:1372-1394` (Story 7.4) ; FR14 `prd.md:431` ; FR38 (content warnings) `prd.md:438`.
- ADR-004 server-driven content: `_bmad-output/planning-artifacts/adr/004-content-delivery.md` (briefings listed in slice 1).
- Briefing authoring: `_bmad-output/planning-artifacts/scenario-authoring-template.md` §8 + Step 7.
- Content-warning law: `_bmad-output/planning-artifacts/ux-decisions/content-warning-dialog.md`.
- Shipped patterns: `content_warning_sheet.dart` (await-bool gate + CTA styling), `debrief_screen.dart` (`_SectionHeader`, section gaps, a11y), `scenario_card.dart` (`_Avatar`, semantics), `router.dart` (`_fadePage`, route table).
- Server precedents: `routes_scenarios.py` (`_safe_json_load` + ValidationError net), `seed_scenarios.py:82-111` (end_phrases validation shape to mirror), `queries.py:239-263` (`SELECT s.*` — already carries briefing).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

| Date | Change |
|---|---|
| 2026-06-12 | Story 7.4 spec created (create-story) — exhaustive context pass: briefing column/YAMLs already shipped (5.1), placeholder route already wired, gate design resolved (Decisions A-D as defaults). Status `backlog` → `ready-for-dev`. |
