# Story 7.5: Overhaul Debrief Report (v2)

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> ## ⛔ DECISION PASS REQUIRED BEFORE DEV
>
> **dev-story MUST NOT start until Walid resolves D1-D6 below** (6.27/6.29 precedent). The idea catalog has been pre-challenged; the decisions pick the locked scope. Every AC below is written for the RECOMMENDED option set and must be amended if Walid picks differently.

## Story

As a user finishing a call,
I want a debrief that is visually compelling, deeply explanatory, verifiably accurate, and directly actionable (tap for detail, copy a focused practice prompt for an external LLM),
so that the report stops being a static summary and becomes the study tool that justifies the product ("the debrief is the real value that justifies payment" — Epic 7 charter).

## Why this story exists (origin)

Story 7.3 shipped the v1 debrief screen faithfully to the locked design docs, and Walid signed its Pixel 9 smoke gate (2026-06-11) — then immediately rejected the REPORT itself: "je n'aime pas trop le style ni même ce qui a marqué dans le rapport." His directives, verbatim intent:

1. Restyle — he dislikes the current visual design.
2. Go much deeper in explanations and in what the report offers.
3. Re-derive the hesitation rules so the >3s threshold and the measurement anchor are demonstrably right.
4. Same rigor pass on `areas_to_work_on`.
5. Flagship: make items ACTIONABLE — tap for richer explanation/detail card, and a copy button per area that puts a complete, single-focus practice prompt on the clipboard, ready to paste into another LLM (e.g. ChatGPT voice mode) to drill ONE thing at a time.
6. "On fait pas mal d'idées et on va les challenger" — broad catalog, then challenge.

This is a CONTENT + ACCURACY + INTERACTIVITY overhaul spanning server and client. It is NOT a 7.3 bug-fix: 7.3's render contract was honored; this story changes the contract.

## Idea Catalog — challenged (KEEP / KILL / DEFER)

### A. Visual design

| # | Idea | Verdict | Challenge |
|---|------|---------|-----------|
| A1 | Full restyle: richer hierarchy, score visualization (ring/arc gauge around the %), section icons, stronger cards | **KEEP** (D4 picks token policy) | Needs a design-spec v2 FIRST — dev must not fly blind; AppColors is a locked 13-token system (theme test fails the build on any new hex outside `core/theme/`) |
| A2 | Animated score reveal (count-up on entry) | **DEFER** | Design doc declared the debrief a static content screen; cheap but cosmetic — revisit after v2 ships |
| A3 | Tabs instead of single scroll | **KILL** | Tabs hide content; single scroll is the validated mobile pattern (UX-DR15) |
| A4 | Per-section icons for scanning rhythm | **KEEP** | Material icons = zero new assets |

### B. Content depth (server-generated — content-is-server-side LAW)

| # | Idea | Verdict | Challenge |
|---|------|---------|-----------|
| B1 | Per-error depth: WHY it's wrong (the rule), 1-2 extra example sentences | **KEEP** | Feeds the E2 detail sheet; on-screen card stays brief (clinical charter), depth revealed on tap |
| B2 | "Better phrasing" suggestions for correct-but-clumsy utterances | **KEEP, capped 0-2** (D5) | Risk of nitpick noise on a weak model; hard cap + only when clearly more natural |
| B3 | Transcript replay in the debrief | **KILL** | 7.1 D1 locked "transcript never persisted" (privacy + storage); reversing is its own decision, not a rider |
| B4 | Personalize depth to the user's level | **DEFER** | `users` has no level field; prompt hardcodes "intermediate level" — needs profile/onboarding work first |
| B5 | Per-area practice prompt (the copy-button payload) | **KEEP — core** | Walid's flagship; server-generated (D2) |
| B6 | Sub-score radar (fluency/grammar/vocab) | **KILL** | Survival % is the product's single honest score (checkpoint-derived); a radar invites fake precision from Scout |
| B7 | Checkpoint breakdown: the met/missed beat list with hint texts | **KEEP** (D5) | NOT praise — it is the factual decomposition of the % the user already saw on the HUD; answers "why 67?" with "you missed THESE 2 beats". Data lives in the bot at teardown (goals state) — must be persisted into `debrief_json` |

