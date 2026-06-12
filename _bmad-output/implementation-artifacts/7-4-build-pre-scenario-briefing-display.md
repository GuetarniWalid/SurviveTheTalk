# Story 7.4: Build Pre-Scenario Briefing Display

Status: review

## ⚠️ Source-Document Drift — READ FIRST

| Stale statement (epics.md / architecture.md / UX spec) | Current truth (code wins) | Evidence |
|---|---|---|
| `briefing_text` column (architecture.md §scenarios table, epics.md AC "displays the scenario's `briefing_text`") | The column shipped in Story 5.1 as **`briefing`** — a JSON object `{vocabulary, context, expect}` stored as TEXT, `NOT NULL`. There is NO `briefing_text` column and none must be added. | `server/db/migrations/004_scenarios_and_user_progress.sql`, `server/db/seed_scenarios.py:126`, `server/pipeline/scenarios/the-waiter.yaml:222-225` |
| "section-title (14px SemiBold) for headers" (epic AC4 / ux-design-specification.md typography table) | SUPERSEDED by the 2026-06-12 design pass (Walid-validated, see Decision E): section labels are 12/500 UPPERCASE eyebrow labels in `textSecondary` with +1.0 letter-spacing — NOT bold white headers. Epic AC4's intent ("established typography on the dark theme") is honored via tokens + composed Inter styles. | Decision E + §Layout spec below |
| "a briefing screen **or dialog**" (epic AC1) | The app already committed to a **screen**: route `/briefing/:scenarioId` + `BriefingPlaceholderScreen` ("Stub screen used until Story 7.4 ships the real pre-scenario briefing") + the ScenarioCard's whole-card tap with semantic hint "View briefing" already navigates there. This story replaces the placeholder; it does not introduce a dialog. | `client/lib/app/router.dart:192-200`, `client/lib/features/briefing/views/briefing_placeholder_screen.dart:9`, `client/lib/features/scenarios/views/widgets/scenario_card.dart:37-47` |
| No Figma frame exists for the briefing screen (checked `figma-export/.figma/` — no `*brief*` extract) | The design was produced by a dedicated research pass and VALIDATED by Walid 2026-06-12 (Decision E) — the §Layout spec + §Copy deck are BINDING, not a derived default. On-device iteration remains possible post-implementation but starts from the validated design. | Decision E |

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
Briefing FIRST, content warning AFTER confirm, for first-timers on warned scenarios (mugger/cop/landlord): briefing screen → "Pick up" → "HEADS UP / Buckle up" sheet → "Pick up" → POST. Two consecutive "Pick up" taps on warned first attempts is INTENTIONAL (same fiction, same action). The warning's UX decision record is LAW (re-appears every time, no "don't show again", `content-warning-dialog.md`) — the briefing never absorbs or replaces it. Returning users keep today's flow untouched: warning sheet (if any) → POST.

