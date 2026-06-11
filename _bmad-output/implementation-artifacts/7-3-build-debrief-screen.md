# Story 7.3: Build Debrief Screen

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to read a detailed, brutally honest debrief showing my specific errors, hesitation moments, and areas to improve,
so that I know exactly what to work on before my next attempt.

## Acceptance Criteria

ACs 1-8 are verbatim from epics.md (Epic 7, Story 7.3, lines ~1337-1371). AC9-AC10 are added from the binding design docs (FR37 section + the BS-7 fallback that Story 7.2 explicitly delegated to this screen).

1. **Given** UX-DR15 defines the debrief screen layout
   **When** the debrief screen renders
   **Then** it displays a scrollable vertical layout with: hero survival percentage (64px Bold, #E74C3C if <100%, #2ECC40 if 100%), attempt number, previous best comparison (if applicable)

2. **Given** FR10 requires specific error flagging
   **When** errors are displayed
   **Then** each error shows "You said: [user's phrase]" and "Correct form: [correction]" with corrections highlighted in accent color (#00E5A0)

3. **Given** FR12 requires hesitation analysis
   **When** the hesitation section renders
   **Then** the longest hesitation moment is displayed with its duration and the conversation context where it occurred

4. **Given** FR13 requires idiom/slang explanations
   **When** idioms were encountered during the call
   **Then** each idiom is listed with its meaning and contextual example (e.g., "'Pull the other one' = British idiom meaning 'I don't believe you'")

5. **Given** FR15b requires encouraging failure framing when >40%
   **When** the user achieved >40% survival
   **Then** the debrief includes proximity to next threshold and specific improvement since last attempt (if applicable)

6. **Given** the debrief ends with areas to work on
   **When** the user scrolls to the bottom
   **Then** a summary section lists 2-3 key areas for improvement — clear enough to guide self-study between sessions

7. **Given** no retry button and no congratulatory messages (UX principles)
   **When** the debrief is complete
   **Then** no CTA buttons exist — the user navigates back to the scenario list via back arrow when ready
   **And** no "great job" or praise messages appear regardless of score

8. **Given** the debrief should be screenshot-worthy
   **When** viewing the top section
   **Then** survival %, character name, and scenario title form a self-contained, visually compelling block suitable for sharing

9. **Given** FR37 requires explaining calls ended for inappropriate behavior (debrief-screen-design.md §"About This Call")
   **When** the payload's `inappropriate_behavior` field is a non-null string
   **Then** an "About This Call" section renders the explanation in a card with a 4px #E74C3C left border
   **And** the section is hidden entirely when the field is null

10. **Given** the BS-7 fallback (call-ended-screen-design.md lines 515-527; `call_ended_screen.dart:282` comment "the debrief screen owns the >10 s loading fallback")
    **When** the screen is entered with a null payload but a non-null `callId`
    **Then** it shows the text-only loading state "Analyzing your conversation..." (Inter Regular 16px, textSecondary, centered — explicitly NOT a spinner) and resumes polling `GET /debriefs/{call_id}` every ~1s
    **And** when the payload arrives, the full content fades in (300ms, `Curves.easeOut`)
    **And** if polling stays unresolved past a 30s budget, OR `callId` is null, OR the payload fails structural parsing, the screen shows a quiet terminal state ("Debrief unavailable for this call.", caption style, centered) — back arrow always available, never a crash, never error chrome/snackbar

## Tasks / Subtasks

- [ ] Task 1: Debrief model layer (AC: 1-6, 9, 10)
  - [ ] 1.1 Create `client/lib/features/debrief/models/debrief.dart` with `Debrief`, `DebriefError`, `DebriefHesitation`, `DebriefIdiom`, `EncouragingFraming` — manual `fromJson` factories (house pattern: `CallSession`/`EndCallResult`; NO freezed/equatable)
  - [ ] 1.2 Parsing rules: required scalars (`survival_pct`, `character_name`, `scenario_title`, `attempt_number`) parse strictly — any missing/mistyped one makes `Debrief.tryParse()` return null (→ unavailable state). Arrays (`errors`, `hesitations`, `idioms`, `areas_to_work_on`) default to empty list when absent/malformed. `previous_best`, `inappropriate_behavior`, `encouraging_framing`, `encouraging_framing.improvement` are nullable (absent key == null value — hide the dependent UI either way)
  - [ ] 1.3 Sort hesitations descending by `duration_sec` defensively (design: longest first; don't trust wire order)
  - [ ] 1.4 Unit tests: full payload, minimal payload (empty arrays, nulls, framing key absent), `count` field, structural failure → `tryParse` null

- [ ] Task 2: DebriefScreen content rendering (AC: 1-9)
  - [ ] 2.1 Create `client/lib/features/debrief/views/debrief_screen.dart` — `StatefulWidget` mirroring the `CallEndedScreen` shape (constructor-injected data + `CallRepository` + timing seams; NO bloc — see Dev Notes "Why no DebriefBloc")
  - [ ] 2.2 Constructor: `{required Map<String, dynamic>? payload, required int? callId, required CallRepository callRepository, Duration pollInterval = kPollInterval (1s), Duration pollBudget = kPollBudget (30s)}`
  - [ ] 2.3 Add `AppTypography.debriefDuration` (Inter 24px w700) for the hesitation duration number — every other style already exists (`display` 64/700, `headline` 18/600, `sectionTitle` 14/600, `body` 16/400, `bodyEmphasis` 16/500, `caption` 13/400)
  - [ ] 2.4 Layout per the spec table in Dev Notes: Scaffold (AppColors.background, no AppBar) → SafeArea → SingleChildScrollView → Column; back arrow `Icons.arrow_back_ios_new` 24px scrolls WITH content (resolved design Q1); 20px horizontal screen padding, 30px top, 40px bottom; spacing via local `_k` consts (7.2 precedent — AppSpacing additions not required)
  - [ ] 2.5 Hero: % (display, destructive <100 / statusCompleted ==100) → "Survival Rate" caption → "{character_name} — {scenario_title}" headline (max 2 lines ellipsis) → "Attempt #N" (+" · Previous best: X%" only when `previous_best != null`) caption — all centered
  - [ ] 2.6 Encouraging framing (only when `encouragingFraming != null`): `proximity` in accent body centered (40px h-padding), `improvement` in caption textSecondary 4px below only when non-null — render server strings VERBATIM (copy is server-owned)
  - [ ] 2.7 "Language Errors" section: headline + count line ("N errors flagged" / "1 error flagged" / "No errors flagged" in caption textSecondary); cards (avatarBg, 12px radius, 16px padding, 12px gap): "You said:" or "You said (×N):" when count ≥2 (sectionTitle textSecondary) → user phrase (body textPrimary) → "Correct form:" (sectionTitle textSecondary) → correction (bodyEmphasis, accent) → context (caption italic textSecondary)
  - [ ] 2.8 "Hesitation Analysis" section: headline + count line ("N moments flagged" / "1 moment flagged" / "No hesitations flagged"); cards: "Pause" (sectionTitle textSecondary) → "X.X seconds" via `toStringAsFixed(1)` (debriefDuration textPrimary) → context in quotes (body italic textSecondary, max 3 lines ellipsis)
  - [ ] 2.9 "Idioms & Slang" section: HIDDEN entirely when list empty (no header, no empty message); cards: 'expression' in single quotes (bodyEmphasis accent) → meaning (body textPrimary) → context in quotes (caption italic textSecondary)
  - [ ] 2.10 "About This Call" (AC9): hidden when null; card with `Border(left: BorderSide(color: AppColors.destructive, width: 4))` + body textPrimary, max 5 lines ellipsis
  - [ ] 2.11 "Areas to Work On": single card, numbered lines "1. …" (body textPrimary), 8px gaps; render whatever count arrives (server clamps to ≤3)
  - [ ] 2.12 A11y: back arrow `Semantics(button: true, label: 'Back to scenarios')`, 44×44 target; hero % labeled "[N] percent survival rate"; section titles `Semantics(header: true)`; linear top-to-bottom reading order (default)

- [ ] Task 3: BS-7 loading fallback + terminal state (AC: 10)
  - [ ] 3.1 State machine in the State object: `content` (payload parsed) / `loading` (null payload, non-null callId — poll) / `unavailable` (callId null, parse failure, poll budget exhausted, or terminal ApiException)
  - [ ] 3.2 Poll loop mirrors `CallEndedScreen._attemptFetch()` (call_ended_screen.dart:286-317): `fetchDebrief(callId:)`, catch `ApiException.code == 'DEBRIEF_NOT_READY'` → re-arm `Timer(pollInterval)`; any other exception → unavailable; cancel all timers in `dispose()`; guard `mounted`
  - [ ] 3.3 Late arrival: swap loading → content through `AnimatedSwitcher(duration: 300ms, switchInCurve: Curves.easeOut)` (BS-7 "content fades in replacing the loading text")
  - [ ] 3.4 Loading/unavailable layouts: back arrow at top + centered message where content would appear; no spinner, no retry button (AC7 — polling IS the retry), no snackbars

- [ ] Task 4: Wire the production handoff (AC: 1, 10)
  - [ ] 4.1 In `call_ended_screen.dart` `_debriefRoute()` (lines 341-358): replace `DebriefPlaceholderScreen(scenarioId: …)` with `DebriefScreen(payload: _debriefPayload, callId: widget.callId, callRepository: widget.callRepository)`; swap the import; KEEP `RouteSettings(name: AppRoutes.debrief, arguments: _debriefPayload)`, the 900ms exit transition (`Interval(1/3, 1.0, easeOut)`), and the `debugDebriefRouteBuilder` seam untouched
  - [ ] 4.2 Do NOT touch `router.dart` or `debrief_placeholder_screen.dart` — the hub report-icon path (`scenario_list_screen.dart:317` → GoRouter `/debrief/:scenarioId`) stays on the placeholder until Epic 9 (no "latest debrief by scenario" endpoint exists)

- [ ] Task 5: Back navigation (AC: 7)
  - [ ] 5.1 Back arrow → `Navigator.of(context).pop()` — the screen lives on the ROOT navigator (stack is `[GoRouter shell (scenario list), debrief]` per call_ended_screen.dart:331); do NOT use go_router's `context.pop()` here
  - [ ] 5.2 System back (Android back / predictive back) must work: default pop behavior, NO `PopScope(canPop: false)` (that was CallEndedScreen's P-4 rule — it does NOT apply here)

- [ ] Task 6: Widget tests (`client/test/features/debrief/views/debrief_screen_test.dart`)
  - [ ] 6.1 Full-payload render: every section present, correction text uses accent, count badge "(×2)", FR37 card when non-null, areas numbered
  - [ ] 6.2 Color switch: 100% → statusCompleted, 73% → destructive
  - [ ] 6.3 Empty states: errors/hesitations count lines, idioms section ABSENT, FR37 absent when null, framing absent when key missing, "Attempt #1" without previous-best segment
  - [ ] 6.4 AC7 negative assertions: no ElevatedButton/TextButton/FilledButton anywhere; none of the praise strings ("great job", "congratulations", "well done") appear in any rendered text
  - [ ] 6.5 BS-7: null payload + callId → "Analyzing your conversation..." visible, then mocked repo resolves → content appears (pump through pollInterval seams); budget exhaustion → "Debrief unavailable for this call."; callId null → unavailable immediately; terminal ApiException → unavailable
  - [ ] 6.6 Back arrow pops (use a Navigator observer or `tester.pageBack`-equivalent assertion)
  - [ ] 6.7 House test rules: `setSurfaceSize(const Size(320, 568))` + tearDown reset; NEVER `pumpAndSettle` while poll timers may be live (explicit `pump(duration)`); mocktail `MockCallRepository`; overflow-free at the small surface

- [ ] Task 7: Gates (AC: all)
  - [ ] 7.1 `cd client && flutter analyze` → "No issues found!" (infos block CI)
  - [ ] 7.2 `cd client && flutter test` → ALL pass (451 existing must stay green; 7.2's call_ended_screen tests use the route seam so they should not break — verify)
  - [ ] 7.3 Commit per project format (`feat:` + bullets, no Co-Authored-By), flip story + sprint-status to `review`

## Pixel 9 Smoke Gate (on-device validation — owed before review → done)

Client-only story: no VPS deploy, no migration, no server change (the server Smoke Test Gate section is intentionally omitted). The on-device gate validates the post-call render path end-to-end. Ready-to-play script for Walid:

1. **Scenario:** open **The Waiter** (any difficulty), start the call.
2. **Say, turn by turn** (deliberately imperfect English — engineered to seed debrief errors):
   - "Hello. I am not want the menu." → waiter responds with something sardonic about the menu; HUD may tick the greeting checkpoint.
   - "Give me one coke and the chicken." → waiter acknowledges/pushes back; order checkpoint may tick.
   - Then hang up with the red button (voluntary exit is fine — the debrief generates for it).
3. **Watch:** Call Ended overlay holds 3-4s → **money moment #1**: the debrief fades in FULLY FORMED (no spinner): red survival % (you won't hit 100), "Survival Rate", "The Waiter — [scenario title]", "Attempt #N".
4. **Money moment #2:** scroll — an error card should show something close to *You said: "I am not want the menu" / Correct form: "I don't want the menu"* with the correction in mint green. Responses are approximate (live LLM) — the exact errors picked may differ; what matters is the card structure renders.
5. Check the bottom: "Areas to Work On" lists 2-3 items. "Idioms & Slang" only appears if the waiter used one.
6. Tap the back arrow → you land on the scenario list. Press the same scenario again, do a quick second call, hang up → debrief now shows "Attempt #2 · Previous best: X%" (and the mint proximity line if you scored >40%).
7. If the debrief is slow (rare): "Analyzing your conversation..." text (no spinner) then content fades in — report if you ever see a crash or a stuck screen instead.

## Dev Notes

### Why this story is mostly assembly, not invention

Everything hard already shipped: 7.1 generates + serves the debrief (`GET /debriefs/{call_id}`), 7.2 polls it during the Call Ended overlay and hands the result over. **This screen receives a pre-fetched payload and renders it. Zero new endpoints, zero server diffs, zero new packages.** The only network code is the BS-7 resume-poll reusing the existing `CallRepository.fetchDebrief` (call_repository.dart:61-66).

### Data contract (LOCKED — server is source of truth)

Endpoint: `GET /debriefs/{call_id}` (server/api/routes_debriefs.py; Pydantic `DebriefOut` in server/models/schemas.py:212-273). The screen receives the UNWRAPPED `data` block (CallRepository already strips the `{data, meta}` envelope). Reference payload (from server/tests/test_routes_debriefs.py):

```json
{
  "survival_pct": 73,
  "character_name": "The Mugger",
  "scenario_title": "Give me your wallet",
  "attempt_number": 2,
  "previous_best": 67,
  "errors": [
    {"user_said": "I am agree", "correction": "I agree",
     "context": "Responding to the demand", "count": 3}
  ],
  "hesitations": [
    {"duration_sec": 4.2, "context": "After the threat escalated"}
  ],
  "idioms": [
    {"expression": "Pull the other one", "meaning": "I don't believe you",
     "context": "When you claimed to have no wallet"}
  ],
  "areas_to_work_on": ["Negative sentence structure (don't/doesn't)", "Articles (a/an/the)"],
  "inappropriate_behavior": null,
  "encouraging_framing": {
    "proximity": "27% away from surviving The Mugger",
    "improvement": "+6% since last attempt"
  }
}
```

Field semantics the UI depends on:

| Field | Type | Presence rule |
|---|---|---|
| `survival_pct` | int 0-100 | always; backend `floor(passed/total*100)` — equals the overlay's client formula |
| `character_name` | str | always — scenario's proper name ("The Mugger"); do NOT confuse with the next field |
| `scenario_title` | str | always — the mission title ("Give me your wallet") |
| `attempt_number` | int ≥1 | always |
| `previous_best` | int \| null | null on first attempt → omit the "· Previous best" segment |
| `errors[]` | 0-5 items | always present (possibly empty); `count ≥ 1`; show "(×N)" only when ≥2 (Q8) |
| `hesitations[]` | 0-3 items | always present (possibly empty); only >3s gaps exist |
| `idioms[]` | 0-3 items | always present (possibly empty); empty → HIDE the whole section (Q-resolved) |
| `areas_to_work_on[]` | strings | server clamps ≤3; render as-is |
| `inappropriate_behavior` | str \| null | non-null IFF the call ended on `inappropriate_content` (backend-enforced) |
| `encouraging_framing` | obj \| ABSENT | key OMITTED entirely when `survival_pct ≤ 40`; never null-valued. In Dart, absent and null read identically via `json['encouraging_framing']` — treat both as "hide" |
| `encouraging_framing.improvement` | str \| absent | only when this attempt beat `previous_best` |

`proximity`/`improvement` copy is composed SERVER-side (debrief_assembly.py notes "Story 7.3 owns the final wording" — changing the copy means a server change, OUT of this story's scope; render verbatim).

### Entry handoff — the ONLY production entry point

`CallEndedScreen._exit()` does `Navigator.of(context).pushReplacement(_debriefRoute())` (call_ended_screen.dart:324-358). `_debriefRoute()` currently builds `DebriefPlaceholderScreen` and forwards the payload only via `RouteSettings.arguments`. **The payload can legitimately be null** (10s cap fired, callId was null, or a terminal fetch error — see `_debriefSettled` logic at lines 286-317). The route builder must therefore pass three things by CONSTRUCTOR (arguments stay for 7.2's tests): `payload` (`_debriefPayload`), `callId` (`widget.callId`), `callRepository` (`widget.callRepository`). The entry fade (900ms window, child fades in over the `Interval(1/3, 1.0)`) is already owned by that route — the debrief screen itself adds NO entry animation.

### Screen states (complete machine)

| State | Trigger | Render |
|---|---|---|
| content | payload non-null AND `Debrief.tryParse` succeeds | full layout |
| loading (BS-7) | payload null AND callId non-null | back arrow + centered "Analyzing your conversation..." (body, textSecondary; NO spinner) + 1s poll loop |
| content (late) | poll resolves | AnimatedSwitcher 300ms easeOut into full layout |
| unavailable | callId null • tryParse fails • poll budget (30s) exhausted • non-NOT_READY ApiException | back arrow + centered "Debrief unavailable for this call." (caption, textSecondary). No retry button (AC7), no error chrome |

`DEBRIEF_NOT_READY` arrives as `ApiException` with `code == 'DEBRIEF_NOT_READY'` (it's a 404 — but a NORMAL "still generating" signal, not an error). Known server reality (7.1 review, deferred): a permanently-failed generation returns NOT_READY forever — hence the 30s budget, not infinite polling.

### Layout spec (condensed from debrief-screen-design.md — the doc is authoritative for pixel detail)

Order, top to bottom (single `SingleChildScrollView`, sections 24px apart, cards 12px apart, card = avatarBg / radius 12 / padding 16):

1. **Back arrow** — `Icons.arrow_back_ios_new`, 24px, textPrimary, 8px top/left inside SafeArea, scrolls with content.
2. **Hero (screenshot block, AC8)** — 30px below arrow, all centered: `"$pct%"` display + variant color; 8px; "Survival Rate" caption textSecondary; 16px; "{character_name} — {scenario_title}" headline textPrimary (2 lines ellipsis); 8px; attempt caption textSecondary.
3. **Encouraging framing** (conditional) — proximity accent body centered, 40px h-padding; improvement caption textSecondary 4px below (conditional).
4. **Language Errors** — always; header + count caption; 0-5 cards.
5. **Hesitation Analysis** — always; header + count caption; 0-3 cards, longest first.
6. **Idioms & Slang** — conditional (hidden when empty); no count line; 0-3 cards.
7. **About This Call** — conditional (AC9); 4px destructive left border card.
8. **Areas to Work On** — always; one card, numbered items, 8px gaps.
9. 40px bottom padding above SafeArea.

Widget mapping table: debrief-screen-design.md lines 922-946 (Scaffold no-AppBar, Containers with BoxDecoration, conditional renders via `if`/`isEmpty` checks).

### Design tokens — bindings and the ONE discrepancy

- Colors: use ONLY existing `AppColors` tokens — `background`, `avatarBg`, `textPrimary`, `textSecondary`, `accent`, `destructive`, `statusCompleted`. The static token test (`theme_tokens_test.dart`) fails the build on ANY hex literal outside `lib/core/theme/` and asserts the AppColors count == 13 — do NOT add color tokens (header rule: UX-DR1 update required first; none is needed).
- **Discrepancy resolved:** the design doc writes text-secondary as `#9A9AA5`; the shipped token `AppColors.textSecondary` is `#8A8A95` (app_colors.dart:29). THE CODE TOKEN WINS — same decision class as 7.2's locked avatar/track colors. Do not "fix" the token.
- Typography: all styles exist except the 24px Bold hesitation duration → add `AppTypography.debriefDuration` (7.2 precedent: it added 4 `callEnded*` styles). Italics via `copyWith(fontStyle: FontStyle.italic)`.
- Spacing: local `_k` consts in the widget file (7.2 precedent) — no AppSpacing additions required; `AppSpacing.screenHorizontal` (20) may be reused.
- The design doc's "File Locations" table cites `core/navigation/app_router.dart` — stale; the real router is `client/lib/app/router.dart` (untouched by this story anyway).

### Why no DebriefBloc (declared deviation from the design doc's file table)

The design doc lists a `debrief_bloc.dart`, but the state here is screen-local and tiny (3 states, one timer), the payload arrives pre-fetched through the constructor, and the direct sibling (`CallEndedScreen`, reviewed + done in 7.2) established the exact pattern: StatefulWidget + injected `CallRepository` + constructor timing seams for deterministic tests. A bloc would add event/state/provider boilerplate with zero testability gain. The `features/debrief/bloc/` dir keeps its `.gitkeep`.

### What NOT to do

- Do NOT call `fetchDebrief` when a payload was provided (happy path = zero network).
- Do NOT delete/modify `DebriefPlaceholderScreen` or the GoRouter `/debrief/:scenarioId` route — the hub report icon (scenario_list_screen.dart:317) still targets it; real hub access to past debriefs is Epic 9 (needs a "latest debrief by scenario" endpoint that does not exist).
- Do NOT add retry buttons, share buttons, paywalls (Epic 8 overlays later), analytics, or caching (Epic 9).
- Do NOT render praise. No 🎉. At 100% the only celebration is the green number (resolved Q2: "the hero % IS the only validation"; 100% framing string "You survived [character]" comes from the server and is data, not praise).
- Do NOT show "No idioms encountered" — absence of the section IS the design.
- Do NOT use `context.pop()` (go_router) for the back arrow — root-navigator imperative route; use `Navigator.of(context).pop()`.
- Do NOT use the envelope's `survival_pct` from `call_end` — the debrief payload's value is the authoritative one here (7.2 review note: the envelope field is now unread and slated for retirement).
- Do NOT `pumpAndSettle` in tests with the poll timer alive (client/CLAUDE.md gotcha #3).

### Previous story intelligence (7.1 + 7.2)

- 7.2's `debugDebriefRouteBuilder` test seam means existing call_ended_screen tests exercise the exit WITHOUT building the real debrief route — swapping the placeholder should not break them; the default-route render tests never reach `_exit`. Verify with the full suite anyway.
- 7.2 shipped `CallRepository.fetchDebrief` + the `DEBRIEF_NOT_READY` poll convention this story reuses verbatim.
- 7.1 review learnings that shape AC10: generation can fail permanently (timeout >8s, Groq error, malformed JSON, empty transcript) → NOT_READY forever → the screen MUST have a polling budget + terminal state.
- 7.1: `attempt_number`/`previous_best` come from `user_progress` (bumped atomically at teardown) — first attempt genuinely arrives as `previous_best: null`.
- 7.2 layout lesson (review patch): wrap tall Columns in the Story 5.4 overflow pattern when content can exceed the viewport — here the whole screen is already a `SingleChildScrollView`, which covers it; still assert overflow-free at 320×568 in tests.
- House model pattern (`EndCallResult.fromJson`): defensive `as T?` casts + sensible defaults — but for the debrief's required hero scalars prefer strict-parse-or-unavailable (a silently-defaulted "0%" would lie to the user about their score).

### Git intelligence

Recent commits show the active conventions: one commit per story stage (`feat:`/`fix:`/`docs:` + verb bullets, no Co-Authored-By), client test count currently 451 green, `flutter analyze` zero-issue discipline (infos included). Story 6.28 just removed per-scenario difficulty — difficulty is GLOBAL-only; nothing in this story touches difficulty.

### Latest tech note

No new dependencies. Existing pins cover everything: `flutter_bloc 9.1.1` (unused here), `go_router 17.2.1` (untouched), `dio 5.9.2`, `mocktail 1.0.5`, `bloc_test 10.0.0`. No web-research deltas relevant to a pure-render Flutter screen.

### Project Structure Notes

- New files land in the already-scaffolded `client/lib/features/debrief/` (`models/`, `views/`); tests mirror under `client/test/features/debrief/`.
- Modified: `client/lib/core/theme/app_typography.dart` (+1 style), `client/lib/features/call/views/call_ended_screen.dart` (`_debriefRoute()` + import swap).
- Untouched: `router.dart`, `debrief_placeholder_screen.dart`, all server code, `AppColors`, `AppSpacing`.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-7 Story 7.3] — story statement + ACs 1-8
- [Source: _bmad-output/planning-artifacts/debrief-screen-design.md] — full layout/typography/spacing spec, widget mapping (lines 922-946), resolved Q1-Q10, schema constraints
- [Source: _bmad-output/planning-artifacts/debrief-content-strategy.md] — content schema authority (LLM fields + backend fields)
- [Source: _bmad-output/planning-artifacts/call-ended-screen-design.md lines 515-527] — BS-7 fallback spec ("Analyzing your conversation...", no spinner, 300ms fade-in)
- [Source: _bmad-output/planning-artifacts/prd.md FR9-FR15b, FR37, NFR7] — functional requirements
- [Source: server/models/schemas.py:212-273 DebriefOut] — locked wire contract
- [Source: server/api/routes_debriefs.py] — status codes: 200, 404 CALL_NOT_FOUND, 404 DEBRIEF_NOT_READY, 500 DEBRIEF_UNAVAILABLE
- [Source: client/lib/features/call/views/call_ended_screen.dart:286-358] — poll pattern + handoff to modify
- [Source: client/lib/features/call/repositories/call_repository.dart:61-66] — fetchDebrief
- [Source: client/CLAUDE.md] — Flutter gotchas (token test, pumpAndSettle, surface size, mocktail fallbacks, lint traps)
- [Source: _bmad-output/implementation-artifacts/7-1-build-debrief-generation-backend.md] — generation timing/failure modes
- [Source: _bmad-output/implementation-artifacts/7-2-build-call-ended-overlay-transition.md] — overlay handoff decisions (B/E/F), test seams

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