### C. Hesitation accuracy (server)

| # | Idea | Verdict | Challenge |
|---|------|---------|-----------|
| C1 | Re-anchor the measured gap (it is systematically OVER-stated today — see Dev Notes forensics) | **KEEP** (D3 picks how) | Server-only compensation is cheap but approximate; client-side measurement is accurate but adds a data-channel protocol |
| C2 | Capture the patience-escalation blind spot: a freeze so long the character re-speaks is currently NEVER recorded (gap only closes on user speech) | **KEEP — high value** | The most dramatic freezes are invisible in v1; fix is observer-local (close the gap at the next `BotStartedSpeaking`/escalation, tag it `unresolved`) |
| C3 | Pair LLM contexts to gaps by ID, not index | **KEEP** | Retires the documented mis-pair residual (deferred-work 7.1); schema pins the echo |
| C4 | Mid-utterance stall detection (user starts then trails off) | **DEFER** | Needs interim-STT/VAD-restart analysis — hairy, low confidence; revisit with real data |
| C5 | Display honesty: "~" prefix + rounding, context says what the character had just asked | **KEEP** | Cheap client tweak that stops over-claiming precision |

### D. Areas-to-work-on rigor (server)

| # | Idea | Verdict | Challenge |
|---|------|---------|-----------|
| D-a | Evidence-linked areas: each area must cite ≥1 flagged error/hesitation from THIS call | **KEEP** | Kills generic filler ("practice grammar"); schema carries `evidence` |
| D-b | Fixed area taxonomy (enum of themes) | **KILL for now** | Procrustean labels from a weak model; free text + evidence gives quality now, taxonomy can come with Epic 9 history features |
| D-c | Guaranteed priority order + "focus first" marker on #1 | **KEEP** | Cheap prompt + display rule; matches "one thing at a time" philosophy |

### E. Actionability (client + server)

| # | Idea | Verdict | Challenge |
|---|------|---------|-----------|
| E1 | Copy-practice-prompt button per area ("Practice with an AI coach") | **KEEP — core** | Clipboard via SDK `Clipboard.setData` (zero new deps); confirmation feedback must respect the house error-UX rule (toast = informational only — a "Copied" toast/inline check is fine) |
| E2 | Tap error/idiom/area card → detail bottom sheet (B1 depth, examples, the practice prompt full text) | **KEEP** (D1) | Bottom sheet pattern already exists (content-warning/difficulty sheets) — reuse, don't reinvent |
| E3 | Deep-link straight into the ChatGPT app | **KILL** | No stable public scheme contract, can't target voice mode, platform-fragile; clipboard is robust and LLM-agnostic |
| E4 | In-app practice chat with our own LLM | **KILL for 7.5** | A whole new product surface (chat UI, cost, safety) — candidate FUTURE epic, not a rider on a report overhaul |
| E5 | Native share button on the hero block | **DEFER** | AC8 made the hero screenshot-worthy WITHOUT a button by design; share_plus = new dep; growth feature, separate decision |
| E6 | AC7 product ruling v2 — buttons are now needed | **KEEP — must be explicit** | 7.3 AC7 says "no CTA buttons exist". The PRINCIPLE was no-retry/no-praise/no-trampoline (FR15 lock). v2 ruling: in-place LEARNING actions (copy, expand) are allowed; navigation/retry/monetization CTAs stay banned. This story formally amends AC7's wording — fold into D1 |

### F. Plumbing / opportunistic fixes (fold in, all KEEP)

| # | Item | Why |
|---|------|-----|
| F1 | Schema v2 back-compat: ALL new `DebriefOut` fields nullable/defaulted — old stored v1 rows MUST keep serving (route validates stored dicts against `DebriefOut`), and the 7.3 client tolerates absent keys by construction | No SQL migration needed for shape (`debrief_json` is TEXT) — but a `debrief_version` field is cheap insurance |
| F2 | Fix `DEFAULT_END_REASON = "user_hangup"` mislabeling a fully-completed call (framing tone keys on reason) | Documented 7.1 residual, content-quality bug |
| F3 | `_normalize_core` per-item validate-and-drop (one malformed item currently drops the WHOLE debrief on the fallback path) | Documented 7.1 residual |
| F4 | Generation budget re-size for the bigger document (max_tokens 2048 / timeout 8s today) + decide single vs split LLM call | NFR7 holds: <5s target / 10s ceiling, masked by the 7.2 overlay |