### Decision E — Visual + copy design: "The Handler's Brief" (RESOLVED — Walid validated 2026-06-12)
A dedicated research pass (6 parallel researchers: acclaimed game mission briefings / award-winning wellness pre-session screens / speaking-practice apps / dark-minimal design canon / UX-writing masters / detail→start pattern anatomy → distilled rulebook → 3 competing concepts → 3-judge panel: taste, soul, reality) produced the winning design, corrected per the judges and validated by Walid. The full binding spec is §"Layout spec" + §"Copy deck" in Dev Notes — it REPLACES any earlier layout sketch. Key arbitrations baked in: the masked-phone-number prop was REJECTED (2/3 judges: reads as a glitch, anxiety amplifier); all color discipline is expressed in AppColors tokens (inline hex would fail `theme_tokens_test`); ONE new token `AppColors.hairline` is sanctioned with its full gate cost. Signature references: Hitman briefings (clinical second-person register, size-contrast-as-cinema), MGSV episode cards (fixed-lockup ritual), Speak (3 bounded blocks, quoted speakable phrases), Mela (weight-in-prose emphasis, no chips), Flighty (one rail, above-the-fold discipline), Persona 5/Opal (one flat consequence line at the threshold).

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
5. **AC-C2 — real BriefingScreen ("The Handler's Brief", Decision E).** `BriefingPlaceholderScreen` is replaced by `BriefingScreen` (StatefulWidget, no bloc — state is the pop-once guard + the scroll controller for the conditional hairline). One left alignment rail for everything; nothing centered. Top to bottom: back arrow 44×44 top-left (pop `false`; `canPop ? pop : go(root)` fallback kept) → 72px circle character photo (`assets/images/characters/<riveCharacter>.jpg`, `errorBuilder` → flat `avatarBg` circle, `Semantics` label `'<title>, photo'`) → kicker **`INCOMING CALL`** (12/500 uppercase, +1.0 letter-spacing, `textSecondary`) → scenario title (`scenario.title`, 24/700 `textPrimary`, height 1.2, maxLines 2 ellipsis, `Semantics(header: true)`) → fact line **`Live voice call · English only · No script`** (caption 13/400 `textSecondary`) → the dossier triad in fixed order, three IDENTICAL eyebrow+prose sections wrapped in `MergeSemantics`: **`THE SITUATION`** → `briefing['context']` (16/400 `textPrimary`, height 1.5), **`WHAT TO EXPECT`** → `briefing['expect']` (16/400), **`SAY THIS`** → `briefing['vocabulary']` **verbatim** at **16/500** (weight + last-position are the ONLY emphasis — no box, no chips, no parsing; the authored quotation marks are the chips). A section whose value is null/empty/whitespace is hidden entirely (no bare eyebrow). Zero boxes, cards, icons, or dividers in the body — the 8px-inside / 32px-between spacing ratio does all grouping. Pinned threshold footer: conditional 1px `AppColors.hairline` top edge (visible ONLY when content actually scrolls beneath the footer) → stakes line **`They can hang up on you. So can you.`** (caption 13/400 *italic* `textSecondary`, no maxLines clamp) → 12px → the locked CTA pill (full-width, StadiumBorder, `AppColors.accent`, `Icons.phone_outlined`, label **"Pick up"** 14/700 dark text, height ≥48) that pops `true` exactly once.
6. **AC-C3 — route carries the Scenario.** The `/briefing/:scenarioId` GoRoute passes the full `Scenario` via `state.extra` (both entries push with `extra: scenario`) and gains a route-level `redirect` → `AppRoutes.root` when `extra` is not a `Scenario` (deep-link / refresh entry — graceful bounce, no fallback widget).
7. **AC-C4 — first-attempt gate (epic AC1).** Tapping the **call icon** on a scenario with `attempts == 0` that has briefing content and was not initiated this session pushes `BriefingScreen` BEFORE any call initiation — no `POST /calls/initiate` fires until the user confirms.
8. **AC-C5 — confirm proceeds normally (epic AC2).** Briefing pops `true` → the unchanged chain runs: content-warning sheet if `contentWarning != null` (Decision D order) → `POST /calls/initiate` (with global difficulty) → `CallScreen` pushed on the root navigator (connecting animation untouched). Pop `false`/back → hub, zero network calls.
9. **AC-C6 — skip for returning users (epic AC3).** `attempts > 0` OR already initiated this session OR no briefing content → call-icon tap runs the chain directly (content warning still shown when applicable), byte-identical to today's behavior.
10. **AC-C7 — browse entry.** Whole-card tap pushes the same screen with the same confirm contract (confirm from browse starts the call chain too). Double-tap on the card or the call icon never double-pushes the route, and double-tap on the CTA / back never double-pops (a second pop would dismiss the hub).
11. **AC-C8 — design-system + a11y compliance (epic AC4 + Decision E).** Exactly ONE new color token: `AppColors.hairline = Color(0x14FFFFFF)` added with its full gate cost (values list + `theme_tokens_test` count assertion bumped + the UX-DR1 governance note, per the house token procedure). Two-ink discipline in token terms: text colors are ONLY `textPrimary` (title + the 3 server strings) and `textSecondary` (all chrome: kicker, eyebrows, fact line, stakes line); `AppColors.accent` is referenced exactly ONCE (the pill fill — green is never a text/icon tint elsewhere); `destructive`/`warning`/`statusCompleted` zero references. Zero new typography tokens (inline composed Inter styles per the `_DifficultyHubLine`/content-warning-sheet precedent). ≥44px touch targets (exactly two interactive elements: back arrow + pill), `Semantics` on back/CTA/title-header/sections, no RenderFlex overflow at 320×568 with `textScaler` 1.5 **including the stakes line wrapping to 2 lines** (footer grows, body scrolls under it — never compress spacing/line-height to avoid scrolling).

## Tasks / Subtasks

- [x] **Task 1 — Server: expose `briefing` on the list** (AC-S1, AC-S2)
  - [x] 1.1 `models/schemas.py`: add `briefing: dict | None = None` to `ScenarioListItem`; update the class docstring (it currently documents briefing as detail-only).
  - [x] 1.2 `api/routes_scenarios.py` list constructor: `briefing=_safe_json_load(row["briefing"], scenario_id=row["id"], column="briefing")` (the SQL already `SELECT s.*` — no query change).
  - [x] 1.3 Tests (`tests/test_scenarios.py`): list items carry the 3-key briefing dict (seeded fixture); corrupt-JSON briefing → 500 SCENARIO_CORRUPT; valid-JSON-wrong-shape (e.g. `"[1,2]"`) → 500 SCENARIO_CORRUPT. Mirror the existing `end_phrases` test trio.
- [x] **Task 2 — Server: seeder shape validation** (AC-S3)
  - [x] 2.1 `db/seed_scenarios.py`: validate `doc["briefing"]` before the `json.dumps` at line 126 — dict, keys exactly `{vocabulary, context, expect}`, all values `str` (empty OK). `ValueError` messages name the scenario id, matching the `end_phrases` / `resolve_patience_config` convention.
  - [x] 2.2 Tests: non-dict / missing key / extra key / non-string value each raise; confirm all 6 shipped YAMLs still seed (existing seed tests cover the happy path).
  - [x] 2.3 Run `ruff check . && ruff format --check . && pytest` (in-sandbox, warmed — full suite, ~880+ expected green incl. `test_migrations`). → **884 passed**, ruff check + format clean.
- [x] **Task 3 — Client: model** (AC-C1)
  - [x] 3.1 `scenario.dart`: `briefing` field + defensive `fromJson` parse (copy the `endPhrases` block shape) + `hasBriefingContent` getter + doc comment citing Story 7.4.
  - [x] 3.2 Model tests: present / absent / non-map / mixed-type entries filtered / all-empty → `hasBriefingContent == false`. → 6 new tests, 16/16 green.
