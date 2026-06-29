# Claude Code Instructions — `server/` (Python / Pipecat / FastAPI)

Loaded automatically when working in `server/`. Mirrors `client/CLAUDE.md` —
hard-won traps from real prod regressions, so future iterations don't
rediscover them.

## Pre-commit (non-negotiable, same as project root)

```bash
cd server && python -m ruff check .         # zero issues
cd server && python -m ruff format --check . # zero issues
cd server && .venv/Scripts/python -m pytest # all green incl. test_migrations
```

Migrations replay against `tests/fixtures/prod_snapshot.sqlite` — see project
root `CLAUDE.md` §"Database Migrations — Test Against Production Shape".

---

## Pipecat Gotchas

### 1. Frame-direction tests — drive frames through real pipecat, don't
mock the direction

When testing a `FrameProcessor`'s behavior on a specific frame type, **prefer
driving the frame through a real pipecat pipeline** (with the actual
upstream/downstream transports involved) over calling
`processor.process_frame(frame, FrameDirection.X)` directly.

**Why it matters.** Story 6.4 / 6.5 Déviation #28 — `PatienceTracker` had a
silent regression that went undetected for 2 days in production. The unit
tests called:

```python
await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
```

…matching the production code's `direction == FrameDirection.DOWNSTREAM`
check. Tests passed. But `pipecat 0.0.108`'s `BaseOutputTransport`
actually pushes BSF in BOTH directions — the downstream copy goes into the
sink (output is the last processor, `_next is None`), and the **upstream
copy** travels back through the pipeline. `PatienceTracker` lives upstream
of the output transport, so it only ever sees BSF as `UPSTREAM`. The
production check never fired. The bug was invisible because **test and code
were mutually wrong, agreeing on a wrong assumption**.

**The class of bug**: when a test hard-codes a frame direction to validate a
`FrameProcessor`, it severs the binding between pipecat's actual routing and
the processor's check. The two can drift independently — and if they drift
in the same direction (test direction == code direction == wrong), both
pass.

**Two layers of defense**:

1. **Cross-reference contract test** — `tests/test_patience_tracker.py::
   test_BSF_direction_matches_pipecat_emission_routing` reads the SOURCE
   TEXT of both pipecat's `_bot_stopped_speaking()` and our
   `patience_tracker.py`, asserting they agree on direction. Fires on any
   pipecat upgrade that changes routing OR any local edit that reverts the
   fix. Source-text matching is fragile (renames break it) — when pipecat
   upgrades, expect to re-verify the assumption.

2. **Pipeline integration test** (recommended for any new direction-
   sensitive `FrameProcessor`) — instead of calling `process_frame()`
   directly, drive a trigger frame (e.g. `TTSStoppedFrame`) through a
   minimal real pipeline that includes the actual pipecat transport that
   emits the frame you care about. The transport decides the direction;
   the test observes the outcome. Higher setup cost than direct calls but
   the only way to truly catch direction drift.

#### Don't shadow a base `FrameProcessor` attribute (the `_clock` trap)

Same class of bug, different mechanism — Story 7.1 `HesitationObserver`. A
custom `FrameProcessor` stored its injected monotonic clock as `self._clock`.
But pipecat's base `FrameProcessor` **already owns `self._clock`**
(`frame_processor.py:184`), and `setup()` (run at `StartFrame` on every REAL
call) UNCONDITIONALLY overwrites it with a non-callable `BaseClock`
(`frame_processor.py:563`). So `self._clock()` raised `'SystemClock' object is
not callable` on the first frame, pipecat swallowed it via `push_error_frame`,
and the observer captured **nothing in prod** — while every unit test passed,
because direct `process_frame()` calls never run `setup()` (the §1 trap again,
via attribute-name collision instead of direction).

**Rule:** a `FrameProcessor` subclass must NOT name an instance attribute after
a base-class one. Pipecat owns `_clock`, `_next`, `_prev`, `_id`, `_name`,
`_observer`, `_task_manager`, `_event_handlers`, `_cancelling`, … When in doubt,
prefix your own (`self._now`, `self._hesitation_gaps`) and add a real-pipeline
drive test (one that calls `setup()` — i.e. runs the processor inside a
`PipelineTask`/`PipelineRunner`) so a shadow surfaces loud, not silent.

#### Asymmetric `TranscriptionFrame.finalized` defaults — intentional

`CheckpointManager` and `PatienceTracker` both observe
`TranscriptionFrame`, and both check `getattr(frame, "finalized", X)` with
DIFFERENT defaults — this is intentional, not a bug:

