# Story 6.29: Character Dialogue Coherence

Status: ready-for-dev

> ✅ **DECISION PASS RESOLVED (Walid, 2026-06-10, same day):** **D1 = (c) bounded wait (~800 ms budget)** · **D2 = face half IN this story** · **D3 = (b) back to 70B on Groq**. All decision-scoped ACs (AC7-AC10) are ACTIVE; T5's option-(c) provider-split sub-task is struck (not built now). `dev-story` may start.

## Story

As a learner practicing spoken English on a live call,
I want the character's replies and facial emotion to stay coherent with what I just said and with what she herself already asked and credited,
so that the call feels like a real conversation instead of a scripted bot that re-asks answered questions, reads its stage directions aloud, or recites canned lines.

## Why this story exists — call 274 forensics (2026-06-10, waiter, 55s)

Surfaced by Walid during the 6.27 smoke gate ("très dérangeant pour l'expérience utilisateur") and explicitly scoped OUT of 6.27 into this story. Full transcript recovered from journalctl. **Three distinct patterns in one call:**

| # | Pattern | Evidence | Mechanism |
|---|---------|----------|-----------|
| P1 | **Answered-question re-asked** | User: "I have the grilled chicken" → Tina: "Grilled or fried? I'm not psychic." (the answer was in the sentence she just read) | Attention miss on the user's latest line — strongest suspect: weak character model (Scout fallback since 2026-06-08; personas authored for Qwen, never recalibrated) |
| P2 | **Spoken meta / stage direction** | Tina says aloud: "(Actually, I still need to confirm - you said grilled chicken. That's all I have so far.)" — verbalized goal-steering scaffolding, self-contradicting | Weak model verbalizing the objectives block + NOTHING strips parentheticals before TTS (no sanitizer exists between `llm` and `tts`) |
| P3 | **Verbatim segment re-recitation** | User: "Yes, that's right." → Tina re-asks the `confirm` segment's example line word-for-word ("Did I get that right, or are you going to change your mind again?") | **By-design one-turn steering lag**: reply LLM generates CONCURRENTLY with the checkpoint judge (fire-and-forget since 6.6). Journal proof: 13:51:18.588 LLM starts replying to "Yes, that's right" → 13:51:18.817 `confirm=met` lands **229 ms LATER** → the reply was steered by the PRE-verdict objectives (confirm still pending) and parroted its scripted example line |

**NOT a 6.27 regression** — all three mechanisms predate it (6.27 touched neither the reply path nor the steering compose; STT was clean, transcript exact). This is also the rediscovered, **never-shipped Story 6.12 "Reactive Character Mood"** design: decided 2026-05-29, no spec/sprint entry ever created, its reliability gate (Qwen 429s) was cleared the same day by the all-Groq migration and nobody circled back. The fix never existed — see `memory/project_story_6_12_reactive_mood.md`.

## Decision Pass — D1 / D2 / D3 (PENDING)

### D1 — Steering timing: should the reply LLM WAIT for the judge's verdict? (fixes P3 + helps P1)

**Walid's stated direction (2026-06-10):** systematically WAIT for the judge's verdict BEFORE the character formulates her reply — for BOTH reply coherence and facial-emotion coherence.

**The 2026-05-29 decision this contradicts** (Walid + assistant, deliberately challenged): keep the checkpoint judge SEPARATE/parallel, explicitly REJECTING reply-waits-for-judge because (1) resilience — a judge failure must never mute Tina (a Qwen 429 literally killed the voice on 2026-05-28); (2) stepper latency — a parallel verdict returns in ~120 ms regardless of reply length.