## Open Decisions — Walid (D1-D6)

- **D1 — Interactivity scope.** (a) copy buttons on areas only; **(b) RECOMMENDED: copy buttons + tap-detail bottom sheets on errors/idioms/areas**; (c) (b) + share + animations. Includes ratifying the E6 AC7-v2 ruling (learning actions allowed; retry/nav CTAs still banned).
- **D2 — Practice-prompt origin.** **(a) RECOMMENDED: server-generated per area at teardown, stored in `debrief_json`** (content-is-server-side law — copy evolves without app release; user's real utterances baked in); (b) client-side template filled with debrief data (no extra LLM cost, but copy frozen per app version, violates the law's spirit).
- **D3 — Hesitation re-anchor depth.** (a) minimal: C2 blind-spot + C3 id-pairing only, keep the raw anchor; **(b) RECOMMENDED: (a) + server-side compensation — subtract the known playout/jitter delay (`LIVEKIT_MIN_PLAYOUT_DELAY_MS`, default 200ms) + a calibrated RTT constant, validated on-device with a stopwatch during the smoke gate, + C5 "~" display honesty**; (c) full client-side measurement (device hears audio end → device detects speech start, shipped over the data channel) — most accurate, biggest scope (new protocol + client timing + sync).
- **D4 — Visual restyle depth.** (a) restyle within the existing 13 tokens; **(b) RECOMMENDED: small token extension (1-3 additions, e.g. an elevated-card surface) — requires updating UX-DR1 + `theme_tokens_test` count + a design-spec v2 section BEFORE client dev**; (c) full re-skin (out of proportion). Also decide: design v2 authored as a section in this story during dev (recommended) vs a separate Sally/UX pass.
- **D5 — Content additions set.** Recommended: checkpoint breakdown B7 = **YES**; per-error depth B1 = **YES**; better-phrasing B2 = **capped 2, YES**; radar B6 = **NO**; transcript B3 = **NO**. Confirm or amend.
- **D6 — Story split.** **(a) RECOMMENDED: single 7.5** (one coherent wire-contract change, one deploy, one smoke gate; phased tasks server→client); (b) split 7.5-server / 7.6-client (smaller reviews, but risks a v2-payload/v1-screen limbo between them and two deploy+gate cycles).

## Acceptance Criteria (provisional — written for the recommended option set)