- **CheckpointManager** — `getattr(frame, "finalized", False)`. Conservative:
  a future pipecat that drops the field stops firing the classifier on every
  interim transcription. A false-positive (classifier fires on a half-word)
  would advance a checkpoint on noise; the cost asymmetry favors the
  conservative default.
- **PatienceTracker** — `getattr(frame, "finalized", True)`. Aggressive:
  matches the current pipecat 0.0.108 behavior where `finalized` is always
  emitted. A false-positive (silence ladder cancelled on an interim TF)
  defers a hangup by one ladder tick — recoverable. A false-negative
  (ladder NOT cancelled when user spoke) escalates impatience while the
  user is talking — worse UX.

If pipecat ever drops the `finalized` field, the asymmetry surfaces:
CheckpointManager goes silent (classifier never fires); PatienceTracker
fires on every interim. Re-evaluate both defaults together at upgrade
time. Cross-references live in inline comments at both call sites.

### 2. Migrations must replay against the prod snapshot

A test that passes on an empty DB says nothing about production. Any new
file under `server/db/migrations/` must keep `tests/test_migrations.py`
green — that test replays migrations against
`tests/fixtures/prod_snapshot.sqlite` (a sanitised copy of the live VPS DB)
and asserts no FK / CHECK / integrity violations.

If your migration introduces a new table, new constraint, or a structural
change you want represented in the snapshot, run:

```bash
cd server && python scripts/refresh_prod_snapshot.py
```

…then commit the refreshed snapshot alongside the migration. See project
root `CLAUDE.md` for the canonical contract — Story 5.1 shipped a tier-
rename migration that crashed on first deploy because the local test DB
was empty (no FK-referencing rows to violate). Snapshot-based testing
makes that class of bug impossible to ship.

### 3. Loguru logs don't propagate to `caplog` — use a temp sink instead

Pytest's `caplog` fixture intercepts `logging.*` calls. Pipecat (and our
code) uses `loguru`. Loguru does NOT propagate to stdlib `logging` by
default, so `caplog` sees nothing.

To assert a loguru log in a test, use a temporary loguru sink:

```python
from loguru import logger as loguru_logger

captured: list[str] = []
sink_id = loguru_logger.add(captured.append, level="ERROR")
try:
    # ... action that logs ...
finally:
    loguru_logger.remove(sink_id)

assert any("expected message" in entry for entry in captured)
```

Bit us on Story 6.5 review P6 (NULL `duration_sec` log assertion).

### 4. ALL LLM paths run on OpenAI gpt-4.1-mini (Story 10.6, 2026-06-29)

> **FINAL STATE (Story 10.6, 2026-06-29).** All three LLM roles —
> `classifier_model` (judge), `debrief_model`, `character_model` — default to
> OpenAI **`gpt-4.1-mini`** via the OpenAI-compatible endpoint
> (`llm_base_url=https://api.openai.com/v1`). gpt-4.1-mini supports strict
> `json_schema` (`strict:true`) NATIVELY, so the judge + debrief keep their
> server-validated structured-output contract, and it is NOT a reasoning model so
> NO `reasoning_effort` is sent. The Groq / gpt-oss / Gemini material below is
> MIGRATION HISTORY (Scout → gpt-oss on Groq → Gemini 2.5 → OpenAI); the LAW it
> states still holds — only the provider/model names changed.

> **PROJECT LAW — checkpoint-judge model swaps.** Any future change to
> `CLASSIFIER_MODEL` / `Settings.classifier_model` MUST pick a model that
> supports **strict structured output** (`response_format=json_schema`, or the
> provider equivalent). Never pin a judge model that lacks it. Reason: the
> 2026-05-29 "nothing checks" bug — a free-form-JSON judge intermittently echoed
> a mangled goal id (`goal_id="greet"`) → silent all-None → no checkpoint
> flipped. The format guarantee OUTRANKS a few points of raw accuracy: a
> mangled-format turn silently drops a checkpoint (bad UX), worse than an
> occasional wrong verdict. Verify the candidate accepts `json_schema` on the
> target provider BEFORE adopting it. **Story 10.6 (2026-06-29, FINAL): the judge
> + debrief migrated off the Groq-decommissioned Llama 4 Scout (off 2026-07-17)
> onto OpenAI `gpt-4.1-mini`**, which supports strict `json_schema` NATIVELY
> (incl. `["string","null"]` unions). The migration passed through
> `openai/gpt-oss-20b`/`120b` on Groq (the only Groq family with real
> `strict:true`; the paid Dev tier stayed walled) and Gemini 2.5 (character too
> weak) before landing on OpenAI. gpt-4.1-mini is NOT a reasoning model, so NO
> `reasoning_effort` is sent (the gpt-oss/Gemini reasoning gating was removed in
> the 10.6 review). 70B returns HTTP 400 on `json_schema`; Qwen is
> json_object-only → both disqualified.

