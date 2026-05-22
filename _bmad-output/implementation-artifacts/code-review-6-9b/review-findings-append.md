
## Review Findings (2026-05-22 — `/bmad-code-review`)

Three parallel adversarial layers ran on the uncommitted Phase A + Phase A.5 diff (Blind Hunter, Edge Case Hunter, Acceptance Auditor). After dedup and triage: **6 decision-needed**, **22 patches**, **22 deferred**, **~30 dismissed**.

### Decision-Needed

- [ ] **[Review][Decision] D1 — `in-progress → review` transition premature?** The spec's Deviation #1 contract requires `_recommend()` to emit `{"verdict": "migrate", "winner": "<provider>"}` from a SINGLE head-to-head bench run. Committed reports each contain ONE provider; the Groq-vs-Qwen comparison was stitched manually. AC5 latency-target boxes (Pixel 9 Pro XL `LATENCY_PROBE=1`) also unrun. Options: (a) flip back to `in-progress`, re-run head-to-head bench (~5 min on VPS) + Pixel smoke before re-flipping `review`; (b) amend Deviation #4 to carve out the latency-probe + head-to-head bench as `review → done` concerns (matching Story 6.5 D6 pattern); (c) accept current state as documentation debt only. Sources: Acceptance Auditor BLOCKER A2 + HIGH A6.
- [ ] **[Review][Decision] D2 — Rollback URL hardcoded.** `_PROVIDER_URL` in `server/pipeline/exchange_classifier.py:70` is hardcoded to Groq; `CLASSIFIER_MODEL` env override exists but URL does not. `server/CLAUDE.md` §4 says rollback to Qwen requires both env var AND code release, but the deferred-work entry implies env-only rollback is possible. Options: (a) add `Settings.classifier_url` paired with `classifier_model` — both travel via env; (b) derive URL from model id prefix (`qwen/...` → OpenRouter, `llama-...` → Groq) — auto-routing; (c) delete the misleading rollback comments and document truthfully: rollback requires a redeploy. Sources: Blind Hunter HIGH B3 + Edge Case HIGH E20.
- [ ] **[Review][Decision] D3 — AC3 docstring missing streaming-choice statement.** AC3 (spec line 112) requires `server/pipeline/exchange_classifier.py` docstring to document the streaming choice with one of three exact wording variants ("streaming activated", "streaming skipped — gain <100 ms", "streaming unsupported by provider Y"). The Phase A.5 docstring contains zero occurrences of the word "streaming". Confirm the choice ("streaming skipped" — Groq's 70-90 ms TTFT from VPS is already well under any practical streaming savings) and add a two-sentence paragraph. Source: Acceptance Auditor BLOCKER A1.
- [ ] **[Review][Decision] D4 — Document undeclared deviations in the spec's Deviations section.** Four deviations landed in code but were never declared up-front: (i) **Qwen baseline measured 587 ms p50 vs cited 1046 ms** — the spec's "concept dead approaching" premise was empirically falsified, migration justification shifts from latency to accuracy + Story 6.12 unblock; (ii) **7-provider benchmark catalog vs spec's 4** — DashScope×2 + Groq Llama 3.3 70B added mid-flight; (iii) **`Settings.model_config` switched from forbid-extras to `extra: "ignore"`** — validation loosened across all of Settings, not just the bench API keys; (iv) Phase A vs A.5 narrative drift (cosmetic). Walid: add all, add subset, or skip? Sources: Acceptance Auditor HIGH A3 + A4 + A5 + MED A9.
- [ ] **[Review][Decision] D5 — Default-to-MET principle vs Llama 3.3 70B over-permissiveness.** Principle 5 (`Default to MET when uncertain`) inverts the conservative-non-advance contract. Llama 3.3 70B is a stronger instruction-follower than Qwen Flash — could push the classifier far more permissive than the calibration bands assume (Mugger/Cop target 15-35% survive). String-match tests in `test_exchange_classifier.py` don't catch this — they assert the WORDS are in the prompt, not the actual MET/NOT-MET behavior on borderline cases. Options: (a) add integration test that exercises MET/NOT-MET on the 28 NOT-MET corpus samples and fails if winner FP rate exceeds baseline + 5 pp; (b) add calibration-validation step before `review → done` (run Mugger/Cop scenarios on Pixel 9, check survival rate stays in band); (c) accept as deferred — calibration re-tune is already a Walid follow-up (Deviation #4, `deferred-work.md` line 451). Source: Blind Hunter HIGH B6.
- [ ] **[Review][Decision] D6 — Debug logging of raw `user_text` (PII).** Two `logger.debug` calls in `exchange_classifier.py:284, 335` emit raw user transcription + classifier verdict + raw model response. PII risk if `LOG_LEVEL=DEBUG` is flipped on VPS. The existing deferred-work entry already says "remove before public launch" but mis-states the level as `logger.info()`. Options: (a) delete the two `logger.debug` calls outright (cleanest); (b) truncate `user_text[:80]` to match sibling fields + gate behind a separate `CLASSIFIER_TRACE=1` env flag; (c) keep as-is, rewrite the deferred-work entry to reflect actual `logger.debug` level (lowest friction). Sources: Blind Hunter HIGH B4 + Acceptance Auditor MED A8.

### Patches (unambiguous fixes)

- [ ] [Review][Patch] P1 — Migration witness asserts model against `_PROVIDER_MODEL` constant, not literal `"llama-3.3-70b-versatile"` [server/tests/test_exchange_classifier.py:857]
- [ ] [Review][Patch] P2 — `test_settings_classifier_model_defaults_to_groq_70b` use `patch.dict(clear=True)` for hermetic env [server/tests/test_config.py:675-679]
- [ ] [Review][Patch] P3 — Move `os.environ.setdefault("GROQ_API_KEY", "test-key")` out of module-scope into conftest TEST_ENV_VARS [server/tests/test_benchmark_classifier.py:40-41]
- [ ] [Review][Patch] P4 — Move `load_dotenv()` into `main()` so it only fires under direct invocation, not at import [server/scripts/benchmark_classifier.py:109-111]
- [ ] [Review][Patch] P5 — Move `import os` to top of test file [server/tests/test_benchmark_classifier.py]
- [ ] [Review][Patch] P6 — Treat empty-string env var as unset in `_run_provider` skip check [server/scripts/benchmark_classifier.py:780]
- [ ] [Review][Patch] P7 — Cap bench `aiter_bytes` accumulated bytes (e.g. 64 KiB) to bound RAM on adversarial response [server/scripts/benchmark_classifier.py:494-500]
- [ ] [Review][Patch] P8 — Bench harness mirrors prod retry handling on 5xx (not just 429) [server/scripts/benchmark_classifier.py:480-493]
- [ ] [Review][Patch] P9 — Tighten broad `except RuntimeError` to match only "closed" message, log any other RuntimeError [server/pipeline/exchange_classifier.py:305]
- [ ] [Review][Patch] P10 — Defensive `winner.p50_total_ms or 0` in `_recommend` reason-string format [server/scripts/benchmark_classifier.py:1689-1696]
- [ ] [Review][Patch] P11 — Add `test_corpus_has_canonical_size` (75 samples, 47 MET / 28 NOT-MET) [server/tests/test_benchmark_classifier.py]
- [ ] [Review][Patch] P12 — `_recommend` tiebreak deterministic on `(p50_total_ms, -accuracy_pct, name)` [server/scripts/benchmark_classifier.py:663]
- [ ] [Review][Patch] P13 — Add `baseline_failed` verdict to `_recommend` when `baseline.p50_total_ms is None` [server/scripts/benchmark_classifier.py:1643-1704]
- [ ] [Review][Patch] P14 — Escape `user_text` / `last_character_line` / `success_criteria` / `scenario_description` before `str.format()` (replace `{` with `{{`, `}` with `}}`) [server/pipeline/exchange_classifier.py:250-254]
- [ ] [Review][Patch] P15 — Raise classifier `max_tokens` 32 → 64 (Llama 70B verbosity tendency truncates mid-JSON) [server/pipeline/exchange_classifier.py:267]
- [ ] [Review][Patch] P16 — On JSON `ValueError`, log `response.headers.get("content-type")` + `response.text[:200]` for debug visibility [server/pipeline/exchange_classifier.py:325-330]
- [ ] [Review][Patch] P17 — Cross-reference comment at `groq_api_key` field: "openrouter_api_key above ALSO required (EmotionEmitter + main character LLM)" [server/config.py:36]
- [ ] [Review][Patch] P18 — Use `max(s.samples_total for s in summaries)` for top-level `samples_total` (or assert all providers ran identical counts) [server/scripts/benchmark_classifier.py:742]
- [ ] [Review][Patch] P19 — Surface `false_positive_rate` + `false_negative_rate` in `_ProviderSummary` printout (info only — gating is D5/decision) [server/scripts/benchmark_classifier.py]
- [ ] [Review][Patch] P20 — Acknowledge +2 Groq-failure-mode tests (`test_classify_returns_None_on_429_rate_limit` + `test_classify_returns_None_on_5xx_groq_incident`) in completion notes / sprint-status (test count breakdown: 14 new, not 12) [completion notes + sprint-status.yaml]
- [ ] [Review][Patch] P21 — Rewrite deferred-work entry to reflect actual `logger.debug` level (not `logger.info`) [_bmad-output/implementation-artifacts/deferred-work.md last entry]
- [ ] [Review][Patch] P22 — Distinguish Groq 200 + empty `choices: []` (content-filter refusal — treat as `False`, drain patience) from malformed envelope (treat as None) [server/pipeline/exchange_classifier.py:325-330]

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