- [x] **Task 4 — Client: BriefingScreen + router** (AC-C2, AC-C3, AC-C8)
  - [x] 4.1 Add `AppColors.hairline = Color(0x14FFFFFF)` to `app_colors.dart` with the UX-DR1 governance note; bump the `theme_tokens_test` count assertion + values list in the same change. → token #14, both tests bumped.
  - [x] 4.2 Create `client/lib/features/briefing/views/briefing_screen.dart` per the §Layout spec (local layout consts like DebriefScreen — `_kAvatarSize 72`, gaps 16/8/8/40/32/12; reuse `AppSpacing.screenHorizontal`; the four composed Inter styles defined once at the top of the file; the §Copy deck strings as consts UNDER the banned-copy comment block, verbatim).
  - [x] 4.3 `router.dart`: swap the briefing GoRoute to `BriefingScreen(scenario: state.extra! as Scenario)` + route-level `redirect` guarding non-`Scenario` extra → root. Keep `_fadePage` (the 500ms fade is the title-card beat — no further motion ever).
  - [x] 4.4 Delete `briefing_placeholder_screen.dart` (+ its test file if one exists — none existed; `scenario_list_screen_test.dart` stub route upgraded to the pop-a-bool contract, compiles).
  - [x] 4.5 Widget tests (`test/features/briefing/views/briefing_screen_test.dart`): renders avatar/kicker/title/fact line/3 eyebrow sections in order; vocabulary rendered verbatim in exactly one Text at w500; hides empty sections (all-empty fixture → no bare eyebrows); stakes line + "Pick up" pill present; CTA pops `true`; back pops `false`; CTA double-tap pops once; hairline hidden when content fits / visible when it scrolls; 320×568 @ textScaler 1.5 zero RenderFlex overflow incl. 2-line stakes wrap; semantics (title header flag, merged sections, back + pill buttons); review greps per AC-C8 (accent referenced once, destructive/warning zero, each server field feeds exactly one Text with no string operations). → 17 tests green.