Story 6.9b (2026-05-22) moved only the classifier to Groq; the
**2026-05-29 all-Groq migration** then moved the remaining two LLM
paths off Qwen-via-OpenRouter too. **Reason:** OpenRouter's *shared
free pool* access to Qwen kept returning HTTP 429 "rate-limited
upstream" from Alibaba (`is_byok: False`) — even on single slow test
calls, freezing the character. Story 10.6 (2026-06-29) later left Groq
entirely for OpenAI gpt-4.1-mini (above); the three-path structure below
is unchanged — only the provider/model/URL differ, so the Groq specifics
in these bullets are history:

- **`ExchangeClassifier`** (`pipeline/exchange_classifier.py`) → the configured
  OpenAI-compatible endpoint via raw httpx (`resolve_llm_chat_url`, now
  `api.openai.com/v1/chat/completions`). Reads the LLM key + `Settings.
  classifier_model`. **The multi-goal judge (`classify_multi`) sends STRICT
  structured outputs (`response_format=json_schema`): a schema-pinned object
  `{goal_id: "met"|"unmet"|"unsure"}` validated server-side. So `classifier_model`
  defaults to **`gpt-4.1-mini`** (Story 10.6 — was Llama 4 Scout until its
  2026-07-17 decommission, then gpt-oss-20b on Groq), NOT 70B — 70B returns HTTP
  400 on `json_schema`. Strict structured output killed the format-instability
  bug where 70B intermittently echoed the literal id tag (`goal_id="greet"`) under
  the old free-form `{"goals_met":[...]}` contract → broke id matching → silent
  all-None → NO checkpoint flipped for the SAME input that worked a call earlier.
  `CLASSIFIER_MODEL` must stay a structured-output-capable model. gpt-4.1-mini is
  not a reasoning model, so no `reasoning_effort` is sent. See
  `_build_verdict_schema` + `EXCHANGE_CLASSIFIER_MULTI_PROMPT`.**
- **`EmotionEmitter` — RETIRED (Story 6.29, 2026-06-10).** The face
  emotion is now CO-GENERATED by the reply LLM as a trailing
  `<mood:VALUE>` tag (`prompts.MOOD_TAG_DIRECTIVE`, appended to every
  system-instruction composition); `pipeline/reply_sanitizer.py` strips
  the tag (plus `(...)`/`*...*` stage directions) from the streamed
  reply before TTS/transcript/context and re-emits the same
  `{"type":"emotion"}` envelope. Deletes one LLM call per turn;
  `EMOTION_MODEL` is a legacy no-op env var (kept parseable).
- **Main character LLM** (`bot.py`) → **`OpenAILLMService` pointed at the
  configured `llm_base_url`** (now `https://api.openai.com/v1`, Story 10.6) with
  the LLM key + `Settings.character_model`. We use `OpenAILLMService` (the
  already-present `openai` SDK), **NOT** pipecat's `GroqLLMService` — importing
  `pipecat.services.groq` pulls in `groq.tts`, which hard-requires the `groq` SDK
  (`pipecat-ai[groq]` extra) that we do NOT install → `ModuleNotFoundError` at
  boot. The warm-up (`llm_warmup.py`) hits the same endpoint.

`character_model`, `classifier_model`, and `debrief_model` all default to
`"gpt-4.1-mini"` (Story 10.6, 2026-06-29). All env-overridable (`CHARACTER_MODEL`
/ `CLASSIFIER_MODEL` / `DEBRIEF_MODEL`; `EMOTION_MODEL` legacy since 6.29). **Judge
benchmark history (75-sample `tests/fixtures/classifier_benchmark_corpus.json`):**
during the Groq migration both gpt-oss-20b and gpt-oss-120b scored **98.7%** vs
Scout's 93.3%; that bench was the gpt-oss decision proxy, NOT a gpt-4.1-mini
measurement. ⚠️ **The judge's accuracy on the SHIPPED model (gpt-4.1-mini) against
the §6 golden net is OWED** (Story 10.6 review D1 — run `calibrate_scenario.py`
before flipping the story to `done`; a gpt-4.1 judge mis-credit is also backlogged
to story 10-7).

