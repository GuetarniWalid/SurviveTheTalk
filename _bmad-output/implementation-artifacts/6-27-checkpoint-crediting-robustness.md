# Story 6.27: Checkpoint crediting robustness — superset-overlap back-fill + judge resilience

Status: ready-for-dev

> **Surfaced by the Story 7.1 Pixel-9 smoke gate (2026-06-09, call_id=266, scenario `waiter_easy_01`).** Walid completed 5 of 6 checkpoints, but the FIRST checkpoint (`greet`) never credited and the character never "came back" to it — he hung up himself at 5/6. He suspected a regression of Story 6.21 (the character returns to the lowest unmet beat). A 7-agent diagnostic workflow (log-evidence + code-audit + git-history bisect + 3 adversarial verifiers, all run against the prod call-266 journal + current `main`) returned a **HIGH-confidence verdict: NOT a regression** of 6.21 / 6.10 / 6.23 — the engine code is intact. The real cause is a latent **scenario-design fragility** (a superset criteria overlap), amplified by two LLM-behavioural misfires and a difficulty aggravator. This story is the "état des lieux" + the durable fix.

> **⛔ This is NOT a regression-fix story. Do NOT touch the Story 6.21 steer-back or the `judgeable_goals` gating — both were verified correct in current `main` (file:line below).**

---

## Why "two mechanisms both failed" is still NOT a regression (read this first)

The intuition — *"TWO safety mechanisms both failed, so something must have regressed"* — is reasonable, but it treats both mechanisms as deterministic code. They are not; **both are LLM-dependent**:

- **Mechanism 1 — the checkpoint judge** is an **LLM verdict** (Groq Scout, `classify_multi`). The *code* that feeds `greet` to the judge every turn worked perfectly — greet was in the judge payload on every pending turn (verified). The judge *model* simply returned the wrong/ambiguous answer for `greet` on a sentence that should arguably pass it. An LLM judge giving an imperfect verdict is not a code regression — Scout benches ~92%, never 100%.
- **Mechanism 2 — "return to the lowest unmet beat" (Story 6.21)** is a **steering PROMPT**, not a hard control. The *code* that composes the steering correctly pinned the character on `greet` (verified: the boot `system_instruction` literally targeted greet's `prompt_segment`). But the steering can only *ask* the character LLM to pursue greet — it cannot *force* it. The character *model* ignored the pull and kept advancing.

So **both mechanisms did their coded job; the two LLMs behind them made imperfect calls.** A regression = code that used to work and now does not. Here the code is unchanged and correct — `greet`'s success_criteria is **byte-identical in git from before Story 6.21 to HEAD**. Nothing changed; this failure path was always possible. The 7.1 smoke gate is simply the first time it was *seen*, because Epic 7 finally surfaces the checkpoint outcome in a debrief.

**The deeper structural cause that made BOTH LLMs fail on the SAME beat:** `greet`'s criteria is a strict logical **SUPERSET** of `main_course`'s (below). That overlap sets the trap; the two LLM misfires just walked into it. The durable fix is therefore **structural and deterministic** — exactly the Story 6.23 philosophy ("the guarantee is structural and upstream of the LLM"), applied to the inverse problem: 6.23 stops a beat from crediting *too early*; 6.27 stops an earlier beat from being *stranded* when a logically-narrower later beat credits.

---

## État des lieux — exactly what happened on call_id=266 (`waiter_easy_01`)

STT was clean on every turn (no garbling). Turn-by-turn, reconstructed from the prod journal (process `python[1144623]`):

| Turn | User said (clean STT) | Judge result | Cumulative met set |
|---|---|---|---|
| 1 | "Hi, good evening. Could I see the menu, please?" *(satisfies `greet`: "asks for the menu")* | ⚠️ classifier **ReadTimeout** → inconclusive, **nothing judged** | `[]` |
| 2 | "Hmm, I have the grilled chicken, please." | credits `main_course`(1) + `clarify`(2) **but NOT `greet`(0)** | `[1,2]` |
| 3 | "Grilled." | no flip | `[1,2]` |
| 4 | "Water." | credits `drink`(3) | `[1,2,3]` |
| 5 | "No, it's right." | credits `confirm`(4) | `[1,2,3,4]` |
| 6 | "Okay." | credits `close`(5) | `[1,2,3,4,5]` |
| 7 | "Thank you." | no flip (only `greet`(0) remains) | `[1,2,3,4,5]` |

Final: **5/6, `greet` (index 0) permanently unmet.** Walid hung up. The **same turn-1 ReadTimeout on the identical opening line also occurred on the prior attempt call_id=265** → reproducible, not a one-off.

---

## Root cause — three compounding factors + one aggravator (none is an engine regression)

1. **🟠 PRIMARY — the superset criteria overlap (scenario design; predates 6.21).**
   `greet` criteria = *"...states they want to order, asks for the menu, ... **or names a food item**."* `main_course` criteria = *"**names a specific dish**."* So *naming a dish satisfies BOTH* — `greet` ⊇ `main_course`. On "grilled chicken," the judge (applying the MULTI prompt's "must satisfy the SPECIFIC objective" + "default to UNMET in doubt") credited the **narrower** beat (`main_course`) and declined the **broader** one (`greet`) on the same text. Reproduced **2/2** (calls 265 + 266) → **deterministic**, not flaky. This clause is **byte-identical in git** from before Story 6.21 to HEAD (`git show 0a55283^ == 0a55283 == HEAD`) → a latent design fragility, not introduced by any story. Once a later beat is credited, `greet` can only recover if the user re-volunteers ordering intent while the already-moved-on character circles back — practically unwinnable.

2. **🟢 First-turn judge timeout.** The one turn that cleanest-satisfied `greet` ("Could I see the menu") hit an exchange-classifier ReadTimeout → patience-neutral, nothing judged. Same timeout on the same opening line in call 265 → a **cold-classifier slow-first-call** pattern. Mechanically: the classifier's own `httpx.AsyncClient` is created **lazily on the first classify** ([exchange_classifier.py:247-272](../../server/pipeline/exchange_classifier.py)) with `_HTTP_TIMEOUT_SECONDS = 1.5` — a cold TLS handshake + Groq first-hit can exceed 1.5 s. The Story 6.24 `llm_warmup` does NOT help here: it warms Groq through its **own throwaway client**, not the classifier instance's client. (Even without the timeout, factor 1 would likely still strand greet — but this guaranteed greet got no verdict on its single strongest turn.)

3. **🟢 Character-LLM non-compliance.** The 6.21 steer-back fired (the boot prompt pinned the character on greet), but Scout ignored it and advanced ("Grilled or fried?", "And to drink?"); the generated hang-up line pursued sides, not a greeting. Steering "back to greet" is also semantically incoherent once the user has ordered everything — greet's `prompt_segment` is "reel off the menu so they can pick," which Tina already did on turn 1.

4. **🔧 AGGRAVATOR (config, working-as-designed) — hard difficulty on an easy scenario.** The call ran the **HARD** patience preset (initial 60 / fail −25 / recovery 0) because Walid picked **hard** globally — Story 6.19 *intentionally* lets a global pick override an easy-authored scenario. That is the difficulty selector working, **NOT a bug** — but on a "tutorial" easy scenario it left no runway (two −25 fails drove patience 60→35→10), converting a recoverable miss into a forced 5/6 hang-up.

---

## What is verified INTACT (do NOT touch)

- **Story 6.10 any-order judging** — `judgeable_goals` keeps every ungated pending beat (incl. `greet`, index 0, no `requires`) in the judge payload every turn (`checkpoint_manager.py:264-303`; payload build `:1033,1057-1060`). `greet` WAS judged each turn, not dropped.
- **Story 6.21 return-to-lowest-unmet** — steering composes from `pending_goals` (author order) and targets `pending_goals[0]` = the lowest unmet beat (`checkpoint_manager.py:255`, `:566-570`; recompose on every success turn `:1204/1329`; boot `bot.py:172`). Confirmed firing in the call-266 journal (boot prompt targeted greet).
- **Story 6.23 reactive gating** — irrelevant here (greet is index 0, cannot have a `requires`).
- The git-history "regression" nomination (echo-guard commit `04078d6`) was **FALSIFIED** by reading the journal: **zero** `checkpoint_echo_skip_while_bot_speaking` lines in call 266.

---

## Story

As a **learner playing a scenario**,
I want **every checkpoint I have logically satisfied to be credited — even when one sentence satisfies two overlapping beats, and even on the very first turn of the call**,
so that **I never end a clean run stranded at N−1/N with the HUD telling me I failed a step I actually did**.

As the **solo maintainer**, I also want **per-goal judge verdicts in the logs**, so the next crediting anomaly is diagnosable from the journal instead of needing a 7-agent forensic workflow.

---

## Design Decisions — ✅ ALL RESOLVED (Walid, 2026-06-10)

### Decision 1 — the crediting fix (primary)

Stop a superset-earlier beat from being stranded when a subset-later beat is credited:

- **Option A (RECOMMENDED) — deterministic back-fill via an `implies` edge in `advance_goals`.** A later beat declares `implies: <earlier_checkpoint_id>` in the YAML (the exact mirror of 6.23's `requires` — same field shape, same loader validation, same builder wiring). When that beat flips to met and the implied earlier beat is still pending, the engine auto-credits the earlier one **in code, same turn, no LLM** — transitively (A←B←C chains resolve in one pass; edges point strictly earlier so it terminates). Robust, general, kills the whole class; `golden==prod` by construction because the rule lives in the shared pure `advance_goals`. For the waiter: `main_course` gets `implies: greet`.
- **Option B — re-author `greet`'s criteria** so a bare dish name does NOT satisfy it (greet = pure intent-to-order / menu-request, EXCLUDING a dish name). Narrow (waiter-only); the superset class can recur in any builder-generated scenario; and it makes the no-greeting opener ("I'll have the chicken") UNWINNABLE for beat 0 instead of auto-credited — strictly worse UX than A.
- **Option C — builder-time superset guard** so future generated scenarios are born clean: instruct the checkpoint-draft + critique LLM passes that no earlier beat's `success_criteria` may be a logical superset of a later beat's, and that when a broader-earlier/narrower-later pair is intentional, the later beat must carry `implies: <earlier_id>`. Prevention, not cure — **pairs with A** (a pure-code superset detector is not feasible; supersetness is semantic, so the guard lives in the builder's existing LLM critique pass + the human review step, exactly like the 6.23 `requires` authoring rule).

**✅ RESOLVED → A + C** (Walid, 2026-06-10): A = the engine cure, C = the authoring prevention. B rejected — not needed once A ships. Reflected in AC1-AC3 + T1-T5.

### Decision 2 — judge resilience (secondary)

The first `classify_multi` of a call timed out on both attempts on the same opening text (cold per-instance httpx client + 1.5 s budget). Scope options (cumulative):

- **(a) Classifier warm-up at call start** — new `ExchangeClassifier.warm_up()` that fires ONE throwaway `max_tokens=1` completion **through the instance's own `_get_client()`** (warming ITS connection — the llm_warmup client doesn't help), fire-and-forget from `bot.py` right after construction, mirroring the `llm_warmup` contract (never blocks, never raises, time-boxed).
- **(b) One-shot retry on the FIRST classify failure of the instance** — if the first-ever `classify_multi` returns `None` (infra failure), retry once before giving up. Belt-and-suspenders for (a); bounded: only the first call, only one retry (worst case ~+2 s on a fire-and-forget path that doesn't block the character's reply).
- **(c) Per-goal verdict logging** — one INFO line per successful classify with the full verdict map (`checkpoint_verdicts {goal_id: met|unmet|unsure, ...}`), emitted inside `ExchangeClassifier` so BOTH prod and the calibration harness get it. This is what would have made call-266 diagnosable from the journal (the 2026-06-09 evidence-gap verifier flagged exactly this hole).

**✅ RESOLVED → all three (a + b + c)** (Walid, 2026-06-10) — each is small, they close different halves of the same hole. Reflected in AC4-AC5 + T6-T7.

### Decision 3 — difficulty-on-tutorial UX (design conversation, NOT a bug)

Should a global "hard" pick apply to easy/tutorial scenarios, or should tutorials clamp to a gentler floor? Pure UX/product call — Story 6.19 works as designed.

- **(a) Keep as-is (RECOMMENDED for now)** — global pick always wins; with D1+D2 fixed, call 266 would have ended 6/6 even on hard. Zero code; revisit after real-user data.
- **(b) Clamp easy-authored scenarios** to at most medium when the global pick is hard (small `scenarios.py` change).
- **(c) Defer to the future per-scenario difficulty-selector story** (already in memory as a planned feature) and record nothing now.

**✅ RESOLVED → (a) keep as-is for THIS story (zero D3 code in 6.27)** (Walid, 2026-06-10) — **plus a bigger product ruling that supersedes option (c):** the notion of per-scenario difficulty must DISAPPEAR entirely. There are no "easy/medium/hard scenarios" anymore — the ONLY difficulty cursor is the user's GLOBAL setting; scenarios exist purely to vary the experience. The per-scenario `difficulty` field is legacy from the original design and now causes confusion (this very story's aggravator #4 was framed as "hard-on-easy", a frame that should not exist). The cleanup is a **separate story** (`6-28-remove-per-scenario-difficulty`, added to the backlog) — known touchpoints: YAML `metadata.difficulty`, the DB `scenarios.difficulty` column + CHECK + API/client exposure, the legacy `*_easy_01`-style scenario ids, and the calibration bands that derive from `difficulty` (difficulty-calibration.md §4.3 — must re-anchor on the global setting). **Implication for the 6.27 dev: do not introduce any NEW coupling to `metadata.difficulty`.** The future "per-scenario difficulty selector" idea in memory is retired by this ruling.

---

## Acceptance Criteria (locked to the resolved decisions: D1=A+C, D2=a+b+c, D3=keep-as-is)

1. **AC1 — deterministic back-fill.** Given a scenario where a later beat declares `implies: <earlier_id>`, when the later beat flips to met and the earlier one is still pending, then the earlier beat is credited the SAME turn, in code (no LLM verdict needed for it), transitively for chains, with a `checkpoint_advanced` envelope emitted for the back-filled beat too (HUD ticks both). A **call-266 replay regression test** drives the exact verdict sequence from the table above through the engine with `main_course → implies: greet` and asserts the final state is **6/6**.
2. **AC2 — golden==prod.** The back-fill rule lives in the pure `advance_goals` shared with the Story 6.15 harness (no re-implementation); `compute_scenario_hash` includes `implies`; `ENGINE_VERSION` bumps 3 → 4; a pure (non-LLM) `implies` assertion runs in the golden net alongside `requires_gating_failures`. The waiter scenario carries the live `implies: greet` edge and `calibrate_scenario.py waiter_easy_01` passes post-change.
3. **AC3 — loader + builder wiring (mirror of 6.23).** `load_scenario_checkpoints` fail-fasts on an `implies` that is non-string/empty, names an unknown id, names a non-EARLIER beat, or targets a beat that itself carries `requires` (a reactive trap-response must never be auto-credited). The builder preserves the field through `sanitize_checkpoints`, validates it in `validate_structure` with the same rules, and `CHECKPOINTS_PROMPT`/`CRITIQUE_PROMPT` teach the draft LLM the superset rule (D1-C).
4. **AC4 — first-turn judge resilience.** A first-classify infra failure no longer silently strands the opening turn: `ExchangeClassifier.warm_up()` is fired at call start (fire-and-forget, never raises), and the first-ever `classify_multi` of an instance retries once on infra failure. Proven by a test that injects a single first-call `httpx.ReadTimeout` and asserts the verdicts still land.
5. **AC5 — per-goal verdict logging.** Every successful `classify_multi` logs ONE INFO line with the full per-goal verdict map; the call-266 situation (greet=unmet/unsure while main_course=met on the same turn) would now be readable directly from `journalctl`. Asserted via a loguru temp-sink test (server/CLAUDE.md §3 — `caplog` does not capture loguru).
6. **AC6 — D3 decision recorded.** ✅ Satisfied at spec time — D3 resolved "keep as-is" (zero D3 code in this story), and the wider global-only difficulty ruling is recorded in the Decisions section + spun off to backlog story `6-28-remove-per-scenario-difficulty`. Dev constraint that remains active: introduce no NEW coupling to `metadata.difficulty`.
7. **AC7 — zero client change.** No Flutter code: the envelope shape is unchanged (`goals_met_indices` already carries the full met set; the HUD already animates multi-tick turns). `flutter analyze` + `flutter test` stay green (pre-commit law), server suite grows by the new tests with everything green.

---

## Tasks / Subtasks

- [ ] **T1 — `implies` back-fill in the pure engine (AC1, AC2)** — `server/pipeline/checkpoint_manager.py`
  - [ ] Extend `advance_goals(goals_state, verdicts)` ([checkpoint_manager.py:332-369](../../server/pipeline/checkpoint_manager.py)) with a **keyword-only, required** `checkpoints: list[dict]` param (same list `judgeable_goals` takes — forcing both call sites to thread it consciously; golden==prod by construction). Build `implies_map = {cp["id"]: cp.get("implies") for cp in checkpoints}` and, after the direct verdict flips (line ~354), run the back-fill to fixpoint: for each newly-met id, if its `implies` target is still `"pending"`, flip it, append to `flipped_ids` (AFTER the direct flips, in discovery order), and re-queue it (transitive chains). `met_count`/`all_met`/`outcome` are computed after back-fill — no other changes (`outcome` is `"success"` iff `flipped_ids` non-empty, unchanged semantics).
  - [ ] Update the GoalAdvance docstring (`:306-329`) + `advance_goals` docstring to document the back-fill rule.
  - [ ] Update the prod call site `advance = advance_goals(self._goals, verdicts)` ([checkpoint_manager.py:~1137](../../server/pipeline/checkpoint_manager.py)) to pass `checkpoints=self._checkpoints`. The existing per-flip envelope loop (`:1211-1212` → `_emit_checkpoint_advanced`) and `_goals_met_indices()` need **zero changes** — back-filled ids ride `flipped_ids`, so the HUD envelope + the 7.1 debrief counts (read from this same state at teardown) pick the back-fill up automatically.
  - [ ] Update the harness call site in `scripts/calibration_engine.py::run_calibration` to pass `checkpoints=` too (it already holds `data.checkpoints`).
- [ ] **T2 — loader validation, mirror of `requires` (AC3)** — `server/pipeline/scenarios.py`
  - [ ] In `load_scenario_checkpoints` after the `requires` block ([scenarios.py:749-778](../../server/pipeline/scenarios.py)), add the `implies` validator with the SAME fail-fast `RuntimeError` posture: (1) non-string/empty → raise; (2) unknown id → raise; (3) `id_to_index[implied] >= idx` → raise (**must point STRICTLY EARLIER** — note: same direction as `requires`, the field sits on the LATER beat); (4) NEW: target beat carries `requires` → raise (auto-crediting an unsprung reactive trap is always wrong).
  - [ ] Keep the field a single string (like `requires`); list-form is a future extension, do not build it.
- [ ] **T3 — waiter data fix (AC1, AC2)** — `server/pipeline/scenarios/the-waiter.yaml`
  - [ ] Add `implies: greet` to the `main_course` checkpoint. Do NOT reword `greet`'s criteria (Option B rejected — the broad criteria + back-fill together make the no-greeting opener auto-credit, which is the desired UX).
  - [ ] Audit the other 5 scenario YAMLs (`the-cop`, `the-mugger`, `the-girlfriend`, `the-landlord`, `cop-interrogation-01`) for the same earlier-⊇-later overlap pattern; add `implies` edges only where a genuine superset exists (the cop's reactive beats are `requires`-gated — different mechanism, mostly immune). Record the audit verdict per scenario in the Dev Agent Record.
  - [ ] No DB migration: checkpoints are seeded as a JSON blob into the `scenarios.checkpoints` TEXT column (`db/seed_scenarios.py:86` `json.dumps(checkpoints, ...)` carries any new key); the runtime loads checkpoints from YAML, not the DB. Reseed happens automatically at service restart.
- [ ] **T4 — golden==prod plumbing (AC2)** — `server/scripts/calibration_engine.py`
  - [ ] Add `"implies": cp.get("implies")` to the `compute_scenario_hash` checkpoint projection ([calibration_engine.py:1313-1334](../../server/scripts/calibration_engine.py)).
  - [ ] Bump `ENGINE_VERSION = 3` → `4` ([calibration_engine.py:116](../../server/scripts/calibration_engine.py)) — the rule change must force ledger revalidation.
  - [ ] Add a pure non-LLM assertion (sibling of `requires_gating_failures`, [calibration_engine.py:736-777](../../server/scripts/calibration_engine.py), called from `run_golden` at `:962`): for every beat with `implies`, simulate the later beat flipping via `advance_goals` and assert the implied beat lands met (exercises the REAL shared function, not a re-implementation).
- [ ] **T5 — builder wiring (AC3, D1-C)** — `server/scripts/scenario_builder.py`
  - [ ] `sanitize_checkpoints` ([scenario_builder.py:364-410](../../server/scripts/scenario_builder.py)): preserve `implies` exactly like `requires` (slugify the value; malformed-shape sentinel pattern already exists for `requires` — mirror it).
  - [ ] `validate_structure` ([scenario_builder.py:690-800](../../server/scripts/scenario_builder.py)): duplicate the loader's 4 `implies` rules (same messages, `problems.append` posture, after the `requires` block at `:729-752`).
  - [ ] `CHECKPOINTS_PROMPT` ([scenario_builder.py:212-275](../../server/scripts/scenario_builder.py)) + `CRITIQUE_PROMPT`: add the superset rule — *"no earlier beat's success_criteria may be a logical superset of a later beat's; if a broader-earlier beat is intentional, the NARROWER LATER beat must declare `implies: <earlier_id>` so the engine back-fills it"*. Keep both prompts difficulty-neutral (server/CLAUDE.md §8).
- [ ] **T6 — classifier warm-up + first-call retry (AC4)** — `server/pipeline/exchange_classifier.py` + `server/pipeline/bot.py`
  - [ ] New `async def warm_up(self) -> None` on `ExchangeClassifier`: ONE `max_tokens=1` chat completion POST to `self._base_url` with `self._model`, **through `await self._get_client()`** (the whole point — warm THIS instance's connection; [exchange_classifier.py:247-272](../../server/pipeline/exchange_classifier.py)). Contract mirrors `warm_up_llm` ([llm_warmup.py:36-68](../../server/pipeline/llm_warmup.py)): time-boxed, INFO on success, DEBUG on failure, **never raises**. No new env flag (the LLM warm-up is unconditional too — [bot.py:322-331](../../server/pipeline/bot.py)).
  - [ ] Fire it from `bot.py` right after the classifier is constructed (`:606-610`), `asyncio.create_task` + `_BACKGROUND_TASKS` strong-ref + done-callback discard (the exact 6.24/6.26 task-ref pattern).
  - [ ] First-call retry in `classify_multi` ([exchange_classifier.py:339-389](../../server/pipeline/exchange_classifier.py)): track `self._completed_one_classify`; if the FIRST-ever call returns `None` (timeout/HTTP error/parse), log `exchange classifier first-call retry` and re-run the whole guarded attempt ONCE. Never retry after the first call has succeeded once; never retry twice.
- [ ] **T7 — per-goal verdict logging (AC5)** — `server/pipeline/exchange_classifier.py`
  - [ ] After a successful multi parse, log ONE INFO line: `checkpoint_verdicts model=<model> {goal_id: met|unmet|unsure, ...}` (render from the raw enum values BEFORE the bool mapping so the journal shows `unsure` vs `unmet` distinctly — the exact distinction call-266 forensics could not recover). Lives in the classifier so prod AND the calibration harness both emit it.
- [ ] **T8 — tests** (server suite currently ~801; expect ≈ +15)
  - [ ] `tests/test_checkpoint_manager.py`: back-fill direct / transitive chain / target-already-met no-op / no-implies byte-identical behaviour / back-filled ids appended to `flipped_ids` after direct flips / `all_met` reachable via back-fill / **call-266 replay → 6/6** (drive the table's verdict sequence through `advance_goals` with the waiter checkpoints + edge).
  - [ ] `tests/test_scenarios.py`: 4 `implies` validator tests mirroring the `requires` patterns ([test_scenarios.py:1005-1106](../../server/tests/test_scenarios.py) — `_requires_yaml` helper style) + an end-to-end `test_waiter_implies_edge_loads` asserting `main_course`'s `implies == "greet"`.
  - [ ] `tests/test_exchange_classifier.py`: `warm_up` posts once + never raises (use the `_mock_http` MockTransport pattern, `:32-45`); first-call `httpx.ReadTimeout` → retry → verdicts land (handler raises on call 1, succeeds on call 2); no retry on second-call failure; no double retry. Loguru temp-sink assertion for `checkpoint_verdicts` (server/CLAUDE.md §3).
  - [ ] `tests/test_calibration_engine.py`: hash includes `implies`; the new pure golden assertion flags a hypothetical broken back-fill; ENGINE_VERSION == 4.
  - [ ] Builder tests: `sanitize_checkpoints` preserves `implies`; `validate_structure` rejects the 4 bad shapes.
- [ ] **T9 — validate, deploy, gate**
  - [ ] `python -m ruff check .` + `python -m ruff format --check .` + full `pytest` (warm the sandbox first: `import aiohttp` — known Defender cold-start quirk) + `flutter analyze` + `flutter test` (zero client change expected, run anyway — pre-commit law).
  - [ ] Run `server\scripts\calibrate.cmd waiter_easy_01` (live Groq; default 2.1 s throttle is fine) — must PASS post-edge; the ENGINE_VERSION bump will mark the other scenarios stale, which is expected (full sweep is a deliberate budgeted action — golden-only sweep `--golden-only` is the cheap alternative if quota is tight).
  - [ ] Deploy to VPS (`deploy-server.yml` path or scp + `systemctl restart pipecat.service`) and run the Smoke Test Gate below.

---

## Smoke Test Gate (Server / Deploy Stories Only)

> Every unchecked box is a stop-ship for `in-progress → review`. Paste the actual command + output as proof. This story has **no new endpoint and no migration** — the gate centres on deploy health + two scripted Pixel-9 calls.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_
- [ ] **DB reseed carried the edge (read-only check).** The seeded waiter row's checkpoints JSON contains the `implies` key.
  - _Command:_ `ssh root@167.235.63.129 "/opt/survive-the-talk/current/server/.venv/bin/python -c \"import sqlite3,json; c=sqlite3.connect('/opt/survive-the-talk/data/db.sqlite'); cps=json.loads(c.execute(\\\"SELECT checkpoints FROM scenarios WHERE id='waiter_easy_01'\\\").fetchone()[0]); print([cp.get('implies') for cp in cps])\""`
  - _Expected:_ `[None, 'greet', None, None, None, None]`
  - _Actual:_
- [ ] **DB backup:** N/A — no migration, no schema change (reseed is an idempotent upsert).
- [ ] **Pixel 9 call 1 — the back-fill (MONEY CALL), script for Walid below.** Greet ticks via back-fill on a no-greeting opener; call completes 6/6.
  - _Proof (journal):_ `checkpoint_advanced` for `main_course` AND `greet` on the same turn; `checkpoint_verdicts` lines present; debrief shows 6/6.
- [ ] **Pixel 9 call 2 — first-turn resilience.** The exact call-265/266 opening line gets a verdict on turn 1 (no silent ReadTimeout strand).
  - _Proof (journal):_ turn-1 `checkpoint_verdicts` line with `greet: met`; if a timeout still fires, the `first-call retry` line followed by a landed verdict.
- [ ] **Server logs clean.** `journalctl -u pipecat.service --since "10 min ago"` shows no ERROR/Traceback for the two calls.
  - _Proof:_

### 🎬 Ready-to-play script for Walid (hand this over verbatim at gate time)

**Réponses approximatives — c'est un LLM live, pas du déterminisme ; le but est de lire et d'observer, pas de prédire au mot près.**

**Appel 1 — "The Waiter", difficulté AU CHOIX (easy recommandé pour isoler le mécanisme).** Tu testes le back-fill : tu commandes SANS jamais saluer ni demander le menu.

| # | Tu dis (verbatim) | Réponse attendue (approx.) | HUD à surveiller |
|---|---|---|---|
| 1 | **"Hmm, I'll have the grilled chicken, please."** | Tina enchaîne (question de précision, ex. "grilled or fried?" ou passe aux boissons) | 💰 **MOMENT CLÉ : l'étape 1 (greet) se coche TOUTE SEULE en même temps que la commande** (2-3 coches d'un coup, dont la première) — c'est le back-fill. Avant ce fix, l'étape 1 restait bloquée pour toujours. |
| 2 | "Just water for me." | Elle note la boisson, récapitule peut-être | coche `drink` |
| 3 | (quand elle récapitule) "Yes, that's right." | Elle confirme, parle du temps d'attente | coche `confirm` |
| 4 | "Thank you!" | Phrase de clôture / fin de l'appel | coche `close` → **6/6, fin `survived`, débrief 6/6** |

**Appel 2 — "The Waiter" again.** Tu testes le tour 1 (la ligne exacte qui a échoué 2 fois les 9-10 juin) :

| # | Tu dis (verbatim) | Réponse attendue (approx.) | HUD à surveiller |
|---|---|---|---|
| 1 | **"Hi, good evening. Could I see the menu, please?"** | Tina te déroule le menu | 💰 **l'étape 1 (greet) se coche DÈS CE TOUR** (avant le fix : timeout silencieux, rien ne cochait) |
| 2+ | Continue ou raccroche — le gate est déjà validé après la ligne 1. | | |

Pendant les appels : monitoring silencieux côté agent, rapport unique en fin (règle smoke-gate).

---

## Dev Notes

### The one mental model to hold

Two structural guards now bracket the LLM judge, both living OUTSIDE the LLM:

| | Story 6.23 `requires` | **Story 6.27 `implies`** |
|---|---|---|
| Problem | beat credited **too early** (unsprung trap) | earlier beat **stranded** when a narrower later beat credits |
| Field sits on | the LATER (reactive) beat | the LATER (narrower) beat |
| Points to | an EARLIER beat id | an EARLIER beat id |
| Engine hook | `judgeable_goals` (gates judging) | `advance_goals` (back-fills crediting) |
| Validator | string + exists + strictly earlier | same + target must NOT carry `requires` |

Both edges point strictly earlier → both acyclic by construction → the 6.23 "earliest pending beat is always judgeable" proof (server/CLAUDE.md §7) is **preserved** (implies only flips beats met *faster*; it never gates).

### Engine mechanics you must not re-derive (verified file:line, current `main`)

- `advance_goals` ([checkpoint_manager.py:332-369](../../server/pipeline/checkpoint_manager.py)) is a **plain pure function** (not async), the SINGLE shared flip rule (prod + harness). The back-fill goes here and nowhere else — putting it in `_classify_and_flip_goals` would silently fork golden from prod.
- `GoalAdvance` (`:306-329`) is `@dataclass(frozen=True)`; `flipped_ids` order is documented as "the order the verdicts dict presented them" — extend that doc: back-filled ids follow the direct flips.
- The prod flow: `_classify_and_flip_goals` (`:1000-1237`) → `judgeable_goals` (`:1033`) → `classify_multi` (`:1057-1060`) → `advance_goals` (`:1137`) → assign state (`:1187`) → recompose steering (`:1204`) → per-flip envelopes (`:1211-1212`, `_emit_checkpoint_advanced` `:1239-1305`, double-emit URGENT + queued) → completion (`:1214-1231`, `schedule_completion(survival_pct=100)`) or `apply_exchange_outcome(success=True)` (`:1237`). **None of this changes** except the one-line call-site update at `:1137`.
- The envelope already carries the FULL met set (`goals_met_indices`, `:1307-1313`) — the Flutter HUD (`checkpoint_step_hud.dart`) animates from that set, and multi-tick turns already exist (double-flip ~2.5 s hold is intentional, do not "optimise" it). Hence AC7 zero client change.
- `judgeable_goals` (`:264-303`) — do not touch; `implies` interacts with it only by making beats leave `pending` sooner.

### ExchangeClassifier mechanics (D2 context)

- Lazy client: `_get_client()` double-checked-lock creates `httpx.AsyncClient(timeout=1.5)` on first use (`:247-272`) — THE cold-start. `classify_multi` (`:339-389`) wraps `_classify_multi` in `asyncio.wait_for(2.0)`; infra failures (`httpx.HTTPError` incl. ReadTimeout at `_post_for_content:410-442`, non-2xx `:444-455`, outer timeout) all return `None`; the manager then logs `checkpoint_classifier_inconclusive` and the turn is patience-neutral — that is the "silently lost opening turn".
- Strict structured output is LAW (server/CLAUDE.md §4): `response_format=json_schema` (`_build_verdict_schema:625-653`), enum `met|unmet|unsure` → `_VERDICT_TO_BOOL` (`:119`). The warm-up does NOT need json_schema (connection warmth is the goal); `max_tokens=1` plain completion is enough and cheapest.
- `_multi_max_tokens(n) = 96 + 24*n` (`:143-151`) — untouched.
- Groq free-tier reality: 30 req/min (memory `infra_groq_free_tier_rpm_limit`); the warm-up adds ONE request per call start — negligible. Scout (`classifier_model` default) benches 92% with 0 false negatives; every error is over-generous — consistent with back-fill being deterministic, not judge-tuning.

### Golden==prod + builder wiring (D1 context)

- Harness imports the REAL functions ([calibration_engine.py:79-94](../../server/scripts/calibration_engine.py)): `advance_goals`, `judgeable_goals`, `compose_goal_system_instruction`, loaders. `run_calibration` calls `advance_goals` per turn — passing `checkpoints=` there is the entire harness-side change for T1.
- The ledger (`validation-ledger.json`) skips unchanged-AND-passing scenarios; both the `implies` hash key and the ENGINE_VERSION bump correctly invalidate prior passes.
- Builder: `requires` end-to-end wiring (prompt → sanitize → validate → loader → engine → golden) is the template; Story 6.23's story file + server/CLAUDE.md §7 document it. Mirror, don't innovate.

### Previous-story intelligence

- **6.26 (bot pool):** parked bots pre-pay IMPORTS only; per-call config arrives via stdin job + env AFTER boot, so the classifier warm-up must run at **call start inside `run_bot`** (pool-park time has no call context). Use the `_BACKGROUND_TASKS` strong-ref + done-callback pattern (6.26 review patched exactly this class of fire-and-forget leak). Server suite was 801 green post-6.26-review.
- **7.1 (debrief):** the bot computes `checkpoints_passed` at teardown from the SAME CheckpointManager state — back-filled beats flow into the debrief + `call_sessions` counts automatically, zero 7.1 code touched. (This is why call 266 showed 5/6 in the debrief — 6.27 makes that same debrief show 6/6.)
- **6.24 (tts warm-up):** the warm-up-module contract to mirror (never raises, logs INFO on success / DEBUG on failure, standalone httpx — except HERE the client must be the classifier's own).

### What NOT to do

- ❌ Do NOT put back-fill logic in `_classify_and_flip_goals`, the loader, or the classifier — `advance_goals` only (golden==prod).
- ❌ Do NOT reword `greet`'s success_criteria (Option B) unless Walid picks B.
- ❌ Do NOT touch `judgeable_goals`, the 6.21 steering compose, `_DIFFICULTY_PRESETS`, or the MULTI prompt (judge-tuning is the existing "trim Scout's 6 FPs" follow-up, out of scope).
- ❌ Do NOT add a DB migration or refresh the prod snapshot — no schema change.
- ❌ Do NOT make `checkpoints` an optional/defaulted param on `advance_goals` — silent call-site divergence is exactly the bug class golden==prod exists to kill.
- ❌ Do NOT add new env flags for the warm-up/retry (mirror the unconditional `llm_warmup`; `BOT_POOL_SIZE`-style kill-switches are for riskier lifecycle changes).
- ❌ Do NOT name instance attributes after pipecat base-class ones (`_clock`, `_observer`, … — server/CLAUDE.md §1 `_clock` trap) if any FrameProcessor edit becomes necessary (none is expected).

### Project Structure Notes

- All changes in `server/` (pipeline/, scripts/, tests/, scenarios YAML). Zero client files. No migrations.
- Latest-tech check: no new dependencies; httpx + Groq json_schema + loguru already pinned and working. Nothing to research upstream.

### References

- Story 7.1 smoke gate (call_id=266) — where this surfaced; the 7.1 debrief backend itself was confirmed working.
- Stories **6.10** (any-order crediting), **6.21** (return-to-lowest-unmet, commit `0a55283`), **6.23** (`requires` reactive gating — THE pattern to mirror), **6.15/6.16** (harness/builder), **6.24** (warm-up contract), **6.26** (task-ref pattern, pool boot lifecycle).
- `server/CLAUDE.md` §1 (frame-direction + `_clock` traps), §3 (loguru-vs-caplog), §4 (judge structured-output LAW), §6 (calibrate when editing a scenario), §7 (`requires` invariants incl. the earliest-pending-always-judgeable proof), §8 (difficulty-neutral prompts).
- Memory: `project_reactive_checkpoint_gating` (6.23 model), `infra_groq_free_tier_rpm_limit`, `infra_groq_capacity_and_scout_fallback` (Scout judge limits), `feedback_sandbox_livekit_import_hang` (warm pytest sandbox first).

---

## Evidence appendix

- **Diagnostic workflow (2026-06-09):** 7 agents — log-evidence + code-audit + git-history bisect + synthesis + 3 adversarial verifiers (scenario-design / code-actually-broken / evidence-gap lenses). Verdict: **HIGH-confidence "not a regression."** All three adversarial lenses confirmed the top-line; the scenario-design lens argued (correctly) that the superset overlap is the PRIMARY frame, which this story adopts.
- **Honest confidence caveat (from the evidence-gap verifier):** there is **NO per-goal verdict logging** anywhere in the codebase, so whether the turn-2 `greet` verdict was "unmet" vs "unsure" is *unknowable from logs* (it is an inference). This does NOT change the fix — the superset overlap is the lever either way — but **per-goal verdict logging ships in this story (AC5)** so `calibrate_scenario waiter_easy_01` can reproduce judge behaviour deterministically next time.
- **Key journal lines (call 266 / process `python[1144623]`):** turn-1 `exchange classifier HTTP error: (ReadTimeout)` → `checkpoint_classifier_inconclusive ... pending=6 (infra failure)`; turn-2 `checkpoint_advanced ... goals_met_indices=[1, 2]` (greet absent); final `checkpoint_unmet no_goal_flipped met_count=5 pending=1`. Hard preset confirmed in the boot log (`initial_patience=60 / fail_penalty=-25 / escalation=[30,0]` = `_DIFFICULTY_PRESETS['hard']`).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
