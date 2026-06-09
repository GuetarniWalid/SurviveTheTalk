# Story 7.2: Build Call Ended Overlay Transition

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to see a dramatic "Call Ended" screen for a few seconds after the call before the debrief appears,
so that the emotional weight of what just happened settles before I receive detailed feedback.

This is a **Flutter-client-only** story (zero server changes — see the Decision on the theatrical phrase below). It builds the post-call **Call Ended overlay**: the non-interactive transition screen that (a) shows the result block (character identity, duration, %, theatrical phrase), (b) masks debrief-generation latency by fetching `GET /debriefs/{call_id}` in the background during a 3–10 s hold, and (c) auto-fades to the debrief. Story 7.1 (debrief backend) is **already deployed live** — the `GET /debriefs/{call_id}` endpoint exists. Story 7.3 (the real debrief screen) ships later and replaces the current `DebriefPlaceholderScreen`.

---

## ⚠️ Source-Document Drift — READ FIRST

The design doc [`call-ended-screen-design.md`](../planning-artifacts/call-ended-screen-design.md) (2026-04-01) and the epic AC were written **before Epic 6 rebuilt the pipeline and before Story 7.1 shipped the debrief backend**. The layout/typography/variant/timing/a11y specs in the design doc are still authoritative and excellent — **follow them**. But three *data-flow* assumptions are now stale. This story pins the current truth:

| Stale source statement | Current truth (use THIS) | Evidence |
|---|---|---|
| "The theatrical phrase comes from the server as part of the `call_end` payload" (design doc §Theatrical Phrase) | **FALSE — no written phrase exists anywhere on the server.** Scenarios carry only **spoken** `exit_lines` (TTS-delivered: `hangup`/`completion`/`patience_warning`/`noisy_environment`), never a written display phrase. The `call_end` envelope carries no phrase. → **Phrases are authored client-side** (Decision A). | [server/pipeline/scenarios/the-waiter.yaml]; [server/pipeline/patience_tracker.py:1338-1357]; [server/models/schemas.py `DebriefOut`] |
| "The percentage is the `survival_pct` field from the `call_end` payload — the same value used in the debrief screen" (design doc IG-5) | **The live envelope's `survival_pct` uses a DIFFERENT formula than the debrief** (patience-meter ratio for hung-up vs. the debrief's `floor(passed/total)`), AND it is absent on `user_hung_up`. Reading it would make the overlay % **disagree** with the 7.3 debrief %. → **Compute `floor(checkpoints_passed/total*100)` client-side** from the checkpoint snapshot (Decision B). | [server/pipeline/patience_tracker.py:1327-1333] (envelope = patience ratio) vs [server/pipeline/debrief_assembly.py `compute_survival_pct`] (debrief = `floor(passed/total)`) |
| Variant reasons are `{character_hung_up, user_hung_up, survived, network_lost}` (design doc §Variant Selection) | The live reason set is **6**: adds `inappropriate_content` (→ failure variant, red) and `noisy_environment` (→ stays on the existing notice screen, NOT the overlay). `network_lost`/`noisy_environment`/gifted-short-calls keep `CallEndedNoticeScreen`. | [server/models/schemas.py `EndCallIn`]; [client .../call_screen.dart:734-743] |

**Net:** all three values the overlay shows — **%**, **duration**, **phrase** — are available **client-side today** with no server change. % = client-computed from the checkpoint snapshot; duration = `EndCallResult.durationSec` (already captured from the `POST /calls/{id}/end` response); phrase = a new client-side map keyed by `riveCharacter` × outcome.

---

## Decisions

> One genuine fork (A) needs Walid's sign-off; the dev can proceed on the recommended path. B–E are pinned by the drift analysis above and the existing code — no action needed, kept for rationale.

### Decision A — Where do the theatrical phrases live? *(the only open fork)*

The dramatic written phrase ("The mugger gave up on you", "She's still on the line. Barely.") exists **nowhere** as data. Two clean shapes:

- **Option A1 (RECOMMENDED) — client-side map.** Author a `kTheatricalPhrases` map in `client/lib/features/call/` keyed by `riveCharacter` × variant (`hungUp` / `voluntary` / `survived`), lifting the copy verbatim from the design doc's phrase tables. **Rationale:** this is byte-for-byte how the client already owns character identity — `kCharacterCatalog` (name/role/avatar) is a client-side map keyed by `riveCharacter`, and its own dartdoc blesses client-side authoring "for MVP scale (5–20 entries)" with a documented promotion path to a server endpoint later. Adding a phrase alongside is the *same* touch-point (a new scenario already needs a `kCharacterCatalog` entry). Keeps 7.2 a pure Flutter story (no migration, no deploy, no smoke-gate-on-VPS). **5 characters × 3 variants = 15 short strings.**
- **Option A2 — server YAML + thread through.** Add a per-scenario, per-outcome `display_phrases` block to the scenario YAML + `scenarios` table + serve it. **Heavier:** a migration, a snapshot refresh, a deploy, AND it *still* needs a client fallback because `user_hung_up`/`network_lost` send no `call_end` envelope. The debrief can't carry it either (the overlay shows the phrase *before* the debrief is guaranteed ready — that's the whole point of the hold).

**→ Recommended: A1.** The ACs/Tasks below assume A1 (client-only). **Walid: confirm A1, or pick A2** (which flips this to a server+deploy story and re-adds the Smoke Test Gate). The 15 phrases are content — **the dev proposes them (lifted from the design doc), Walid approves the final copy** before the on-device gate (mirrors Story 7.1's `scenario_title` approval).

### Decision B — Percentage source = **client-computed `floor(passed/total*100)`**, not the envelope.
Pinned by the drift table. Compute from the checkpoint snapshot captured at end (`metCount`/`total`), which the client already reconciles UP to the server-authoritative met set at call end ([call_screen.dart:620-660]). This **equals** the debrief's `survival_pct` formula → overlay % == 7.3 debrief % (the design's IG-5 intent). Do **not** read `data['survival_pct']` from the `call_end` envelope.

### Decision C — Overlay scope = the current `maybePop()` branch only.
Pinned by existing code, which already names this story: [call_screen.dart:722-723] ("*Story 7.2 will own the richer Call-Ended overlay for those later*") and [call_ended_notice_screen.dart:14-17]. The overlay **replaces the `else`/`maybePop()` branch** for the debrief-eligible reasons (`user_hung_up`, `survived`, non-gifted `character_hung_up`, non-gifted `inappropriate_content`). The `showsNotice` branch (`network_lost`, `noisy_environment`, gifted-short-calls) **keeps `CallEndedNoticeScreen` unchanged** — those carry quota/connection messaging the overlay can't. **No "neutral/network" overlay variant is built** (design doc IG-4 is superseded by the shipped notice screen).

### Decision D — Duration source = `EndCallResult.durationSec`.
Server-computed from `started_at → now()` at `POST /calls/{id}/end` ([routes_calls.py]); already captured client-side in `_endCallResult` but never surfaced. Thread it (plus `callId`) into the `CallEnded` state.

### Decision E — Transition handoff to the debrief = imperative `pushReplacement`, payload forwarded.
The overlay fetches the debrief during the hold, then `pushReplacement`es to the debrief screen (currently `DebriefPlaceholderScreen`), **forwarding the fetched payload** so 7.3 renders with no re-fetch / no spinner. Use the same imperative `Navigator.of(context, rootNavigator: true).pushReplacement(MaterialPageRoute(...))` pattern the notice screen already uses ([call_screen.dart:746-756]) — consistent post-call nav. 7.3 will own the final debrief model + the >10 s loader.

---

## Acceptance Criteria

> Reasons in scope for the overlay (Decision C): `user_hung_up`, `survived`, `character_hung_up` (non-gifted), `inappropriate_content` (non-gifted). Out of scope (keep `CallEndedNoticeScreen`): `network_lost`, `noisy_environment`, any gifted-short-call.