> **R1 — Groq tier / TPM (HISTORICAL).** This applied only while the judge/debrief
> ran on Groq gpt-oss (reasoning models, `prompt + max_tokens` counted against an
> 8000-TPM `on_demand` cap → 413/429). On OpenAI gpt-4.1-mini it no longer
> applies. Kept for the graceful-degradation contract, which still holds: a
> 413/429/timeout judge fails OPEN (no credit, patience-neutral); a failed debrief
> falls back to the degraded score-only debrief.

**Persona note:** the character prompts were written for Qwen (`/no_think`
prefix is a Qwen-ism, inert on Llama/gpt-oss); a persona recalibration is a
deliberate follow-up.

Only `GROQ_API_KEY` is REQUIRED now. `OPENROUTER_API_KEY` is **legacy /
optional** (default `""`) — no longer read by the runtime; safe to
remove from `/opt/survive-the-talk/.env`. The dev-only bench scripts
still read it from the env directly.

Rollback: revert this migration's commit + redeploy (a provider switch
is code, not an env knob — the Groq base_url/URL is hardcoded).

### 5. TTS provider is switchable — Cartesia default, ElevenLabs fallback (Story 6.13 → 6.14)

The TTS provider is selected by `Settings.tts_provider` (env
`TTS_PROVIDER=cartesia|elevenlabs`, default **`cartesia`** since Story
6.14 / 2026-05-30). The single branching point is
`pipeline/tts_factory.py::build_tts_service(settings)`; `bot.py` never
names a provider class. To add a third provider (OpenAI gpt-4o-mini-tts,
Deepgram Aura…), add one branch there + matching `Settings` fields —
`bot.py` stays untouched.

**Why Cartesia is the default again (REVERSED 2026-05-30).** The
2026-05-26 multi-frame "freeze" that drove us to ElevenLabs (calls
156/157: ≥4 short sends on one context within ~300 ms → silence →
`type=error` ~30 s later) turned out to be a **RESOLVED Cartesia platform
incident** (support reply 2026-05-28, Ege Tinmaz;
status.cartesia.ai/incidents/1j04yfp4048k) — both our reproductions
landed inside the incident window. Cartesia also confirmed: no client
pacing is needed, and the `FreshContextCartesiaTTSService` "fix attempt"
was unnecessary/counter-productive (it multiplied the contexts the
incident choked on) → **removed in Story 6.14**. Walid's on-device A/B
(2026-05-30) found Cartesia FAR smoother under network jitter: its
smaller audio frames don't time-stretch ("voix rallongée") the way
ElevenLabs' larger frames do. ElevenLabs Flash v2.5 still wins raw TTFA
(~75 ms vs ~300 ms) but loses on jitter smoothness — it's now the
**last-resort fallback** until the jitter buffer (next paragraph) makes
it viable again.

**Cartesia error schema is always-on now.** The default service is
`ErrorLoggingCartesiaTTSService` (not a debug gate) — it surfaces
Cartesia's documented error frame
(`{"type":"error","context_id":...,"status_code":<int>,"done":true,
"error":"<str>"}`) at WARNING (`cartesia_ws_error ...`) at the websocket
boundary, BEFORE pipecat's `audio_context_available` guard can silently
drop an abandoned-context error (the freeze case). Grep journalctl for
`cartesia_ws_error`.

**Story 6.14 jitter buffer (the "voix rallongée" fix), server-side.** The
stretching is receiver-side WebRTC NetEq time-stretching audio to fill
bursty-packet gaps (network jitter, diagnosed call_id=198 — server logs
clean, `DTLN_ENABLED=0` never helped). `flutter_webrtc` 1.3.0 exposes NO
client playout-delay knob, so the lever is LiveKit's room config
`min_playout_delay` (ms), attached to BOTH call tokens in
`pipeline/livekit_tokens.py` (env `LIVEKIT_MIN_PLAYOUT_DELAY_MS`, default
200, 0 disables). The SFU then emits the `playout-delay` RTP extension →
the phone's NetEq keeps a bigger jitter buffer → no stretching. Helps
EVERY provider (Cartesia and ElevenLabs). Trades a small fixed latency
for smoothness; keep it the smallest value that kills the stretching
(PRD ceiling = 2 s perceived). The client logs inbound-audio stats
(`InboundAudioStatsLogger`, `kLogInboundAudioStats`) so the before/after
is measurable (watch `concealedSamples` deltas drop).

**Required env for Cartesia (default):** `CARTESIA_API_KEY`. For
ElevenLabs: `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` (+ optional
`ELEVENLABS_MODEL`, default `eleven_flash_v2_5`). The factory raises at
boot if the chosen provider's creds are missing — fail-loud, not
mid-call.