1. **Given** the v2 schema, **when** a debrief is generated, **then** `debrief_json` carries (all nullable/defaulted for back-compat): `debrief_version: 2`, `checkpoints[]` (id, hint text, met/missed — B7), per-error `explanation` + `examples[]` (B1), ≤2 `better_phrasings[]` (B2), per-area `{title, evidence, practice_prompt}` (D-a, B5), and hesitations carrying `{id, duration_sec, context, resolved}` (C2/C3).
2. **Given** old v1 rows in `debriefs`, **when** `GET /debriefs/{call_id}` serves them, **then** the response validates and the v2 client renders them without crash (absent v2 fields → sections hidden) — and a v2 payload parsed by the OLD client (7.3 build) must not break its `tryParse` (additive-only keys).
3. **Given** hesitation measurement (D3-b), **when** a gap is recorded, **then** the stored duration subtracts the configured playout-delay compensation, a freeze that triggers character re-speak IS captured (closed at the bot's next speech start, flagged `resolved: false`), contexts pair to gaps by id (never index), and the UI renders durations as approximate ("~5s" rounding per design v2).
4. **Given** `areas_to_work_on` v2, **when** areas render, **then** each cites in-call evidence, order is priority (the first marked as the focus), and count stays ≤3.
5. **Given** a non-null `practice_prompt` on an area, **when** the user taps its copy button, **then** the clipboard receives the complete self-contained prompt (coach role + the ONE focus area + the user's actual failing utterances + voice-conversation instructions), a "Copied" confirmation appears (informational pattern only), and NO network call is made.
6. **Given** D1-b, **when** the user taps an error/idiom/area card, **then** a bottom sheet presents the depth content (rule, examples, full practice text where applicable) — reusing the established sheet pattern.
7. **Given** the AC7-v2 ruling, **when** the debrief renders, **then** learning-action buttons (copy/expand) exist but NO retry, navigation, share, or monetization CTA does, and no praise strings appear (clinical charter intact).
8. **Given** the design-spec v2 (D4), **when** the screen renders, **then** layout/typography/colors match it, `flutter analyze`'s token test passes (any new color added through `AppColors` + UX-DR1 update), and the hero block remains a self-contained screenshot-worthy unit (AC8 preserved).
9. **Given** NFR7, **when** the v2 generation runs at teardown, **then** total generation respects the 10s hard ceiling (measured in logs), with the token budget and single/split-call choice documented; a generation failure still yields the graceful `DEBRIEF_NOT_READY` → 7.3 fallback chain.
10. **Given** the gates, **when** the story completes, **then** server `ruff` + `pytest` and client `flutter analyze` + `flutter test` are green, golden/calibration suites are untouched (no scenario YAML changes), and the deferred-work residuals F2/F3 + the 7.1 hesitation/index residual are marked retired.

## Tasks / Subtasks (provisional — re-cut after the decision pass)

- [ ] Task 0: Decision pass — Walid resolves D1-D6; amend ACs/tasks accordingly (BLOCKING)
- [ ] Task 1: Design spec v2 (AC: 8)
  - [ ] 1.1 Author the v2 visual spec (new section appended to debrief-screen-design.md or a v2 doc): hierarchy, gauge/hero treatment, card anatomy incl. tap affordance + copy button, sheet layouts, approximate-duration display, section icons
  - [ ] 1.2 If D4-b: define the new token(s), update UX-DR1 note + `AppColors.values` + `theme_tokens_test` count
- [ ] Task 2: Server — hesitation accuracy (AC: 3)
  - [ ] 2.1 `hesitation_observer.py`: id per gap; close-at-bot-restart capture (`resolved: false`); playout-delay compensation (config-driven, default = `LIVEKIT_MIN_PLAYOUT_DELAY_MS` + calibrated constant, floor at 0)
  - [ ] 2.2 Threshold re-validation: with compensation in place, re-affirm or adjust the 3.0s threshold; document the rationale in-code
  - [ ] 2.3 `_merge_hesitations` → id-based pairing; schema echoes `hesitation_id`
  - [ ] 2.4 Unit tests incl. the escalation-blind-spot scenario and compensation floor
- [ ] Task 3: Server — content v2 (AC: 1, 4, 9 + F2/F3/F4)
  - [ ] 3.1 Extend `_build_debrief_schema` + `DEBRIEF_SYSTEM_PROMPT` (per-error explanation/examples, better_phrasings cap, evidence-linked prioritized areas, per-area practice_prompt rules) — STRICT json_schema law holds (Scout)
  - [ ] 3.2 Thread checkpoint met/missed state from the bot teardown into assembly (B7)
  - [ ] 3.3 `assemble_debrief` v2 + `debrief_version: 2`; `DebriefOut` additive nullable fields
  - [ ] 3.4 F2 end-reason `completed` label; F3 per-item salvage in `_normalize_core`; F4 budget re-size + single-vs-split call measurement
  - [ ] 3.5 Server tests: schema round-trip, v1-row back-compat through the route, budget/timeout behavior
- [ ] Task 4: Client — model v2 (AC: 2)
  - [ ] 4.1 Extend `Debrief` tryParse with the additive fields (same strict-hero/defensive-array philosophy); v1 payloads parse unchanged
- [ ] Task 5: Client — screen v2 (AC: 5, 6, 7, 8)
  - [ ] 5.1 Restyle per design v2; checkpoint-breakdown section; approximate durations; focus-first area marker
  - [ ] 5.2 Detail bottom sheets (D1-b) reusing the established sheet pattern
  - [ ] 5.3 Copy button per area: `Clipboard.setData`, "Copied" confirmation, a11y labels
  - [ ] 5.4 Widget tests: v2 render, v1-payload fallback render, copy-to-clipboard assertion, sheet open/close, AC7-v2 negatives (no retry/nav CTA, no praise)
- [ ] Task 6: Gates + deploy + smoke (AC: 9, 10)
  - [ ] 6.1 Full server + client gates green
  - [ ] 6.2 VPS deploy; Smoke Test Gate boxes below
  - [ ] 6.3 Finalize the Pixel 9 ready-to-play script (stopwatch hesitation check, freeze-to-escalation check, copy→paste-into-ChatGPT-voice check)

## Smoke Test Gate (Server / Deploy Stories Only)

> Server schema/generation changes + deploy → this section applies. Boxes to be filled at dev time; every unchecked box is a stop-ship for `in-progress → review`.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_
- [ ] **Happy-path endpoint round-trip.** `GET /debriefs/{call_id}` for a fresh v2 call returns the v2 fields (`debrief_version: 2`, checkpoints, practice prompts).
  - _Command:_ curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/debriefs/{id}
  - _Actual:_
- [ ] **v1 back-compat round-trip.** An OLD `debriefs` row (pre-deploy) still serves 200 with the v1 shape — no validation error.
  - _Command:_ curl against a pre-deploy call_id
  - _Actual:_
- [ ] **DB side-effect verified.** New row carries `debrief_version: 2` JSON.
  - _Command:_ venv python sqlite3 read of the latest debriefs row
  - _Actual:_
- [ ] **DB backup taken BEFORE deploy.** (No SQL migration expected — JSON-shape change only — but back up anyway: schema guard.)
  - _Proof:_
- [ ] **Server logs clean + generation budget.** `journalctl` shows the v2 generation completing under the ceiling, no ERROR/Traceback.
  - _Proof:_

## Pixel 9 Smoke Gate (owed before review → done — script to FINALIZE after the decision pass)

Draft shape (the dev finalizes exact lines + expected visuals once D1-D5 lock):

1. Waiter scenario, normal short call with 2 seeded errors → hang up → debrief v2: new visual style, checkpoint breakdown matches the HUD ticks seen in-call.
2. Second call: after the character's first question, FREEZE deliberately with a stopwatch (~6s) until the character re-speaks, then answer normally → debrief must list that hesitation (money moment: the duration shown ≈ stopwatch minus compensation, marked approximate; in v1 this freeze was invisible).
3. Tap an error card → detail sheet opens with the rule + examples.
4. Tap the copy button on area #1 → "Copied" → paste into ChatGPT (voice) → money moment: the pasted prompt sets up a one-focus coaching conversation using YOUR actual phrases from the call.
5. Back arrow → list (no retry/nav CTAs anywhere).

## Dev Notes

### Current-state forensics (what v1 actually does — verified in code 2026-06-11)

**Hesitation measurement (`server/pipeline/hesitation_observer.py`)** — gap = server-side `BotStoppedSpeakingFrame` → next `UserStartedSpeakingFrame`, `time.monotonic` diff, `> 3.0s` recorded, top-3 longest kept with the preceding character line. Four documented flaws:
1. **Systematic over-statement** (deferred-work 7.1, blind hunter): the anchor includes downlink + client jitter-buffer playout (`LIVEKIT_MIN_PLAYOUT_DELAY_MS` default **200ms** — our own config, `pipeline/livekit_tokens.py`) + uplink + VAD detection latency. The user's FELT pause is shorter than the measured one.
2. **Escalation blind spot** (NEW finding this story): `_bot_stopped_at` is only closed by a `UserStartedSpeakingFrame`. If the user freezes long enough that the patience ladder makes the character speak again, the next `BotStoppedSpeakingFrame` OVERWRITES the anchor — the dramatic freeze is never recorded. The very behavior the feature exists to surface is invisible.
3. **By-index context pairing** (deferred-work 7.1): `_merge_hesitations` (debrief_assembly.py) trusts the LLM to return `hesitation_contexts` in input order; a reordered/short list mis-pairs duration↔context.
4. Mid-utterance stalls are out of scope by design (only bot-stop→user-start gaps exist).
Observer hygiene rules that MUST survive any edit: observe-never-consume (push_frame FIRST), no direction gating (frame-direction trap, server/CLAUDE.md §1), NEVER name an attribute `_clock`/`_next`/`_prev`/etc. (base-class shadow trap — it stores its clock as `_now` for exactly this reason).

**Generation (`server/pipeline/debrief_generator.py`)** — single non-streaming Groq call, `Settings.debrief_model` = Scout, STRICT `response_format=json_schema` (`strict: True`, all-required + `additionalProperties:false` — Groq strict mode REJECTS minItems/maxItems, so length rules live in prompt + backend clamps). `_MAX_TOKENS = 2048`, outer timeout 8.0s / httpx 7.5s, temp 0.2. Never raises — any failure returns None → no debrief row → eternal `DEBRIEF_NOT_READY` (the 7.3 client's 30s budget handles it). `finish_reason == "length"` → None (truncation guard): v2's bigger document MUST re-size `_MAX_TOKENS` with the same ~4× headroom logic and re-measure wall-clock. `_enforce_inappropriate_behavior` pins the FR37 invariant backend-side. The fence/first-`{...}` fallback parse + `_normalize_core` exist for non-strict providers; F3 = per-item salvage there.

**Prompt (`server/pipeline/prompts.py` → `DEBRIEF_SYSTEM_PROMPT`, line ~464)** — the clinical tone charter (NEVER praise/hedge/exclaim; ALWAYS exact quotes, one-sentence contexts, char caps per field), top-5 error selection (frequency > impact > diversity, dedup with count), idiom inclusion rules, areas format `"[Theme] ([specific example])"`. v2 extends — does NOT relax — the charter: depth fields stay factual ("the rule is X; examples: …"), practice prompts are instructions to a COACH, not praise to the user.

**Assembly (`server/pipeline/debrief_assembly.py`)** — pure functions; survival = floor(passed/total*100) clamp 0-100; `encouraging_framing` only >40% (key omitted otherwise — client keys on presence); copy composed server-side. v2 additions slot here (checkpoint list, version field).

**Teardown (`server/pipeline/debrief_teardown.py` + `bot.py` ~814-819)** — bot generates at teardown (7.1 D1: Option A, transcript NEVER persisted), single `BEGIN IMMEDIATE` claims idempotency for progress bump + counts (7.1 review P1 — do not break the atomic claim when threading checkpoint state through). `DEFAULT_END_REASON = "user_hangup"` mislabels survived-by-completion calls (F2: emit a distinct `completed` reason). Known residual: `busy_timeout` contention swallow (low priority, not in scope unless trivial).

**Wire contract (`server/models/schemas.py:212-273 DebriefOut` + `server/api/routes_debriefs.py`)** — the route serves the STORED dict (already omission-correct) validated against `DebriefOut`; therefore **every v2 field must be nullable/defaulted or old rows 500** (AC2 is the regression guard). `debriefs.debrief_json` is TEXT — JSON-shape changes need NO SQL migration; if any column IS added, the migration replay law applies (prod_snapshot, PRAGMA foreign_keys=OFF for rebuilds).

**Client v1 (`client/lib/features/debrief/…`, Story 7.3, review pending)** — `Debrief.tryParse` strict on 4 hero scalars / defensive on everything else (absent v2 keys are already safe in BOTH directions); `DebriefScreen` = StatefulWidget, NO bloc, 3-phase machine (content/loading/unavailable), BS-7 poll (1s/30s seams), `AnimatedSwitcher` 300ms, back = root-`Navigator.pop()` (never `context.pop()`), `RouteSettings.arguments` kept for 7.2 tests, hub report-icon path still on `DebriefPlaceholderScreen` (Epic 9 — do NOT touch `router.dart`). House test rules: 320×568 surface, never `pumpAndSettle` with live poll timers, mocktail.

### Locked laws that BOUND this story (violating any = automatic review finding)

- **Content-is-server-side** (Walid 2026-06-09): all copy/practice prompts that may evolve live in the payload, not the app.
- **Structured-output law** (server/CLAUDE.md §4): any model used for generation must support strict `json_schema`; Scout is the pin; 70B HTTP-400s on it.
- **Clinical no-praise charter** (debrief-content-strategy Q1/Q2/Q9): no strengths section, no summary, no praise — B7's checkpoint list is DATA, keep it that way.
- **FR15 lock**: no retry button, no forward CTA — the AC7-v2 ruling allows learning actions only.
- **7.1 D1**: transcript never persisted — B3 stays dead unless Walid reopens it as its own decision.
- **Theme token test**: no hex outside `core/theme/`; AppColors count asserted (13 today) — D4-b must update the test + UX-DR1 note together.
- **NFR7**: <5s target / 10s hard ceiling for generation; the 7.2 overlay masks 3-10s only.
- **Groq quotas** (infra memory): free tier; bigger debriefs burn more TPD — measure, and keep the one-call-per-call shape if possible.
- **iOS untested** (Epic 10): clipboard behavior verified on Android (Pixel 9) only; note any iOS-conditional code for 10-4.

### Practice-prompt content spec (B5/E1 — draft for the generator prompt)

Each area's `practice_prompt` is a self-contained block the user pastes into ANY LLM:
- Sets the assistant role: English conversation coach for an intermediate learner, voice-mode friendly (short turns, ask-then-wait).
- States the SINGLE focus: the area title + its evidence (the user's real utterances + corrections from this call, quoted).
- Instructs the flow: brief diagnosis recap → drill through 5-8 prompted exchanges targeting the pattern → end with a 3-line progress verdict. No praise inflation; correct on the spot.
- Explicitly forbids drifting to other topics ("one thing at a time" — Walid).
- Length target ≤ ~900 chars (clipboard-friendly, fits voice-mode context comfortably).

### Latest tech check

No new packages required: clipboard = `flutter/services` `Clipboard.setData` (SDK); bottom sheets = existing house pattern (content-warning/difficulty sheets); icons = bundled Material set. Server: no new deps (httpx + Groq json_schema as today). If D3-c (client-side timing) were chosen, livekit_client 2.6.4 audio-event timing capabilities must be researched first — flagged as a research subtask, not assumed.

### Project Structure Notes

- Server: `pipeline/hesitation_observer.py`, `pipeline/debrief_generator.py`, `pipeline/debrief_assembly.py`, `pipeline/debrief_teardown.py`, `pipeline/prompts.py`, `models/schemas.py`, `api/routes_debriefs.py` + mirror tests.
- Client: `features/debrief/models/debrief.dart`, `features/debrief/views/debrief_screen.dart` (+ new `views/widgets/` for sheets/cards as the design v2 dictates), `core/theme/` only if D4-b.
- Design: `_bmad-output/planning-artifacts/debrief-screen-design.md` (v2 section) + `debrief-content-strategy.md` (v2 amendment — new Q decisions recorded there to stay the schema authority).

### References

- [Source: _bmad-output/implementation-artifacts/7-3-build-debrief-screen.md] — v1 screen, smoke-gate sign-off + Walid's verdict (origin of this story)
- [Source: _bmad-output/implementation-artifacts/deferred-work.md §story-7.1] — hesitation approximation + index-pairing + _normalize_core + end-reason residuals (F2/F3/C1/C3 retire these)
- [Source: server/pipeline/hesitation_observer.py] — measurement mechanics + traps
- [Source: server/pipeline/debrief_generator.py + prompts.py DEBRIEF_SYSTEM_PROMPT] — generation contract + tone charter
- [Source: server/pipeline/debrief_assembly.py + models/schemas.py:212-273] — assembly + wire contract
- [Source: _bmad-output/planning-artifacts/debrief-content-strategy.md] — Q1-Q10 locked content decisions (v2 amends, never silently contradicts)
- [Source: _bmad-output/planning-artifacts/debrief-screen-design.md] — v1 design (to be superseded by the v2 section)
- [Source: _bmad-output/planning-artifacts/prd.md FR9-FR15b, FR37, NFR7] — functional bounds
- [Source: server/CLAUDE.md §1 §4] — frame-direction/attribute-shadow traps, structured-output law
- [Source: client/CLAUDE.md] — token test, pumpAndSettle, surface size, mocktail rules

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
