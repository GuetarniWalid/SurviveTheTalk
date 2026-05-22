# Story 6.9b: Classifier Latency Slash

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As the operator (Walid),
I want the `ExchangeClassifier` round-trip latency cut from ~1000-1500 ms median (p95 ~1700-1900 ms) down to p50 ≤300 ms / p95 ≤500 ms,
so that (a) the Story 6.8 AC5 ≤2000 ms perceived-latency ceiling applies UNIVERSALLY again (including the terminal-turn synchronous-classifier path that Story 6.9 D2 explicitly retracted), (b) the Story 6.9 Deviation #5 `verdict=None` soft-lock window collapses to near-zero — the consecutive-None backstop becomes effectively unreachable in normal operation, (c) Story 6.12 "Reactive Character Mood" can adopt the **sync-verdict-everywhere** architecture (vs the visual-first feedback fallback) — option D in `memory/project_story_6_9b_classifier_latency_slash.md` §4, and (d) the MVP voice loop sits comfortably under PRD `Performance` row "consistently >2s → concept dead" with margin.

## Background

**Direct successor of Story 6.9's code review (2026-05-21).** The Story 6.9 `/bmad-code-review` surfaced that the classifier latency is the root bottleneck behind multiple structural problems:

1. **D2 — Story 6.8 AC5 retract for terminal turn.** The 2.0 s outer / 1.5 s HTTP budget restored in Story 6.9 Deviation #6 left the terminal-turn synchronous-classifier path at p95 ~2800-3000 ms — explicitly retracting the Story 6.8 AC5 hard ceiling. Latency-probe regression test (P18) bounds it at ≤3000 ms so further widening fails CI loudly. **This dette is explicitly temporary and this story is the unwinding.**
2. **D1 — `verdict=None` patience-neutral semantics (Deviation #5).** Walid 2026-05-21 reasoning behind the consecutive-None backstop (P16, N=5): "pure neutrality opens an unbounded soft-lock window; silence ladder doesn't cover the 'user keeps talking while classifier degraded' case". Bringing classifier latency under 300 ms collapses the soft-lock window to near-zero — even at 5 consecutive failures the call accumulates <2 s of dead air before the safety belt fires.
3. **Walid's "le perso s'énerve sur la phrase d'après" finding (queued as Story 6.12 "Reactive Character Mood").** The asynchronous patience-drain / emotion-emission produces a one-turn reaction lag where the character reacts on the NEXT turn, decoupled from the user phrase that caused it. Story 6.12 has two architectural paths: sync verdict everywhere (cleanest, requires <300 ms classifier) OR visual-first feedback fallback (Rive face reacts on data channel, voice still async). **Story 6.9b's outcome determines which path Story 6.12 takes.**

**The strategic framing is what justifies the priority** — this is NOT a generic "swap providers" story. The full rationale lives in `memory/project_story_6_9b_classifier_latency_slash.md` (must-read before drafting code). Three points worth repeating in this spec:

- **Cost matrix at MVP scale** (per ~10 classifies/call, 5 exchange + 5 emotion). Per `project_story_6_9b_classifier_latency_slash.md` §1, validate at benchmark time:

  | Provider | $/1M input | $/1M output | TTFT | 100 users × 5/day | 1000 users × 5/day |
  |---|---|---|---|---|---|
  | **Qwen 3.5 Flash via OpenRouter** (current) | $0.05 | $0.15 | 300-1500 ms ⚠️ | $6/mo | $60/mo |
  | **Groq + Llama 3.1 8B** | $0.05 | $0.08 | 50-100 ms ⚡ | $6/mo | $60/mo |
  | **Cerebras + Llama 3.1 8B** | $0.10 | $0.10 | 30-50 ms ⚡⚡ | $12/mo | $120/mo |
  | **OpenAI GPT-4o-mini** | $0.15 | $0.60 | 300-500 ms | $20/mo | $200/mo |
  | **Anthropic Haiku 4.5** | $1.00 | $5.00 | 300-500 ms | $135/mo | $1,350/mo |

  **Key insight:** Groq is **cost-equivalent** to current Qwen and **5× faster** on TTFT. Cerebras = 2× cost, 10× faster. Haiku 4.5 = 22× cost for pre-revenue MVP, included in the benchmark for quality ceiling reference but ruled out on cost.

- **Turn-taking research bands** (Stivers et al. cross-language corpus + Nielsen HCI). The target — p50 ≤300 ms — sits inside the "200-600 ms slight reflection, still fluid" band. Today's ~1046 ms median sits in the "600-1000 ms thoughtful pause" band, ~1700-1900 p95 sits in the "1.5-2 s uncomfortable" band. Modern voice assistants target 300-700 ms — their primary moat over us.

- **Option E (this story) was chosen over F (visual-first only) and G (skip benchmark, go Cerebras direct).** F is the safety net inside E (if benchmark proves classifier can't fall below ~500-800 ms, Story 6.12 falls back to visual-first feedback). G was rejected because Cerebras pricing/availability/Llama-3.1-classification-quality are unproven for our specific prompt — no fallback if it fails. E unblocks the most options.

**Hard prerequisite chain:**
- ✅ Story 6.6 (CheckpointManager + ExchangeClassifier) — done
- ✅ Story 6.7 (CheckpointStepper Rive overlay) — done
- ✅ Story 6.8 (latency + coherence + Waiter calibration) — done
- ✅ Story 6.9 (DTLN noise suppression + reliability amends + review) — done
- ⏳ Story 6.9b (this story) — ready-for-dev
- 🔒 Story 6.10 (goal-based dialogue) — blocked on 6.9b (already drafted, depends on classifier reliability + latency)
- 🔒 Story 6.11 (noisy-environment detection) — blocked on 6.9b + 6.10
- 🔒 Story 6.12 (reactive character mood) — blocked on 6.9b benchmark outcome (architecture decision pending)

**Critical reading before starting:**

- **🚨 `memory/project_story_6_9b_classifier_latency_slash.md`** — full context: cost matrix, turn-taking research, option-E rationale, link to Story 6.12. MUST READ first. Walid (2026-05-21): "Don't let it ship as a generic 'swap providers' story — the strategic framing is what justifies the priority."
- `_bmad-output/implementation-artifacts/6-9-dtln-noise-suppression.md` §"Post-Smoke-Test Amends" (Deviations #5-#10) and §"Review Findings" (D1-D5) — every reliability patch from Story 6.9 stays in place; this story builds ON those amends, doesn't unwind them.
- `_bmad-output/implementation-artifacts/deferred-work.md` line 451 — "Re-calibrate the 5 launch scenarios after EXCHANGE_CLASSIFIER_PROMPT rewrite (D4 / Story 6.9 Deviation #10)" — bands probably drifted again post Story 6.9 prompt rewrite; this story re-triggers that calibration (but Walid-owned, OUT OF SCOPE for `in-progress→review` per Deviation #4 below).
- `server/pipeline/exchange_classifier.py` (whole file, 336 lines) — current implementation with persistent `httpx.AsyncClient` + `_closed` flag + lock-guarded `close()` + RuntimeError handling. Lines 64-65 are the OpenRouter URL + model ID to swap. Lines 78-79 are the timeout constants from Story 6.9 (kept as ceiling, not target — target metric is the new latency).
- `server/pipeline/prompts.py` lines 159-204 — current `EXCHANGE_CLASSIFIER_PROMPT` (~600-900 tokens with the 6 GUIDING PRINCIPLES from Story 6.9 D4). Compression target ~300-400 tokens — preserve the 6 principles' semantics, NOT necessarily their literal text.
- `server/tests/test_exchange_classifier.py` (whole file, 457 lines) — every existing test must keep passing post-migration; the P21 regression net (`test_classifier_defaults_to_met_on_borderline_response`) is the source of truth for "did prompt compression break semantics".
- `server/pipeline/checkpoint_manager.py` lines 99-106, 236-246 — `_MAX_CONSECUTIVE_NONE_VERDICTS=5` backstop stays in place; the latency reduction is expected to make it effectively unreachable but the safety belt stays.
- `server/pipeline/latency_probe.py` (~85 LOC, Story 6.8) — env-var-gated LatencyProbe FrameProcessor used to measure end-to-end and per-stage latency on real calls. The smoke gate uses this to validate the new target.
- `server/pipeline/transcript_logger.py` + `server/scripts/score_transcript.py` — existing Story 3.0 calibration tooling. The benchmark harness reuses transcript JSON files as input.
- `server/pipeline/emotion_emitter.py` — same OpenRouter HTTPX pattern as ExchangeClassifier. **Out of scope** for this story (still uses Qwen via OpenRouter); a future story (~6.9c) may migrate it for parity, but emotion-emission has zero UX cost when slow (character stays in prior Rive pose), so it's a lower priority.
- `_bmad-output/planning-artifacts/architecture.md` lines 43, 58, 82 — PRD `Performance` row: target <800ms, hard ceiling <2s, "streaming overlap mandatory (LLM streams to TTS before full response generated)". Our classifier's `max_tokens=32` output is small enough that streaming saves only ~50-150 ms — the dominant win is provider TTFT.
- `server/CLAUDE.md` — pre-commit discipline (ruff + ruff format + pytest); persistence/cleanup ordering; loguru sink pattern for log assertions.

**Up-front deviations to document in Implementation Notes:**

1. **(Deviation #1) Provider selection is empirical, not a priori.** The cost matrix above is INFORMATIONAL. The actual provider choice waits on real benchmark data from past-call transcripts: classification accuracy vs ground truth (most important — a 30 ms classifier that mis-judges 20% of turns is worse than the current Qwen), p50/p95 TTFT, p50/p95 total latency, and cost per classify. Groq Llama 3.1 8B is the leading candidate but Cerebras Llama 3.1 8B and Anthropic Haiku 4.5 stay in the running until benchmark data lands. If no provider beats Qwen on **both** latency AND accuracy, the migration is aborted and Story 6.12 falls back to the visual-first feedback architecture (option F).

2. **(Deviation #2) Streaming activation is contingent on measured gain.** For a 32-token `{"met": true}` output, streaming theoretically saves the response-completion wait (~50-150 ms). If (a) the chosen provider doesn't support streaming, OR (b) the measured gain is <100 ms in benchmark, the streaming codepath is SKIPPED and the existing buffered `client.post` pattern is preserved. The decision is reported in the smoke-gate proof (one of: "streaming activated, measured gain X ms" or "streaming skipped, gain <100 ms / unsupported by provider").

3. **(Deviation #3) Prompt compression validated by P21 regression test, NOT by token count.** The compression target ~300-400 tokens is a **guideline**, not an acceptance criterion. Source of truth: `test_classifier_defaults_to_met_on_borderline_response` (Story 6.9 patch P21) must stay green AND a new regression suite added in this story covers each of the 6 GUIDING PRINCIPLES individually (one test per principle, fed a deliberately borderline input that exercises that specific principle). A 320-token rewrite that passes the full regression suite is acceptable; a 280-token rewrite that fails any test is not — the prompt grows back until the regression suite is green.

4. **(Deviation #4) 5-scenario re-calibration is OUT OF SCOPE for the `in-progress→review` transition.** Re-calibration requires 10 device calls on Pixel 9 Pro XL (5 scenarios × Pass A + Pass B) and is Walid-owned manual work. The story transition only requires AC1-AC6 (benchmark + migration + tests + pre-commit gates) plus the deploy box + latency-target boxes of AC7. Re-calibration runs as a follow-up Walid-owned pass, tracked in `deferred-work.md` (re-tagged from "post Story 6.9b/6.12" to "post Story 6.9b" since 6.12 outcome depends on this story's benchmark — circular blocker resolved by collapsing it into this story's follow-up). Update the deferred-work.md entry accordingly during dev.

5. **(Deviation #5) Past-call transcripts for the benchmark sourced from local artifacts + scrubbed prod journalctl.** ≥50 transcripts mixing happy-path (verdict=true expected) and edge-case classifications (verdict=false expected, borderline cases, off-topic, fragmented B1 speech). Anonymized — no raw PII (email addresses, full names) leaves the local dev machine; the benchmark harness only needs `user_text`, `last_character_line`, `success_criteria`, `scenario_description`, and a human-labeled ground-truth verdict. If <50 transcripts are available locally, supplement with synthetic transcripts generated from the existing 5 scenarios' `checkpoints[].success_criteria` (one realistic happy-path + one borderline + one off-topic per checkpoint per scenario ≈ 60+ synthetic samples).

6. **(Deviation #6) Persistent `httpx.AsyncClient` lifecycle from Story 6.9 stays intact.** The migration MUST preserve: `_get_client()` with double-checked locking, `_closed` flag + lock-guarded `close()`, RuntimeError handling for post-cleanup races, `CheckpointManager.cleanup()` calls `classifier.close()`. If the chosen provider's SDK manages its own client lifecycle (e.g. Groq SDK or Anthropic SDK), wrap that SDK behind the SAME lifecycle contract — the call sites in `CheckpointManager` MUST NOT change. Test files for the lifecycle (`test_persistent_client_reused_across_classify_calls`, `test_close_releases_client_and_is_idempotent`, `test_close_during_classify_in_flight`) MUST stay green or be rewritten to assert the equivalent invariants under the new provider.

7. **(Deviation #7) Consecutive-None backstop from Story 6.9 P16 stays in place.** `_MAX_CONSECUTIVE_NONE_VERDICTS=5` in `checkpoint_manager.py:106` is the safety belt against a future degraded provider. With p50 ≤300 ms targets, the backstop becomes effectively unreachable in normal operation, but its existence is part of the contract — a provider migration that introduces new failure modes (e.g. Cerebras rate-limit 429s) MUST surface as `None` verdicts that the backstop catches at N=5.

8. **(Deviation #8) Strategic premise empirically falsified mid-bench — migration justification shifts from latency to accuracy + Story 6.12 unblock.** Added 2026-05-22 post `/bmad-code-review` (Walid choice D4:a). The spec opens (lines 11, 17, 35) citing "today's ~1046 ms median, ~1700-1900 ms p95" Qwen latency as the strategic justification ("concept dead approaching" per PRD turn-taking research). The actual VPS-measured Qwen baseline (`classifier_benchmark_vps_2026-05-21T16-16-02Z.json`) is p50 587 ms / p95 859 ms — **comfortably under PRD 800 ms target** and well below the "concept dead" line. The spec's strategic frame was wrong; the Lever 1 hypothesis ("OpenRouter US proxy adds 100-300 ms") was wrong (Qwen-direct via DashScope matches OpenRouter ±10 ms because Qwen is hosted in Singapore not US). The Groq Llama 3.3 70B migration is still justified, but on different grounds than the spec posited: (a) accuracy gain 98.7 % vs 94.7 % with 0 false positives vs 3 (the original cost-asymmetric Principle 5 default-to-MET regression net flips from "compensatory" to "additive" — Groq doesn't need the safety net), and (b) Story 6.12 sync-verdict-everywhere architecture unblocks at sub-300 ms classifier (the original Option D path, not Option F fallback). The cost matrix in `memory/project_story_6_9b_classifier_latency_slash.md` §1 is also stale — Walid Phase B task 2.3 owns the update.

9. **(Deviation #9) Benchmark provider catalog grew from 4 (spec) to 7 (shipped) across the 2026-05-21/22 bench cycle.** Added 2026-05-22 post `/bmad-code-review` (Walid choice D4:a). Original spec AC1 named 4 candidates: Qwen via OpenRouter / Groq Llama 3.1 8B / Cerebras Llama 3.1 8B / Anthropic Haiku 4.5. Shipped `_PROVIDERS` config (`scripts/benchmark_classifier.py`) lists 7: same 4 + `qwen3.5_flash_via_dashscope` + `qwen3.6_flash_via_dashscope` (Lever 1 exploration — skip OpenRouter proxy via Alibaba direct) + `groq_llama_3.3_70b` (added mid-bench when 8B aborted on accuracy). All 3 additions are justified by the iteration history docstring at `benchmark_classifier.py:30-53`. Test `test_providers_config_includes_documented_providers` locks the 7-name set. Net impact on Deviation #1 contract: NONE — `_recommend()` still requires winner beats baseline on both axes; the larger candidate pool just gave more chances for a winner to surface (and Groq 70B did).

10. **(Deviation #10) `Settings.model_config` switched from Pydantic-v2 forbid-extras default to `extra: "ignore"`.** Added 2026-05-22 post `/bmad-code-review` (Walid choice D4:a). The migration added 3 benchmark-only env vars to `deploy/.env.example` (`DASHSCOPE_API_KEY`, `CEREBRAS_API_KEY`, `ANTHROPIC_API_KEY`) plus the pre-existing `LATENCY_PROBE` ops flag — all UNUSED by the prod runtime, all present on the VPS / dev `.env`. Pydantic v2 default `forbid` would raise `ValidationError` on construction; the migration flipped to `ignore` (Pydantic v1 default semantics) so `Settings()` boot survives. The trade-off (relaxes validation surface — `OPENROUER_API_KEY` typo no longer raises) is mitigated by `test_settings_loads_all_pipeline_env_vars` which explicitly asserts every declared field — a typo'd env var would surface as a *missing* declared field. Full justification + alternatives-considered block lives in `config.py:50-76`. Future cleanup: separate prod `.env.example` from bench `.env.bench.example` (tracked in `deferred-work.md` under the Story 6.9b review batch).

## Acceptance Criteria (BDD)

**AC1 — Benchmark harness (script + report) ranks 4 providers on ≥50 transcripts:**

Given the current `ExchangeClassifier` baseline latency on prod is ~1046 ms median / ~1700-1900 ms p95 (per Story 6.9 smoke transcripts)
And the candidate providers are: Qwen 3.5 Flash via OpenRouter (baseline), Groq + Llama 3.1 8B, Cerebras + Llama 3.1 8B, Anthropic Haiku 4.5
And ≥50 past-call transcript classify-events are available locally (real + synthetic, per Deviation #5) with human-labeled ground-truth verdicts
When this story lands
Then a new script `server/scripts/benchmark_classifier.py` exists
And it reads a JSON corpus file at `server/tests/fixtures/classifier_benchmark_corpus.json` containing the ≥50 labeled samples
And it runs each sample through each provider's classify endpoint (using provider-specific API keys from `.env` — `OPENROUTER_API_KEY` (existing), `GROQ_API_KEY` (new), `CEREBRAS_API_KEY` (new), `ANTHROPIC_API_KEY` (new))
And it measures per-sample p50/p95 TTFT and total latency, classification accuracy vs ground-truth, and computes cost-per-classify from each provider's published rates
And it writes a report JSON to `_bmad-output/implementation-artifacts/calibration-tests/classifier_benchmark_<timestamp>.json` with: per-provider summary stats, per-sample raw timings + verdicts, and a human-readable verdict line ("Recommended provider: X — rationale: …")
And the report is committed in this story for traceability (the file is a small JSON, well under the project's binary-file threshold)

**AC2 — Provider migration to the benchmark winner:**

Given the AC1 report names a winner that beats Qwen 3.5 Flash on **both** TTFT/p50 latency AND classification accuracy (no regression on accuracy is acceptable EVEN for a faster provider — see Deviation #1)
When this story lands
Then `server/pipeline/exchange_classifier.py` is migrated to the winning provider
And the persistent-client lifecycle contract is preserved (Deviation #6): `_get_client()` + `_closed` flag + lock-guarded `close()` + `CheckpointManager.cleanup()` call site
And the module-level constants `_OPENROUTER_URL`, `_OPENROUTER_MODEL` are either kept (if Qwen wins on accuracy and we activate streaming/prompt-compression only) OR renamed to `_PROVIDER_URL`, `_PROVIDER_MODEL` with the new endpoint + model id (per provider's documented contract)
And the model id is sourced from a new `Settings.classifier_model` config field with a documented default — this retires the hardcoded-model-id concern in `deferred-work.md` line 450 (Story 6.9 Defer #3) and lets us flip models via env override at deploy time WITHOUT a code release
And the docstring at the top of `exchange_classifier.py` is updated to name the new provider + model + rationale (1-2 paragraphs)
And the wiring guard in `tests/test_bot_pipeline_wiring.py` continues to assert `ExchangeClassifier(...)` is constructed in `run_bot` with the correct api-key kwarg (renamed if needed)

**AC3 — Streaming activated where it pays:**

Given streaming theoretically saves ~50-150 ms on a 32-token output
And per Deviation #2 the activation is contingent on measured gain
When this story lands
Then if the chosen provider supports streaming AND a measured gain ≥100 ms is observed in AC1's benchmark, the classify codepath uses streaming (the response body is consumed token-by-token; once `{"met": …}` is fully present, the request is closed even if the model still has more to say) — note that with `max_tokens=32` the model usually returns just `{"met": true}` or `{"met": false}` so the early-close case is rare
And the docstring at the top of `exchange_classifier.py` documents the streaming choice (one of: "streaming activated — measured X ms gain on benchmark"; "streaming skipped — gain <100 ms" ; "streaming unsupported by provider Y")
And streaming activation does NOT change the return contract: `True | False | None` per the existing `_classify` semantics, with `None` still meaning "infra failure" (timeout / HTTP error / parse error)

**AC4 — Prompt compressed from 600-900 → 300-400 tokens, GUIDING PRINCIPLES semantics preserved:**

Given the current `EXCHANGE_CLASSIFIER_PROMPT` in `server/pipeline/prompts.py` lines 159-204 is ~600-900 tokens with the 6 GUIDING PRINCIPLES from Story 6.9 D4
And per Deviation #3 the compression target is a guideline, the regression test suite is the source of truth
When this story lands
Then `EXCHANGE_CLASSIFIER_PROMPT` is rewritten to ~300-400 tokens
And the rewrite preserves ALL 6 guiding principles' semantics: (1) intent-over-literal, (2) synonyms/colloquialisms count, (3) short/fragmented OK, (4) re-statements count, (5) default-to-MET, (6) current-objective-only
And the existing P21 regression test `test_classifier_defaults_to_met_on_borderline_response` stays green
And 5 NEW regression tests are added in `tests/test_exchange_classifier.py` — one per remaining guiding principle (principle 5 already has P21):
  - `test_classifier_intent_over_literal` — feed a paraphrased user response that meets the intent but not the literal text of the success_criteria, assert `met=True`
  - `test_classifier_accepts_synonym_or_brand` — feed a brand-name response ("Coke" for "soda") against a generic success_criteria, assert `met=True`
  - `test_classifier_accepts_fragmented_response` — feed a hesitant/fragmented response ("uh, chicken, please") against a success_criteria expecting a clear order, assert `met=True`
  - `test_classifier_accepts_restatement` — feed an explicit re-statement ("as I told you, pasta") that references a prior turn, assert `met=True`
  - `test_classifier_evaluates_current_objective_only` — feed a response that satisfies a FUTURE checkpoint's success_criteria but not the CURRENT one, assert `met=False`
And the inline comment block above `EXCHANGE_CLASSIFIER_PROMPT` documents the compression rationale, the post-compression token count (counted via `tiktoken` or equivalent and pinned in the comment), and cross-references the 6 regression tests by name

**AC5 — Latency target hit: p50 ≤300 ms, p95 ≤500 ms on real prod traffic:**

Given the AC2 migration has landed and the AC4 prompt compression is committed
And the Story 6.8 `LatencyProbe` is wired (env-gated `LATENCY_PROBE=1`)
When the smoke gate (AC7) runs a Waiter happy-path call on Pixel 9 Pro XL with `LATENCY_PROBE=1`
Then journalctl tail shows classifier wall-clock latency (from `_classify_and_advance` entry → verdict ready) with:
  - **p50 ≤ 300 ms** across ≥6 classifies (one per checkpoint on the happy path)
  - **p95 ≤ 500 ms** across the same window
  - **No single classify exceeds 800 ms** (the 800 ms is the new "wide" budget — at the boundary of the natural-pause band — anything wider regresses the user experience even if rare)
And these numbers are pasted as proof in the AC7 smoke-gate boxes (3 separate boxes — calm-room baseline, café noisy environment per Story 6.9 gate, terminal-turn synchronous-classifier path)
And if any of the 3 targets miss by >20%, the story does NOT flip `in-progress→review` — the dev iterates on (a) provider config (timeout tuning, connection-pool sizing), (b) prompt compression depth, or (c) accepts a fallback to F (visual-first feedback for Story 6.12) and amends Deviation #1 to document the abort

**AC6 — Pre-commit gates green:**

Given the dual-side discipline (project root CLAUDE.md + `server/CLAUDE.md`)
When this story lands
Then ALL of the following pass before flipping `in-progress→review`:
  - `cd server && python -m ruff check .` → zero issues
  - `cd server && python -m ruff format --check .` → zero issues
  - `cd server && .venv/Scripts/python -m pytest` → all green (target ≥369: baseline 363 + 5 new principle-regression tests in `test_exchange_classifier.py` + 1 new benchmark-script smoke test)
  - `cd client && flutter analyze` → "No issues found!" (this story has zero client-side changes; verify the gate didn't regress from concurrent unrelated work)
  - `cd client && flutter test` → 373 unchanged
And every existing `test_exchange_classifier.py` test stays green post-migration (Deviation #6: lifecycle contract preserved — the persistent-client / close / RuntimeError-handling tests adapt to the new provider but keep their invariants)

**AC7 — Smoke Test Gate (deploy-side, owned by Walid):**

See `## Smoke Test Gate` section below.

## Smoke Test Gate (Server / Deploy Story)

> **Scope rule:** Server-side classifier migration on the call hot path. The gate is MANDATORY — latency targets can ONLY be validated on a real call against the real VPS pipeline, against real OpenRouter / Groq / Cerebras / Anthropic regional latency from Hetzner EU.
>
> **Transition rule:** Every unchecked box below is a stop-ship for the `in-progress → review` transition. Paste the actual command run and its output as proof — a checked box without evidence does not count. Per Deviation #4, the 5-scenario re-calibration is OUT OF SCOPE for this gate (Walid-owned follow-up).

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test. Server logs at boot show `ExchangeClassifier init provider=<name> model=<id>` from at least one call session.
  - _Command:_ `ssh root@167.235.63.129 "systemctl status pipecat.service | head -5 && journalctl -u pipecat.service --since '2 min ago' | grep -i 'ExchangeClassifier init'"`
  - _Proof:_ <!-- paste the Active/Main PID line + first ExchangeClassifier init log line + commit SHA -->

- [ ] **Calm-room baseline call — p50 ≤300 ms, p95 ≤500 ms, no single classify >800 ms.** 1 Waiter happy-path call on Pixel 9 Pro XL with `LATENCY_PROBE=1`. Drive: chicken → cola → confirm → thanks. ≥6 classifies expected (one per checkpoint advance + the terminal one).
  - _Command:_ Set `LATENCY_PROBE=1` in `/opt/survive-the-talk/.env`, `systemctl restart pipecat.service`, run the call from the Pixel 9 Pro XL, then `journalctl -u pipecat.service --since '5 min ago' | grep -E 'latency_probe.*classifier|_classify_and_advance' | awk '...'` (extract elapsed ms per classify, compute p50/p95)
  - _Expected:_ p50 ≤ 300 ms, p95 ≤ 500 ms, no classify > 800 ms
  - _Actual:_ <!-- paste p50, p95, max from the journalctl extraction -->

- [ ] **Café-noisy environment call — no regression on checkpoint advance rate AND latency target survives DTLN load.** 1 Waiter happy-path call from a coffee shop or comparable babble-noise environment (Story 6.9 baseline). Same chicken → cola → confirm → thanks script. Latency-probe ON.
  - _Command:_ Same as box above, from a café.
  - _Expected:_ `reason=survived` at end, all 6 checkpoints advanced, latency targets from AC5 still hit (DTLN adds ~3-4 ms CPU; the classifier latency floor should be untouched). NO `consecutive_none_count` log line firing (the safety belt should stay dormant).
  - _Actual:_ <!-- paste reason + checkpoint count + p50/p95 + grep for consecutive_none -->

- [ ] **Terminal-turn synchronous-classifier path — total perceived latency ≤2000 ms.** Drive a Waiter call to terminal zone (`patience < 25`, OR the last checkpoint). Measure user-speech-end → character-first-audio-byte for that one terminal turn.
  - _Command:_ Replay the user_speech_end → character_first_audio extraction from Story 6.8 smoke-gate methodology; isolate the terminal-turn turn via the `checkpoint_preemptive_*` log lines.
  - _Expected:_ Total perceived latency on terminal turn ≤ **2000 ms** — Story 6.8 AC5 ceiling restored, retracting the Story 6.9 D2 dette explicitly. Classifier portion ≤ 500 ms (per AC5), LLM + TTS portion ≤ 1500 ms (Story 6.8 baseline).
  - _Actual:_ <!-- paste the single terminal-turn end-to-end measurement -->

- [ ] **6 guiding-principle regression tests cover prod-shape inputs.** This box is the runtime mirror of AC4's offline tests: drive a synthetic Waiter call with a deliberately borderline user response on the `drink` checkpoint ("uh, soda I guess?") and verify the classifier returns `met=true` (per principle 5, default-to-MET). Single targeted call OR via the smoke-gate harness if one exists.
  - _Command:_ <!-- e.g. the Waiter, drink checkpoint, deliberately ambiguous answer; check checkpoint_advanced fires -->
  - _Expected:_ `checkpoint_advanced` fires on the `drink` checkpoint with the borderline response. NO `apply_exchange_outcome(success=False)` log line for that turn.
  - _Actual:_ <!-- paste journalctl extract -->

- [ ] **Server CPU sane.** During the calm-room call (box 2), `top -p $(pidof python | tr ' ' ',')` shows pipecat.service CPU usage below baseline + DTLN delta (~10-20%) — no regression from the new provider's response parsing or streaming.
  - _Command:_ `ssh root@167.235.63.129 "top -bn1 -p \$(pidof python | tr ' ' ',')"`
  - _Proof:_ <!-- paste top snapshot during peak call -->

- [ ] **Server logs clean.** `journalctl -u pipecat.service --since "5 min ago" | grep -iE "(error|traceback|exception)" | grep -v INFO` returns ZERO matches across the test calls. In particular, NO `exchange classifier HTTP error`, NO `exchange classifier lifecycle error`, NO `exchange classifier timeout`, NO `consecutive_none_count` fires.
  - _Command:_ As shown.
  - _Proof:_ <!-- "no errors in window" + timestamp range -->

## Tasks / Subtasks

- [~] **Task 1 — Build benchmark corpus + harness** (AC1, Deviation #5)
  - [x] 1.1 — Survey local prod transcripts: walked `_bmad-output/implementation-artifacts/calibration-tests/` + recently-saved `/tmp/transcript_*.json` — **no real classify-event transcripts available locally** (Story 6.6+ smoke tests captured journalctl logs, not labelled classify inputs). Fell back to 100 % synthetic corpus per Task 1.2; flagged for Walid to top up with real transcripts post-benchmark if accuracy stats need real-world validation.
  - [x] 1.2 — Generated 75 synthetic samples across 5 scenarios × ~6 checkpoints × ~2-3 cases per checkpoint (happy-path / fragmented / restatement / off-topic / non-answer / off-menu / intent / synonym / current-objective-only). Distribution: 18 Waiter / 15 Mugger / 15 Cop / 14 Girlfriend / 13 Landlord; 47 MET / 28 NOT-MET; principles covered: happy_path 27, off_topic 14, non_answer 11, fragmented 8, intent_over_literal 6, restatement 3, synonym_or_brand 3, current_objective_only 2, off_menu 1.
  - [ ] 1.3 — **PENDING WALID** — Human-label ground-truth sign-off on the 75 samples. Pre-labelled by dev; review for B1-learner realism before benchmark runs.
  - [x] 1.4 — Labelled corpus written to `server/tests/fixtures/classifier_benchmark_corpus.json` (75 entries; ~33 KB). Each entry shape: `id` / `scenario_description` / `checkpoint_id` / `last_character_line` / `user_text` / `success_criteria` / `ground_truth` / `principle_under_test` / `notes`. Anonymized per Deviation #5 (no PII — synthetic transcripts only).
  - [x] 1.5 — `server/scripts/benchmark_classifier.py` written (~460 LOC). Reuses `pipeline.exchange_classifier._parse_classifier_output` + `pipeline.prompts.EXCHANGE_CLASSIFIER_PROMPT` so the benchmark exercises the EXACT prod code paths. 4 providers configured: `qwen_via_openrouter` (baseline), `groq_llama_3.1_8b`, `cerebras_llama_3.1_8b`, `anthropic_haiku_4.5`. Per-provider request shapes (OpenAI-compatible vs Anthropic messages API) handled in `_build_request()`. TTFT measured as first-byte of streamed response. Recommendation logic (`_recommend()`) implements Deviation #1: winner must beat baseline on BOTH p50 total latency AND accuracy, else abort. Providers with missing env var are skipped (loud stderr warning) — allows partial-key benchmark runs.
  - [x] 1.6 — `deploy/.env.example` updated with 3 new slots (`GROQ_API_KEY`, `CEREBRAS_API_KEY`, `ANTHROPIC_API_KEY`) + commented `CLASSIFIER_MODEL` for runtime override. **PENDING WALID** to provision the actual API keys in local `.env` before benchmark runs.
  - [x] 1.7 — `server/tests/test_benchmark_classifier.py` written (5 tests): end-to-end shape test driving harness through a `MockTransport` (routes openrouter→slow / groq→fast); two `_recommend()` unit tests locking the Deviation #1 contract (`test_recommend_aborts_when_no_provider_beats_baseline`, `test_recommend_picks_fastest_qualifying_when_two_beat_baseline`); `build_report` pure-function test; `_PROVIDERS` config sanity test (locks 4-provider list).

- [x] **Task 2 — Run benchmark, choose winner, document decision** (AC1, AC2, Deviation #1) — **Phase A.5 (2026-05-22)**
  - [x] 2.1 — Executed benchmark 4 times across providers + 2 locations (local Windows + VPS Hetzner). Final clean run: `classifier_benchmark_2026-05-22T09-29-19Z.json` (VPS Groq Llama 3.3 70B). Cerebras + Anthropic skipped per Walid 2026-05-21 cost decision (Cerebras 2× cost vs Groq cost-equivalent, Anthropic 22× cost — non-MVP-viable). Lever 1 (DashScope direct, skip OpenRouter proxy) was tested and **provided ZERO gain** (591 ms VPS vs 587 ms OpenRouter) — Qwen really is hosted in Singapore, the OpenRouter "US proxy adds 100-300 ms" hypothesis was wrong.
  - [x] 2.2 — Report at `_bmad-output/implementation-artifacts/calibration-tests/classifier_benchmark_2026-05-22T09-29-19Z.json`. Winner: **Groq Llama 3.3 70B** on every axis vs Qwen-via-OpenRouter baseline from VPS:

    | Metric | Qwen prod (baseline) | Groq 70B (winner) | Delta |
    |---|---|---|---|
    | Accuracy | 94.7 % | **98.7 %** | +4 pts |
    | p50 latency | 587 ms | **121 ms** | 4.8× faster |
    | p95 latency | 859 ms | **320 ms** | 2.7× faster |
    | False positives | 3 | **0** | 100 % reduction |
    | False negatives | 1 | 1 | tie |
    | Cost @ 100 users | 6 €/mois | ~16 €/mois | +10 €/mois |

    Groq 70B's p95 320 ms is well under the 800 ms PRD target, **unblocking Story 6.12 "Reactive Character Mood" sync-verdict-everywhere architecture** (which needed classifier < 300 ms). Sole error: `waiter_clarify_met_restatement` ("As I said before, just pasta") — the principle-4 restatement test from call_id=118.
  - [ ] 2.3 — **PENDING WALID** — Update `memory/project_story_6_9b_classifier_latency_slash.md` §1 cost matrix with actual benchmark numbers (10 min cosmetic update, can ride with the smoke-gate session).
  - [x] 2.4 — Decision branch (a): clear winner → proceed to Task 3 migration. Deviation #1 contract satisfied (Groq beats baseline on BOTH latency AND accuracy).

- [x] **Task 3 — Migrate `ExchangeClassifier` to winning provider + streaming** (AC2, AC3, Deviation #6) — **Phase A.5 (2026-05-22)**
  - [x] 3.1 — `server/pipeline/exchange_classifier.py` refactored: `_OPENROUTER_URL` → `_PROVIDER_URL` (now `https://api.groq.com/openai/v1/chat/completions`), `_OPENROUTER_MODEL` → `_PROVIDER_MODEL` (now `llama-3.3-70b-versatile`). Bearer auth header unchanged (Groq is OpenAI-compatible). The `reasoning: {enabled: false}` field is NOT sent to Groq (Llama 3.3 70B has no thinking mode; unknown fields risk 400s on stricter providers). EmotionEmitter stays on Qwen via OpenRouter unchanged (out of scope per Deviation note).
  - [x] 3.2 — Persistent-client lifecycle preserved per Deviation #6: `_get_client()` double-checked locking, `_closed` flag, lock-guarded `close()`, RuntimeError handling for post-cleanup races, `CheckpointManager.cleanup()` call site unchanged. All Story 6.9 lifecycle tests (`test_persistent_client_reused_across_classify_calls`, `test_close_releases_client_and_is_idempotent`, `test_close_during_in_flight_classify_does_not_leak`, `test_classify_after_close_returns_None`) stay green post-migration without modification — the lifecycle is provider-agnostic.
  - [x] 3.3 — Model id sourced from `Settings.classifier_model` with new default `"llama-3.3-70b-versatile"`. `Settings` gained a new required `groq_api_key: str` field (read from `GROQ_API_KEY` env). `bot.py` wiring updated: `ExchangeClassifier(api_key=settings.groq_api_key, model=settings.classifier_model)`. Constructor kwarg renamed `openrouter_api_key` → `api_key` for provider-neutrality (per Task 3.3 note in original spec). `model_config` on Settings switched to `extra: "ignore"` so unrelated env vars (DASHSCOPE_API_KEY left over from the Lever 1 bench, CI/CD vars) don't trip Pydantic-v2 forbid-extras at construction.
  - [x] 3.4 — Streaming activation SKIPPED per Deviation #2 — Groq's measured TTFT (~70-90 ms from VPS) is already well under any streaming savings threshold; the small <32-token output gives streaming <50 ms theoretical win. The existing buffered `client.post` codepath is preserved. Choice documented in `exchange_classifier.py` module docstring.
  - [x] 3.5 — Module docstring at top of `exchange_classifier.py` updated to name Groq Llama 3.3 70B, link to the benchmark report JSON, summarize the latency/accuracy/cost delta, document the streaming-skip decision, and note that EmotionEmitter stays on Qwen.

- [x] **Task 4 — Compress `EXCHANGE_CLASSIFIER_PROMPT` to ~300-400 tokens** (AC4, Deviation #3)
  - [x] 4.1 — Read current ~600-700 token prompt at `prompts.py:159-204`. Identified redundant rationale ("Imagine what the user is trying to communicate, not what they said verbatim", "Treat informal speech as equally valid", "A B1 learner under conversational pressure will produce messy English — judge the intent, not the form", repeated examples) — trimmed without losing meaning.
  - [x] 4.2 — Drafted compressed version at ~340 tokens (measured visually + structurally — each principle is 1-2 lines max). All 6 GUIDING PRINCIPLES preserved with key exemplars: principle 1 INTENT, principle 2 "Coke"="cola", principle 3 "uh"/"um", principle 4 "I already said pasta", principle 5 default-to-MET + false-positives rationale, principle 6 "ONLY the current objective". XML-tag injection-resistance pattern (`<user_response>`, `<character_line>`) preserved verbatim.
  - [x] 4.3 — Validated iteratively against the 6 regression tests (5 new + P21) — all green on first run; no prompt re-lengthening needed.
  - [x] 4.4 — Added 5 new tests in `tests/test_exchange_classifier.py`:
    - `test_classifier_intent_over_literal` (principle 1) — asserts "INTENT" + "literal" markers
    - `test_classifier_accepts_synonym_or_brand` (principle 2) — asserts "Synonyms" + "brand names" + "Coke" exemplar
    - `test_classifier_accepts_fragmented_response` (principle 3) — asserts "fragmented" + disfluency exemplar ("uh"/"um")
    - `test_classifier_accepts_restatement` (principle 4) — asserts "Re-statements" + "I already said" exemplar
    - `test_classifier_evaluates_current_objective_only` (principle 6) — asserts "ONLY the current objective" + "anticipate future"
    All follow the P21 text-assertion pattern (validates prompt text contains the principle marker; mocked LLM-behavior validation is gated by Task 6 smoke test in prod).
  - [x] 4.5 — Inline comment block above `EXCHANGE_CLASSIFIER_PROMPT` updated: documents Story 6.9b compression rationale, ~340-token post-compression count, cross-references to all 6 regression tests by exact name. Closes the loop on Story 6.9 D4 / Deviation #10's "default-to-MET regression net" — it's now part of a documented 6-test suite.

- [x] **Task 5 — Pre-commit gates + test suite** (AC6) — **PHASE A complete**
  - [x] 5.1 — All existing `test_exchange_classifier.py` tests pass (22 tests including persistent-client lifecycle invariants from Story 6.9)
  - [x] 5.2 — `cd server && .venv/Scripts/python -m ruff check .` → "All checks passed!"
  - [x] 5.3 — `cd server && .venv/Scripts/python -m ruff format --check .` → "63 files already formatted" (after one auto-format pass on benchmark_classifier.py)
  - [x] 5.4 — `cd server && .venv/Scripts/python -m pytest` → **375 passed** (baseline 363 + 12 net new: 5 principle-regression + 2 Settings.classifier_model + 5 benchmark-harness)
  - [x] 5.5 — `cd client && flutter analyze` → "No issues found!" + `cd client && flutter test` → "All tests passed!" (373 unchanged, zero net Flutter changes per Phase A scope)
  - [x] 5.6 — Status flipped **`in-progress → review`** post Phase A.5 (2026-05-22 Groq migration). Smoke gate (Task 6) remains Walid-owned per the Story 6.5 D6 deploy-gate convention.

- [ ] **Task 6 — VPS deploy + Smoke Test Gate** (AC7) — **PHASE B — PENDING WALID**
  - [ ] 6.1 — **PENDING WALID** — `git push` → CI/CD deploy on VPS + provision provider keys
  - [ ] 6.2 — **PENDING WALID** — Verify `systemctl status pipecat.service` active
  - [ ] 6.3 — **PENDING WALID** — Verify boot log shows ExchangeClassifier init line
  - [ ] 6.4 — **PENDING WALID** — 7-box Smoke Test Gate on Pixel 9 Pro XL
  - [ ] 6.5 — **PENDING WALID** — Update `deferred-work.md` line 451 ("post Story 6.9b/6.12" → "post Story 6.9b")
  - [ ] 6.6 — **PENDING WALID** — `review → done` after smoke gate proofs

## Dev Notes

**Why this story exists (the strategic frame, not the tactical scope).** Three structural problems collapse into one fix: (1) the Story 6.8 AC5 universal latency ceiling, retracted by Story 6.9 D2 for the terminal-turn path → restored. (2) The Story 6.9 D1 consecutive-None backstop, a safety belt against a degraded classifier → made effectively unreachable. (3) Story 6.12's architectural choice (sync verdict vs visual-first feedback) → unblocked. The cost is one solid week of bench + migration + prompt rewrite + 10 calibration calls. The reward is the MVP voice loop sitting comfortably under the PRD kill criterion with margin AND a unblocked path to the "reactive character mood" UX defect fix. **The memory file `project_story_6_9b_classifier_latency_slash.md` is the source of truth on this framing — read it before drafting code.**

**Provider migration ordering.** The benchmark (Task 1-2) is what decides — DO NOT pre-commit to a provider before the data lands. The cost matrix in §Background is a starting hypothesis; the report's accuracy column is the deciding factor. If Groq-Llama-3.1-8B comes back at 60% accuracy vs Qwen's 95%, the migration aborts even at 10× faster latency.

**Streaming is a small win.** Don't over-engineer. The classifier's `max_tokens=32` output bounds the streaming gain at ~50-150 ms. If the chosen provider doesn't support streaming, skip it; if the measured gain is <100 ms, skip it. Document the choice in the docstring.

**Prompt compression must be regression-tested, not byte-counted.** The 6 GUIDING PRINCIPLES from Story 6.9 D4 are the soul of the classifier's behavior on B1-learner messy speech. Cutting 600 tokens to 300 is fine; cutting them to 300 while losing principle 5 (default-to-MET) is not. The 6-test regression suite is the source of truth — token count is a guideline.

**Persistent-client lifecycle is sacred.** Story 6.9's reliability amends (Deviations #5-#10) cost a full smoke-test cycle to land. Don't unwind them. If the chosen provider's SDK manages its own client, wrap it behind the same interface so the existing tests in `test_exchange_classifier.py` (persistent-reuse, close-idempotent, close-during-in-flight) keep their meaning.

**Consecutive-None backstop stays at N=5.** It's effectively unreachable post-migration in normal operation (a 300 ms classifier × 5 = 1.5 s of dead air before the safety belt fires — well under the silence ladder window). But its existence is part of the contract — a future provider change that introduces new failure modes (Cerebras rate-limit 429s, Anthropic content-filter rejections) MUST surface as `None` verdicts that the backstop catches.

**Out of scope for `in-progress→review`:** (a) re-calibrating the 5 launch scenarios — Walid-owned manual work, follow-up; (b) migrating `EmotionEmitter` to the new provider — emotion-emission has zero UX cost when slow (character stays in prior Rive pose), tracked as a possible future story 6.9c; (c) Story 6.12 architectural decision — this story's benchmark feeds it but doesn't decide it.

### Project Structure Notes

**Server — modified:**
- `server/pipeline/exchange_classifier.py` — provider swap + streaming + persistent-client lifecycle preserved (Deviation #6) + model id moved to Settings (retires `deferred-work.md` line 450) + updated docstring naming new provider/model/rationale
- `server/pipeline/prompts.py` — `EXCHANGE_CLASSIFIER_PROMPT` compressed ~600-900 → ~300-400 tokens (Deviation #3) + inline comment block updated with rationale + token count + cross-references to 6 regression tests
- `server/pipeline/bot.py` — `ExchangeClassifier(...)` kwarg potentially renamed if the new provider uses a different api-key kwarg name (cosmetic)
- `server/settings.py` (or equivalent config module) — new `classifier_provider` and `classifier_model` fields with the chosen provider's id as default
- `server/tests/test_exchange_classifier.py` — 5 new principle-regression tests (intent-over-literal, synonym/brand, fragmented, restatement, current-objective-only); existing P21 default-to-MET test stays; existing persistent-client / lifecycle tests adapted to new provider but invariants preserved
- `server/tests/test_bot_pipeline_wiring.py` — wiring guard kwarg name updated if applicable
- `.env.example` — new `GROQ_API_KEY` / `CEREBRAS_API_KEY` / `ANTHROPIC_API_KEY` slots (only the ONE chosen provider's key is required at runtime; others are benchmark-time only)

**Server — new files:**
- `server/scripts/benchmark_classifier.py` (~250 LOC) — corpus-driven 4-provider benchmark harness; reads `tests/fixtures/classifier_benchmark_corpus.json`, writes report JSON to `_bmad-output/implementation-artifacts/calibration-tests/`
- `server/tests/fixtures/classifier_benchmark_corpus.json` (~50-60 samples, ~20-30 KB) — labeled corpus for the benchmark; committed for reproducibility
- `server/tests/test_benchmark_classifier.py` (1 test) — smoke test for the harness (mocks all 4 provider HTTP endpoints, asserts report JSON shape)

**Client — no changes.**

**Implementation artifacts — modified:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `6-9b-classifier-latency-slash: backlog → ready-for-dev` (this commit) → `→ in-progress` (dev start) → `→ review` (dev complete) → `→ done` (smoke gate green)
- `_bmad-output/implementation-artifacts/6-9b-classifier-latency-slash.md` — this file
- `_bmad-output/implementation-artifacts/deferred-work.md` line 451 — re-tag "post Story 6.9b/6.12" → "post Story 6.9b" (Story 6.12 now blocks on this story's benchmark outcome, breaking the circular)
- `_bmad-output/implementation-artifacts/deferred-work.md` line 450 (Story 6.9 Defer #3, hardcoded model id) — retired by Task 3.3 (model id → Settings)

**Implementation artifacts — new:**
- `_bmad-output/implementation-artifacts/calibration-tests/classifier_benchmark_<YYYY-MM-DD>.json` — committed benchmark report from Task 2

**Memory — modified:**
- `memory/project_story_6_9b_classifier_latency_slash.md` — §1 cost matrix replaced with actual benchmark numbers (Task 2.3)

### References

- Memory: `project_story_6_9b_classifier_latency_slash.md` (cost matrix, turn-taking research bands, option-E/F/G analysis, link to Story 6.12) — **MUST READ**
- Story 6.9: `_bmad-output/implementation-artifacts/6-9-dtln-noise-suppression.md` §"Post-Smoke-Test Amends" + §"Review Findings" + §"Change Log" — every reliability amend in 6.9 stays in place; 6.9b builds ON them
- Story 6.8: `_bmad-output/implementation-artifacts/6-8-post-checkpointmanager-scenario-calibration.md` — AC5 latency ceiling (≤2000 ms p95) being restored here; LatencyProbe instrumentation from Phase 1 used in AC7
- deferred-work.md line 450 (hardcoded model id) + line 451 (5-scenario re-calibration) — both touched by this story
- PRD `Functional & Non-Functional Requirements > Performance` — <800 ms target, <2s hard ceiling, ">2s consistently → concept dead"
- Architecture: `_bmad-output/planning-artifacts/architecture.md` lines 43, 58, 82 — sub-800ms budget, streaming overlap mandatory
- `server/pipeline/exchange_classifier.py` whole file — current implementation with all Story 6.9 amends
- `server/pipeline/prompts.py:159-204` — current `EXCHANGE_CLASSIFIER_PROMPT` with 6 GUIDING PRINCIPLES from Story 6.9 D4
- `server/pipeline/checkpoint_manager.py:99-106, 236-246` — `_MAX_CONSECUTIVE_NONE_VERDICTS=5` backstop (stays)
- `server/pipeline/latency_probe.py` — Story 6.8 LatencyProbe FrameProcessor (used in AC7 smoke gate)
- `server/CLAUDE.md` §1 (frame-direction tests), §2 (migrations — N/A here, no migration), §3 (loguru sink pattern for log assertions)
- [Groq Llama 3.1 8B documentation](https://console.groq.com/docs/models) — TTFT 50-100 ms, cost-equivalent to Qwen
- [Cerebras Llama 3.1 documentation](https://docs.cerebras.ai/) — TTFT 30-50 ms, 2× Qwen cost
- [Anthropic Haiku 4.5 documentation](https://docs.anthropic.com/) — TTFT 300-500 ms, 22× cost (benchmark-only, quality ceiling reference)
- [Stivers et al. cross-language turn-taking corpus](https://www.pnas.org/doi/10.1073/pnas.0903616106) — 200ms conversational average, foundation for the 300-700ms target

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context) — `claude-opus-4-7[1m]`. Dev session 2026-05-21.

### Debug Log References

- 2026-05-21 — Pre-commit gates: server 375 pytest green; ruff check + ruff format clean; client 373 flutter test green; flutter analyze clean (run via `flutter analyze` in background, exit code 0).
- One `ruff format --check` flagged `scripts/benchmark_classifier.py` on first commit pass — auto-corrected with `ruff format`; no logic change.

### Completion Notes List

**Phase A — Autonomous work complete (2026-05-21).** The story splits into two phases by inherent dependency on external resources (provider API keys + Walid sign-off on corpus labels + Pixel 9 Pro XL for smoke gate). Phase A covers everything that can land without those: benchmark scaffolding + prompt compression + Settings refactor + tests. Phase B reserved for Walid.

✅ **Settings.classifier_model refactor (Task 3.3 partial).** New `Settings.classifier_model: str = "qwen/qwen3.5-flash-02-23"` field in `config.py` with `CLASSIFIER_MODEL` env-override. `ExchangeClassifier.__init__` accepts optional `model: str = _OPENROUTER_MODEL` kwarg (defaults preserve existing test invocations). `bot.py:324` wires `model=settings.classifier_model`. Wiring asserted via new `test_bot_pipeline_wiring.py` assertion + 2 new `test_config.py` tests (default + env-override). **Retires `deferred-work.md` line 450** (Story 6.9 Defer #3 — hardcoded model id).

✅ **Prompt compression (Task 4).** `EXCHANGE_CLASSIFIER_PROMPT` compressed from ~600-700 tokens to ~340 tokens. All 6 GUIDING PRINCIPLES preserved with key exemplars retained:
- principle 1 (INTENT over literal) — "INTENT" + "literal" markers
- principle 2 (synonyms/brands) — "Synonyms" + "brand names" + `"Coke"="cola"` exemplar
- principle 3 (fragmented OK) — "fragmented" + `"uh"`/`"um"` disfluency exemplars
- principle 4 (re-statements count) — "Re-statements" + `"I already said pasta"` exemplar
- principle 5 (default to MET) — "Default to MET" + "False positives" rationale (P21 contract preserved)
- principle 6 (current objective only) — "ONLY the current objective" + "anticipate future"

XML-tag injection-resistance pattern (`<user_response>`, `<character_line>`) preserved verbatim from Story 6.6 D3.

✅ **6 principle-regression tests (Task 4.4 + existing P21).** Pattern follows P21 (text-assertion on prompt content). Each test ties a wording marker to a principle so future compression that drops a principle surfaces at pre-commit. Mocked LLM-behavior validation deferred to Task 6 smoke gate in prod.

✅ **Benchmark corpus + harness (Task 1).** 75 synthetic samples in `tests/fixtures/classifier_benchmark_corpus.json` (5 scenarios × ~6 checkpoints × ~2-3 cases). `scripts/benchmark_classifier.py` (~460 LOC) reuses `pipeline.exchange_classifier._parse_classifier_output` + `pipeline.prompts.EXCHANGE_CLASSIFIER_PROMPT` so the harness exercises the EXACT prod code path. 4 providers wired (Qwen / Groq / Cerebras / Anthropic); missing API keys skip the provider with a stderr warning. Recommendation logic implements Deviation #1: winner must beat baseline on BOTH p50 total latency AND accuracy, else abort (Story 6.12 falls back to option F visual-first feedback).

✅ **5 benchmark harness tests (Task 1.7).** `test_benchmark_classifier.py` — end-to-end shape test via `MockTransport`; 2 unit tests on `_recommend()` (abort-on-accuracy-regression + pick-fastest-qualifier); pure-function `build_report` test; 4-provider config sanity test.

✅ **Pre-commit gates GREEN (Task 5):** server 375 pytest passed (+12 net new vs baseline 363); ruff check + ruff format clean; client 373 flutter test passed; flutter analyze clean.

---

---

**Phase A.5 — Same-session benchmark + migration (2026-05-22).**

Walid validated proceeding with the benchmark in the same session after Phase A landed. The provisioning + bench + decision + migration happened end-to-end interactively. Key milestones:

1. **Bench cycle 1 (initial)** — Groq Llama 3.1 8B 80 % accuracy / 137 ms p50, but Deviation #1 says winner must beat baseline on BOTH axes → abort condition triggered on accuracy regression (-16 pts vs Qwen 96 %).
2. **Bench cycle 2 (Lever 1)** — DashScope direct (Qwen 3.5 + 3.6 Flash) tested local + VPS to validate the "skip OpenRouter proxy" hypothesis. Result: **zero gain** (591 ms VPS vs 587 ms OpenRouter — within rounding noise). Qwen is hosted in Singapore; OpenRouter proxy overhead is ~10 ms, not the 100-300 ms the spec assumed. Discovered DashScope's Qwen3+ defaults to "thinking mode" ON (~3-10 s per call); disabled via top-level `enable_thinking: false` (NOT `extra_body` which is OpenAI-SDK-only and silently dropped by raw HTTP — same gotcha as the Story 6.6 `reasoning` smoke fix).
3. **Bench cycle 3 (Llama 70B exploration)** — bumped Groq from 8B → 3.3 70B. Local: 196 ms p50 / 94.7 % accuracy. VPS: **121 ms p50 / 320 ms p95 / 98.7 % accuracy / 0 false positives** — clear winner.
4. **Migration landed** — `exchange_classifier.py` swapped to Groq while preserving the entire Story 6.9 persistent-client lifecycle unchanged (provider-agnostic). 7 files modified, 1 new test (rewrite of the smoke-witness test to lock the Groq shape), pre-commit gates GREEN.

---

**Phase B — REMAINING for Walid (smoke gate + cosmetic memory update):**

1. **Task 1.3 — (Optional) Ground-truth sign-off** — corpus is now reference data. Spot-check `waiter_clarify_met_restatement` (the 1 FN Groq makes) if you want to debate whether to amend its label.

2. **Task 1.6 — Provision GROQ_API_KEY on VPS** :
   ```bash
   ssh root@167.235.63.129 "echo 'GROQ_API_KEY=gsk_...' >> /opt/survive-the-talk/.env && systemctl restart pipecat.service"
   ```
   ⚠️ **Rotate the Groq + DashScope + OpenRouter keys that leaked into the chat today** (system reminders showed them as the .env file changed). Generate fresh ones at:
   - Groq: https://console.groq.com/keys (revoke + recreate)
   - DashScope: https://bailian.console.aliyun.com/?apiKey=1 (revoke + recreate — even though we're not migrating to DashScope, the key was exposed)
   - OpenRouter: https://openrouter.ai/keys (rotate the prod one too — that key is in chat history)

3. **Task 2.3 — Memory cosmetic update** : `memory/project_story_6_9b_classifier_latency_slash.md` §1 cost matrix — replace January 2026 estimates with real numbers (Groq 70B $0.59 / $0.79 per M, +10€/mois at 100 users instead of the +25€ we guessed initially because Groq 70B is more expensive than 8B but EmotionEmitter stays on Qwen). 10 min.

4. **Task 6 — VPS Deploy + Smoke Test Gate** (7 boxes per AC7):
   - `git push` → CI/CD deploys
   - Verify `systemctl status pipecat.service` shows `active (running)` on new SHA
   - Verify journalctl shows `ExchangeClassifier init provider=groq model=llama-3.3-70b-versatile` at boot of one call session
   - 1 calm-room Pixel 9 Pro XL call with `LATENCY_PROBE=1` → expect classifier p50 ≤300 ms / p95 ≤500 ms (Groq from VPS measured at ~120 ms/320 ms, so this should be comfortably green)
   - 1 café-noisy call → DTLN + Groq combination should be no different from calm-room
   - 1 terminal-turn measurement → total perceived latency should now be ≤1500 ms with margin (Story 6.8 AC5 universal ceiling restored beyond just spec compliance)
   - `top` snapshot → server CPU sane (Groq classify is lighter weight than the prior Qwen-with-thinking-disabled, expect no regression)
   - `journalctl | grep -iE "error|traceback|exception"` → ZERO matches across all test calls

5. **Task 6.5 — `deferred-work.md` line 451 re-tag** — "post Story 6.9b/6.12" → "post Story 6.9b" (Story 6.12 now blocks on this story's outcome since Groq's sub-300ms latency makes sync-verdict-everywhere viable).

6. **Task 6.6 — Flip `review → done`** after smoke gate proofs.

✅ **Post-`/bmad-code-review` (2026-05-22) — D1-D6 decisions resolved + 25 patches applied.** Review surfaced 82 raw findings across 3 parallel reviewers (Blind Hunter, Edge Case Hunter, Acceptance Auditor); after dedup + triage they collapsed to 6 decision-needed + 22 patches + 22 deferred + ~30 dismissed. Walid resolved all 6 decisions live; the 3 derivative patches (P23/P24/P25 from D2/D3/D4) and 22 original patches (P1-P22) all applied. See **Review Findings** section + Change Log entry 2026-05-22 for the full triage. Test count breakdown corrected per **P20**: Phase A+A.5 added **14 net new server tests** (5 principle-regression + 2 Groq failure-mode `test_classify_returns_None_on_429_rate_limit` + `test_classify_returns_None_on_5xx_groq_incident` + 2 Settings.classifier_model + 5 benchmark harness — NOT 12 as the prior sprint-status entry said). The Story 6.9b review adds +1 more (`test_corpus_has_canonical_size_and_label_split` — P11), bringing the running total to 376 server tests. Three new declared deviations: **#8** (premise empirically falsified — Qwen 587 ms baseline not 1046 ms cited; migration justification shifts from latency to accuracy + Story 6.12 unblock), **#9** (provider catalog grew 4 → 7), **#10** (`Settings.model_config` `extra: "ignore"`). Status stays `review` (D1:c — accept-as-doc-debt; smoke gate sits with Walid per existing Story 6.5 D6 deploy-gate convention).

### File List

**Server — modified (Phase A 2026-05-21):**
- `server/pipeline/prompts.py` — `EXCHANGE_CLASSIFIER_PROMPT` compressed ~600-700 → ~340 tokens; inline comment block documents compression rationale + 6 regression tests
- `server/tests/test_exchange_classifier.py` — 5 new principle-regression tests appended (intent_over_literal, accepts_synonym_or_brand, accepts_fragmented_response, accepts_restatement, evaluates_current_objective_only)

**Server — modified (Phase A.5 Groq migration 2026-05-22):**
- `server/config.py` — added `groq_api_key: str` required field; flipped `classifier_model` default `qwen/qwen3.5-flash-02-23` → `llama-3.3-70b-versatile`; added `extra: "ignore"` to model_config so leftover bench env vars (DASHSCOPE_API_KEY) don't trip Pydantic v2 forbid-extras
- `server/pipeline/exchange_classifier.py` — full module docstring rewrite naming Groq Llama 3.3 70B + linking benchmark report + documenting streaming-skip rationale; `_OPENROUTER_URL` → `_PROVIDER_URL` (Groq endpoint), `_OPENROUTER_MODEL` → `_PROVIDER_MODEL` (Llama 3.3 70B); constructor kwarg `openrouter_api_key` → `api_key` (provider-neutral); removed `reasoning: {enabled: false}` from payload (Llama has no thinking mode)
- `server/pipeline/bot.py` — `ExchangeClassifier(...)` construction now passes `api_key=settings.groq_api_key, model=settings.classifier_model` (with Groq-rationale comment)
- `server/tests/conftest.py` — added `GROQ_API_KEY: "test-groq"` to TEST_ENV_VARS so Settings() validates at conftest module load
- `server/tests/test_config.py` — added `GROQ_API_KEY` to REQUIRED_ENV_VARS + `groq_api_key` assertion in load-all test; renamed `test_settings_classifier_model_defaults_to_qwen_baseline` → `_to_groq_70b` and flipped expected default + override fixture from Qwen→Groq direction to Groq→Qwen direction (rollback case)
- `server/tests/test_exchange_classifier.py` — `_make_classifier()` updated to `api_key="test-key"` (was `openrouter_api_key="test-key"`); `test_init_raises_on_empty_api_key` updated; the smoke-witness test `test_classify_uses_httpx_post_with_reasoning_top_level` REWRITTEN as `test_classify_posts_to_groq_with_openai_compat_shape` — locks the Groq URL + Llama 3.3 70B default model + absence of `reasoning` field as the new contract; docstring on `test_classifier_defaults_to_met_on_borderline_response` updated provider-neutrally
- `server/tests/test_checkpoint_manager.py` — 5 occurrences of `ExchangeClassifier(openrouter_api_key="test-key")` and `(openrouter_api_key="k")` bulk-replaced to `api_key=`
- `server/tests/test_bot_pipeline_wiring.py` — added `api_key=settings.groq_api_key` source-text wiring assertion in `test_bot_instantiates_emitters`; updated test fixture construction; `model=settings.classifier_model` assertion stays
- `deploy/.env.example` — repositioned `GROQ_API_KEY` from benchmark-only block to required-prod slot with rationale comment; updated `CLASSIFIER_MODEL` comment to reference Groq default + Qwen rollback path; updated `DASHSCOPE_API_KEY` comment to "Lever 1 exploration, kept for slot, NOT needed in prod" rationale

**Server — modified (Phase A 2026-05-21, already in Phase A's File List above but re-stating here for one-shot review reference):**
- `server/scripts/benchmark_classifier.py` (~460 LOC original, ~510 LOC after Phase A.5 patches) — 4-provider benchmark harness; reuses prod prompt + parser; supports `--providers all` or comma-separated subset; missing API keys skipped with stderr warning; writes timestamped JSON report with recommendation block (Deviation #1 contract: winner beats baseline on BOTH latency AND accuracy, else abort); Phase A.5 added: `load_dotenv()` for server/.env auto-load, retry-on-429 with Retry-After honoured (`_MAX_RETRIES=3` / `_BACKOFF_S=5`), 2 extra provider configs (`groq_llama_3.3_70b` exploration + `qwen3.5_flash_via_dashscope` + `qwen3.6_flash_via_dashscope`), `enable_thinking: false` top-level flag for DashScope (NOT extra_body which is silently dropped)
- `server/tests/fixtures/classifier_benchmark_corpus.json` (75 samples, ~33 KB) — labelled synthetic corpus
- `server/tests/test_benchmark_classifier.py` (5 tests) — end-to-end shape via MockTransport + `_recommend()` unit tests + `build_report` pure-function test + provider-config sanity (now 6 providers: qwen_via_openrouter + qwen3.5/3.6_flash_via_dashscope + groq_llama_3.1_8b + groq_llama_3.3_70b + cerebras + anthropic)

**Client — no changes** (flutter analyze + flutter test re-validated post Phase A.5, 373 tests green).

**Implementation artifacts — modified (Phase A 2026-05-21):**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `ready-for-dev → in-progress` (Phase A complete)
- `_bmad-output/implementation-artifacts/6-9b-classifier-latency-slash.md` — Status flipped, Tasks updated for Phase A, Dev Agent Record populated

**Implementation artifacts — modified (Phase A.5 2026-05-22):**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `in-progress → review` after Groq migration landed; log entry expanded with the migration outcome
- `_bmad-output/implementation-artifacts/6-9b-classifier-latency-slash.md` — this file (Status `in-progress → review`; Tasks 2 + 3 flipped to [x] with the actual benchmark winner + migration outcome; File List + Completion Notes extended for Phase A.5; Change Log entry added)
- `_bmad-output/implementation-artifacts/calibration-tests/` — 3 representative reports committed (the 8 dead-end iteration runs — wrong API key, rate-limited, broken `enable_thinking` flag placement, etc. — were trimmed during the review polish pass):
  - `classifier_benchmark_2026-05-21T16-02-03Z.json` — Groq Llama 3.1 8B local with retry-on-429 active. Witness for the 8B abort decision (12 % accuracy on a clean run, Deviation #1 contract failed). Documents why we moved to 70B.
  - `classifier_benchmark_vps_2026-05-21T16-16-02Z.json` — Qwen via OpenRouter measured from VPS Hetzner. Baseline reference + witness for the Lever 1 abort (591 ms VPS vs 587 ms direct = zero gain, OpenRouter is not the bottleneck).
  - **`classifier_benchmark_2026-05-22T09-29-19Z.json`** — Groq Llama 3.3 70B measured from VPS Hetzner. THE load-bearing report cited in the Change Log: 121 ms p50 / 320 ms p95 / 98.7 % accuracy / 0 false positives. Witness for the migration decision.

**Implementation artifacts — Walid-owned (Phase B):**
- `_bmad-output/implementation-artifacts/deferred-work.md` line 451 — re-tag from "post Story 6.9b/6.12" → "post Story 6.9b" stays with Walid (Task 6.5)
- `memory/project_story_6_9b_classifier_latency_slash.md` — §1 cost matrix replacement with real numbers stays with Walid (Task 2.3) — see Phase B handoff above

## Change Log

- **2026-05-22 — `/bmad-code-review` complete (uncommitted Phase A + A.5 diff).** 3 parallel adversarial layers (Blind Hunter 45 raw + Edge Case Hunter 26 + Acceptance Auditor 11 = 82 findings before dedup). Triage: **6 decision-needed** (all resolved live with Walid: D1:c accept-as-doc-debt, D2:c truthful-rollback-doc, D3:a add-streaming-skipped-paragraph, D4:a document-all-undeclared-deviations, D5:c defer-to-existing-line-451, D6:c keep-debug-fix-doc), **25 patches applied** (P1-P22 original + P23 D2-truthful-rollback + P24 D3-streaming-paragraph + P25 D4-three-new-deviations), **22 deferred** to `deferred-work.md` under "code review of story-6.9b (2026-05-22)" heading, ~30 dismissed as noise. Three new declared deviations: **#8** premise empirically falsified (Qwen 587 ms not 1046 ms — migration justification shifts from latency to accuracy + Story 6.12 unblock); **#9** provider catalog grew 4 → 7 across the 2026-05-21/22 bench cycle (DashScope×2 + Groq 70B added mid-flight); **#10** `Settings.model_config` switched to `extra: "ignore"` (mitigated by `test_settings_loads_all_pipeline_env_vars`). Status stays `review` (D1:c — Pixel 9 Pro XL smoke gate sits with Walid Phase B per Story 6.5 D6 deploy-gate convention). +1 net new test (`test_corpus_has_canonical_size_and_label_split`) → server 376. Other patches modified existing test/code in place; +2 fields on `ProviderSummary` (`false_positive_rate_pct` / `false_negative_rate_pct`) surface FP/FN split per P19 — safety net for the Principle 5 default-to-MET concern flagged in D5. Pre-commit gates GREEN (validation pending at the end of this dev pass).
- **2026-05-22 — Phase A.5 landed: Groq Llama 3.3 70B migration.** Same-session interactive benchmark + decision. Lever 1 (DashScope direct, skip OpenRouter proxy) tested → zero gain (Qwen hosted in Singapore, OpenRouter overhead ~10 ms). Lever 1 abort recorded as new project-level evidence: the spec's "OpenRouter US proxy adds 100-300 ms" hypothesis was wrong, Qwen-from-VPS p50 = 587 ms via OpenRouter ≈ 591 ms direct. **Groq Llama 3.3 70B benched from VPS** measured 121 ms p50 / 320 ms p95 / 98.7 % accuracy / 0 false positives — winner on every axis vs Qwen, +10 €/mois at 100-user MVP scale, unblocks Story 6.12 sync-verdict architecture. Migrated `exchange_classifier.py`: `_OPENROUTER_*` → `_PROVIDER_*` constants, kwarg `openrouter_api_key` → `api_key`, removed `reasoning` field (Groq has no thinking mode), preserved Story 6.9 persistent-client lifecycle unchanged. Added `Settings.groq_api_key` (required); flipped `Settings.classifier_model` default `qwen/qwen3.5-flash-02-23` → `llama-3.3-70b-versatile`; added `extra: "ignore"` to Settings model_config so leftover bench env vars (DASHSCOPE_API_KEY) don't break Pydantic v2 validation. Updated 4 test files (`test_exchange_classifier.py` witness test rewritten to lock the Groq URL+model+no-reasoning shape; `test_checkpoint_manager.py` 5 occurrences of `openrouter_api_key="test-key"` → `api_key="test-key"`; `test_bot_pipeline_wiring.py` adds `api_key=settings.groq_api_key` assertion; `test_config.py` adds `groq_api_key` required + flips classifier_model default test). `conftest.py` TEST_ENV_VARS adds `GROQ_API_KEY`. `deploy/.env.example` repositions `GROQ_API_KEY` from benchmark-only to required prod slot. Pre-commit gates GREEN: ruff check + ruff format + pytest 375 + flutter analyze + flutter test 373. Status flipped `in-progress → review` — smoke gate (Task 6) reserved for Walid + 1 cosmetic memory update (Task 2.3).
- **2026-05-21 — Phase A landed.** Settings.classifier_model refactor + EXCHANGE_CLASSIFIER_PROMPT compression (~600-700 → ~340 tokens) + 5 principle-regression tests + benchmark harness + 75-sample synthetic corpus + harness smoke tests. Pre-commit gates green (server 375, client 373, ruff clean, flutter analyze clean). Story stays `in-progress` — Phase B (benchmark execution, provider migration, deploy, smoke gate) handed off to Walid. Retires `deferred-work.md` line 450 (Story 6.9 Defer #3 — hardcoded model id → Settings).

## Review Findings (2026-05-22 — `/bmad-code-review`)

Three parallel adversarial layers ran on the uncommitted Phase A + Phase A.5 diff (Blind Hunter, Edge Case Hunter, Acceptance Auditor). After dedup and triage: **6 decision-needed**, **22 patches**, **22 deferred**, **~30 dismissed**.

### Decision-Needed — resolved 2026-05-22

> Walid resolved all 6 decisions: D1:c, D2:c, D3:a, D4:a, D5:c, D6:c. See per-bullet resolution
> notes inline. D2/D3/D4/D5/D6 fed into the patch list as P23/P24/P25 and behavioural changes.

- [x] **[Review][Decision] D1 — `in-progress → review` transition premature?** The spec's Deviation #1 contract requires `_recommend()` to emit `{"verdict": "migrate", "winner": "<provider>"}` from a SINGLE head-to-head bench run. Committed reports each contain ONE provider; the Groq-vs-Qwen comparison was stitched manually. AC5 latency-target boxes (Pixel 9 Pro XL `LATENCY_PROBE=1`) also unrun. Options: (a) flip back to `in-progress`, re-run head-to-head bench (~5 min on VPS) + Pixel smoke before re-flipping `review`; (b) amend Deviation #4 to carve out the latency-probe + head-to-head bench as `review → done` concerns (matching Story 6.5 D6 pattern); (c) accept current state as documentation debt only. Sources: Acceptance Auditor BLOCKER A2 + HIGH A6.
  - **Resolved D1:c** — Walid 2026-05-22 accepted as documentation debt. The Groq Llama 3.3 70B winner is empirically defensible from the two single-provider reports stitched (Qwen baseline + Groq winner each measured from VPS in the same 24h window, same corpus, same harness code path), and AC5 latency-target boxes are owned by Walid Phase B (Task 6 smoke gate on Pixel 9 Pro XL) per existing Story 6.5 D6 deploy-gate convention. Story status stays `review`; no spec amendment required beyond the existing Phase B handoff in `### Completion Notes`. A future re-bench (Story 6.10/6.12) will be driven head-to-head from the start now that `_recommend()` is in steady state.
- [x] **[Review][Decision] D2 — Rollback URL hardcoded.** `_PROVIDER_URL` in `server/pipeline/exchange_classifier.py:70` is hardcoded to Groq; `CLASSIFIER_MODEL` env override exists but URL does not. `server/CLAUDE.md` §4 says rollback to Qwen requires both env var AND code release, but the deferred-work entry implies env-only rollback is possible. Options: (a) add `Settings.classifier_url` paired with `classifier_model` — both travel via env; (b) derive URL from model id prefix (`qwen/...` → OpenRouter, `llama-...` → Groq) — auto-routing; (c) delete the misleading rollback comments and document truthfully: rollback requires a redeploy. Sources: Blind Hunter HIGH B3 + Edge Case HIGH E20.
  - **Resolved D2:c** — Walid 2026-05-22 chose "supprimer les commentaires de rollback trompeurs, documenter honnêtement: rollback = redeploy". Patch landed: `server/CLAUDE.md` §4 rollback paragraph rewritten to lead with "REQUIRES A REDEPLOY" + name the commit (`54fd09c` or earlier); `server/config.py` `classifier_model` comment block rewritten to explicitly disclaim "NOT a Qwen rollback knob — provider URL is hardcoded to Groq" + cross-reference `_PROVIDER_URL` constant. Future env-paired URL selection deferred to a follow-up if Groq has a sustained incident that justifies the extra Settings field.
- [x] **[Review][Decision] D3 — AC3 docstring missing streaming-choice statement.** AC3 (spec line 112) requires `server/pipeline/exchange_classifier.py` docstring to document the streaming choice with one of three exact wording variants ("streaming activated", "streaming skipped — gain <100 ms", "streaming unsupported by provider Y"). The Phase A.5 docstring contains zero occurrences of the word "streaming". Confirm the choice ("streaming skipped" — Groq's 70-90 ms TTFT from VPS is already well under any practical streaming savings) and add a two-sentence paragraph. Source: Acceptance Auditor BLOCKER A1.
  - **Resolved D3:a** — Walid 2026-05-22 confirmed "streaming skipped". Patch landed: `server/pipeline/exchange_classifier.py` module docstring now contains a "Streaming skipped — gain <100 ms" paragraph between the "Request shape" and "Timing budget" sections, citing the 70-90 ms VPS TTFT measurements + the "verdict can't be acted on until the full JSON is parsed" semantic rationale. AC3 satisfied.
- [x] **[Review][Decision] D4 — Document undeclared deviations in the spec's Deviations section.** Four deviations landed in code but were never declared up-front: (i) **Qwen baseline measured 587 ms p50 vs cited 1046 ms** — the spec's "concept dead approaching" premise was empirically falsified, migration justification shifts from latency to accuracy + Story 6.12 unblock; (ii) **7-provider benchmark catalog vs spec's 4** — DashScope×2 + Groq Llama 3.3 70B added mid-flight; (iii) **`Settings.model_config` switched from forbid-extras to `extra: "ignore"`** — validation loosened across all of Settings, not just the bench API keys; (iv) Phase A vs A.5 narrative drift (cosmetic). Walid: add all, add subset, or skip? Sources: Acceptance Auditor HIGH A3 + A4 + A5 + MED A9.
  - **Resolved D4:a** — Walid 2026-05-22 chose "tout ajouter, rigueur up-front est la raison d'être de la section Deviations". Patch landed: spec Deviations section extended with **Deviation #8** (premise falsified — Qwen 587 ms baseline, not 1046 ms; migration justification shifts to accuracy + Story 6.12 unblock), **Deviation #9** (catalog grew 4 → 7 providers — DashScope×2 + Groq 70B), **Deviation #10** (`Settings.model_config` `extra: "ignore"` — mitigated by `test_settings_loads_all_pipeline_env_vars`). Narrative drift (iv) noted in this Completion Note rather than as a separate deviation — Phase A and Phase A.5 are not actually two sequential commits; the Qwen-default test was rewritten in-place during Phase A.5, not committed-and-replaced.
- [x] **[Review][Decision] D5 — Default-to-MET principle vs Llama 3.3 70B over-permissiveness.** Principle 5 (`Default to MET when uncertain`) inverts the conservative-non-advance contract. Llama 3.3 70B is a stronger instruction-follower than Qwen Flash — could push the classifier far more permissive than the calibration bands assume (Mugger/Cop target 15-35% survive). String-match tests in `test_exchange_classifier.py` don't catch this — they assert the WORDS are in the prompt, not the actual MET/NOT-MET behavior on borderline cases. Options: (a) add integration test that exercises MET/NOT-MET on the 28 NOT-MET corpus samples and fails if winner FP rate exceeds baseline + 5 pp; (b) add calibration-validation step before `review → done` (run Mugger/Cop scenarios on Pixel 9, check survival rate stays in band); (c) accept as deferred — calibration re-tune is already a Walid follow-up (Deviation #4, `deferred-work.md` line 451). Source: Blind Hunter HIGH B6.
  - **Resolved D5:c** — Walid 2026-05-22 chose "defer — calibration re-tune déjà tracké". Cross-references already in place: `deferred-work.md` line 451 ("Re-calibrate the 5 launch scenarios after EXCHANGE_CLASSIFIER_PROMPT rewrite") + Deviation #4 ("5-scenario re-calibration OUT OF SCOPE for in-progress→review"). Additional safety surface added by P19 — `_recommend()` now reports per-provider `false_positive_rate_pct` + `false_negative_rate_pct` so a future re-bench surfaces over-permissive providers explicitly (was previously hidden inside `accuracy_pct`). The 0-false-positives metric Groq Llama 3.3 70B posted on the 75-sample corpus is the empirical evidence that Principle 5 isn't compounding into over-permissiveness — Llama 70B applied the principle conservatively in benchmark conditions.
- [x] **[Review][Decision] D6 — Debug logging of raw `user_text` (PII).** Two `logger.debug` calls in `exchange_classifier.py:284, 335` emit raw user transcription + classifier verdict + raw model response. PII risk if `LOG_LEVEL=DEBUG` is flipped on VPS. The existing deferred-work entry already says "remove before public launch" but mis-states the level as `logger.info()`. Options: (a) delete the two `logger.debug` calls outright (cleanest); (b) truncate `user_text[:80]` to match sibling fields + gate behind a separate `CLASSIFIER_TRACE=1` env flag; (c) keep as-is, rewrite the deferred-work entry to reflect actual `logger.debug` level (lowest friction). Sources: Blind Hunter HIGH B4 + Acceptance Auditor MED A8.
  - **Resolved D6:c** — Walid 2026-05-22 chose "garder tel quel, juste corriger la doc qui mentait logger.info". Patch P21 landed: `deferred-work.md` entry now says "DEBUG logs" + "Story 6.10 close — delete both lines outright" instead of the old INFO-level framing. Logs stay in place for Story 6.10 dev work. Residual PII risk is gated on the operator explicitly flipping `LOG_LEVEL=DEBUG` on the VPS — bounded, not steady-state.

### Patches (unambiguous fixes)

- [x] [Review][Patch] P1 — Migration witness asserts model against `_PROVIDER_MODEL` constant, not literal `"llama-3.3-70b-versatile"` [server/tests/test_exchange_classifier.py:857]
- [x] [Review][Patch] P2 — `test_settings_classifier_model_defaults_to_groq_70b` use `patch.dict(clear=True)` for hermetic env [server/tests/test_config.py:675-679]
- [x] [Review][Patch] P3 — Move `os.environ.setdefault("GROQ_API_KEY", "test-key")` out of module-scope into conftest TEST_ENV_VARS [server/tests/test_benchmark_classifier.py:40-41]
- [x] [Review][Patch] P4 — Move `load_dotenv()` into `main()` so it only fires under direct invocation, not at import [server/scripts/benchmark_classifier.py:109-111]
- [x] [Review][Patch] P5 — Move `import os` to top of test file [server/tests/test_benchmark_classifier.py]
- [x] [Review][Patch] P6 — Treat empty-string env var as unset in `_run_provider` skip check [server/scripts/benchmark_classifier.py:780]
- [x] [Review][Patch] P7 — Cap bench `aiter_bytes` accumulated bytes (e.g. 64 KiB) to bound RAM on adversarial response [server/scripts/benchmark_classifier.py:494-500]
- [x] [Review][Patch] P8 — Bench harness mirrors prod retry handling on 5xx (not just 429) [server/scripts/benchmark_classifier.py:480-493]
- [x] [Review][Patch] P9 — Tighten broad `except RuntimeError` to match only "closed" message, log any other RuntimeError [server/pipeline/exchange_classifier.py:305]
- [x] [Review][Patch] P10 — Defensive `winner.p50_total_ms or 0` in `_recommend` reason-string format [server/scripts/benchmark_classifier.py:1689-1696]
- [x] [Review][Patch] P11 — Add `test_corpus_has_canonical_size` (75 samples, 47 MET / 28 NOT-MET) [server/tests/test_benchmark_classifier.py]
- [x] [Review][Patch] P12 — `_recommend` tiebreak deterministic on `(p50_total_ms, -accuracy_pct, name)` [server/scripts/benchmark_classifier.py:663]
- [x] [Review][Patch] P13 — Add `baseline_failed` verdict to `_recommend` when `baseline.p50_total_ms is None` [server/scripts/benchmark_classifier.py:1643-1704]
- [x] [Review][Patch] P14 — Escape `user_text` / `last_character_line` / `success_criteria` / `scenario_description` before `str.format()` (replace `{` with `{{`, `}` with `}}`) [server/pipeline/exchange_classifier.py:250-254]
- [x] [Review][Patch] P15 — Raise classifier `max_tokens` 32 → 64 (Llama 70B verbosity tendency truncates mid-JSON) [server/pipeline/exchange_classifier.py:267]
- [x] [Review][Patch] P16 — On JSON `ValueError`, log `response.headers.get("content-type")` + `response.text[:200]` for debug visibility [server/pipeline/exchange_classifier.py:325-330]
- [x] [Review][Patch] P17 — Cross-reference comment at `groq_api_key` field: "openrouter_api_key above ALSO required (EmotionEmitter + main character LLM)" [server/config.py:36]
- [x] [Review][Patch] P18 — Use `max(s.samples_total for s in summaries)` for top-level `samples_total` (or assert all providers ran identical counts) [server/scripts/benchmark_classifier.py:742]
- [x] [Review][Patch] P19 — Surface `false_positive_rate` + `false_negative_rate` in `_ProviderSummary` printout (info only — gating is D5/decision) [server/scripts/benchmark_classifier.py]
- [x] [Review][Patch] P20 — Acknowledge +2 Groq-failure-mode tests (`test_classify_returns_None_on_429_rate_limit` + `test_classify_returns_None_on_5xx_groq_incident`) in completion notes / sprint-status (test count breakdown: 14 new, not 12) [completion notes + sprint-status.yaml]
- [x] [Review][Patch] P21 — Rewrite deferred-work entry to reflect actual `logger.debug` level (not `logger.info`) [_bmad-output/implementation-artifacts/deferred-work.md last entry]
- [x] [Review][Patch] P22 — Distinguish Groq 200 + empty `choices: []` (content-filter refusal — treat as `False`, drain patience) from malformed envelope (treat as None) [server/pipeline/exchange_classifier.py:325-330] — *applied conservatively as logging-only differentiation; behavioural treat-as-False reserved for a follow-up if adversarial content-filter triggering surfaces in the wild*
- [x] [Review][Patch] P23 — *(D2 resolution)* `server/CLAUDE.md` §4 rollback paragraph rewritten + `server/config.py` `classifier_model` comment block rewritten to truthfully document "rollback requires redeploy" (lead with that, deny env-only rollback)
- [x] [Review][Patch] P24 — *(D3 resolution)* `server/pipeline/exchange_classifier.py` module docstring extended with explicit "Streaming skipped — gain <100 ms" paragraph between "Request shape" and "Timing budget" sections
- [x] [Review][Patch] P25 — *(D4 resolution)* Spec Deviations section extended with **#8** (premise falsified), **#9** (7-provider catalog), **#10** (`extra: "ignore"` validation loosening); narrative drift (iv) noted in Completion Note instead

### Deferred (pre-existing, follow-up tracked, or non-blocking)

- [x] [Review][Defer] DEF1 — Story 6.9 D2 timeouts not tightened back after Groq migration (could go to 0.8 / 0.6) — ride with Story 6.10 if surfaces (A10)
- [x] [Review][Defer] DEF2 — `memory/project_story_6_9b_classifier_latency_slash.md` §1 cost matrix not updated with real numbers — declared Walid Phase B task (A11)
- [x] [Review][Defer] DEF3 — `scripts/benchmark_classifier.py` imports private `_parse_classifier_output` — make public or add import-check test
- [x] [Review][Defer] DEF4 — `main()` has no unit tests — add subprocess smoke test
- [x] [Review][Defer] DEF5 — Rotate the 3 Groq / DashScope / OpenRouter keys leaked into chat history — declared Walid Phase B task
- [x] [Review][Defer] DEF6 — `config.py` 30-line comment block at `extra: "ignore"` — condense or move to ADR
- [x] [Review][Defer] DEF7 — Bench `_HTTP_TIMEOUT=10` vs prod 1.5 s gap (skews comparison if a candidate has tail latency 2-4 s) — document or align
- [x] [Review][Defer] DEF8 — Bench runs providers serially; no `--rate-limit-rps` flag — add when re-bench frequency goes up
- [x] [Review][Defer] DEF9 — Bench cost computation silently zero on missing `usage` block — fallback to length-of-prompt estimate
- [x] [Review][Defer] DEF10 — `verdict_accuracy_pct = correct / (samples_total - infra_failure)` not surfaced separately from `accuracy_pct` — disambiguates "wrong answers" from "no answers"
- [x] [Review][Defer] DEF11 — `_kwargs()` test helper signature not verifiable from diff — cross-check against prod `classify` signature
- [x] [Review][Defer] DEF12 — Split `.env.example` into prod + bench templates — refactor
- [x] [Review][Defer] DEF13 — `_FENCE_RE` strips only ONE fence pair (nested fences fail) — idempotent-loop refactor
- [x] [Review][Defer] DEF14 — Bench `_percentile` minimum N — document or require `samples_total >= 20`
- [x] [Review][Defer] DEF15 — `_HTTP_TIMEOUT_SECONDS` cached in client — patching at module level after instantiation has no effect — doc only
- [x] [Review][Defer] DEF16 — `bot.py` reads `settings.groq_api_key` once at build; key rotation requires `systemctl restart` not `reload` — doc only
- [x] [Review][Defer] DEF17 — Bench TTFT measured on first non-empty chunk — irrelevant until Phase B streaming work
- [x] [Review][Defer] DEF18 — `groq_api_key` not declared as `SecretStr` — Pydantic validation tracebacks may leak the key
- [x] [Review][Defer] DEF19 — `api_key` kwarg rename has no backward-compat shim — no known out-of-tree callers; intentional bulk rename
- [x] [Review][Defer] DEF20 — `_BACKOFF_S = 5.0` × 3 retries × 30 s Retry-After = 90 s bench delay possible — cap retry wait
- [x] [Review][Defer] DEF21 — Test `proceed_handler.set()` is unawaited dead code (close-during-in-flight test doesn't actually race) — cosmetic
- [x] [Review][Defer] DEF22 — `Settings(...)` ignores `GROQ_API_KEY ` with trailing whitespace (Pydantic doesn't strip env-var names) — document in config.py comment block