**Cartesia debug env-gates (still in the repo, inert by default):**
`CARTESIA_INSTRUMENT=1` → verbose WS send/recv logging
(`pipeline/cartesia_instrumented.py`, on top of the always-on error
surfacing); `TTS_AUDIO_DEBUG=1` → per-frame audio amplitude/sample-rate
logging in `TTSWatchdog`. Both off in prod; flip + `systemctl restart`
to re-arm. (`CARTESIA_FRESH_CTX` was removed in Story 6.14.)

**LLM warm-up:** `pipeline/llm_warmup.py` fires a throwaway `max_tokens=1`
OpenRouter completion at call start (fire-and-forget from `bot.py`) to
kill the ~0.5 s turn-1 cold-start. Never blocks, never raises.

Beware the Bluetooth red herring: "no audio on device" was once just the
test phone routing call audio to BT earbuds — verify output routing
before chasing a server-side audio bug (the `TTS_AUDIO_DEBUG` frames will
show real amplitude at the watchdog if the server side is fine).

### 6. Validate a scenario with `calibrate_scenario` when you add or edit one (Story 6.15)

**Adding or editing a scenario? Run the validation engine before trusting it.**
The rigor lives in the engine, NOT in scenario authoring — author the YAML
simply (write `success_criteria` in plain prose; scenarios carry NO difficulty
since Story 6.28 — the learner's GLOBAL setting drives it at runtime) and let
the tool prove the logic:

```bash
cd server
python scripts/calibrate_scenario.py <scenario_id>          # golden net + calibration
python scripts/calibrate_scenario.py                        # smart sweep (only new/changed)
python scripts/calibrate_scenario.py --golden-only          # fast regression-only sweep
python scripts/calibrate_scenario.py <scenario_id> --generate-golden  # bootstrap fixtures
```

It is a **text-driven** validator (no Soniox/TTS/LiveKit/device) that reuses the
EXACT prod code paths — `ExchangeClassifier.classify_multi`, the pure
`checkpoint_manager.advance_goals`, `patience_tracker.step_patience`,
`compose_goal_system_instruction`, and the YAML loaders — so a green run means
PROD behaves. The library is `scripts/calibration_engine.py`; logic is unit-
tested in `tests/test_calibration_engine.py` (those mocked-LLM tests DO run in
`pytest`).

What it checks (PASS ✅ / FAIL ❌, with a non-zero exit code on FAIL so an agent
or CI can branch on it):

- **Golden net** — a UNIVERSAL off-topic seed (zero authoring, every scenario)
  asserts off-topic input is judged `unmet` on every checkpoint — this is the
  2026-05-30 "judge passes everything" bug as a permanent assertion. Plus
  per-checkpoint cases that you `--generate-golden` then review (`reviewed: true`
  in `tests/fixtures/golden/<id>.json` makes them gating; the Waiter fixture is
  the hand-authored worked example).
- **Calibration** — an AI learner plays N=10 conversations COMPOSED at the
  RUN-level global difficulty (`--difficulty`, default easy — Story 6.28:
  scenarios carry no authored difficulty); the cooperative completion rate
  must land in that level's band (easy 60-80, medium 35-55, hard 15-35 per
  `difficulty-calibration.md` §4.3; ±5 pts = ⚠️ warning, still passes), and an
  off_topic learner must NOT complete.

On FAIL it prints a copy-pasteable Markdown diagnostic (named YAML field paths +
likely cause/fix + reproduction command) you can hand straight to an AI agent.

**Ledger + revalidate-only-what-changed.** A `calibration-tests/validation-ledger.json`
records each PASS with a behaviour-only `scenario_hash` (covers base_prompt,
checkpoints, the 8 patience overrides, briefing, exit_lines — NOT cosmetic
fields like `tts_voice_id` or `display_order`). The no-arg sweep skips scenarios that are
unchanged AND still PASS. Bumping `ENGINE_VERSION` in `calibration_engine.py`
(when the rules change) forces a full revalidation on the next sweep.

**Cost + determinism (gated out of `pytest`).** Live runs need `GROQ_API_KEY`
and run only via the CLI (never imported by prod). A full
`calibrate_scenario <id>` ≈ a few US cents at N=10 (Groq); `--golden-only` is a
fraction of a cent. Treat a full sweep as a deliberate, budgeted action.

### 7. Reactive checkpoints — gate them with `requires`, never with prose (Story 6.23)

Not all checkpoints are equal. **Proactive** beats are info the learner can
volunteer at any time (give your name, state your alibi) — they stay fully
any-order (the Story 6.10 win). **Reactive** beats only make sense as a
*response* to a specific earlier CHARACTER action: a misquote trap, a
named-associate confrontation, an inside-handle reveal, a circle-back recall,
a cited CCTV timestamp. A reactive beat *literally cannot occur before its
trigger* — so crediting it earlier is always wrong.

