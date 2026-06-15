# Story 7.5: Overhaul Debrief Report (v2)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> ## ✅ DECISION PASS RESOLVED — Walid 2026-06-11, dev UNBLOCKED
>
> **D1=(b)** copy buttons + tap-detail bottom sheets (AC7-v2 ruling ratified: learning actions allowed, retry/nav CTAs banned) · **D2=(a)** practice prompts server-generated at teardown · **D3=(c) CLIENT-SIDE hesitation measurement** — the device measures felt gaps (character audio ends on the phone → user speech starts at the mic) and ships them over the data channel; server-side v1 measurement (escalation-fixed) stays as FALLBACK. The one pick that diverges from the recommendation — it is the biggest-scope option and drives Task 2's research spike. · **D4=(b)** small token extension (1-3) with UX-DR1 + theme-test update, design v2 before client dev · **D5=confirmed** (checkpoints YES, per-error depth YES, better-phrasings capped-2 YES, radar NO, transcript NO) · **D6=(a)** single story.
>
> ACs and tasks below are amended to this locked scope.

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

## Decision Pass — RESOLVED (Walid, 2026-06-11)

- **D1 = (b).** Copy buttons on areas + tap-detail bottom sheets on errors/idioms/areas. The E6 **AC7-v2 product ruling is RATIFIED**: in-place LEARNING actions (copy, expand) are allowed on the debrief; retry / navigation / share / monetization CTAs stay banned; no praise.
- **D2 = (a).** Practice prompts are SERVER-generated per area at teardown and stored in `debrief_json` (content-is-server-side law — copy evolves without an app release; the user's real utterances are baked into the prompt text).
- **D3 = (c) — CLIENT-SIDE measurement (diverges from the recommendation; biggest-scope option, deliberately chosen).** The DEVICE measures the felt gap: character audio finishes playing on the phone → user's speech starts at the mic. Measured gaps ship to the bot over the LiveKit data channel. The server-side v1 observer stays as the FALLBACK source (old app builds, channel failures) and gets the escalation-blind-spot fix on its path too. See Dev Notes §"D3-c architecture" — Task 2 opens with a research spike because neither the client speech-boundary events nor pipecat's data-receive path are proven yet.
- **D4 = (b).** Small token extension (1-3 additions max) — UX-DR1 note + `AppColors.values` + `theme_tokens_test` count updated together; design-spec v2 authored BEFORE client dev (in-story).
- **D5 = confirmed as recommended.** Checkpoint breakdown B7 YES · per-error depth B1 YES · better-phrasings B2 YES capped at 2 · radar B6 NO · transcript replay B3 NO.
- **D6 = (a).** Single story 7.5 — one wire-contract change, one deploy, one smoke gate; tasks phased server → client.

## Acceptance Criteria (provisional — written for the recommended option set)

1. **Given** the v2 schema, **when** a debrief is generated, **then** `debrief_json` carries (all nullable/defaulted for back-compat): `debrief_version: 2`, `checkpoints[]` (id, hint text, met/missed — B7), per-error `explanation` + `examples[]` (B1), ≤2 `better_phrasings[]` (B2), per-area `{title, evidence, practice_prompt}` (D-a, B5), and hesitations carrying `{id, duration_sec, context, resolved, source}` (C2/C3/D3-c — `source` ∈ `"device"|"server"`).
2. **Given** old v1 rows in `debriefs`, **when** `GET /debriefs/{call_id}` serves them, **then** the response validates and the v2 client renders them without crash (absent v2 fields → sections hidden) — and a v2 payload parsed by the OLD client (7.3 build) must not break its `tryParse` (additive-only keys).
3. **Given** hesitation measurement (D3-c), **when** the user pauses after a character turn, **then** the DEVICE measures the felt gap (character audio playback ends on the phone → user speech onset at the mic, both boundaries local — no network terms), gaps >3s ship to the bot over the data channel as versioned `hesitation` envelopes, the debrief stores device gaps as authoritative (`source: "device"`) and falls back to the server observer (`source: "server"`) when none arrived (old app build, channel failure), a freeze that triggers character re-speak IS captured on BOTH paths (closed at the character's next speech start, `resolved: false`), contexts pair to gaps by id (never index), and the UI renders durations as approximate ("~5s" per design v2). On-device validation: a stopwatch-timed deliberate freeze reports within ±0.5s. **[Code-review 2026-06-15 — SHIPPED DELTA: the device-authoritative half of this AC did NOT ship. The live source is the server `HesitationObserver` re-anchored on the client `playback_idle` signal (accurate gap-START at the user's ear, gap-END via server VAD, threshold raised to 4 s). The DEVICE path (`DeviceHesitationCollector` + `merge_hesitation_sources`) is built but DORMANT (`merge` uncalled) because the on-device onset detector under-produces. Device-authoritative measurement is DEFERRED to a follow-up story: fix the client onset detector → wire the teardown merge → smoke. See Review Findings.]**
4. **Given** `areas_to_work_on` v2, **when** areas render, **then** each cites in-call evidence, order is priority (the first marked as the focus), and count stays ≤3.
5. **Given** a non-null `practice_prompt` on an area, **when** the user taps its copy button, **then** the clipboard receives the complete self-contained prompt (coach role + the ONE focus area + the user's actual failing utterances + voice-conversation instructions), a "Copied" confirmation appears (informational pattern only), and NO network call is made.
6. **Given** D1-b, **when** the user taps an error/idiom/area card, **then** a bottom sheet presents the depth content (rule, examples, full practice text where applicable) — reusing the established sheet pattern.
7. **Given** the AC7-v2 ruling, **when** the debrief renders, **then** learning-action buttons (copy/expand) exist but NO retry, navigation, share, or monetization CTA does, and no praise strings appear (clinical charter intact).
8. **Given** the design-spec v2 (D4), **when** the screen renders, **then** layout/typography/colors match it, `flutter analyze`'s token test passes (any new color added through `AppColors` + UX-DR1 update), and the hero block remains a self-contained screenshot-worthy unit (AC8 preserved).
9. **Given** NFR7, **when** the v2 generation runs at teardown, **then** total generation respects the 10s hard ceiling (measured in logs), with the token budget and single/split-call choice documented; a generation failure still yields the graceful `DEBRIEF_NOT_READY` → 7.3 fallback chain.
10. **Given** the gates, **when** the story completes, **then** server `ruff` + `pytest` and client `flutter analyze` + `flutter test` are green, golden/calibration suites are untouched (no scenario YAML changes), and the deferred-work residuals F2/F3 + the 7.1 hesitation/index residual are marked retired.

## Tasks / Subtasks (provisional — re-cut after the decision pass)

- [x] Task 0: Decision pass — RESOLVED 2026-06-11 (D1=b, D2=a, D3=c, D4=b, D5=confirmed, D6=a); ACs/tasks amended same day
- [x] Task 1: Design spec v2 (AC: 8) — **DONE + WALID-VALIDATED 2026-06-15** (Direction B "riche au clic, sobre au premier regard"; concept→judge→synth workflow). 4 decisions: (1) gauge 3-color red≤40/amber41-99/green100, (2) add `AppColors.gaugeTrack`, (3) detail sheet DARK (not the light reuse), (4) copy button on AREAS ONLY (errors = tap-detail). Spec appended to `debrief-screen-design.md` §v2.0.
  - [x] 1.1 Author the v2 visual spec — arc-gauge hero (AC8 screenshot-worthy), checkpoint breakdown, error cards w/ tap-detail (DARK sheet: rule+examples), hesitations w/ approximate `~Ns` + freeze note, idioms, "said more naturally", area cards w/ copy-practice button + "Copied" toast; copy deck (banned-copy lint) + build notes in the doc.
  - [x] 1.2 D4-b: `AppColors.gaugeTrack = 0xFF2A2B30` (1 of 3 budget) + UX-DR1 note + `AppColors.values` (15) + `theme_tokens_test` count 14→15 — green.
- [ ] Task 2: Hesitation accuracy — D3-c client-authoritative measurement + server fallback (AC: 3)
  - [x] 2.0 RESEARCH SPIKE (timeboxed; blocks 2.1+): prove the three unknowns — (a) character-audio-END signal on the phone (candidates: the 6.3b lip-sync/viseme machinery which already tracks character speech against real playback; livekit_client remote `SpeakingChangedEvent`/audioLevel — measure each candidate's lag); (b) user-speech-ONSET signal (local participant speaking/audioLevel events vs raw mic-energy threshold); (c) uplink data path: client `publishData` → pipecat LiveKitTransport data-received hook on the bot (the bot only SENDS envelopes today). Record findings + chosen signals in Dev Agent Record. If (a) or (b) proves unworkable in the timebox, STOP and re-open D3 with Walid (fallback = the D3-b server-compensation design).
  - [x] 2.1 Client `HesitationMeter` service — **DONE 2026-06-15 (commits 293591d + 3700ed3)**: the noise-robust onset state machine (10 unit tests incl. the MONEY TEST) + the native `AudioCaptureChannel.kt` record-side RMS tap (mirrors `AudioClockChannel` reflection, fail-soft) registered in `MainActivity` + `call_screen.dart` wiring (monotonic Stopwatch clock, arm off the end-of-turn `onSilenceConfirmed`, feed mic RMS, DISARM on any non-REST viseme = the arming gate, dispose teardown). Native tap accuracy/noise proven on the Pixel 9 smoke gate.
  - [x] 2.2 Client→server envelope `{type:"hesitation_onset", gap_ms, censored}` published via the existing `publishData` (`_publishHesitationOnset`, reliable, fail-soft) → bot `on_data_received` → `DeviceHesitationCollector` (commit 5eb0e36). Versioned type: old servers ignore it, old clients never send it.
  - [x] 2.3 Server-side D3-c — **DONE 2026-06-15 (commits 420517e + 5eb0e36)**: `HesitationObserver` escalation-blind-spot fix (C2) + id-tagging (C3); assembly id-based `_merge_hesitations`; NEW `DeviceHesitationCollector` (gathers `hesitation_onset` envelopes, `source="device"`, snapshots the line bot-side) + `merge_hesitation_sources` (teardown prefers device, adds the observer's unresolved freezes, full fallback when no device gaps); bot.py wires `on_data_received` to RECORD device gaps. **[code-review 2026-06-15: teardown does NOT call the merge — it passes the server observer only; `merge_hesitation_sources` is DORMANT, deferred to a follow-up story.]**
  - [x] 2.4 Threshold — 4.0 s (raised from 3 s, Story 7.5 smoke 2026-06-15), enforced in BOTH layers (`HesitationMeter.minGap` client-side + `DeviceHesitationCollector` threshold server-side), rationale documented in-code; final confirm = the smoke gate's ±0.5 s check.
  - [x] 2.5 Tests — **server-side DONE**: observer escalation/id (+5), device collector + merge + fallback (+6), `HesitationMeter` onset unit tests incl. the MONEY TEST (+10). **REMAINING: the client envelope-contract test once `call_screen` publishes (with 2.2).**
- [x] Task 3: Server — content v2 (AC: 1, 4, 9 + F2/F3/F4) — **DONE 2026-06-14 (commits 7cb97d9 + 9d677ca), full server suite 899 green**
  - [x] 3.1 Extend `_build_debrief_schema` + `DEBRIEF_SYSTEM_PROMPT` (per-error explanation/examples, better_phrasings cap, evidence-linked prioritized areas, per-area practice_prompt rules) — STRICT json_schema law holds (Scout); designed via the content-design workflow (concept→judge→synth), drift guard + 2 authority docs updated in lockstep, version 2.1
  - [x] 3.2 Thread checkpoint met/missed state from the bot teardown into assembly (B7) — `CheckpointManager.checkpoint_breakdown` → `persist_debrief` → `assemble_debrief`
  - [x] 3.3 `assemble_debrief` v2 + `debrief_version: 2`; `DebriefOut` additive nullable fields (back-compat AC2; rich `areas` + derived `areas_to_work_on`; backend-pinned `is_focus`)
  - [x] 3.4 F2 end-reason `completed` (`resolve_end_reason`); F3 per-item salvage in `_normalize_core`; F4 `_MAX_TOKENS` 2048→3072 — single call (split is the contingency; wall-clock to re-measure at deploy per AC9)
  - [x] 3.5 Server tests: schema round-trip, v1-row back-compat through the route, clamps/salvage, teardown threading
- [x] Task 4: Client — model v2 (AC: 2) — **DONE 2026-06-14 (commit ec99b91), client suite 532 green**
  - [x] 4.1 Extend `Debrief` tryParse with the additive fields (same strict-hero/defensive-array philosophy); v1 payloads parse unchanged
- [x] Task 5: Client — screen v2 (AC: 5, 6, 7, 8) — **DONE 2026-06-15 (commit 12aa987), full client suite 533 green**
  - [x] 5.1 Restyle per design v2: arc-gauge scorecard hero (3-color CustomPainter, AC8), checkpoint-breakdown section (B7), approximate `~Ns` durations + freeze note, FOCUS-FIRST area marker; 12-caps eyebrows + two-ink discipline
  - [x] 5.2 DARK detail bottom sheet (D1-b, Walid override of the light reuse) on errors with depth — rule + examples, reuses the showModalBottomSheet plumbing
  - [x] 5.3 Copy button on AREAS (Walid: areas-only) — `Clipboard.setData` server prompt verbatim + "Copied" `AppToast` (informational) + a11y label
  - [x] 5.4 Widget tests (24): v2 render, gauge 3-color, checkpoints, v1-payload fallback (AC2), copy-to-clipboard assertion, dark sheet open/close, AC7-v2 negatives (no retry/nav CTA, no praise, no "!"), BS-7, a11y
- [x] Task 6: Gates + deploy + smoke (AC: 9, 10) — deploy DONE; Pixel 9 smoke gate OWED (Walid)
  - [x] 6.1 Full gates green: server ruff + pytest (CI 27537998924) + client analyze + flutter 543
  - [x] 6.2 VPS deploy: pushed b1c7d56, CI success, `/health` SHA match + `db: ok`, DB backups confirmed, v1 back-compat verified live, quota clear (3 available)
  - [x] 6.3 Pixel 9 ready-to-play script FINALIZED above (report visual + checkpoint breakdown + tap-detail sheet + copy→paste + the on-device hesitation + the NOISE money-test) + release APK built from b1c7d56

## Smoke Test Gate (Server / Deploy Stories Only)

> Server schema/generation changes + deploy → this section applies. Boxes to be filled at dev time; every unchecked box is a stop-ship for `in-progress → review`.

- [x] **Deployed to VPS.** `active`; `/health` `git_sha: b1c7d56` matches HEAD, `db: ok`. CI run 27537998924 success (ruff + pytest + Deploy to VPS).
  - _Proof:_ `{"data":{"status":"ok","db":"ok","git_sha":"b1c7d56c…"}}`
- [ ] **Happy-path endpoint round-trip.** `GET /debriefs/{call_id}` for a fresh v2 call returns `debrief_version: 2` + checkpoints + practice prompts. **→ verified by the Pixel 9 smoke gate's first call (no v2 debrief exists on prod until a post-deploy call runs).**
  - _Command:_ curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/debriefs/{id}
- [x] **v1 back-compat round-trip.** OLD `debriefs` row (call_id=287, pre-deploy v1 shape) serves **HTTP 200** through the v2 `DebriefOut` route — `debrief_version` absent (defaults to 1 client-side), keys are the v1 set. No validation error (AC2 guard holds on real prod data).
- [ ] **DB side-effect verified.** New row carries `debrief_version: 2`. **→ verified on the smoke gate's first call** (the bot writes it at teardown).
- [x] **DB backup taken BEFORE deploy.** `db.pre-b1c7d56.sqlite` (deploy-server.yml auto-backup) + `db.pre-smoke75-20260615-095440.sqlite` (manual pre-quota-check). No SQL migration (JSON-shape only).
- [ ] **Server logs clean + generation budget.** `journalctl -u pipecat.service` shows the v2 generation under the 10 s ceiling, no ERROR/Traceback. **→ verified on the smoke gate's first call.**

## Pixel 9 Smoke Gate (owed before review → done) — READY-TO-PLAY (finalized 2026-06-15)

**Prereqs:** install the release APK **rebuilt from `e84a24e`** (the post-code-review HEAD — the old b1c7d56 APK predates the client review patches). You have 3 calls available today (UTC). Responses below are APPROXIMATE (live LLM) — replay the lines, watch the HUD/debrief, no need to predict exactly.

> **Scope update (code-review 2026-06-15):** device-authoritative hesitation is DEFERRED to a follow-up story; the SHIPPED hesitation is the SERVER hybrid (gap-start anchored on the client `playback_idle` signal, gap-end via the server VAD). So CALL 2 still validates the freeze + anti-inflation (now via the server observer), and the old CALL 3 "noise money-test" — which tested the DEVICE onset detector's noise robustness — moves to the device follow-up story and is NOT a 7.5 gate.

**CALL 1 — the new report + checkpoint breakdown + tap-detail + copy (no freezing).** Scenario: **"Order your dinner"** (The Waiter).
- "Hello, I am want to order food."  → waiter takes it (error seeded: *I am want* → *I want*)
- "I will take the chicken please."  → waiter acknowledges
- "He don't have a Coke?"  → waiter replies (error seeded: *He don't* → *Doesn't he* / *Don't you*)
- Hang up.
- **WATCH the debrief:** the **arc-gauge** score (red ≤40 / amber 41-99 / green 100), the **CHECKPOINTS** list (ticks match what you saw on the in-call HUD), your 2 errors with corrections.
- **Tap an error card** → a **dark sheet** slides up with the rule + example sentences. ← money moment (tap-for-detail).
- **Tap "Copy practice"** under the first "AREAS TO WORK ON" card → a small **"Copied"** appears → paste into ChatGPT (or any LLM): it should be a complete coaching prompt built from YOUR real phrases. ← money moment (copy→paste).
- Back arrow → scenario list. Confirm: **no** "retry"/"replay"/"share"/upsell buttons anywhere.

**CALL 2 — the hesitation freeze (server-hybrid measurement; the freeze v1 missed/inflated).** "Order your dinner" again.
- "Hi, I would like to order."  → waiter asks what you'd like
- **FREEZE — say nothing for ~6 s (use a stopwatch)** until the waiter speaks again ("Sir? Ready to order?"), then: "Sorry. The soup, please." → hang up.
- **WATCH the debrief HESITATIONS:** your freeze must appear as **"~6s"** (expect within ~±1 s — the hybrid measures gap-end at the server VAD, so a small over-read is normal). ← money moment (in v1 this freeze was invisible and durations were network-inflated; the playback_idle anchor fixes the inflation).

**CALL 3 — DEFERRED to the device follow-up story (NOT a 7.5 gate).** The old "noise money-test" validated the DEVICE onset detector's noise robustness; the device path is now deferred (it under-produces — see Review Findings — Client). The shipped hybrid uses the mature server-side VAD, so the noise case is re-tested when the device follow-up ships. For 7.5 you only need CALL 1 (the v2 report) + CALL 2 (the freeze). A 3rd call is optional — e.g. repeat CALL 1 on a different scenario to spot-check the report renders.

**If anything's off** — the v2 report looks wrong (gauge / checkpoints / copy / tap-sheet), a checkpoint tick mismatches, or a freeze is wildly off (>~2 s) — tell me the exact numbers and I dig in. Otherwise: report verdict → the formal code review is already DONE, so your sign-off is the LAST gate and I flip `review → done`.

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

### D3-c architecture — client-authoritative hesitation measurement (decided 2026-06-11)

> **SHIPPED DELTA (code-review 2026-06-15):** This design is the DEFERRED target, not what 7.5 ships. 7.5 ships the server `HesitationObserver` re-anchored on the client `playback_idle` signal (accurate gap-START at the user's ear + server-VAD gap-END, threshold 4 s). The full device-authoritative path below is built but DORMANT (`merge_hesitation_sources` uncalled) because the on-device onset detector under-produces (seed-window contamination). Reviving it = a follow-up story: fix the onset detector → wire the merge → smoke. Walid 2026-06-15 ratified the device direction; the work is client-first.

- **Why client-side:** the v1 server anchor includes downlink + the phone's jitter-buffer playout (our own `LIVEKIT_MIN_PLAYOUT_DELAY_MS` = 200ms) + uplink + VAD lag — felt time ≠ measured time, and no server-side constant can be exact. Measuring BOTH boundaries on the device removes every network term. The gap is computed locally with a monotonic clock — only the final `duration_ms` ships, so there is NO cross-device clock-sync problem.
- **Boundary candidates (2.0 proves them):** character-audio-end — the Story 6.3b lip-sync stack (`viseme_scheduler`) already tracks character speech against actual playback for the puppet's mouth, likely the best anchor; alternative = remote participant `SpeakingChangedEvent`/audioLevel (beware built-in hysteresis, typically 100-300ms — measure it). User-speech-onset — local participant speaking/audioLevel events (same hysteresis caveat) or a raw mic-energy threshold; onset accuracy matters, word accuracy does not.
- **Uplink path:** client `LocalParticipant.publishData` (reliable mode) → SFU → bot. pipecat's `LiveKitTransport` data-received hook must be PROVEN (today the bot only sends envelopes; the client only receives — `data_channel_handler.dart`'s unknown-type `default` branch silently drops, which is exactly why a new versioned `type` is safe in both directions).
- **Robustness contract:** device measurements are authoritative WHEN PRESENT; the server observer (escalation fix + id tagging applied) covers old app builds and channel failures. The `source` field in the payload makes the active path visible to tests, the smoke gate, and future debugging.
- **Edge cases owned by 2.1:** user interrupts the character (no gap to record); character re-speaks first (close `resolved: false` — the v1 invisible-freeze class); mic muted mid-gap (discard); app lifecycle/backgrounding (cancel/flush timers like the CallEnded patterns); one anchor at a time by construction.

### Practice-prompt content spec (B5/E1 — draft for the generator prompt)

Each area's `practice_prompt` is a self-contained block the user pastes into ANY LLM:
- Sets the assistant role: English conversation coach for an intermediate learner, voice-mode friendly (short turns, ask-then-wait).
- States the SINGLE focus: the area title + its evidence (the user's real utterances + corrections from this call, quoted).
- Instructs the flow: brief diagnosis recap → drill through 5-8 prompted exchanges targeting the pattern → end with a 3-line progress verdict. No praise inflation; correct on the spot.
- Explicitly forbids drifting to other topics ("one thing at a time" — Walid).
- Length target ≤ ~900 chars (clipboard-friendly, fits voice-mode context comfortably).

### Latest tech check

No new packages required: clipboard = `flutter/services` `Clipboard.setData` (SDK); bottom sheets = existing house pattern (content-warning/difficulty sheets); icons = bundled Material set. Server: no new deps (httpx + Groq json_schema as today). **D3-c is chosen → the livekit_client 2.6.4 speech-boundary/timing capabilities and pipecat's data-receive hook are NOT assumed — they are Task 2.0's research spike, with an explicit STOP-and-re-decide exit if unworkable.**

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

claude-opus-4-8[1m] (Claude Opus 4.8, 1M context)

### Debug Log References

#### Task 2.0 — RESEARCH SPIKE (2026-06-14): D3-c client-side hesitation measurement — VERDICT: GREEN (proceed), STOP-exit NOT triggered

Three unknowns proven in code (livekit_client 2.6.4 + installed pipecat + native Android layer). Read-only investigation, no edits.

**(a) Character-audio-END signal — AVAILABLE, device-local.**
- The Story 6.3b viseme stack already measures character playback silence ON the phone: native `android/app/src/main/kotlin/com/surviveTheTalk/client/AudioClockChannel.kt` hooks flutter_webrtc's `JavaAudioDeviceModule.PlaybackSamplesReadyCallback` (`onWebRtcAudioTrackSamplesReady`) → RMS classified by `FormantVisemeAnalyzer.kt` → viseme IDs on `EventChannel('com.surviveTheTalk.client/viseme_events')`.
- `client/lib/features/call/services/viseme_scheduler.dart` consumes it; `onSilenceConfirmed` fires after a REST viseme stays silent for 600 ms (`_kDefaultSilenceConfirmation`). Already wired in `call_screen.dart:~551` → `_publishPlaybackIdle` + `PlaybackDrained`.
- ANCHOR REFINEMENT (Task 2.1 owns): the 600 ms confirmation window is a known constant offset; anchor the gap-start on the REST-viseme-emitted instant (minus the ~50-200 ms hardware buffer) rather than the silence-CONFIRMED instant, so the start boundary is ~600 ms more accurate.

**(b) User-speech-ONSET signal — AVAILABLE device-local, but NOT via livekit speaking events.**
- livekit_client 2.6.4 DOES expose `SpeakingChangedEvent`/`ActiveSpeakersChangedEvent`/`Participant.isSpeaking`/`Participant.audioLevel` (events.dart:439/187, participant.dart:101) — but `core/room.dart:_onSignalSpeakersChangedEvent`/`_onEngineActiveSpeakersUpdateEvent` show these are driven by the SFU's SERVER-computed active-speaker update ("from data channel"), so the LOCAL participant's onset would round-trip mic→SFU→compute→downlink. REJECTED for D3-c (re-introduces the network terms D3-c removes; also coarse — only sent on speaker-ordering changes).
- CLEAN local signal: livekit_client's `createVisualizer(AudioTrack)` (`lib/src/track/audio_visualizer.dart:30`, native FFI via `Native.startVisualizer` → `EventChannel('io.livekit.audio.visualizer/...')`) attached to the LOCAL mic track yields a device-local audio-level stream (no server). Threshold-cross = onset. FALLBACK if its smoothing/latency is unacceptable: a native capture-samples analyzer mirroring AudioClockChannel (`JavaAudioDeviceModule.SamplesReadyCallback`/`onWebRtcAudioRecordSamplesReady`) — proven pattern, Android-only until 10-4.
- The visualizer's smoothing/latency and onset threshold are RUNTIME properties → finalize the constant + prove ±0.5s on the Pixel 9 smoke gate (Task 2.4 / gate item #2).

**(c) Uplink client→bot — AVAILABLE and ALREADY LIVE in prod.**
- pipecat `LiveKitTransport` receives client data: it registers `self.room.on("data_received")` → surfaces `on_data_received(data: bytes, participant_id: str)` (installed pipecat `transports/livekit/transport.py`).
- The bot ALREADY consumes it: `server/bot.py:~837` `@transport.event_handler("on_data_received")` JSON-decodes and dispatches; `playback_idle` → `patience_tracker.handle_playback_idle()` today. New `type:"hesitation"` is an additive `elif` (unknown types already ignored both directions — `data_channel_handler.dart` default branch silently drops).

**Conclusion:** D3-c is feasible. Onset MUST use a device-local mic-energy signal (livekit `createVisualizer` on the local track, native capture hook as fallback), NOT livekit `SpeakingChangedEvent`. End-anchor reuses the viseme PCM-silence machinery with the 600 ms offset compensated. Uplink reuses the proven `publishData`/`on_data_received` path. Final ±0.5s accuracy is a Pixel 9 smoke-gate proof (Walid's gate), not a code blocker.

#### Task 2.0 ADDENDUM — onset NOISE-ROBUSTNESS spike (2026-06-14, Walid-requested): VERDICT proceed_d3c, noise rejection by ALGORITHM + ARMING GATE (not signal cleanliness)

A 7-agent workflow (4 investigators / 2 adversarial verifiers / synth) settled the question Walid raised — "does mic onset reject background noise, or will it detect no blank at all?":

- **Signal:** a NATIVE record-side PCM tap on the LOCAL mic — clone `client/android/.../AudioClockChannel.kt`, reflect `recordSamplesReadyCallbackAdapter` (record) instead of the playback adapter (VERIFIED reachable: same private-field reflection path; `MethodCallHandlerImpl.java:280` wires it via `setSamplesReadyCallback`). Delivers PCM16 ~10 ms chunks — the exact shape `FormantVisemeAnalyzer.kt` already RMS-classifies. NOT livekit `createVisualizer` (it emits RAW FFT bands → trips on any sound), NOT livekit speaking events (server round-trip).
- **CRITICAL signal-position correction:** the tap is POST hardware-AEC/NS but **PRE** the libwebrtc SOFTWARE APM (AEC3/strong-NS/AGC) — "mostly-cleaned near-end", NOT AEC3-clean. So robustness CANNOT rest on signal cleanliness. There is no reachable post-software-APM record hook, and the RFC 6464 voice-activity bit is not exposed.
- **Noise rejection = the ALGORITHM (the structural defeat of Walid's failure mode):** adaptive noise-FLOOR **seeded from the known-silent gap window** (the viseme stack just told us the character went silent and the user hasn't spoken yet — a clean per-gap ambient estimate) then FROZEN while armed; trigger on **SNR margin (~8 dB ABOVE the floor), never absolute level** → a steady noisy room sits at ~0 dB over its own floor and can NEVER read as permanent speech (so the gap never collapses to ~0); + min-sustained-duration debounce (~200 ms, kills impulsive transients) + hangover. The fixed `FormantVisemeAnalyzer.kt:47 SILENCE_RMS=350` constant is EXACTLY Walid's trap and MUST NOT be reused.
- **Echo rejection = ARCHITECTURE (arming gate), not AEC:** the detector is DISARMED while the character speaks; ARMS only on `VisemeScheduler.onSilenceConfirmed` (`call_screen.dart:551`). Character TTS bleeding into the mic can't register as onset because nothing listens for onset during character speech. + an echo-tail/seed guard folds residual reverb into the seeded floor.
- **MANDATORY guards (from the adversarial pass, none optional):** max-gap timeout → emit a CENSORED sentinel (never 0, never ∞) for a missed quiet-speaker onset; floor ceiling (quiet-speaker protection, no AGC in this path); echo-tail guard; LOUD health-check on the reflection attach → self-report the feature UNAVAILABLE if a future flutter_webrtc rename breaks reflection (a silent failure here corrupts DATA, not just visuals).
- **Honest limits (deferred, not solved by energy+floor):** NON-stationary noise — TV dialogue / a second talker / vocal music — is speech-like and defeats energy+floor by construction → defer to the EXISTING server `EnvironmentMonitor`/`env_warning`/`NoisyEnvironmentBanner` path (down-weight onset on a parasitic-voice-flagged call) + a documented Silero/`vad`-package on-device upgrade if Pixel 9 tuning demands it. Voiced transients (cough/door-slam ~300-500 ms) can false-close the gap (under-measure). Every figure/param is an ESTIMATE — only a real noisy-room Pixel 9 smoke gate clears the product-gating claim.
- **Smoke-gate "money checks" (added to Task 6.3):** steady background (TV white-noise/fan) + deliberate ~4 s freeze → gap must NOT collapse to ~0; character-echo probe on loudspeaker → no false onset from TTS tail; TV-with-dialogue + cough/door-slam → watch for early false-close; quiet-speaker → onset still detected OR the censored sentinel fires; reflection-failure build → feature self-reports UNAVAILABLE.
- **Task 2.1 implementation outline (locked):** `AudioCaptureChannel.kt` (record-side clone, RMS reuse, health event on attach-fail) → onset state machine in Kotlin (adaptive-floor/SNR/debounce/hangover/seed-freeze, no fixed threshold) → arm off `onBotSpeakingEnded`/`onSilenceConfirmed` in `call_screen.dart` → gap = onset − onSilenceConfirmed → uplink via the existing `publishData` as `{type:"hesitation_onset", gap_ms, censored}` → server `HesitationObserver`/teardown consumes (D3-c device source preferred). Unit-test the state machine on canned PCM fixtures (silent/steady-noise/transient/quiet) + a fail-soft reflection health contract test; then the on-device smoke gate tunes params + decides the Silero upgrade.

#### Server-contract v2 design (derived from a full read of the v1 subsystem, 2026-06-14) — the locked blueprint for Tasks 3/2.3

Back-compat law (AC2): every v2 field is ADDITIVE + nullable/defaulted; NO field changes type. The v1 `areas_to_work_on: list[str]` STAYS (old clients + old rows read it); a NEW rich `areas` list rides alongside. Verified guards that move in lockstep: `test_debrief_generator.py:125` verbatim drift guard extracts the first fenced block after `## System Prompt` in `debrief-generation-prompt.md` and asserts `== "1.0"` → a v2 prompt must amend that doc block + bump `DEBRIEF_PROMPT_VERSION` to `"2.0"` + update the guard; `debrief-content-strategy.md` is the schema authority and gets the v2 Q-amendments.

- **`models/schemas.py` `DebriefOut` v2 (all additive/nullable):** `debrief_version: int = 1` (old rows → 1); `checkpoints: list[DebriefCheckpoint] = []` (`{id, hint, met}` — B7, from teardown NOT the LLM); `better_phrasings: list[DebriefBetterPhrasing] = []` cap 2 (`{original, suggestion, reason}` — B2); NEW `areas: list[DebriefArea] = []` (`{title, evidence, practice_prompt, is_focus}` — D-a/B5/D-c) kept SEPARATE from the retained `areas_to_work_on: list[str]`; `DebriefError` += `explanation: str | None = None` + `examples: list[str] = []` (B1); `DebriefHesitation` += `id: str | None = None`, `resolved: bool = True`, `source: str = "server"` (C2/C3/D3-c).
- **`debrief_generator._build_debrief_schema` v2 (STRICT, all-required + additionalProperties:false, NO min/maxItems):** errors items += explanation + examples[]; hesitation_contexts items += `hesitation_id` echo (id-based pairing, retires the by-index residual C3); NEW `better_phrasings[]`; NEW `areas[]` `{title, evidence, practice_prompt}` (the LLM authors evidence + the ≤900-char practice prompt per the Dev-Notes spec). `checkpoints` are NOT LLM-generated. New `_CORE_KEYS`.
- **`prompts.DEBRIEF_SYSTEM_PROMPT` v2:** EXTENDS (never relaxes) the clinical charter — per-error `explanation`/`examples` are factual ("the rule is X; e.g. …"); `better_phrasings` only when clearly more natural, hard cap 2; areas carry in-call `evidence` + a coach-role `practice_prompt` (single focus, user's real quoted utterances, ≤900 chars, forbids topic drift — Dev-Notes §Practice-prompt spec); no praise anywhere.
- **`debrief_assembly.assemble_debrief` v2:** add `debrief_version: 2`; thread `checkpoints` (from teardown); `_merge_hesitations` → id-based pairing + `source`/`resolved` passthrough; derive `areas_to_work_on` (titles) from `areas` for old-client back-compat; passthrough errors.explanation/examples + better_phrasings.
- **`debrief_teardown` / `bot.py`:** Task 3.2 threads checkpoint `{id, hint, met}` state from the bot's goals at teardown into `persist_debrief` → assembly (NOT through the LLM; do NOT break the single `BEGIN IMMEDIATE` atomic claim — 7.1 review P1). F2 = emit a distinct `completed` end-reason for survived-by-completion calls (today `DEFAULT_END_REASON="user_hangup"` mislabels them; framing tone keys on reason). F4 = re-size `_MAX_TOKENS` (~4× the bigger worst case) + re-measure wall-clock under the 10s ceiling, keep ONE call.
- **`debrief_generator._normalize_core` F3:** per-item validate-and-drop (one malformed item must not drop the whole debrief on the non-strict fallback path).
- **`routes_debriefs`:** unchanged mechanism — it already serves the stored dict validated against `DebriefOut`; the additive/nullable v2 fields keep old rows validating (AC2 regression guard). v1 rows lacking `debrief_version`/`areas`/`checkpoints` validate via the defaults above.
- **Task 2.3 server hesitation v2:** escalation blind-spot fix in `HesitationObserver` — close the pending gap at the character's NEXT `BotStartedSpeakingFrame` (re-speak) tagged `resolved: false` instead of letting the new `BotStoppedSpeakingFrame` overwrite the anchor; id-tag each gap; a bot-side collector for `type:"hesitation"` device envelopes (`bot.py` `on_data_received` += elif) that teardown PREFERS (`source:"device"`) over the observer (`source:"server"`).

### Completion Notes List

**Session 2026-06-14 (dev-story start — in-progress):**
- ✅ **Task 2.0 research spike** — RESOLVED GREEN (proceed with D3-c, STOP-exit not triggered). Full findings in Debug Log References above. Key result: client-side hesitation measurement is feasible, but user-speech ONSET must use a device-local mic-energy signal (livekit `createVisualizer` on the local mic track, native capture hook as fallback) — NOT livekit `SpeakingChangedEvent` (server-round-tripped). End-anchor = existing viseme PCM-silence machinery; uplink = the already-live `publishData`/`on_data_received` path.
- ✅ **Design direction LOCKED with Walid (2026-06-14)** — chose **Direction B "Rapport structuré / scorecard"** but with the explicit philosophy **"riche au clic, sobre au premier regard"** (rich on interaction, calm at first glance). Walid's binding requirements for the design-spec v2 (Task 1): heavy UX/UI + copywriting work incl. the displayed strings AND likely the server generation prompt; every insight must be ACTIONABLE — one tap to COPY a self-contained practice prompt pasteable into ANY LLM (voice OR text) to keep drilling that one topic, OR one tap to REVEAL more detail; must be pertinent — explain + show examples; "riche mais sobre au premier regard". → Task 1 design-spec v2 reconciles B's structure (gauge hero, checkpoint breakdown, per-area cards w/ copy + detail) with the Handler's Brief restraint via progressive disclosure (calm surface, depth in sheets).
- ✅ **v2 wire contract landed (Task 3.3 / 4.1 foundation, AC2)** — `models/schemas.py`: `DebriefOut` extended additive-only (`debrief_version:int=1`, `checkpoints[]`, `better_phrasings[]`, rich `areas[]`, all default-empty) + `DebriefError` += `explanation`/`examples`, `DebriefHesitation` += `id`/`resolved`/`source`, NEW `DebriefBetterPhrasing` / `DebriefCheckpoint` / `DebriefArea`. Every stored v1 row STILL validates (defaults). GATES GREEN: ruff check+format clean on the file, debrief suites pass (63: routes/assembly/teardown/generator/queries).
- ✅ **SERVER v2 COMPLETE (Tasks 3.1-3.5 + 2.3 server-half + F2/F3/F4), 5 commits, server suite 899 / client 532 green:**
  - **Content design** via a concept→judge→synth workflow (3 concepts, 3 judges): v2 `DEBRIEF_SYSTEM_PROMPT` (clinical charter EXTENDED — per-error rule+examples, ≤2 better-phrasings, evidence-linked prioritized areas, copy-to-LLM practice prompts), v2 strict json_schema (validated: zero strict violations, `hesitation_id` echo), wired byte-exact into `prompts.py` + `debrief_generator.py` + the 2 authority docs in lockstep with the drift guard; version 2.1; `_MAX_TOKENS` 3072; single call.
  - **`_normalize_core` v2** with per-item salvage (F3) + backend clamps (errors≤5, areas≤3 evidence-mandatory, better_phrasings≤2, examples≤2, practice_prompt 900-char). **`assemble_debrief` v2**: version, checkpoints, backend-pinned `is_focus`, `areas_to_work_on` derived from titles, id-based hesitation pairing (C3) with source/resolved.
  - **`HesitationObserver` v2**: escalation-blind-spot fix (C2, captured at re-speak `resolved:false`) + stable gap ids (C3) + a §1 real-pipeline drive test.
  - **B7 + F2**: `CheckpointManager.checkpoint_breakdown` threaded teardown→debrief; `resolve_end_reason` → `completed` for a user-ended fully-completed call.
  - **Client model v2** (`debrief.dart`): additive v2 parse, v1 back-compat, defensive item-skipping.
- ✅ **Mic-onset NOISE-ROBUSTNESS spike (Walid-requested)** — 7-agent workflow: proceed_d3c; noise rejection by adaptive-floor+SNR+arming-gate (native record-side PCM tap), NOT signal cleanliness; honest limits on non-stationary noise defer to `env_warning` + a Silero upgrade; full design in the Debug Log addendum.
- 📋 **Remaining (CLIENT phase, next push):** Task 1 design-spec v2 doc (Direction B "riche au clic sobre" — **Walid validates before the screen build**) · Task 5 client screen v2 (scorecard hero + checkpoint breakdown + error/area tap-sheets + per-area copy button + approximate durations) · Tasks 2.1/2.2 + 2.3-device (client `HesitationMeter`: `AudioCaptureChannel.kt` record-side native tap + onset state machine + `publishData` uplink + the bot `on_data_received` device-gap collector + teardown-prefers-device — one co-designed/tested D3-c unit per the spike outline) · Task 6 gates + VPS deploy (no migration — JSON-shape only; back up anyway) + Pixel 9 smoke gate (incl. the noisy-room money check).

### File List

**Server (Tasks 3 + 2.3 server-half + B7/F2):**
- `server/models/schemas.py` — v2 wire contract: `DebriefOut` additive v2 fields + `DebriefBetterPhrasing`/`DebriefCheckpoint`/`DebriefArea` + `DebriefError`/`DebriefHesitation` additive fields.
- `server/pipeline/prompts.py` — v2 `DEBRIEF_SYSTEM_PROMPT` + `DEBRIEF_PROMPT_VERSION = "2.1"`.
- `server/pipeline/debrief_generator.py` — v2 `_build_debrief_schema` (JSON constant) + `_MAX_TOKENS` 3072 + v2 `_CORE_KEYS` + per-item salvage clamps + `_format_hesitations` ids.
- `server/pipeline/debrief_assembly.py` — `assemble_debrief` v2 + id-based `_merge_hesitations` + `_pin_focus`.
- `server/pipeline/hesitation_observer.py` — escalation fix (C2) + gap ids/resolved (C3).
- `server/pipeline/checkpoint_manager.py` — `checkpoint_breakdown` property (B7).
- `server/pipeline/debrief_teardown.py` — `resolve_end_reason` (F2) + `checkpoints` threading.
- `server/pipeline/bot.py` — teardown uses `resolve_end_reason` + passes `checkpoint_breakdown`.
- `server/tests/{test_debrief_generator,test_debrief_assembly,test_debrief_teardown,test_hesitation_observer,test_checkpoint_manager}.py` — v2 + new coverage.
- `_bmad-output/planning-artifacts/{debrief-generation-prompt.md,debrief-content-strategy.md}` — v2 prompt block + JSON schema + examples + v2 content amendment.

**Client (Task 4):**
- `client/lib/features/debrief/models/debrief.dart` — v2 additive parse.
- `client/test/features/debrief/models/debrief_test.dart` — v2 + back-compat tests.

**Tracking:**
- `_bmad-output/implementation-artifacts/7-5-overhaul-debrief-report.md` — Status in-progress; task checkboxes; Dev Agent Record (spike findings + noise addendum + v2 blueprint + session notes).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `7-5-...`: ready-for-dev → in-progress.

### Review Findings — Server (Group 1: Python), code review 2026-06-15

3-layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor) of `git diff 74002f6..HEAD -- server/` (15 files, +1408/-315). Client + native (Group 2) are a SEPARATE review pass. 31 raw findings → **1 decision-needed, 6 patch, 2 defer, 10 dismissed**. Schema/contract fidelity verified high-quality (DebriefOut additive + v1 back-compat, strict json_schema, every cap backend-clamped). No crash/data-loss defect in the shipped path.

**Decision-needed:**

- [x] [Review][Decision] **RESOLVED 2026-06-15 (Walid) → accept the hybrid for 7.5; device-authoritative DEFERRED to a follow-up story (client onset fix → wire merge → smoke); doc-honesty patches applied. Original finding:** D3-c device-hesitation measurement shipped DORMANT — the real measurement is the server `HesitationObserver` re-anchored on the client `playback_idle` signal.** `merge_hesitation_sources` is NEVER called (`bot.py:944` passes `hesitation_observer.top_hesitations()`); `device_hesitation_collector.record()` runs live (`bot.py:887`) but its gaps are discarded (consumed only by the DIAG logs). The observer's gap-START is now set ONLY in `handle_playback_idle()` (`hesitation_observer.py:126`) — `BotStoppedSpeakingFrame` is no longer observed. This is a smoke-gate-validated pivot (commits `5498388` "anchor on playback_idle (no inflation)", `208185e` "threshold 3s→4s") because the device source over-stated gaps. BUT: (a) AC3 + Tasks 2.1-2.3 + the "D3-c architecture" note + Completion-Notes "teardown-prefers-device" still describe device-authoritative as DELIVERED — undeclared deviation; (b) `DeviceHesitationCollector` + `merge_hesitation_sources` are dead code shipped (kept only for diagnostics); (c) the "independent server fallback" now REQUIRES the client `playback_idle` envelope — an old client / data-channel failure → ZERO hesitations (graceful, but coupled, contra AC3's "independent fallback"); (d) stale module/arg docstrings still describe the BSF anchor + by-index merge; (e) the TEMP smoke-gate DIAG logs (`bot.py:883`, and the `onset_rms_alive` "TEMP DIAGNOSTIC" branch `bot.py:891-895`) fire `logger.info` every call. DECIDE: **(A)** accept the playback_idle hybrid as final → make the story honest (AC3/Tasks/notes), choose keep-as-diagnostic vs REMOVE the dormant device collector + merge + TEMP logs, refresh docstrings; **(B)** actually wire the device source at teardown (call `merge_hesitation_sources`); **(C)** other.

**Patch:**

- [x] [Review][Patch] Stale ">3s" in the hesitation capture log [server/pipeline/hesitation_observer.py:187] — threshold is 4.0s; interpolate `self._threshold` (misleads journalctl debugging).
- [x] [Review][Patch] Stale "3 s" docstrings + old-anchor/by-index prose [server/pipeline/hesitation_observer.py:1-13,55; server/pipeline/device_hesitation_collector.py:38; server/pipeline/debrief_generator.py:310-320; server/pipeline/debrief_assembly.py:7] — update to 4.0s + playback_idle anchor + by-id merge.
- [x] [Review][Patch] `count` accepts bool + has no upper bound [server/pipeline/debrief_generator.py:406-407] — `isinstance(True,int)` is True so a bool leaks through as `count`; add `and not isinstance(count, bool)` (+ a sane cap) for consistency with the device collector's bool guard. Theoretical (strict schema enforces integer on the happy path).
- [x] [Review][Patch] `gap_ms` finiteness guard at the live client-input boundary [server/pipeline/device_hesitation_collector.py:62-65] — an `inf` gap_ms passes the numeric check and is NOT dropped by `<= threshold`; add `math.isfinite`. (record() processes live envelopes even while the path is dormant.)
- [x] [Review][Patch] Stale `_MAX_TOKENS` rationale comment [server/pipeline/debrief_generator.py:52-57] — "~4× the ~525-token worst case" no longer matches v2's much larger output; update the comment (see the deferred budget-measurement item).
- [x] [Review][Patch] Doc/version drift vs shipped code [planning-artifacts/debrief-content-strategy.md Q6 (">3s"); planning-artifacts/debrief-generation-prompt.md (mixed 3s/4s + "version 1.0" footer); `DEBRIEF_PROMPT_VERSION="2.1"` vs the File List / Completion-Notes / both authority docs saying "2.0"; story AC3 + Task 2.4 (">3s" / "3.0 s stands")] — align all to the shipped 4.0s + version 2.1.
- [x] [Review][Patch] Gate the DIAG/TEMP hesitation diagnostics behind `HESITATION_DIAG=1` (clean prod; re-armable for the device follow-up's smoke) [server/pipeline/bot.py]
- [x] [Review][Patch] Story honesty — AC3 / Tasks 2.3-2.4 / D3-c note / File List corrected to the shipped reality (hybrid live, device dormant → follow-up, 4 s, version 2.1) [story 7.5]

**Deferred:**

- [x] [Review][Defer] `_MAX_TOKENS=3072` headroom vs v2 worst-case [server/pipeline/debrief_generator.py:58] — 5 errors (explanation + 2 examples) + 3 areas (900-char practice prompts ≈ 675 tok) + better_phrasings + idioms could approach/exceed 3072 → finish_reason=length → no debrief (graceful). Measure real-call generation tokens + truncation rate on the VPS per AC9 (<5s / 10s ceiling) and raise if needed. — deferred, needs live-call data (AC9 smoke item).
- [x] [Review][Defer] AC10 deferred-work retirement entries not recorded [deferred-work.md] — AC10 requires marking F2/F3 + the 7.1 hesitation/index residuals retired; no entry exists. — deferred, bookkeeping.
- [x] [Review][Defer] **Device-authoritative hesitation = follow-up story** — fix the client onset detector (under-production / seed-window contamination) in `hesitation_meter.dart` + `AudioCaptureChannel.kt`, THEN wire `merge_hesitation_sources` at teardown, THEN smoke. The server merge code is already in place (dormant) as the foundation. — deferred, Walid-ratified 2026-06-15 (client-first).

**Dismissed (not written as tasks — verified false-positive / by-design / not reachable):**
- `inappropriate_behavior` not re-pinned (Blind Hunter) — FALSE: `_enforce_inappropriate_behavior` exists + is called (`debrief_generator.py:543-551`, `759`).
- `cp["id"]`/hint KeyError in `checkpoint_breakdown` — not reachable: `id` guaranteed by the constructor (`checkpoint_manager.py:518`) + loader; `hint_text` loader-validated; `hint` field name intentionally matches the schema.
- `resolve_end_reason` "completed" conflation — by-design (F2 intent; `tracker_reason` wins otherwise; `met >= total` is a safe clamp).
- `area["title"]` subscript + "always ≥1 area" floor — `title` guaranteed by `_clamp_areas`; empty areas → client hides the section.
- per-string char caps unenforced — by-design: only the clipboard `practice_prompt` needs a hard cap; other fields are model-instructed soft caps + client-rendered with overflow handling.
- hesitation_id collision last-write-wins — benign: backend gap ids are unique, so a duplicate echoed context only swaps between two same-moment contexts.
- examples casefold-exact dedup — matches the literal "never a verbatim copy" rule; fuzzy matching risks false drops.
- `float()`/NaN/inf on `duration_sec` (assembly + prompt build) — not reachable: `duration_sec` is always backend-computed finite float (observer + guarded device record()).
- `gap['source']` non-string — `str(gap.get("source") or "server")` already coerces; `source` is backend-set, never external.
- `merge_hesitation_sources` returns `server` by reference — latent aliasing in dormant code; folded into the decision item (add `list(server)` if kept).

**Server review status (2026-06-15):** COMPLETE — decision resolved, all 8 patches applied, gates green (ruff check + format clean, server `pytest` **905 passed**). Story STAYS `review`. Owed before `review → done`: **(1)** the CLIENT (Group 2: Dart/Kotlin) code-review pass — ✅ DONE 2026-06-15 (4 patches applied + gates green flutter analyze + test 546; see "Review Findings — Client" below), **(2)** the Pixel 9 smoke gate — still owed. Per the root-CLAUDE.md flip discipline, the reviewer flips `review → done` only when BOTH the full code review (server + client) and the smoke gate clear.

### Review Findings — Client (Group 2: Dart/Flutter + Kotlin), code review 2026-06-15

3-layer adversarial review of `git diff 74002f6..HEAD -- client/` (11 files, +2262/-354). 34 raw findings → **4 patch, 1 deferred bundle, 7 dismissed**. AC2/AC5/AC6/AC7-v2/AC8 verified SATISFIED (additive v1 back-compat parse, copy→clipboard with no network, tap-detail sheets, no praise/CTA strings, design tokens + theme-count test). The debrief v2 SCREEN is high-quality; the findings split cleanly into a few active-screen fixes and the dormant device-meter issues, which belong to the deferred device follow-up story.

**Patch (active debrief screen + clean prod):**

- [ ] [Review][Patch] Inline area copy row below the 44px touch-target law [client/lib/features/debrief/views/debrief_screen.dart `_CopyInlineRow` ~1341-1372] — `Padding(vertical: 8)` + a 16px icon ≈ 32px; wrap to `AppSpacing.minTouchTarget` (design-spec §4b/§7). (Auditor A1)
- [ ] [Review][Patch] "Copied" toast shown even on a failed clipboard write + unhandled async rejection [debrief_screen.dart `_CopyInlineRow._onTap` ~1348, `_CopyPromptCta._onTap` ~1401] — `unawaited(Clipboard.setData(...))` then toast, no error path; add `.catchError` (toast only on success). (Blind + Edge)
- [ ] [Review][Patch] Gate the TEMP `_publishOnsetDiag` (`onset_rms_alive`, reliable channel every ~1.5s) behind a const debug flag — clean prod, mirrors the server P7; the device follow-up re-arms it [client/lib/features/call/views/call_screen.dart ~512, ~538]. (Blind + Auditor)
- [ ] [Review][Patch] Re-add the deleted BS-7 "fetched payload fails parse → unavailable" widget test [client/test/features/debrief/views/debrief_screen_test.dart] — the host machinery is unchanged, so the coverage should stay. (Blind)

**Deferred — to the device-authoritative follow-up story (it reworks the dormant meter + native tap):**

- [x] [Review][Defer] **Dormant device-meter correctness / perf / test bundle** — folded into the device follow-up: gap math inflated by the confirmation offset + no negative clamp (`hesitation_meter.dart`); **no-retry callback attach → the meter can be DEAD for the whole call, silently (`AudioCaptureChannel.kt` `tryAttachCallback`) — the LIKELY "under-production" root cause**; Kotlin RMS ignores `channelCount`; native 100Hz main-thread `post` flood + post-cancel race; `seedFloor` / `arm-idempotent` tests assert by timing-luck not logic; `disarm()` doesn't reset accumulators; silent non-`num` channel drop with no log; `_kRestVisemeId=0` magic-constant coupling to the viseme scheme; + the decision whether to gate the WHOLE client machinery off in prod vs leave it running as the follow-up's foundation. — deferred, Walid-ratified 2026-06-15 (the follow-up reworks this code).

**Dismissed (verified not-reachable / by-design):**
- Gauge >100% / negative text-vs-fill disagreement — server `compute_survival_pct` clamps 0-100, not reachable.
- "~0s" hesitation rounding — server only ships gaps >4 s, not reachable.
- Empty `practice_prompt` → dead area card — server `_clamp_areas` requires `practice_prompt`, not reachable.
- Checkpoint "0 of N" / triple-traversal — `isNotEmpty`-gated, renders correctly; refactor nit.
- Gauge const naming (`_kGaugeSize` vs spec `_kGaugeDiameter`) — cosmetic, same value.
- `publishData` after dispose — already inside try/catch, benign.
- Design-spec body not reconciled with Walid's error-copy / area-card overrides — code is correct; the overrides are recorded at the design-doc top.