**What changed since (why re-deciding is legitimate):**
- Judge is fast AND on our own quota: p50 ≈ 121 ms / p95 ≈ 320 ms (Groq bench 2026-05-22; Scout ≈ same, ~220 ms from VPS). Call-274 real-world sample: the verdict landed **229 ms** after LLM start — that IS the cost of waiting.
- 6.27 made the judge more reliable AND observable: boot warm-up, first-call retry, `checkpoint_verdicts` per-goal logging.
- The one-turn steering lag now has an evidence-confirmed UX cost (P3 above).
- The resilience objection is reconcilable by **fail-open**: on judge timeout/infra failure, forward the frame anyway and generate with stale steering (= exactly today's behavior). Tina can never be muted by a judge failure.
- Precedent already shipped: the terminal-turn path ALREADY blocks on the verdict (`_run_classifier_blocking`, [checkpoint_manager.py:1020-1031](../../server/pipeline/checkpoint_manager.py)), and the 6.25 stacked path ALREADY defers forwarding the user frame until the prior classify resolves — its docstring calls that "also CORRECT for coherence". Wait-mode extends two existing, smoke-validated patterns to every judged turn.

**Latency budget check:** net silence-to-turn-end floor is ~1.4 s (`stop_secs=0.8` + `user_speech_timeout=0.6`, [bot.py:374-405](../../server/pipeline/bot.py)) under the PRD 2 s perceived ceiling (🚨 memory `feedback_latency_kill_criterion_exceeded`). Waiting adds the verdict in-line: p50 ~120-220 ms, p95 ~320 ms, hard-bounded by the classifier's 2.0 s outer timeout (then fail-open). The judge call starts when the finalized TranscriptionFrame arrives — typically BEFORE the turn-end timer fires — so part of the wait overlaps dead time already being spent.

| Option | Behavior | Trade-off |
|---|---|---|
| **(a) Keep parallel** (2026-05-29 position) | No change; rely on D2+D3+charter+sanitizer only | Zero added latency; P3 mechanism remains (stale steering window stays open) |
| **(b) Wait, fail-open** (Walid's direction) | Every judged turn: await verdict (≤2.0 s classifier bound) → flips + recompose + envelope land → THEN forward frame to LLM. On `None` verdict: forward anyway | +120-320 ms typical added latency; P3 structurally fixed; checkpoint HUD ticks land BEFORE the reply (reads as "she heard me") |
| **(c) Bounded wait** | Same as (b) but with a dedicated wait budget (e.g. 800 ms): if no verdict by then, forward with stale steering; verdict applies late (today's behavior) | Caps worst-case added latency below the classifier timeout; slightly more code/states |

**Resolution:** ✅ RESOLVED (Walid 2026-06-10): **(c) Bounded wait.** Wait up to a dedicated budget (default **800 ms**, ONE env var with a sane default — the sanctioned exception in What-NOT-to-do) for the verdict's side effects to land before forwarding the frame; on budget miss, forward with stale steering and let the verdict apply late (exactly today's behavior — fail-open is implied: an infra-failure `None` inside the budget also forwards). Caps the worst case below the classifier's 2.0 s bound while capturing the p95 ≈ 320 ms typical case.

### D2 — Face half: co-generate the mood WITH the reply LLM, retiring EmotionEmitter? (scope decision)

The 2026-05-29 design (already decided, never shipped) and still the recommended fix for the FACE half: the model that writes Tina's line tags its own emotion in the same response → text↔mood coherence **by construction**. Today's `EmotionEmitter` ([emotion_emitter.py](../../server/pipeline/emotion_emitter.py)) guesses the mood from the USER's line alone, in a separate async Groq call, without ever seeing the reply Tina actually gives — mismatch and lag are structural. Co-generation also DELETES one Groq call per turn (≈250 LOC + its conversation-context input tokens — the merge is net cheaper, see memory).

Mechanics (the engineering risk is streaming): reply text streams to TTS first; a small trailing tag (e.g. `<mood:frustration>`) is emitted at the END of the reply; the new sanitizer processor (T2) strips it from the text stream and emits the **unchanged** `{"type":"emotion","data":{"emotion":...,"intensity":...}}` envelope. Client is confirmed indifferent (see Zero-Flutter note below). Absent/malformed/invalid tag → no envelope, character keeps prior pose (same degradation as today's timeout path). The checkpoint JUDGE stays separate regardless — merging IT into the reply LLM was weighed and rejected 2026-05-29 and stays rejected (server/CLAUDE.md §4 LAW: judge model must support strict `json_schema`; the character LLM must NOT use `json_schema` — it breaks streaming and 70B doesn't support it).

**Resolution:** ✅ RESOLVED (Walid 2026-06-10): **include the face half in THIS story** — mood co-generated by the reply LLM, EmotionEmitter retired (T4/AC8 active).

### D3 — Character model: move CHARACTER_MODEL off Scout? (strongest single lever for P1+P2)

Since the 2026-06-08 quota fallback, the VPS `.env` pins `CHARACTER_MODEL` to Llama 4 Scout (17B — weak instruction-following; the code default is still `llama-3.3-70b-versatile`, [config.py](../../server/config.py)). Personas were authored for Qwen and never recalibrated (server/CLAUDE.md §4 follow-up note).

| Option | How | Risk/cost |
|---|---|---|
| **(a) Stay on Scout** | Ship D1/D2/charter/sanitizer only; measure | Architecture fixes may not fully compensate a weak model's attention misses (P1) |
| **(b) Back to 70B on Groq** | One-line VPS `.env` change, instant, reversible | Groq free 70B = **100k tokens/day** (binding cap — froze a call mid-way on 2026-06-08). OK for current solo smoke-gate traffic; not durable for launch |
| **(c) Character-only provider split** (DeepInfra/Together per memory `infra_groq_capacity_and_scout_fallback`) | Small code change: per-path `CHARACTER_BASE_URL`/`CHARACTER_API_KEY` env overrides (default = today's global Groq), main LLM only — judge + warm-up stay on Groq | Needs a new provider API key from Walid + a paid account; the durable plan |

**Resolution:** ✅ RESOLVED (Walid 2026-06-10): **(b) back to 70B on Groq** — one-line VPS `.env` re-pin (`CHARACTER_MODEL=llama-3.3-70b-versatile`), instant + reversible; the **100k TPD free-tier cap is an accepted watch item** for current solo traffic (option (c) provider split stays the durable plan, NOT built in this story). Full persona recalibration on Llama remains OUT of scope (separate deliberate follow-up).

## Acceptance Criteria

Unconditional ACs (in scope regardless of D1-D3):

1. **AC1 — Coherence charter extension (P1+P3 floor, system-wide).** `COHERENCE_CHARTER` ([prompts.py:72](../../server/pipeline/prompts.py)) gains three rules, scenario-independent and difficulty-neutral: (a) **answered-question rule** — before asking anything, check the user's MOST RECENT line; if it already contains the answer, acknowledge it instead of asking (the "Grilled or fried?" case); (b) **spoken-dialogue-only rule** — output is ONLY words the character speaks aloud; never parentheses, stage directions, planning notes, or meta-commentary about objectives; (c) **style-not-script rule** — quoted example lines in the objectives are style/tone guidance, never scripts; never recite one verbatim, and never repeat a question (in any phrasing) that was already asked and answered. Charter stays in its fixed slot in `compose_goal_system_instruction` (boot + every recompose).
2. **AC2 — TTS sanitizer.** A new FrameProcessor between `llm` and `tts` strips non-spoken artifacts from LLM-origin streamed text before TTS and before `transcript_character`: parenthetical spans `( … )` and asterisk actions `* … *` (P2). It ONLY transforms `TextFrame`s within an LLM response (`LLMFullResponseStartFrame`/`EndFrame` brackets); `TTSSpeakFrame` exit lines and all other frames pass untouched. Buffering must not add perceivable TTS latency (hold back at most a small tail window for split-span/tag detection) and must reset on interruption frames. A reply that becomes EMPTY after stripping (pure-meta reply, the exact call-274 P2 case) is dropped whole (nothing sent to TTS) and logged — accepted trade-off: a rare silent turn (recoverable; the silence ladder still runs) beats spoken scaffolding, and charter rule (b) reduces occurrence upstream; do NOT regenerate (latency) and do NOT let the raw text through.
3. **AC3 — Zero Flutter changes.** Envelope shapes (`emotion`, `checkpoint_advanced`) are byte-compatible; client confirmed tolerant of any timing change and silently drops unknown types ([data_channel_handler.dart:249-257](../../client/lib/features/call/services/data_channel_handler.dart)). `flutter analyze` + `flutter test` green with zero client diffs.
4. **AC4 — Golden==prod holds.** `ENGINE_VERSION` 4→5 in [calibration_engine.py](../../server/scripts/calibration_engine.py) (the charter is a code constant OUTSIDE `scenario_hash` — same precedent as the 6.19 block-tightening bump). `calibrate_scenario.py --golden-only` sweep PASSES post-change. Full band calibration remains quota-walled → deferred-work entry, exactly like 6.27.
5. **AC5 — Crediting logic untouched.** `advance_goals`, `judgeable_goals`, the judge prompt/schema/model, and the 6.25 fail-coalescing semantics are unchanged (existing tests prove it). This story changes WHEN the verdict is consumed, never WHAT it decides.
6. **AC6 — Gates.** `ruff check` + `ruff format --check` + full `pytest` green (server, 844 baseline); `flutter analyze` + `flutter test` green (451 baseline); new behaviors covered by tests per T6.

Decision-scoped ACs (struck or kept by the decision pass):

7. **AC7 (only if D1 = wait/bounded-wait).** On every judged turn, the verdict's side effects (goal flips, system-instruction recompose, `checkpoint_advanced` envelope, patience outcome) land BEFORE the user frame is forwarded to the LLM. **Fail-open invariant:** a `None` verdict (timeout/HTTP/parse failure) forwards the frame after the classifier bound — the character can NEVER be muted by a judge failure. A real-pipeline drive test (server/CLAUDE.md §1 convention) proves a delayed TranscriptionFrame still yields exactly ONE LLM run containing the full user text — no empty-context run, no dropped turn — including when the wait exceeds `user_speech_timeout` (0.6 s). Echo-guard, post-hangup suppress, and terminal-turn paths keep their current semantics.
8. **AC8 (only if D2 = in scope).** The reply LLM co-generates a trailing mood tag consumed by the T2 sanitizer: tag never reaches TTS audio nor the transcript; a valid tag (7-value enum: `satisfaction|smirk|frustration|impatience|anger|confusion|disgust_hangup`) emits the same `emotion` envelope as today; absent/invalid tag keeps the prior pose. `EmotionEmitter` is retired: removed from `bot.py` wiring, its module + tests deleted, `EMOTION_MODEL` marked legacy in `config.py` (kept, like `OPENROUTER_API_KEY`). The mood-tag directive is appended in EVERY system-instruction composition (boot + every recompose), same invariance as the charter.
9. **AC9 (only if D1 = wait, latency proof).** Added latency is measured and reported: `LATENCY_PROBE=1` on-device before/after, plus a new INFO log of per-turn verdict wait duration. Perceived reply latency stays under the PRD 2 s ceiling on the Pixel 9 smoke gate (p95 wait ≤ ~350 ms expected).
10. **AC10 (only if D3 = (b) or (c)).** `CHARACTER_MODEL` re-pinned per decision on the VPS (env change, backup of `.env` noted in deploy log); if (c), the per-path `CHARACTER_BASE_URL`/`CHARACTER_API_KEY` overrides default to the global Groq values so today's deploys keep working untouched.

## Tasks / Subtasks

- [ ] **T1 — Charter extension (AC1, AC4)**
  - [ ] Add the three rules to `COHERENCE_CHARTER` in `prompts.py`; keep wording difficulty-neutral (no rephrase/idiom/pace vocabulary — see `_PERSONA_DIFFICULTY_LEAK_PATTERNS` for the family of words to avoid).
  - [ ] Bump `ENGINE_VERSION` 4→5 with a dated comment explaining the charter change (mirror the 6.19/6.27 comment style).
  - [ ] Run `python scripts/calibrate_scenario.py --golden-only` (live Groq) and paste the PASS summary; add the full-band-sweep deferred-work line.
- [ ] **T2 — Reply sanitizer FrameProcessor (AC2, +AC8 if D2)**
  - [ ] New `pipeline/reply_sanitizer.py` (name free): strips `(...)`/`*...*` spans from LLM `TextFrame`s; small tail-buffer for spans/tags split across streamed frames; flush on `LLMFullResponseEndFrame`; reset on interruption; pass-through for every other frame type. Do NOT name attributes after pipecat base-class ones (`_clock`, `_observer`, … — §1 trap).
  - [ ] Wire into `bot.py` between `llm_first_text_probe` and `transcript_character` (so probes measure raw LLM TTFT, but transcript + TTS both see CLEAN text).
  - [ ] (D2) Tag extraction: recognize the trailing mood tag, map to the 7-value enum, push the `emotion` `OutputTransportMessageFrame` DOWNSTREAM.
- [ ] **T3 (D1) — Wait-for-verdict in CheckpointManager (AC7, AC9)**
  - [ ] Extend `process_frame`'s non-terminal branch ([checkpoint_manager.py:803-863](../../server/pipeline/checkpoint_manager.py)): after `_serialize_then_classify`, await THIS turn's in-flight task (reuse the `_run_classifier_blocking` shape) bounded by the D1(c) wait budget (`asyncio.wait_for`-style with `asyncio.shield` so the in-flight task SURVIVES a budget miss and applies late) before falling through to `push_frame`. ONE env var for the budget, default 800 ms.
  - [ ] Preserve: 6.25 coalescing (`coalesce_fail`), generation guard, echo guard, 6.22 post-hangup suppress, terminal-turn lock, and the two post-serialize suppress backstops.
  - [ ] Per-turn wait-duration INFO log line (greppable for the smoke gate).
  - [ ] Real-pipeline drive test per AC7 (PipelineTask + PipelineRunner — §1 convention; mirror `test_checkpoint_manager_observes_finalized_TranscriptionFrame_via_real_pipeline_drive`).
- [ ] **T4 (D2) — Mood co-generation + EmotionEmitter retirement (AC8)**
  - [ ] Mood-tag directive constant in `prompts.py`, threaded through `compose_goal_system_instruction` (+ the boot composition in `bot.py`) so it survives every recompose.
  - [ ] Remove `emotion_emitter` from the `bot.py` pipeline list + constructor block; delete `pipeline/emotion_emitter.py` + `tests/test_emotion_emitter.py`; mark `EMOTION_MODEL` legacy.
  - [ ] Tests: tag stripped from TTS text + transcript; valid tag → envelope; invalid/absent → no envelope; tag split across two TextFrames; barge-in mid-reply clears the buffer.
- [ ] **T5 (D3=b) — Character model re-pin (AC10)**
  - [ ] VPS `.env` `CHARACTER_MODEL=llama-3.3-70b-versatile` + `systemctl restart pipecat.service` at deploy time (backup the `.env` first); record the 100k TPD watch item in the deploy note. ~~Option (c) provider split~~ — struck by the decision pass, stays the durable post-launch plan.
- [ ] **T6 — Test suite (AC5, AC6)** — new tests as listed per task; confirm zero regressions on `test_checkpoint_manager.py` / `test_exchange_classifier.py` / `test_bot_pipeline_wiring.py`; add a `bot.py` source-text wiring contract test for the sanitizer slot (mirror 6.27's warm-up wiring test).
- [ ] **T7 — Deploy + smoke gate** — deploy to VPS, verify `[pooled]` boot, then hand Walid the ready-to-play script below.

## Smoke Test Gate (Server / Deploy Stories Only)

> No new endpoints, no DB migration — endpoint/DB boxes are N/A by scope. The gate here is deploy + clean logs + the on-device behavior script.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line -->
- [ ] **Happy-path endpoint round-trip.** N/A — this story adds/changes no HTTP endpoint (pipeline-only change). Existing `/scenarios` smoke covered by prior stories.
- [ ] **Error / unauth path.** N/A — no endpoint surface touched.
- [ ] **DB side-effect verified.** N/A — zero DB impact, no migration.
- [ ] **DB backup taken BEFORE deploy.** N/A — no schema change (the standard pre-deploy auto-backup still runs via deploy-server.yml).
- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 100 --since "10 min ago"` during the script below: no ERROR/Traceback; (D1) per-turn wait log present; (D2) no `emotion_emitter` lines remain; sanitizer strip events logged when triggered.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->
- [ ] **Pixel 9 on-device script (below) validated by Walid.**

### Ready-to-play Pixel 9 script (per root CLAUDE.md rule — read, don't improvise)

Scenario: **The Waiter** (Tina). Goal: replay the exact call-274 failure surface. Responses are approximate — live LLM, not deterministic; watch the BEHAVIOR, not exact words.

1. **Say:** "Hi, I'd like to order, please." → _Expect:_ Tina reels off the menu. HUD: step 1 ticks. **(D1) watch:** the tick lands BEFORE or AS she starts answering, not a turn later.
2. **Say:** "I'll have the grilled chicken." → _Expect:_ she acknowledges grilled chicken and moves toward drinks — **💰 MONEY MOMENT #1 (P1):** she must NOT ask "Grilled or fried?" — the answer was in your sentence. HUD: main-course step ticks (clarify may tick too — both are correct).
3. **Say:** "Just a water, please." → _Expect:_ drink acknowledged, she summarizes the order. Listen for **MONEY MOMENT #2 (P2):** no spoken parentheses/meta ("Actually, I still need to confirm…") at ANY point in the call.
4. **Say:** "Yes, that's right." → _Expect:_ **💰 MONEY MOMENT #3 (P3):** she accepts and moves to wrap-up (wait time line). She must NOT re-ask "Did I get that right…" after your confirmation. HUD: confirm ticks before her reply (D1).
5. **Say:** "Thank you!" → _Expect:_ completion path, survived exit line, Call Ended overlay.
6. **(D2) Throughout:** her FACE should match her line's tone (sarcastic line → smirk, annoyed line → frustration) — not a stale pose from your previous turn.
7. **(D1/AC9) Feel check:** her replies should not feel noticeably slower than the 6.27-era calls (PRD 2 s ceiling).

## Dev Notes

### Architecture compliance (read before coding)

- **Pipeline order today** ([bot.py:673-752](../../server/pipeline/bot.py)): `transport.input → input_gate → stt → endpoint_watchdog → transcript_user → environment_monitor → emotion_emitter → checkpoint_manager → patience_tracker → hesitation_observer → context_aggregator.user() → llm → llm_first_text_probe → transcript_character → tts → tts_watchdog → tts_first_audio_probe → transport.output → context_aggregator.assistant()`. The sanitizer (T2) slots after `llm_first_text_probe`, before `transcript_character`.
- **The wait mechanism is frame-forward gating, nothing exotic.** CheckpointManager sits UPSTREAM of `context_aggregator.user()`; the LLM cannot see a user turn until CheckpointManager calls `push_frame`. Today's terminal path already blocks ([checkpoint_manager.py:758-802](../../server/pipeline/checkpoint_manager.py)), today's stacked path already defers ([:949-998](../../server/pipeline/checkpoint_manager.py)). D1 generalizes that to the normal path at [:803-863](../../server/pipeline/checkpoint_manager.py).
- **Re-entrancy is documented and safe**: `TranscriptionFrame` is a non-system frame (one at a time per processor); SystemFrames (Bot*Speaking, UserStarted/Stopped) re-enter `process_frame` during an await but only touch `_bot_speaking` — see the `_serialize_then_classify` docstring.
- **Downstream effects of holding the TF ~120-320 ms:** PatienceTracker's silence-timer cancel arrives late by the wait (harmless — ladder operates at 10s+ scales); HesitationObserver is UNAFFECTED (it pairs `BotStoppedSpeakingFrame`→`UserStartedSpeakingFrame` speech-boundary frames, not TFs — [hesitation_observer.py:1-22](../../server/pipeline/hesitation_observer.py)); the context aggregator's turn-end strategy (`user_speech_timeout=0.6`) vs a late TF is THE thing AC7's pipeline-drive test must prove out.
- **Judge stays separate — LAW.** server/CLAUDE.md §4: the checkpoint judge model must support strict `json_schema`; never merge it into the reply LLM (2026-05-29 decision half that still stands: accuracy, independent prompt tuning). Conversely the CHARACTER LLM must NOT get `response_format=json_schema` — it breaks streaming-to-TTS and 70B rejects it; the D2 mood tag is a plain-text trailing token, not structured output.
- **Envelope contract is additive-only** (Story 6.7 Deviation #1): same `type` strings, same `data` fields. Client tolerance verified 2026-06-10: unknown types silently dropped; `emotion.intensity` is received but UNUSED client-side; no ordering assumptions between emotion envelopes and audio playback; checkpoint HUD has zero timing dependency on envelope arrival (its 0.75 s hold is local animation).
- **Charter/persona hygiene:** the new charter rules are SYSTEM-level (Walid's standing rule: coherence must never live per-scenario — memory `feedback_coherence_must_be_system_wide`). Do not edit scenario YAML `prompt_segment`s to fix P2/P3 — the segments' example lines are fine as authoring style; the runtime must stop treating them as scripts.
- **Groq budget:** wait-mode adds ZERO requests; D2 REMOVES one request per turn (EmotionEmitter) — net friendlier to the 30 req/min free tier (memory `infra_groq_free_tier_rpm_limit`).

### Previous story intelligence (6.27, review-complete 2026-06-10)

- Fire-and-forget background tasks MUST use the `_BACKGROUND_TASKS` strong-ref + done-callback pattern (6.26 review caught the GC leak class).
- `checkpoint_verdicts model=… verdicts={…}` INFO line exists per parsed verdict (raw enums, `unsure` vs `unmet` distinct) — your wait-duration log should sit next to it; the review hardened it against unhashable values.
- The classifier's first-call retry semantics are pinned by a test — "never retry after the first success; never twice per call"; wait-mode must not double-trigger it (the wait consumes the SAME `classify_multi` call, no extra attempts).
- Warm-up runs at call start inside `run_bot` (pool-parked bots have no call context — 6.26).
- Full gates baseline post-6.27-review: server pytest **844**, flutter **451**, ruff + analyze clean.
- Review discipline: the reviewer flips `review → done` only after BOTH the code review AND the Pixel 9 smoke gate (root CLAUDE.md flip-discipline, rewritten 2026-06-10).

### Git intelligence (last 5 commits)

`1b43aa3` 6.27 review patches + done flip · `db2a2da` process rule + 6-29 enrichment · `1a9b40a` 6.27 smoke gate + 6-29 spin-off · `6b34aa1` 6.27 deploy verified (VPS on `d4e40af`) · `d4e40af` 6.27 implementation. Pattern: one commit per story stage, list-format bodies, no Co-Authored-By, sprint-status flipped in the same commit.

### Latest-tech check

No new dependencies. pipecat 0.0.108, httpx, Groq endpoints all pinned and working. Groq structured outputs intentionally NOT used on the character path (streaming). Provider-switch plumbing (`LLM_BASE_URL`/`LLM_API_KEY`, [llm_provider.py:44-73](../../server/pipeline/llm_provider.py)) already exists for D3(c)'s per-path variant to mirror. Nothing to research upstream.

### What NOT to do

- ❌ Do NOT merge the checkpoint judge into the reply LLM (rejected 2026-05-29; §4 LAW) — D1 changes WHEN the verdict is consumed, not WHO judges.
- ❌ Do NOT put `response_format=json_schema` on the character LLM (breaks streaming; 70B 400s on it).
- ❌ Do NOT touch `advance_goals` / `judgeable_goals` / the judge prompt/schema (AC5) — crediting is 6.27-frozen; golden==prod depends on it.
- ❌ Do NOT fix P2/P3 by editing scenario YAMLs or per-scenario prompts (system-level rule, Walid 2026-05-19) — and do NOT add any new coupling to `metadata.difficulty` (6-28 owns its removal).
- ❌ Do NOT change envelope `type`/`data` shapes or add a schema version field (additive evolution only; zero-Flutter AC3).
- ❌ Do NOT let the sanitizer touch `TTSSpeakFrame`s (exit lines like `*heavy sigh* I'm done.` are PatienceTracker-owned, pre-existing behavior, out of scope).
- ❌ Do NOT hold ALL frames in CheckpointManager — only the finalized, non-echo, judged TranscriptionFrame path waits; SystemFrames keep flowing.
- ❌ Do NOT name FrameProcessor attributes after pipecat base ones (`_clock`, `_observer`, `_next`… — §1 `_clock` trap killed HesitationObserver in prod once).
- ❌ Do NOT add a kill-switch env for the wait (mirror 6.27's no-new-flags posture) UNLESS D1=(c)'s budget value needs tuning — then ONE env with a sane default.
- ❌ Do NOT start dev before D1/D2/D3 are recorded above.

### Project Structure Notes

- All changes in `server/` (`pipeline/`, `scripts/`, `tests/`) + this story file + `sprint-status.yaml`. Zero client files (AC3). No migrations, no endpoint changes, no prod-snapshot refresh.
- Conventions: loguru snake_case event-style log lines; tests next to siblings in `server/tests/`; pure logic stays import-light for the calibration harness.

### References

- Sprint-status `6-29` entry (2026-06-10) — full call-274 forensics + Walid's design direction + the do-not-pre-decide instruction (the authoritative story foundation; epics.md has no 6-29 entry — smoke-gate spin-off).
- Memory: `project_story_6_12_reactive_mood.md` (BOTH 2026-05-29 positions + the 2026-06-10 update — REQUIRED READING for the decision pass), `feedback_coherence_must_be_system_wide.md`, `infra_groq_capacity_and_scout_fallback.md`, `feedback_latency_kill_criterion_exceeded.md`, `infra_groq_free_tier_rpm_limit.md`.
- Code anchors: [checkpoint_manager.py](../../server/pipeline/checkpoint_manager.py) (`process_frame` :719-865, `_serialize_then_classify` :949-1018, `_run_classifier_blocking` :1020-1031, `_classify_and_flip_goals` :1033-1210, `compose_goal_system_instruction` :224-256), [exchange_classifier.py](../../server/pipeline/exchange_classifier.py) (timeouts :143-166, warm-up :283-333, retry :445-464), [emotion_emitter.py](../../server/pipeline/emotion_emitter.py), [prompts.py](../../server/pipeline/prompts.py) (charter :72-101, emotion prompt :125), [bot.py](../../server/pipeline/bot.py) (pipeline :673-752, VAD/turn timing :374-405), [llm_provider.py](../../server/pipeline/llm_provider.py).
- server/CLAUDE.md §1 (pipeline-drive tests + `_clock` trap), §4 (all-Groq + judge structured-output LAW + persona-recalibration follow-up note), §6 (calibrate when prompts change), §8 (difficulty-neutral language).
- Stories: 6.6 (fire-and-forget judge origin), 6.10 (goal steering), 6.20/6.25 (stacked-await + coalescing — the patterns D1 extends), 6.23 (`requires` gating), 6.27 (previous story — warm-up/retry/verdict logging).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

## Change Log

- 2026-06-10 — Story created via create-story (ultimate context engine analysis: 3 parallel artifact analyses — server pipeline, client envelope tolerance, scenario/prompt system — + call-274 forensics + 6.12 design-history reconciliation). Status: backlog → ready-for-dev. D1/D2/D3 decision pass pending with Walid; dev-story blocked until resolved.
- 2026-06-10 (same day) — **Decision pass RESOLVED by Walid:** D1=(c) bounded wait (~800 ms budget, fail-open), D2=face half IN scope (mood co-generation + EmotionEmitter retirement), D3=(b) CHARACTER_MODEL back to 70B on Groq (.env re-pin, 100k TPD accepted watch item). AC7-AC10 active; T5 option (c) struck. Story fully unblocked for /bmad-dev-story.