**The rule: a reactive beat declares `requires: <earlier_checkpoint_id>` in the
YAML.** That one optional field is the entire taxonomy — no `beat_type` enum, no
free-prose precondition. The engine then refuses to even JUDGE that beat until
the required beat is `met` (`checkpoint_manager.judgeable_goals`, the single
crediting choke point — `advance_goals` is untouched). The guarantee is
**structural and upstream of the LLM**, so it is immune to how
`success_criteria` is worded: write reactive criteria as a clean lexical test
and let the gate hold the precondition. Do NOT re-encode "PASS only AFTER Mercer
has ALREADY…" in prose — that approach is blind to traps beyond the single
`last_character_line` and is exactly the brittle hand-patch this story retired
(the cop call_id=222 incident: a bare "actually + a time" alibi credited the
far-later `correct_misquoted_time` trap before it was sprung).

Mechanics / invariants:
- **No `requires` = proactive = byte-identical to pre-6.23.** Only beats with an
  explicit edge are gated; proactive any-order is preserved verbatim.
- **The edge must point STRICTLY EARLIER.** The loader
  (`scenarios.load_scenario_checkpoints`) fail-fasts at call init on a `requires`
  that names a non-existent or non-earlier id (acyclic by construction) — same
  posture as the duplicate-id guard.
- **The "all beats gated" state is IMPOSSIBLE — no tail guard needed.** Because
  every `requires` points strictly earlier and goals are binary (`pending`/`met`),
  the EARLIEST still-pending beat is always judgeable (its trigger, being earlier
  than the earliest pending beat, is necessarily already `met`). So
  `judgeable_goals` is NEVER empty while any beat is pending, and a scenario may
  even END on a reactive beat safely (when only it remains, its trigger is met).
  `_classify_and_flip_goals`'s `if not judgeable: return` is a never-executes
  defensive guard, NOT a patience-drain hole (Story 6.23 review 2026-06-08,
  finding f4/f5 — proven unreachable, no loader tail-guard added). ⚠️ If
  `requires` ever grows OR/list/forward semantics (deferred decisions D2/D3),
  re-verify this property.
- **The UN-gated `pending_goals` still drives the character steering prompt + the
  terminal-turn count** — the character must keep *pursuing* a reactive beat (it
  delivers the trigger), and a gated beat keeps the call from completing with an
  un-sprung trap.
- **Golden==prod is load-bearing.** The Story 6.15 harness
  (`calibration_engine.run_calibration`) MUST judge the SAME `judgeable_goals`
  set; the golden net also runs a pure premature-credit assertion
  (`requires_gating_failures`) and `ENGINE_VERSION` was bumped so the next sweep
  surfaces any reactive-but-ungated beat already shipped.
- **The builder auto-populates it.** `scenario_builder.CHECKPOINTS_PROMPT` asks
  the draft LLM to emit `requires` for reactive beats; `sanitize_checkpoints`
  preserves it (it used to silently drop unknown keys); `CRITIQUE_PROMPT`'s
  circularity pass EXEMPTS reactive beats (it used to launder ordering
  dependencies out — plausibly how the cop trap became a standalone lexical
  test). Human-confirmed, not a build blocker.

### 8. Personas are difficulty-NEUTRAL — difficulty lives ONLY in `_DIFFICULTY_PROMPTS` (Story 6.19 follow-up)

A scenario YAML `base_prompt` describes ONLY the character's **stable identity**:
who they are, the setting, canonical facts, their fixed temperament/tone, and the
hard safety boundaries. It must **NOT** encode any difficulty-coded behavior — no
"squint at grammar mistakes", "overlap/interrupt them", "react with condescension",
"escalate gradually", "rephrase on confusion", idiom/slang-density mandate, or
speech-pace line. ALL difficulty behavior (comprehension load + accommodation) is
composed at LOAD time from `scenarios._DIFFICULTY_PROMPTS` by
`load_scenario_base_prompt(difficulty=…)` — `difficulty` being the learner's
GLOBAL pick, the product's ONLY difficulty cursor (Story 6.28 removed the
per-scenario authored label; absent → `DEFAULT_DIFFICULTY`, "easy"). Neutrality
is MORE critical now: every scenario must play correctly at all 3 global levels.