**AC1 — Call Ended overlay screen renders the design layout.**
A new `CallEndedScreen` (`client/lib/features/call/views/call_ended_screen.dart`) renders the three vertical zones from [`call-ended-screen-design.md`](../planning-artifacts/call-ended-screen-design.md): **identity** (character name 38px, role 16px, duration 38px), **status** (120 px circular avatar + "Call Ended" 20px), **result** (percentage 24px, 8 px progress bar, theatrical phrase 24px italic, max 2 lines). Non-interactive (no buttons/taps). Back navigation is blocked during the hold (`PopScope(canPop: false)`).

**AC2 — Character identity is reused from `kCharacterCatalog`.**
Name, role, and avatar come from `kCharacterCatalog[scenario.riveCharacter]` via the existing `CharacterAvatar` widget (avatar) and `CharacterIdentity` (name/role) — same presentation as the incoming-call/connecting screens (visual continuity). Avatar failure falls back to the widget's existing empty-state.

**AC3 — Percentage + progress bar = client-computed `floor(passed/total*100)`.**
The percentage and progress-bar fill are computed as `floor(checkpointsPassed / totalCheckpoints × 100)`, clamped 0–100, from the checkpoint snapshot captured at call end (NOT from the `call_end` envelope's `survival_pct` — Decision B). `totalCheckpoints == 0` ⇒ `0%` with an empty (track-only) bar (design P-8). This value equals the 7.3 debrief `survival_pct`.

**AC4 — Variant colors driven by the call-end reason.**
- **Failure (red `AppColors.destructive`)** for `user_hung_up`, `character_hung_up`, `inappropriate_content`: percentage text, bar fill, and phrase all `#E74C3C`.
- **Success (green `AppColors.accent`)** for `survived`: all three `#00E5A0`.
Identity + status zones (name/role/duration/avatar/"Call Ended") are color-constant across variants. Percentage is shown for **all** in-scope reasons.

**AC5 — Theatrical phrase is variant- and character-specific (Decision A1).**
The phrase is selected from `kTheatricalPhrases[scenario.riveCharacter]` by variant: `survived` → success phrase; `user_hung_up` → voluntary phrase; `character_hung_up`/`inappropriate_content` → hung-up phrase. Copy ≤ 50 chars recommended / 70 hard limit, third-person, no exclamation/emoji (design tone guide). A missing/empty phrase **hides the phrase element** (design P-7), the lower spacer absorbing the gap. **The 15 strings are dev-proposed (lifted from the design doc tables), Walid-approved.**

**AC6 — Duration renders as `MM:SS` (or `H:MM:SS`).**
Formatted from `CallEnded.durationSec` (Decision D): leading zeros (`02:47`, `00:00`), `H:MM:SS` only over 1 h. `00:00` is a valid state (immediate disconnect), never hidden.

**AC7 — Background debrief fetch masks generation latency.**
On entry the overlay starts fetching `GET /debriefs/{callId}` (new `CallRepository.fetchDebrief`). A `404 DEBRIEF_NOT_READY` means "still generating" → poll/retry (~1 s cadence) until ready or the 10 s cap. A `200` yields the debrief payload (kept for forwarding). The fetch runs concurrently with the hold timer and never blocks the UI / never shows in-overlay error chrome (UX-DR6).

**AC8 — Hold timing: 3 s min / 10 s max, transition on the LAST condition.**
Minimum hold = 3 s (5 s if a screen reader is active — `MediaQuery.accessibleNavigation`, design P-6). The exit transition fires when **both** (a) the minimum hold has elapsed **and** (b) the debrief fetch has resolved — whichever is later. Hard ceiling: at 10 s, transition regardless of fetch state. No visual countdown/loader on the overlay (the achievement progress bar is NOT a loading bar).

**AC9 — Entry + exit transitions per the design timing.**
Entry: the call screen fades out (500 ms `easeIn`) → brief `#1E1F23` beat → overlay content fades in (500 ms `easeOut`). Exit: a ~900 ms crossfade (600 ms out `easeIn` / 600 ms in `easeOut`, 300 ms overlap) to the debrief screen. The overlay is pushed as a `pushReplacement` so the dead call screen is off the back stack (forward-only nav, UX-DR10).

**AC10 — Auto-transition to the debrief, payload forwarded (Decision E).**
On the exit trigger the overlay `pushReplacement`es to the debrief route, **forwarding the fetched debrief payload** (so 7.3 needs no re-fetch). Until 7.3 ships, the target is `DebriefPlaceholderScreen` (which ignores the payload). No user action is required; the back stack ends `[scenario-list, debrief]`.

**AC11 — Navigation wiring preserves the notice-screen path.**
[call_screen.dart] post-call listener: the `showsNotice` branch is **unchanged** (still `CallEndedNoticeScreen`); only the `else` (`maybePop`) branch is replaced with the overlay push. The metric inputs (`checkpointsPassed`, `totalCheckpoints` from `_checkpointNotifier.value`; `callId`, `durationSec`, `endReason` from state/session) are captured in the listener at push time and passed to `CallEndedScreen`'s constructor.

**AC12 — Tokens, a11y, and gates.**
No inline hex (theme-token test): reuse `AppColors`/`CallColors`; add the four call-ended typography styles to `AppTypography` and any new color token under `lib/core/theme/`. Screen-reader live-region announcement on appear, including the outcome word (failed/survived) derived from the reason (design P-5), duration spoken naturally. `flutter analyze` → **"No issues found!"** and `flutter test` → **"All tests passed!"**, both green (the full suites, not just new tests).

---

## Tasks / Subtasks

- [ ] **Task 1 — Theatrical-phrase map + variant model (AC5, Decision A1)**
  - [ ] Add `client/lib/features/call/theatrical_phrases.dart`: an enum `CallEndedVariant { failure, success }` (or `{ hungUp, voluntary, survived }` if keeping voluntary distinct) + a `const Map<String, ...> kTheatricalPhrases` keyed by `riveCharacter` (`waiter`/`mugger`/`girlfriend`/`cop`/`landlord`), values per variant. Lift copy verbatim from [`call-ended-screen-design.md`](../planning-artifacts/call-ended-screen-design.md) §"Emotional Variants" tables.
  - [ ] A pure `phraseFor(reason, riveCharacter)` helper mapping reason → variant (`survived`→success; `user_hung_up`→voluntary; `character_hung_up`/`inappropriate_content`→hungUp). Returns `null`/`''` → phrase element hidden (P-7).
  - [ ] **⚠️ Propose the 15 phrases for Walid's approval** before the on-device gate.
- [ ] **Task 2 — Typography + color tokens (AC1, AC12)**
  - [ ] Add to `AppTypography`: `callEndedDuration` (38 Regular), `callEndedLabel` (20 Regular), `callEndedPercent` (24 Regular), `callEndedPhrase` (24 Regular **italic**). (Name/role reuse the incoming-call 38/16 styles — match how `IncomingCallScreen` renders them.)
  - [ ] Progress-bar track: reuse an existing dark-grey token (`AppColors.avatarBg` #414143 recommended for separation from the #38383A avatar) — **see Dev Notes §"Avatar vs track color"** for the design-doc nuance. Add a new `lib/core/theme/` token ONLY if Walid wants the exact design values; never inline hex (theme-token test).
- [ ] **Task 3 — `CallEndedScreen` widget (AC1–AC6, AC9, AC12)**
  - [ ] Build the `Scaffold` + `Column` (3 zones, 2 `Spacer()`s) per the design's Flutter Widget Mapping table. Reuse `CharacterAvatar(character: scenario.riveCharacter, size: 120)`.
  - [ ] Compute % via `floor(passed/total*100)` (guard `total==0`); drive percentage text, `LinearProgressIndicator` fill, and phrase color from the variant (AC4).
  - [ ] `MM:SS`/`H:MM:SS` duration formatter (AC6). `PopScope(canPop: false)` during the hold (P-4).
  - [ ] Entry `FadeTransition` (AC9); `Semantics` live-region announcement with the outcome word (P-5, AC12).
- [ ] **Task 4 — Debrief fetch + hold/transition controller (AC7, AC8, AC10)**
  - [ ] `CallRepository.fetchDebrief({required int callId})` → `GET /debriefs/$callId`, unwrap `response.data['data']`; map `404 DEBRIEF_NOT_READY` to a "not ready" sentinel (poll), `404 CALL_NOT_FOUND`/other to a terminal "no debrief" outcome (still transition). Mirror `endCall`'s `ApiClient` usage.
  - [ ] In `CallEndedScreen`: kick the fetch on `initState`; poll on `DEBRIEF_NOT_READY` (~1 s) until ready or the 10 s cap. Run a 3 s (5 s w/ screen reader) min-hold timer concurrently. Transition when `(minHold elapsed) && (fetch resolved)`, or force at 10 s (AC8).
  - [ ] Exit crossfade `pushReplacement` to the debrief (`DebriefPlaceholderScreen` for now), forwarding the payload (AC9/AC10). Cancel timers/futures in `dispose`.
- [ ] **Task 5 — State + bloc threading (AC11, Decision D)**
  - [ ] Extend `CallEnded` ([call_state.dart:41-51]) with `final int? durationSec` and `final int? callId`; populate both in `_buildCallEnded()` ([call_bloc.dart:590]) from `_awaitEndCallResult()` and `_session.callId`.
  - [ ] In [call_screen.dart] listener: replace the `else { nav.maybePop(); }` branch with a `pushReplacement(CallEndedScreen(...))`, capturing `metCount`/`total` from `_checkpointNotifier.value` at push time. Keep the `showsNotice` branch byte-identical.
- [ ] **Task 6 — Tests (AC12)**
  - [ ] Widget tests for `CallEndedScreen`: each variant's colors; %/bar (incl. `total==0` → 0%); duration formats (`00:00`, `02:47`, `1:02:15`); phrase hidden when empty; `PopScope` blocks back. Force phone surface size (client/CLAUDE.md §7); use explicit `pump(Duration)` not `pumpAndSettle` (continuous timers/fades — §3).
  - [ ] Timing/transition tests with a fake clock/short `Duration`s: transitions only after BOTH conditions; 10 s cap fires; screen-reader 5 s min via `MediaQuery(accessibleNavigation: true)`.
  - [ ] `CallRepository.fetchDebrief` tests (mocktail): 200 unwrap, `DEBRIEF_NOT_READY` poll-then-ready, `CALL_NOT_FOUND` terminal. Bloc test: `CallEnded` carries `durationSec` + `callId`.
  - [ ] Run the **full** `flutter test` + `flutter analyze` (not just new tests — Task 5 touches the bloc/listener; old call tests may need updating).

---

## Dev Notes

### Where each of the three displayed values comes from (the crux)

| Value | Source (current code) | How to get it in the overlay |
|---|---|---|
| **Percentage** | Client checkpoint snapshot, reconciled to server-authoritative met set at end ([call_screen.dart:620-660]). `floor(passed/total*100)` == the 7.3 debrief formula ([debrief_assembly.compute_survival_pct]). | Capture `_checkpointNotifier.value!.metCount` + `.total` in the listener; compute in the widget. **NOT** `data['survival_pct']` (envelope = patience ratio, [patience_tracker.py:1327-1333]). |
| **Duration** | `EndCallResult.durationSec`, server-computed at `POST /calls/{id}/end`; captured in `_endCallResult` but unused. | Thread `durationSec` into `CallEnded` (Task 5). |
| **Phrase** | Does NOT exist server-side (only spoken `exit_lines`). | New client-side `kTheatricalPhrases` map (Task 1, Decision A1). |

### Reuse, don't reinvent

- **Avatar:** `CharacterAvatar` ([client .../widgets/character_avatar.dart]) is the canonical avatar primitive (its dartdoc says so) — reuse at `size: 120`. Do NOT hand-roll a `CircleAvatar`.
- **Identity:** `kCharacterCatalog[scenario.riveCharacter]` → `CharacterIdentity{name, role, imageAsset}`. Same source the incoming-call/connecting screens use. Mirror how `IncomingCallScreen` lays out name (38) + role (16).
- **Auth'd GET:** `ApiClient` ([client .../core/api/api_client.dart]) — `baseUrl = http://167.235.63.129`, Bearer interceptor; copy the shape of `CallRepository.endCall` ([call_repository.dart:43-53]) for `fetchDebrief`. Server envelope is `{data, meta}` on success, `{detail:{code,message}}`-style on error.
- **Post-call nav pattern:** `Navigator.of(context, rootNavigator: true).pushReplacement(MaterialPageRoute(...))` inside a post-frame callback after the `PopScope` flips to `canPop: true` — copy [call_screen.dart:744-760] exactly. `_popScheduled` guards against double-push.
- **Notice screen stays:** don't touch `CallEndedNoticeScreen` or the `showsNotice` predicate ([call_screen.dart:734-743]).

### Avatar vs track color (minor — for Walid's visual gate)

The design doc assigns avatar-bg `#414143` and progress-track `#38383A`. The shipped `CharacterAvatar` hardcodes `CallColors.avatarBackground` (#38383A) for **all** call avatars. Reusing it (recommended, for cross-screen continuity) makes the Call Ended avatar #38383A; use `AppColors.avatarBg` (#414143) for the track to keep them distinct. This is a 2-token swap vs the doc's literal assignment, justified by avatar continuity + zero new tokens. If Walid prefers the exact design values, add an optional `backgroundColor` param to `CharacterAvatar` (default `CallColors.avatarBackground`) and pass `AppColors.avatarBg`. Cosmetic — settle at the on-device gate.

### Debrief readiness & the >10 s fallback

The overlay's job is to *mask* debrief generation (NFR7: <5 s typical, 10 s ceiling — 7.1 budgets an 8 s generator timeout). On the happy path the debrief is ready within the 3–5 s hold. The design's "Analyzing your conversation…" loader (design §Fallback) lives on the **debrief screen (7.3)**, not the overlay — 7.2 only forwards the payload (or a "not ready, keep polling" signal + the `callId`) so 7.3 can render its loader. At the 10 s cap, transition regardless. Never show a spinner on the overlay.

### Project conventions / traps (client/CLAUDE.md)

- **No inline hex** — theme-token test scans `lib/` outside `lib/core/theme/` (§6). New text styles in `AppTypography`; any color via tokens.
- **`pumpAndSettle` hangs** on continuous animations/timers (§3) — use explicit `tester.pump(Duration(...))`.
- **Force phone surface size** in layout tests (§7) — the 3-zone column is overflow-sensitive on 320 px (design §Responsive notes ~464 px fixed on iPhone SE).
- **Mocktail + sealed events** — `registerFallbackValue` a concrete event (§2). `FlutterSecureStorage.setMockInitialValues({})` in `setUp` if any test touches storage transitively (§1).
- **Error UX** (§10): no snackbar/toast/dialog; the fetch failing is silent (UX-DR6) — just transition.

### Project Structure Notes

- **New:** `client/lib/features/call/views/call_ended_screen.dart`, `client/lib/features/call/theatrical_phrases.dart`, tests under `client/test/features/call/`.
- **Edited:** `client/lib/features/call/bloc/call_state.dart` (+`durationSec`, +`callId` on `CallEnded`), `client/lib/features/call/bloc/call_bloc.dart` (`_buildCallEnded` populates them), `client/lib/features/call/views/call_screen.dart` (replace the `maybePop` branch), `client/lib/features/call/repositories/call_repository.dart` (+`fetchDebrief`), `client/lib/core/theme/app_typography.dart` (+4 styles).
- **Untouched (boundary):** `DebriefPlaceholderScreen` and the `/debrief/:scenarioId` route (7.3 owns the real screen); `CallEndedNoticeScreen` and the `showsNotice` path; the server.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 7.2] — ACs (L1303-1329), Epic 7 framing (L1264-1268).
- [Source: _bmad-output/planning-artifacts/call-ended-screen-design.md] — **authoritative** layout, typography, color variants, hold timing (3 s min / 10 s max), entry/exit transitions, a11y, Flutter widget mapping, file locations, theatrical-phrase tables.
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md] — UX-DR8 (CallEndedOverlay L1062-1070), UX-DR10 forward-only nav, UX-DR11 loading-state masking, flow diagrams (L816/914/1178).
- [Source: _bmad-output/implementation-artifacts/7-1-build-debrief-generation-backend.md] — debrief backend (deployed): `DebriefOut` shape, `GET /debriefs/{call_id}` + `CALL_NOT_FOUND`/`DEBRIEF_NOT_READY` 404s, `survival_pct = floor(passed/total)`.
- [Source: client/lib/features/call/views/call_screen.dart:709-760] — post-call nav (the `else`/`maybePop` branch this story replaces; `showsNotice` stays); :620-660 checkpoint reconcile (% inputs).
- [Source: client/lib/features/call/views/call_ended_notice_screen.dart:14-17] — the explicit 7.2 handoff note; the notice path to preserve.
- [Source: client/lib/features/call/bloc/call_state.dart:41-51] — `CallEnded` (add `durationSec`/`callId`); [call_bloc.dart:555 `_session.callId`, :590 `_buildCallEnded`, :115/:526 `_endCallResult`].
- [Source: client/lib/features/call/services/data_channel_handler.dart:107-127] — `call_end` envelope (client already ignores `survival_pct`).
- [Source: client/lib/features/call/repositories/call_repository.dart:43-53] — `endCall` (template for `fetchDebrief`); [core/api/api_client.dart] base URL + Bearer.
- [Source: client/lib/features/scenarios/character_catalog.dart:22-48] — `kCharacterCatalog` (the pattern `kTheatricalPhrases` mirrors); [models/character_identity.dart]; [models/scenario.dart] (`riveCharacter`, `title`).
- [Source: client/lib/features/call/views/widgets/character_avatar.dart] — reuse; [core/theme/app_colors.dart] (`textPrimary`/`accent`/`destructive`/`avatarBg`), [core/theme/call_colors.dart:21,32] (`secondary` #C6C6C8, `avatarBackground` #38383A), [core/theme/app_typography.dart].
- [Source: client/lib/features/debrief/views/debrief_placeholder_screen.dart] + [app/router.dart:37,183-191] — debrief target (7.3 boundary).
- [Source: server/pipeline/patience_tracker.py:1327-1357] — envelope `survival_pct` = patience ratio (do NOT use); [server/pipeline/debrief_assembly.py] — the `floor(passed/total)` formula to match.
- [Source: client/CLAUDE.md] — Flutter test traps (§1/§2/§3/§6/§7/§10); [Source: project-root CLAUDE.md] — pre-commit gates, review→done smoke-gate discipline.

## On-Device Smoke Gate (Pixel 9 — Walid, visual/timing)

> Client-only story (Decision A1) → **no server/VPS smoke gate**. The `review → done` flip is still gated on Walid's Pixel 9 visual/timing gate per the sprint rule. The dev hands a ready-to-play script (per project CLAUDE.md) before the gate. Checks:

- [ ] **Failure variant.** End a normal call by tapping hang-up (or let the character hang up ≥30 s in). The overlay shows the character's name/role/avatar, `MM:SS` duration, a **red** % + bar matching the in-call checkpoint progress, and the character's red theatrical phrase. Holds ≥3 s, then fades to the debrief.
- [ ] **Success variant.** Complete a scenario (all checkpoints). Overlay shows **green** 100% + bar + the grudging "survived" phrase; auto-fades to debrief.
- [ ] **Latency masking.** The hold feels like a deliberate pause (no spinner on the overlay); the debrief appears already-rendered after the crossfade (no flash/spinner) on a normal call.
- [ ] **% matches the debrief.** The overlay % equals the survival % shown on the next (7.3) screen — no disagreement. *(Until 7.3 ships, eyeball that the overlay % == checkpoints-passed / total from the in-call HUD.)*
- [ ] **Notice path intact.** A `network_lost` / `noisy_environment` / very-short gifted call still shows `CallEndedNoticeScreen` (NOT the overlay) — no regression.
- [ ] **No back-out mid-hold.** A back gesture during the overlay does nothing (forward-only).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

### Change Log

| Date | Change |
|---|---|
| 2026-06-09 | Story 7.2 drafted (`backlog` → `ready-for-dev`). Client-only Call Ended overlay; drift pinned vs the 2026-04-01 design doc (phrase authored client-side, % computed client-side to match the 7.1 debrief, 6-reason variant set, notice path preserved). 1 open decision for Walid: theatrical-phrase location (A1 client-side recommended) + approve the 15 phrases. |