- [x] **Task 5 — Client: hub gate** (AC-C4..C7)
  - [x] 5.1 `scenario_list_screen.dart`: extract `_startCall(BuildContext, Scenario)` from `_onCallTap` (content-warning → POST → push CallScreen — chain order untouched); add `_initiatedThisSession` set, marked right after `initiateCall` succeeds. **Flag choreography (precise — avoid a self-block):** BOTH handlers (`_onCallTap`, `_onCardTap`) start with `if (_initiating) return; setState(() => _initiating = true);`, run their flow (briefing await included — so double-taps can't double-push the route), and reset the flag in `finally`. `_startCall` itself contains NO `_initiating` check or set — it is only ever invoked with the flag already held by its caller.
  - [x] 5.2 `_onCallTap`: gate per Decision B → `context.push<bool>('${AppRoutes.briefing}/${scenario.id}', extra: scenario)` → `ready != true → return` → `context.mounted` check → `_startCall`.
  - [x] 5.3 `_onCardTap`: same push + same continuation (replaces the bare `context.push`).
  - [x] 5.4 Widget tests (extend `scenario_list_screen_test.dart`, mock-router harness already exists): first-attempt call tap pushes briefing + NO POST before confirm; confirm → POST + CallScreen; confirm on warned scenario → warning sheet between briefing and POST; decline → no POST; `attempts > 0` → direct chain (no briefing); null/empty briefing → direct chain; session mark → second call tap after a successful initiate skips the briefing despite stale `attempts == 0`; card tap → briefing + confirm continues. → 10 tests green (null + all-empty as two cases, + the paywall-edge probe: failed POST does NOT set the session mark, briefing re-shows).
- [ ] **Task 6 — Gates, deploy, flip**
  - [x] 6.1 `cd client && flutter analyze` → "No issues found!"; `flutter test` → all pass (489 existing + ~18 new — indicative). → **analyze clean, 522 passed** (+33: 6 model, 17 screen, 10 hub).
  - [x] 6.2 Server gates (Task 2.3) green. → ruff check + format clean, **pytest 884** (+4).
  - [x] 6.3 Deploy server to VPS (normal release flow — no migration, no .env change), `systemctl restart pipecat.service`, fill the Smoke Test Gate boxes below. → CI run 27408638078 deployed `eb0e917`, service restarted by the release flow, all 6 gate boxes filled (4 verified + 2 N/A).
  - [x] 6.4 Flip story + `sprint-status.yaml` → `review`; commit (one commit for the dev stage, list format, no Co-Authored-By).

## Smoke Test Gate (Server / Deploy Stories Only)

> Server slice = list-payload field only: no migration, no writes, no .env change. DB boxes are N/A with rationale.

- [x] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ 2026-06-12 — `Active: active (running) since Fri 2026-06-12 10:01:20 UTC`; `/health` → `{"status":"ok","db":"ok","git_sha":"eb0e9174a32e88eab68ae977a0a22acf012725ea"}` = the dev commit `eb0e917`. CI run 27408638078 green (Test 2m29s + Deploy 30s).
- [x] **Happy-path endpoint round-trip.** Every list item carries the 3-key briefing object.
  - _Command:_ `ssh root@167.235.63.129 'set -a; . /opt/survive-the-talk/.env; set +a; cd /opt/survive-the-talk/current/server && JWT=$(.venv/bin/python -c "from auth.jwt_service import issue_token; print(issue_token(1))") && curl -sS -H "Authorization: Bearer $JWT" http://localhost:8000/scenarios | .venv/bin/python -m json.tool | grep -A4 briefing | head -30'`
  - _Expected:_ 200; each `data[]` item has `"briefing": {"vocabulary": "...", "context": "...", "expect": "..."}`
  - _Actual:_ 200; count=6; all 6 items (`waiter_easy_01`, `girlfriend_medium_01`, `mugger_medium_01`, `cop_hard_01`, `cop_interrogation_01`, `landlord_hard_01`) carry exactly the keys `{vocabulary, context, expect}` with authored content (programmatic key-set check: `keys-ok: True` ×6).
- [x] **Error / unauth path produces the `{error}` envelope.**
  - _Command:_ `curl -sS http://167.235.63.129/scenarios`
  - _Expected:_ 401 + `{"error": {"code": "AUTH_UNAUTHORIZED", ...}}`
  - _Actual:_ HTTP 401 + `{"error":{"code":"AUTH_UNAUTHORIZED","message":"Missing or invalid token."}}`
- [x] **DB side-effect verified.** N/A — read-only payload change; no rows written, no schema change.
- [x] **DB backup taken BEFORE deploy.** N/A — no migration (the standard pre-deploy auto-backup in `deploy-server.yml` still runs).
- [x] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 50 --since "5 min ago"` — no ERROR / Traceback for the requests above.
  - _Proof:_ 2026-06-12 10:05 UTC — grep for `error|traceback` over the last 50 lines / 5 min returned nothing (requests above included).

## Pixel 9 Smoke Gate (on-device validation — owed before review → done)

**Agent prep (before Walid touches the phone — agent runs these, not Walid):**
1. Deploy the server slice; build + hand over the new APK (the old APK ignores `briefing` harmlessly — defensive parse — but only the new one shows the screen).
2. Reset first-attempt state for user_id=1 on TWO scenarios — The Waiter (no content warning) and The Mugger (has one). Back up the rows first, then delete them (restores `attempts=0` AND clears the hub stats line — expected):
   `ssh root@167.235.63.129` → `/opt/survive-the-talk/current/server/.venv/bin/python -c "import sqlite3; c=sqlite3.connect('/opt/survive-the-talk/data/db.sqlite'); rows=list(c.execute(\"SELECT * FROM user_progress WHERE user_id=1 AND scenario_id IN ('waiter_easy_01','mugger_medium_01')\")); print(rows); c.execute(\"DELETE FROM user_progress WHERE user_id=1 AND scenario_id IN ('waiter_easy_01','mugger_medium_01')\"); c.commit()"`
   (paste the printed backup rows into the gate record so they can be restored on request; verify the exact scenario ids against the DB first)
3. If the daily call quota is exhausted, apply the standard quota reset (backup → flip today's rows to `failed`).

> **Agent prep — DONE 2026-06-12 (post-deploy `eb0e917`):**
> - **user_progress reset applied.** Backup of the deleted rows (for restore on request): `[{'user_id': 1, 'scenario_id': 'waiter_easy_01', 'best_score': 100, 'attempts': 24, 'created_at': '2026-06-09T08:14:07Z', 'updated_at': '2026-06-11T16:33:57Z'}]` — `mugger_medium_01` had NO row (already never-attempted). Both ids verified against the DB; both now read `attempts == 0` for user 1 (waiter card shows no stats line — expected).
> - **Quota:** 0/3 quota-counting `call_sessions` today for user 1 — no reset needed, full allowance available.
> - **APK:** release build from `eb0e917` at `client/build/app/outputs/flutter-apk/app-release.apk` — install this one (the old build ignores `briefing` harmlessly but never shows the screen).

**Ready-to-play script (responses approximate — live LLM; the briefing screen itself is deterministic):**

1. Open the app → hub. The Waiter card shows NO stats line (reset worked). Tap the **phone icon** on The Waiter.
   💰 **MONEY MOMENT #1:** instead of the call starting, the dark **briefing screen** fades in — everything aligned on the LEFT edge: small waiter photo (72px), grey caps **INCOMING CALL** over the big white **The Waiter**, the line `Live voice call · English only · No script`, then three grey caps labels **THE SITUATION / WHAT TO EXPECT / SAY THIS** with white text under each, and at the bottom the italic line *They can hang up on you. So can you.* above the green **Pick up** pill. No connecting screen, no audio, nothing centered, no boxes.
2. Tap the **back arrow**. → Back on the hub, NO call started, quota untouched.
3. Tap the **phone icon** on The Waiter again → briefing appears again (still never attempted). Tap **Pick up**.
   → Normal call start (no content warning on the waiter): connecting → Tina answers. Say: **"Hi, I'd like to order the soup of the day."** → she responds in character. Then hang up (red button), let Call Ended → Debrief play out, back-arrow to the hub.
4. Tap the **phone icon** on The Waiter a third time.
   💰 **MONEY MOMENT #2:** the briefing does NOT appear — the call starts directly (session memory covers the stale list). Hang up immediately, back out to the hub.
5. Tap the waiter **card itself** (name/avatar area, not the phone icon).
   💰 **MONEY MOMENT #3:** the same briefing screen opens in browse mode — re-readable any time, identical layout (the "INCOMING CALL" ritual replays). Back-arrow out.
6. Tap the **phone icon** on The Mugger (reset + content-warned).
   💰 **MONEY MOMENT #4:** briefing first → tap **Pick up** → THEN the "HEADS UP / Buckle up" sheet slides up (two "Pick up" buttons in a row is intentional — same fiction) → tap **Not now** → hub, no call burned.
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

### Layout spec — "The Handler's Brief" (BINDING — Walid-validated 2026-06-12, Decision E)

The screen masquerades as the phone's own incoming-call card; the briefing IS part of the fiction. One left alignment rail at x = `AppSpacing.screenHorizontal` (20) for EVERYTHING above the pill. Dark `Scaffold` (`AppColors.background`). Body = `Column[ Expanded(SingleChildScrollView(controller: …, child: contentColumn)), ThresholdFooter inside bottom SafeArea ]`.

**Type styles (defined once at the top of the file, Inter only, all via `AppTypography.fontFamily`):**
- `_eyebrow` 12/500, UPPERCASE strings, letterSpacing 1.0, `textSecondary` — kicker + the 3 section labels
- `_title` 24/700, height 1.2, `textPrimary`
- `_body` 16/400, height 1.5 (24px on-grid leading), `textPrimary` — + a w500 variant for vocabulary
- `_caption` 13/400, `textSecondary` — fact line; italic variant for the stakes line

**Content column (CrossAxisAlignment.start), top to bottom:**
1. Top bar: back-arrow IconButton 44×44, 24px glyph `textPrimary`, glyph optically aligned to the rail (compensate IconButton's internal padding), `Semantics(button, 'Back to scenarios')`. Nothing else — no app-bar title.
2. 16 → **hero**: 72px circle (`ClipOval`, `assets/images/characters/<riveCharacter>.jpg`, `errorBuilder` → flat `avatarBg` circle per `scenario_card.dart:_Avatar`), left on the rail, non-interactive, `Semantics(label: '<title>, photo')`. The ONLY pictorial element on screen.
3. 16 → **kicker** `INCOMING CALL` (`_eyebrow`). Identical on every scenario, forever — the ritual (a retry reads as "they're calling again", not remediation; in browse mode the small fiction is accepted).
4. 8 → **title** `scenario.title` (`_title`, maxLines 2, ellipsis, `Semantics(header: true)`). The 12-caps → 24/700 size jump is the screen's entire cinema budget.
5. 8 → **fact line** `Live voice call · English only · No script` (`_caption`, ' · ' separators). Logistics live here and ONLY here.
6. 40 → **dossier triad**: one reusable `_BriefingSection(label, body, {weight})` wrapped in `MergeSemantics` (eyebrow → 8 → body; server string fed RAW into exactly one `Text`): `THE SITUATION` → context (16/400) → 32 → `WHAT TO EXPECT` → expect (16/400) → 32 → `SAY THIS` → vocabulary verbatim at **16/500** (block-level weight bump + last position = the only differentiation; no box, no hairline, no parsing — the authored quotation marks are the chips; nearest the CTA = freshest in working memory at tap). Empty/whitespace value → section omitted entirely.

**Threshold footer (pinned, `background`, padding LTRB(20,12,20,16) + bottom SafeArea inset):**
- Top edge: 1px `AppColors.hairline` line, rendered ONLY when scroll content actually extends beneath the footer (`maxScrollExtent > 0` via the scroll controller; re-check on metrics changes). The single permitted line on screen.
- **Stakes line** `They can hang up on you. So can you.` (`_caption` italic, left on the rail, NO maxLines clamp) → 12 → the locked pill (full-width `ElevatedButton`, StadiumBorder, `accent` bg, `background` fg, `Icons.phone_outlined` + 'Pick up', 14/700, height ≥48). Tapping = binary flip into the existing call flow (the content-warning sheet, when owed, belongs to that flow — no dialog, no countdown, no "ready?" interstitial).

**Viewport contract:** hero + lockup + fact line + full triad + stakes line above the fold at textScaler 1.0 on a 360×800 baseline; at 320×568 or textScaler 1.5 the body scrolls under the footer and the hairline appears — NEVER compress spacing or line-height to avoid scrolling; the whitespace rhythm IS the calm. With 3 short server strings the screen may look "empty" on tall displays — that restraint is the design, not unfinished work; do not add furniture.

**Fallback (pre-agreed, only if the Pixel 9 gate proves the footer too tall at large text scale):** move the stakes line to be the LAST SCROLL CHILD and keep a pill-only constant-height footer. Do not pre-emptively implement this.

### Copy deck (BINDING — exact strings; voice lives ONLY in the kicker + stakes line)

| Slot | String | Style |
|---|---|---|
| Kicker | `INCOMING CALL` | `_eyebrow` |
| Fact line | `Live voice call · English only · No script` | `_caption` |
| Section labels | `THE SITUATION` / `WHAT TO EXPECT` / `SAY THIS` | `_eyebrow` |
| Stakes line | `They can hang up on you. So can you.` | `_caption` italic |
| CTA | `Pick up` | pill, 14/700 |
| Back semantics | `Back to scenarios` | — |
| Avatar semantics | `<title>, photo` | — |

App-owned word budget: 23 — anything new must displace something. Every chrome word must parse instantly for a French A2/B1 learner under stress (present tense, second person, no idioms). Paste this comment block above the const strings (it is the review gate):

```dart
// COPY LINT (Story 7.4 design pass, Walid-validated 2026-06-12). Banned on
// this screen: exclamation marks, question marks, praise ("Good luck",
// "You've got this"), emoji, "don't worry", tips, urgency cues, episode
// numbering. Voice lives ONLY in the kicker + stakes line; everything else
// is flat data. App-owned word budget: 23.
```

### What NOT to do (hard guardrails)

1. **NO migration, NO YAML edits.** The `briefing` column + all 6 authored briefings exist. Editing any YAML `briefing` content invalidates that scenario's calibration-ledger `scenario_hash` (briefing is hashed — `calibration_engine.py:1400`) and forces revalidation; content changes are out of scope.
2. **Do NOT fetch `GET /scenarios/{id}` from the client.** Spoiler-heavy payload (base_prompt, success_criteria) + needless round-trip. Decision A.
3. **Do NOT persist briefing-seen to storage.** No `shared_preferences`/sqflite exists in this app (flutter_secure_storage is onboarding/auth-scoped); local caching is Epic 9's. Server `attempts` + the in-memory session set are the whole mechanism.
4. **Do NOT touch the content-warning sheet** or weaken its every-time rule (`content-warning-dialog.md` is LAW). Sequence after the briefing, never merge.
5. **Do NOT move call initiation into BriefingScreen.** It stays a render+confirm surface popping a bool; `_ListState` owns the chain (test seams `callRepository`/`callScreenBuilder` depend on it).
6. **Do NOT add a bloc** to BriefingScreen (zero async state — CallEndedScreen/DebriefScreen precedent, and those at least had timers).
7. **Do NOT split/parse the vocabulary string** — render verbatim (authored prose with quotes/commas inside); no chips, pills, bullets, or per-phrase rows, and no string operations on ANY server field.
8. **Do NOT add hex literals** outside `core/theme/` (theme_tokens_test scans `lib/`); the ONE sanctioned token addition is `AppColors.hairline` via Task 4.1; all other colors via existing tokens.
9. **Do NOT touch the debrief surface** (report-icon path, DebriefScreen, debrief payloads) — Story 7.5 owns the debrief overhaul; 7.4 must not collide.
10. **Do NOT reintroduce any per-scenario difficulty** coupling (global-only ruling, Story 6.28).
11. **Do NOT add furniture or drama props** (Decision E judges' rulings): no cards/boxes/dividers/per-section icons in the body, no masked phone number, no difficulty meters/XP/progress chrome, no animated/Rive character preview (the in-call reveal must stay unburned), no staggered entry animations (the 500ms route fade is the only motion, ever).
12. **Do NOT soften or fatten the copy**: no words beyond the 23-word deck; green never as a text/icon color; no comfort copy ("anxiety reduction through predictability, never reassurance" — every comforting instinct becomes information or gets cut). The banned-copy comment block is the enforcement.
13. **Do NOT add any step between briefing and call** — no confirmation dialog, countdown, or "ready?" interstitial; "Pick up" flips straight into the existing chain (the content-warning sheet, when owed, is part of that chain, not a new step).

### Edge cases the review WILL probe (handle in dev, not in review)

- **Paywall/cap path:** briefing confirm → POST → 403 `CALL_LIMIT_REACHED` → PaywallSheet; session mark NOT set (initiate failed) so the briefing re-shows on the next tap — correct: no call ever started.
- **Double-tap classes:** card/icon double-push (widened `_initiating` span), CTA/back double-pop (pop-once guard — the second pop would dismiss the HUB).
- **`context.mounted` after every await** (`:262`/`:273` pattern), including after the briefing push resolves.
- **Empty-section rendering:** test fixtures use `briefing: {vocabulary: '', context: '', expect: ''}` — all-empty must mean NO gate and NO bare eyebrows (7.3 review precedent: empty areas section hidden).
- **Footer growth:** the stakes line has no maxLines clamp — at textScaler 1.5 on 320px it wraps to 2 lines and the footer grows (~135px); the body must keep scrolling cleanly under it (explicit wrap test). The pre-agreed fallback (stakes → last scroll child) triggers ONLY on a failed Pixel 9 verdict.
- **Hairline visibility:** content fits → no hairline; content scrolls → hairline appears; re-evaluate on viewport/metrics changes (rotation, text-scale change), not just on first build.
- **a11y:** textScaler 1.5 @ 320×568 overflow-free; decorative text excluded from semantics only where double-announce occurs (7.3 `ExcludeSemantics` patch precedent); the merged section semantics must read label + body as one unit.
- **Old-APK back-compat:** old `Scenario.fromJson` ignores the new key (no strict keys) — server can deploy first, no coordination needed.

### Previous story intelligence (7.3 / 7.2)

- **7.3 (debrief screen):** StatefulWidget-no-bloc + constructor seams pattern validated; review flagged a11y overflow ellipsis, `ExcludeSemantics` on decorative captions, empty-array sections rendering bare headers, and untested route-handoff code — all four classes apply here (AC-C2/C8 + Task 5.4 cover them). Tests: 320×568 surface, explicit `pump(Duration)` (never `pumpAndSettle` — irrelevant here, no timers, but keep the habit), `FlutterSecureStorage.setMockInitialValues({})` in setUp, mocktail repos.
- **7.2 (end_phrases):** the canonical server-content-field recipe — but 7.4's is SMALLER: the column/seed/upsert plumbing already exists; only model+route+tests change. The 7.2 review added seeder fail-fast shape validation after the fact — Task 2 bakes it in up-front.
- **House format:** every commit per stage, list-format messages, no Co-Authored-By, sprint-status flip in the same commit as the stage.

### Git intelligence

Recent commits confirm the cadence and surfaces: `0c7d2fb` (7.3 review patches + done flip), `e7e2f0e` (7.3 dev — debrief screen + BS-7), `438d891` (7.3 spec). Untracked `.review-*.diff` files + `find.exe.stackdump` at repo root are review-agent artifacts — do not commit them with this story.

### Project structure notes

- New: `client/lib/features/briefing/views/briefing_screen.dart`, `client/test/features/briefing/views/briefing_screen_test.dart`.
- Modified: `client/lib/features/scenarios/models/scenario.dart`, `client/lib/features/scenarios/views/scenario_list_screen.dart`, `client/lib/app/router.dart`, `client/lib/core/theme/app_colors.dart` (+ `client/test/core/theme/theme_tokens_test.dart` — hairline token, Task 4.1), `server/models/schemas.py`, `server/api/routes_scenarios.py`, `server/db/seed_scenarios.py`, `server/tests/test_scenarios.py` (+ seeder tests file), model/list-screen test files.
- Deleted: `client/lib/features/briefing/views/briefing_placeholder_screen.dart`.
- Test-count baseline: client 489, server 880 (post-7.3/6.28).

### References

- Epic AC source: `_bmad-output/planning-artifacts/epics.md:1372-1394` (Story 7.4) ; FR14 `prd.md:431` ; FR38 (content warnings) `prd.md:438`.
- ADR-004 server-driven content: `_bmad-output/planning-artifacts/adr/004-content-delivery.md` (briefings listed in slice 1).
- Briefing authoring: `_bmad-output/planning-artifacts/scenario-authoring-template.md` §8 + Step 7.
- Content-warning law: `_bmad-output/planning-artifacts/ux-decisions/content-warning-dialog.md`.
- Shipped patterns: `content_warning_sheet.dart` (await-bool gate + CTA styling), `debrief_screen.dart` (`_SectionHeader`, section gaps, a11y), `scenario_card.dart` (`_Avatar`, semantics), `router.dart` (`_fadePage`, route table).
- Server precedents: `routes_scenarios.py` (`_safe_json_load` + ValidationError net), `seed_scenarios.py:82-111` (end_phrases validation shape to mirror), `queries.py:239-263` (`SELECT s.*` — already carries briefing).
- Design provenance (Decision E): 2026-06-12 research workflow — 6 researchers → distilled rulebook (12 design + 10 copy rules) → 3 concepts ("The Handler's Brief" / "Front Matter" / "No Caller ID") → 3-judge panel (taste 9/10, soul 8/10 for the winner; reality fixes grafted from "Front Matter"). Key stolen moves: Hitman (clinical handler register, size-contrast cinema), MGSV (fixed-lockup ritual), Speak (3 bounded blocks, quoted speakable phrases), Mela (weight-in-prose emphasis), Flighty (one rail, above-the-fold discipline), Persona 5/Opal (one flat consequence line at the threshold).

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- Red-green honored on every code task: list-payload tests (4), model tests (6), and the seeder test failed first for the expected reasons (KeyError `briefing`, 200-not-500 on corruption, seeder accepting malformed blocks; compile error on the missing model field), then went green on implementation.
- Server suite: 884 passed (880 baseline + 4) — `ruff check` + `ruff format --check` clean. In-sandbox, warmed (`import aiohttp` first per the Defender cold-scan note).
- Client suite: 522 passed (489 baseline + 33) — `flutter analyze` "No issues found!" (one unused-import warning in the new test file fixed during the run). The 33rd test (paywall edge: failed POST → no session mark → briefing re-shows) was added after the dev commit, with the deploy-proof follow-up.
- Hairline visibility: `ScrollMetricsNotification` fires on first layout AND on metrics changes (verified by the two hairline tests passing without an initState fallback) — no extra plumbing needed.

### Completion Notes List

- **Server (AC-S1..S3):** `briefing: dict | None` added to `ScenarioListItem` (docstring no longer lists briefing as detail-only); list constructor decodes via the existing `_safe_json_load` net; the detail route is untouched. Seeder validates the briefing shape at boot — mapping with EXACTLY `{vocabulary, context, expect}`, every value a string, EMPTY strings legal (fixtures rely on them), messages name the offending scenario id; the absent-key case now raises the same clear ValueError instead of a bare KeyError.
- **Model (AC-C1):** defensive parse mirrors `endPhrases` byte-for-byte (string→string entries kept, non-map → null); `hasBriefingContent` = any value with non-empty trimmed content.
- **BriefingScreen (AC-C2, AC-C8):** implemented to the §Layout spec — left rail, eyebrow/title/body/caption styles as file-top consts, copy deck verbatim under the banned-copy comment block, dossier triad with empty-section omission, threshold footer with stakes line (no maxLines) + accent pill (≥48px), conditional hairline via `ScrollMetricsNotification` (post-frame setState), pop-once guard shared by CTA + back. Two-ink discipline machine-checked by the AC-C8 source-grep tests (accent exactly once; destructive/warning/status colors zero; no string transformations; one read site per server field).
- **Hub gate (AC-C4..C7):** `_startCall` extracted with the chain order untouched; gate = `attempts == 0 && !_initiatedThisSession.contains(id) && hasBriefingContent`; the session mark is set ONLY after a successful `initiateCall` POST (paywall/cap failures re-show the briefing — correct, no call happened); `_initiating` spans the whole flow in both handlers, reset in `finally`, no flag logic inside `_startCall`.
- **Declared deviations:**
  1. **AC-C3 redirect has no dedicated unit test** — no `AppRouter.createRouter` harness exists in the repo (nothing tests the production route table today); standing one up needs an authenticated AuthBloc + ConsentStorage rig, disproportionate for a one-line redirect. The extra-carry half of AC-C3 IS asserted (hub tests check `state.extra is Scenario` on every push); the bounce expression itself ships verified by `flutter analyze` only.
  2. **Hairline rendered as a keyed 1px `SizedBox`/`ColoredBox` row** in the footer column rather than a `BoxDecoration` top border — identical visual (full-width 1px line at the footer's top edge), directly testable by key, zero layout-shift semantics.
  3. **`_renderable` calls `trim()`** as the visibility predicate (AC-C1/AC-C2 mandate trimmed-emptiness checks); the RENDERED string stays the raw server value. The AC-C8 grep list bans transformation ops (`split`/`replaceAll`/`substring`/case changes/padding) and deliberately not `trim`, which never feeds the Text.
  4. **Back-arrow glyph stays `Icons.arrow_back`** (the placeholder's glyph; spec names no glyph — DebriefScreen uses `arrow_back_ios_new`, the hub family uses Material defaults; kept the briefing surface's existing one).
  5. **Avatar `Semantics` adds `image: true`** beyond the spec'd label string — honest node type for TalkBack, mirrors the spec's intent ("photo").

### File List

- New: `client/lib/features/briefing/views/briefing_screen.dart`
- New: `client/test/features/briefing/views/briefing_screen_test.dart`
- Modified: `server/models/schemas.py`
- Modified: `server/api/routes_scenarios.py`
- Modified: `server/db/seed_scenarios.py`
- Modified: `server/tests/test_scenarios.py`
- Modified: `server/tests/test_queries.py`
- Modified: `client/lib/features/scenarios/models/scenario.dart`
- Modified: `client/lib/features/scenarios/views/scenario_list_screen.dart`
- Modified: `client/lib/app/router.dart`
- Modified: `client/lib/core/theme/app_colors.dart`
- Modified: `client/test/core/theme/theme_tokens_test.dart`
- Modified: `client/test/features/scenarios/models/scenario_test.dart`
- Modified: `client/test/features/scenarios/views/scenario_list_screen_test.dart`
- Deleted: `client/lib/features/briefing/views/briefing_placeholder_screen.dart`
- Modified: `_bmad-output/implementation-artifacts/sprint-status.yaml`
- Modified: `_bmad-output/implementation-artifacts/7-4-build-pre-scenario-briefing-display.md`

## Change Log

| Date | Change |
|---|---|
| 2026-06-12 | Story 7.4 spec created (create-story) — exhaustive context pass: briefing column/YAMLs already shipped (5.1), placeholder route already wired, gate design resolved (Decisions A-D as defaults). Status `backlog` → `ready-for-dev`. |
| 2026-06-12 | Design pass (Decision E) — Walid requested deep research on best-in-class briefing design; 13-agent workflow (6 researchers → rulebook → 3 concepts → 3-judge panel) produced "The Handler's Brief", Walid validated. AC-C2/C8, Tasks 4.x, Layout spec, Copy deck, guardrails 11-13, and the Pixel 9 script amended. Status stays `ready-for-dev`. |
| 2026-06-12 | dev-story complete — server briefing on the list payload + seeder shape validation; client model parse + BriefingScreen ("The Handler's Brief") + dual-entry hub gate with session mark; placeholder deleted; `AppColors.hairline` token added with full gate cost. Gates: ruff clean + pytest 884, flutter analyze clean + 521 tests. 5 declared deviations (see Dev Agent Record). Status `in-progress` → `review`; VPS deploy + Smoke Test Gate boxes + Pixel 9 gate remain (Task 6.3). |
| 2026-06-12 | Deploy + gate proof (same day) — CI 27408638078 deployed `eb0e917`; all 6 Smoke Test Gate boxes filled (service on-SHA, 6/6 list items carry the 3-key briefing on prod, 401 envelope, logs clean, 2 N/A). Pixel 9 agent prep done: user_progress reset (waiter+mugger, backup in the gate record), quota 0/3, release APK built. +1 paywall-edge hub test (failed POST → no session mark) → client 522. Story stays `review` — waiting on the Pixel 9 smoke gate + `/bmad-code-review`. |