**Why (the cop "squint" leak).** Before this, the cop persona was authored *hard*
("squint at them like you're assessing impairment", "overlap them if the person
pauses") and the waiter *easy* ("escalate gradually"). A global easy/hard pick
appended a generic block that **contradicted** the persona; on the weak prod model
(Scout) the model fell back to the persona, so **easy == hard** on-device. A neutral
persona removes the contradiction. The blocks themselves are now **personality-
neutral** too: each opens with "This is a LANGUAGE setting only — keep your persona's
temperament unchanged", so the SAME block composes onto a cold cop, a tired waiter,
or a mugger. Difficulty rides on **language + precision**, never personality, warmth,
or a fixed catchphrase; speech speed is capped at the natural 1.0 rate. (Difficulty
ALSO scales the **patience/timing** layer — silence tolerance + `ladder_impatience_seconds`
in `_DIFFICULTY_PRESETS`. That is a *separate, sanctioned* difficulty channel — turn-taking
pace + error budget — NOT character personality: "personality held constant" means warmth /
temperament / role, not the meter.)

**Enforced by construction (no LLM):**
- `load_scenario_base_prompt` **warns** (runtime canary; does NOT crash the call — the
  denylist is a fuzzy substring tripwire that could false-positive on innocent backstory)
  when a persona hits `scenarios._PERSONA_DIFFICULTY_LEAK_PATTERNS`.
  `find_persona_difficulty_leaks` is the single source of truth.
- `scenario_builder.validate_structure` **hard-fails** it (imports the same helper) and
  `EXPAND_PROMPT` / `CHECKPOINTS_PROMPT` / `CRITIQUE_PROMPT` instruct the draft LLM
  to keep the persona AND every `prompt_segment` difficulty-neutral — so future
  generated scenarios are born neutral.
- `tests/test_scenarios.py::test_shipped_personas_have_no_difficulty_coded_phrases`
  lints every shipped persona on each commit.

A static denylist only catches KNOWN coded phrases; the real proof the blocks change
BEHAVIOR is the live A/B `scripts/compare_difficulty.py` — **run it on the prod model
(Scout), not 70B** (the tool now defaults to Scout for exactly this reason).

---

### 9. Scenarios must be MODEL-AGNOSTIC + correct-by-construction (2026-06-26)

**PROJECT LAW (Walid 2026-06-26).** Scenarios are mass-produced mechanically and
MUST pass for **ANY** LLM **by construction** — never via manual per-scenario
tweaks. A scenario must behave identically whether the runtime model is Groq's
Llama, Gemini, or a future swap. **Model-agnostic is non-negotiable.** The trigger:
`/no_think` (a Qwen reasoning-control prefix) was frozen into all 5 hand-authored
personas — inert on its native model but **spoken aloud by Gemini**. Every scenario
defect we fix becomes a PERMANENT rule below + a guardrail in the builder/loader; a
one-off manual tweak is a SMELL.

Enforcement has three layers (builder generates them right → fail-fast validators
reject bad ones → calibration golden net validates behavior):

- **R1 — Zero model-specific syntax.** No `/no_think`, `[INST]`, `<<SYS>>`,
  `<|im_*|>`, or any token meaningful to one model family. **Enforced HARD:**
  `scenarios.find_model_specific_tokens` is rejected by
  `scenario_builder.validate_structure` (base_prompt + every prompt_segment), WARNED
  by the loader (`load_scenario_base_prompt`), and fails the commit via
  `tests/test_scenarios.py::test_shipped_scenarios_have_no_model_specific_tokens`. A
  scenario with a model-ism CANNOT ship.
- **R2 — Behavior, not scripts.** A `prompt_segment` describes WHAT the character
  does; never a verbatim sentence in quotes to recite, nor a `[placeholder]`
  template — a weaker model recites the instruction/placeholder aloud (the `confirm`
  "Repeat the order: 'So that's [their order]…'" leak). **Enforced HARD (2026-06-26):**
  `scenarios.find_scripting_violations` (placeholder tokens `[X]`/`{x}`/`<y>` + recite
  directives like `say exactly`) is rejected by `scenario_builder.validate_structure`,
  WARNED by the loader, and fails the commit via
  `tests/test_scenarios.py::test_shipped_scenarios_have_no_scripting_violations`. The
  builder `CHECKPOINTS_PROMPT` is still the first line (generate it right).
- **R3 — Never require what the scenario can't provide.** A `prompt_segment` must
  not tell the character to ask for a choice/variation/option the menu/inventory
  does not contain (the pasta "what kind?" loop — pasta has no varieties). No
  variation → acknowledge and move on. Builder `CHECKPOINTS_PROMPT`.
- **R4 — Always speak.** The character must never emit an all-meta reply (mood tag /
  stage direction only) → silence. `reply_sanitizer` drops an empty-after-strip
  reply (deliberate, but it fired often on Gemini); COHERENCE_CHARTER rule 9
  ("always say at least one spoken sentence; silence is never acceptable").
- **R5 — Abuse detection is model-agnostic + not trigger-happy.** Frustration
  ("stop bothering me"), criticism of the food/service, and clumsy flirtation are
  NOT abuse — only a genuine slur, hate speech, credible threat, or graphic sexual
  proposition is. `EXCHANGE_CLASSIFIER_MULTI_PROMPT` `__user_abusive__` section; must
  judge the same across models.
- **R6 — The character DRIVES, never acknowledges-and-waits.** Each `prompt_segment`
  must make the character ADVANCE (ask the next thing) in the SAME reply; a
  guide/host (waiter) keeps the interaction moving so the learner is never left
  waiting. Builder `CHECKPOINTS_PROMPT`. (Introduced by a fix that over-corrected
  into passivity — proof every tweak must respect R2 + be validated on device.)
- **R7 — Never use runtime-absent info; the character has NO access to the learner's
  name or identity.** A `prompt_segment` must not tell the character to address or
  confirm the learner BY NAME (or any personal datum the pipeline never supplies) —
  given none, the model invents and recites a literal placeholder ("I'm calling for
  Mr./Ms. [Learner Name]. Are you [Learner Name]?", call 334 on cop_interrogation_01).
  The character may ASK for a name; it must never claim to already have one. The literal
  `[Learner Name]` placeholder is caught by the R2 lint above; the SEMANTIC trap (telling
  the character to address the learner *by name* with no literal placeholder) is not
  lexically detectable — it stays builder `CHECKPOINTS_PROMPT` guidance + the smoke gate.
  Sibling of R3 (don't require/use what the scenario can't provide).

**Status (2026-06-26):** R1 + R2 + R7(literal placeholder) are code-enforced via fail-fast
lints over the FULL `_SCENARIO_INDEX` (`find_model_specific_tokens` + `find_scripting_violations`,
each in builder + loader + commit test); R4 + R6 are ENGINE-enforced (a scenario CANNOT
produce dead air or acknowledge-and-stop no matter how it is written — `reply_sanitizer`
never-silent floor + `checkpoint_manager` always-drive branch); R5 is embedded in the
classifier prompt; R3 + R7(semantic) remain builder `CHECKPOINTS_PROMPT` guidance (not
lexically detectable) + the smoke gate. All SIX shipped scenarios are de-scripted + audited
(waiter + cop_hard + girlfriend + landlord + mugger + cop_interrogation); cop_interrogation
also needed a judge-timeout bump for the SLOW Gemini era (`_HTTP/_CLASSIFIER_TIMEOUT_SECONDS`
1.5/2.0→4.0/4.5 s), pulled back to 2.0/2.5 s for the FAST OpenAI gpt-4.1-mini in the 10.6
review (D3; felt `VERDICT_WAIT_BUDGET_MS` UNTOUCHED — owes a Pixel 9 re-validation). Remaining:
per-scenario calibration + Pixel 9 smoke gate.

**THE DURABLE LESSON (why bugs reached production — read before adding any rule).** They
leaked because the rules were SOFT — the builder was *told* to follow them but nothing
*rejected* a violator — and scenarios were audited BY HAND (which missed `cop_interrogation_01`
entirely). Soft guidance + manual audits ALWAYS leak. The only "never again" is the R1
pattern applied everywhere: (1) a fail-fast validator that runs over EVERY scenario via the
glob index (NEVER a hand-list) and BLOCKS a violator at build + commit; AND (2) put the
guarantee in the ENGINE when you can, so the scenario can't break core UX however it is
written (R4/R6 are now engine guards, not prompt wishes). So: every recurring bug class
becomes a lint or an engine guard — NOT a memory note, NOT a one-off scenario patch.
Building a NEW scenario = run the builder (rule-compliant by construction) → the validators
reject anything that slipped → golden calibration on the prod model → Pixel 9 smoke. Full
task list in the migration story
`_bmad-output/implementation-artifacts/10-6-migrate-off-decommissioned-llama-4-scout-model.md`.

---

## When in doubt

- Pipeline regressions (silence escalation, emotion emission, hang-up
  mechanic) — check `journalctl -u pipecat.service --since '...' | grep
  pipeline.patience_tracker` on the VPS first. If NO escalation log lines
  appear in production over days of testing, the chain is broken (see
  Déviation #28).
- Story 6.5 Implementation Notes capture every non-literal choice — read
  them before assuming an "obvious" fix in `routes_calls.py` or
  `patience_tracker.py` is correct.
