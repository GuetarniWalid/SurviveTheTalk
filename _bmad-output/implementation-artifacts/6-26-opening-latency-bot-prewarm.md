# Story 6.26: Opening-latency — kill the per-call bot cold-boot (bot pre-warm / pool)

Status: done

> **Perf-surfaced story (2026-06-05).** Spun off from the Story 6.24 smoke gate (Pixel 9, calls 230/231). Story 6.24's TTS warm-up was confirmed working (TTS first-audio ~150 ms, ZERO `cartesia_tts_watchdog_fired` — the call_id=226 stall is dead), yet Walid **still perceived a blank on the opening line**. Reconstructing the full call-230 timeline showed the blank is **not** the TTS: it is the **per-call bot-subprocess cold boot**. A fresh Python process is spawned for every call and pays the full cold import (torch / pipecat / livekit / soniox / onnxruntime) + model loads (Silero VAD, DTLN) before it can connect and speak.
>
> **✅ DESIGN PASS COMPLETE (2026-06-09).** All four decisions resolved with Walid (D1–D4 below). Approach **A — warm bot-process pool** (one always-ready parked bot, `BOT_POOL_SIZE`-configurable, single-use per call, cold-spawn fallback). The spec below is now decision-complete and has a firm Tasks/Subtasks breakdown — ready for `/bmad-dev-story`.

## Measured evidence (call_id=230, 2026-06-05, deployed `git_sha bca3331`)

| Milestone | Timestamp | Segment |
|---|---|---|
| `routes_calls.initiate_call` — `Spawned tutorial bot for room …` | `13:13:38.760` | — |
| Bot subprocess's first pipeline work (`Loading Silero VAD model…`) | `13:13:43.502` | **≈ 4.74 s — cold Python boot (imports + process start)** |
| Pipeline ready + transports connected (Cartesia/Soniox WS, VAD, `StartFrame` traversed) | `13:13:44.908` | ≈ 1.41 s |
| Opening-line synth starts (`run_tts [Hi. Welcome to The Golden Fork…]`) | `13:13:44.912` | — |
| **First audio out** (`latency_probe label=tts_first_audio`) → bot speaking | `13:13:45.062` | **≈ 0.15 s — TTS, hot ✅** |

**Total `Spawned`→first-audio ≈ 6.30 s.** The TTS is ~150 ms (~2 %); the dominant cost is the ~4.7 s cold process boot, then ~1.4 s of transport/model setup. (Calls 230/231 were near back-to-back, so Cartesia was warm regardless — the TTS warm-up's own payoff shows specifically on the first call after an idle/cold edge, the call_id=226 scenario. Either way, the *opening blank* is the bot boot, not the TTS.)

## Story

As the learner,
I want the character to start speaking **quickly after I start the call** — without a multi-second blank while "connecting" —
so the opening feels live, not like the app froze.

(Maintainer angle: I want the per-call bot subprocess to NOT pay a cold Python-import + model-load boot on the critical path of every call.)

## Root cause

Each call spawns a brand-new Python process (`routes_calls.initiate_call` → bot subprocess running `bot.run_bot`). That process imports the entire heavy voice/ML stack (torch, pipecat, livekit, soniox, onnxruntime) and loads models (Silero VAD, DTLN) **on the call's critical path**, every single time (~4.7 s measured). The Story 6.13 LLM warm-up and the Story 6.24 TTS warm-up both fire *inside* that process — i.e. only **after** the ~4.7 s boot has already been paid — so neither can touch the opening blank.

## Candidate approaches (pick one in the design pass)

- **(A) Warm bot-process pool / pre-fork.** Keep N already-booted, idle bot processes (stack imported, models loaded) ready; on call start, hand one a room+token instead of spawning cold. Biggest win (~removes the full 4.7 s), but needs lifecycle management (pool size, recycle-after-call, crash refill, env/secret injection per call, cap vs idle cost).
- **(B) Persistent warm worker adopts the room.** A long-lived warmed worker (or small set) that joins the LiveKit room on demand rather than `Popen`-per-call. Similar payoff; concurrency model + isolation between calls to design.
- **(C) Trim the cold cost in place.** Lazy-import the heaviest deps off the critical path, preload/cache Silero VAD + DTLN once, defer non-essential setup until after first audio. Lower risk, smaller win (shaves rather than removes the boot); could be a cheap first step combined with A/B.

All three dwarf the 150 ms TTS slice. (A)/(B) are the real fix; (C) is incremental.

## Resolved Decisions (design pass — Walid, 2026-06-09)

- **D1 — approach: A (warm bot-process pool).** Keep `BOT_POOL_SIZE` already-booted "parked" bot processes idle and ready; on call start, hand one its job instead of spawning cold. Rejected B (single persistent worker) — a crash kills all calls, concurrent calls collide, and proving zero cross-call state is hard. Rejected C-only (trim imports) — marginal; doesn't remove the blank. (C-style model-preload is a sanctioned *follow-up* on top of A — see D4.)
- **D2 — pool sizing & lifecycle: 1 parked bot, single-use, refill-on-grab.** `BOT_POOL_SIZE` defaults to **1** (env-overridable; `0` disables the pool → today's cold spawn for every call = clean kill-switch). A parked bot serves **exactly one call** then exits (NO reuse across calls). On acquire, the pool immediately spawns a replacement; a periodic maintainer loop tops the pool back up to size (reaps idle crashes / fills missing slots). Idle cost = `BOT_POOL_SIZE` booted processes holding the import stack in RAM, **zero CPU while parked** (blocked on a stdin read). Per-call config (room/token + `SCENARIO_*`/`SYSTEM_PROMPT`/`CALL_ID`) is injected into the already-booted process via a single JSON **job line written to its stdin** — no env-at-exec, no socket/port, no new network surface.
- **D3 — isolation: guaranteed by single-use.** Each call still gets a brand-new process that exits at call end — identical lifecycle to a cold spawn, just with the import boot pre-paid. The ONLY thing shared from boot is the imported module stack (read-only, stateless). All per-call state — `Settings()`, scenario load, `SileroVADAnalyzer`, `DTLNAudioFilter`, the LLM context, the patience meter, the LiveKit transport/sockets — is constructed **inside `run_bot`**, which runs once, after the job env is applied. Verified: `run_bot` reads every per-call value from `os.environ` at call time (bot.py:111-128) and builds VAD (bot.py:397) / DTLN (bot.py:207) / transport (bot.py:215) per call.
- **D4 — target budget: under the PRD 2 s ceiling.** Removing the ~4.7 s import boot leaves ~1.4 s (per-call model load + transport connect) + ~0.15 s TTS ≈ **~1.6 s** `Spawned`/call-start → first-audio in the first cut — under 2 s. **Follow-up (out of scope here, noted in Dev Notes):** pre-load the scenario-independent Silero VAD + DTLN models in the parked process to shave the remaining ~1.4 s toward <1 s. Not done now because reusing a VAD/DTLN instance across the park→call boundary risks audio-stream state leakage and needs a `run_bot` signature refactor; the import-boot removal alone already clears the ceiling.

## Acceptance Criteria (BDD)

### AC1 — Opening latency under target
Given a fresh call on the default scenario served from the warm pool, when the call connects, then the character's first audio lands **under the PRD 2 s perceived ceiling** (target ≈ 1.6 s; today ≈ 6.3 s), measured `Spawned`/call-start → `tts_first_audio`. (Cold-fallback calls — pool empty/disabled — keep today's ≈ 6.3 s; this AC asserts the pool-served path.)

### AC2 — No per-call cold boot on the critical path (pool path)
Given a pool-served call, when it starts, then the heavy ~4.7 s import boot is NOT paid on that call's critical path — a pre-booted parked process is used and the only cost on-path is the per-call model load + transport connect.

### AC3 — Clean isolation between calls
Given a parked process serving a call, then it carries no leaked state from any prior call (scenario, LLM context, checkpoint meter, transports) — a parked process serves exactly ONE call then exits, behavior identical to a cold spawn.

### AC4 — Resilience / fail-safe
Given a parked process crashes or the pool is exhausted (or `BOT_POOL_SIZE=0`), when a call starts, then the system falls back to a cold `Popen` spawn (today's path) without dropping the call; the pool refills crashed/consumed slots back to `BOT_POOL_SIZE`; idle cost stays within the VPS budget (`BOT_POOL_SIZE` parked processes, zero idle CPU).

### AC4b — Kill-switch
Given `BOT_POOL_SIZE=0`, when the server starts, then no parked processes are spawned and every call cold-spawns exactly as before this story (a clean, code-free rollback knob).

### AC5 — No regression
Given the change is to process lifecycle only, then the in-call pipeline (STT/LLM/TTS, checkpoints, patience, hang-up, the 6.13/6.24 warm-ups) behaves exactly as before once a call is running.

### AC6 — Gates
`ruff check . && ruff format --check . && pytest` green. Client untouched (server-only).

### AC7 — Smoke gate (device)
On a fresh call right after deploy, the opening line speaks within the target with no perceptible "connecting" blank; measured via `latency_probe` + the `Spawned`→first-audio delta in `journalctl`.

## Tasks / Subtasks

- [x] **Task 1 — `BOT_POOL_SIZE` setting (AC4/AC4b).** Add `bot_pool_size: int = 1` to `config.Settings` (env `BOT_POOL_SIZE`) with a boot-time validator (`>= 0`; sane upper bound `<= 8` to stop a typo'd `BOT_POOL_SIZE=100` from OOM-ing the VPS). `0` = pool disabled (kill-switch). +tests in `tests/test_config.py` (default, override, reject negative / over-max).
- [x] **Task 2 — Parked mode in `bot.py` (AC2/AC3).** Add a `--parked` flag; make `--url/--room/--token` optional. Extract a pure helper `apply_parked_job(line: str) -> tuple[str, str, str]` that JSON-parses one job line `{"url","room","token","env":{...}}`, validates the keys, applies `job["env"]` to `os.environ` (the per-call `SCENARIO_*`/`SYSTEM_PROMPT`/`CALL_ID`), and returns `(url, room, token)`. In `--parked` mode: print the readiness sentinel `BOT_PARKED_READY` to stdout (flush) AFTER imports, block on `sys.stdin.readline()`, `apply_parked_job(...)`, then `asyncio.run(run_bot(...))` once and exit. Non-parked path unchanged. +unit tests for `apply_parked_job` (happy path sets env + returns args; missing key / bad JSON raises; absent optional `SCENARIO_DIFFICULTY` not set).
- [x] **Task 3 — `pipeline/bot_pool.py` (AC2/AC3/AC4).** New async `BotPool(settings, *, spawn=...)`:
  - `start()` spawns up to `size` parked bots (await each readiness sentinel, per-process boot timeout; failures logged non-fatal, maintainer tops up later).
  - `acquire(job: dict) -> bool` under an `asyncio.Lock`: pop a ready bot, skipping/reaping any that died while idle (`returncode is not None`); on hit, write the job line to its stdin + drain, schedule an immediate refill, return `True`; on miss return `False`.
  - `_maintain_loop(stop_event)` safety-net top-up (mirror janitor cadence/cancellation) — refill to `size`, reap dead idle.
  - `stop(stop_event)` terminates idle parked bots (they're blocked on stdin) and cancels the maintainer.
  - The spawn function is **injectable** so tests substitute a lightweight stub parked process (no heavy import). +unit tests: spawns N & becomes ready; acquire writes job + refills; empty pool → `False`; dead idle process skipped/reaped; `size=0` spawns nothing; `stop()` terminates idle.
- [x] **Task 4 — Lifespan wiring (AC4).** In `api/app.py` lifespan, construct `app.state.bot_pool = BotPool(settings, size=settings.bot_pool_size)`, `await pool.start()` after seed, spawn the maintainer; on exit `await pool.stop()`. Mirror the janitor's bounded shutdown. `size=0` → a no-op pool. +a lightweight app-startup test that the pool attribute exists and a `size=0` pool spawns nothing.
- [x] **Task 5 — `initiate_call` uses the pool (AC1/AC2/AC4).** Build the `job` dict (url/room/token + the same env the cold path packs). Try `await request.app.state.bot_pool.acquire(job)`; on `True` log `acquired parked bot` (pool-hit); on `False` (or no pool) fall through to the **existing** cold `Popen` path (log `pool miss — cold spawn`). The `Popen`-failure rollback (row→`failed`, LiveKit room delete, `BOT_SPAWN_FAILED`) stays on the cold path. +tests: pool-hit hands the job to the pool and does NOT cold-spawn; pool-miss cold-spawns (existing Popen test still green); rollback unchanged.
- [x] **Task 6 — Gates (AC6).** `python -m ruff check .` + `python -m ruff format --check .` + `.venv/Scripts/python -m pytest` all green (799 passed). Client untouched.
- [x] **Task 7 — Deploy + Smoke Gate (AC1/AC7).** Deployed (`e8e847d`, CI 27235051069); `BOT_POOL_SIZE` defaults to 1 (active). Walid Pixel 9 smoke gate PASSED 2026-06-10 — two `[pooled]` calls at ~1.72 s / ~1.78 s opening (was ~6.3 s), distinct parked-bot pids (isolation), full multi-turn calls clean. `review → done`.

## Dev Notes

**Code references (entry points — to confirm in the design/dev pass):**
- `server/api/routes_calls.py::initiate_call` (~`:378`, logs `Spawned … bot for room …`) — where the per-call bot subprocess is launched. The pooling/warm-worker hook lives here.
- `server/main.py` / `server/pipeline/bot.py::run_bot` — the bot entry + pipeline build (Silero VAD load, transport connects). The ~4.7 s import boot precedes the first log line here.
- `server/pipeline/llm_warmup.py` + `server/pipeline/tts_warmup.py` — existing in-process warm-ups; note they fire *after* the boot, so they don't address this.
- `latency_probe` (`pipeline/latency_probe.py`, label `tts_first_audio`) — the measurement hook for AC1/AC7.

**Relationship to other work:**
- Ties to memory `feedback_latency_kill_criterion_exceeded` (PRD 2 s ceiling) — that note is about *turn* latency; this is the *opening* latency, a distinct (and larger) cause.
- Story 6.24 (TTS warm-up) stays `done` — it killed the TTS cold-start (the call_id=226 stall). This story is the rest of the opening blank.

### Project Structure Notes
- Server-only (process lifecycle). No DB migration. Client untouched. Not in `epics.md` — perf-surfaced (same path as 6.18–6.25).

## Smoke Test Gate (Server / Deploy Story)

- [x] **Deployed** to the VPS (`deploy-server.yml` git_sha match) — CI run 27235051069 success, `/health` git_sha `e8e847d`. `BOT_POOL_SIZE` unset → defaults to 1 (active). `journalctl` shows `bot_pool ready size=1 ready=1` (2026-06-09 20:54:11) + a live `pipeline.bot --parked` process (~206 MB RSS); VPS RAM 3.0 Gi available (no OOM risk).
- [x] **Opening latency:** ✅ Pixel 9, 2026-06-10 (Walid: "ça démarre très, très vite, rien à voir qu'avant"). `journalctl` proof — call 1 (`call-55ee5fdf`): `acquired parked bot pid=1148964` 07:44:36.835 → `tts_first_audio` 07:44:38.553 = **~1.72 s**; call 2 (`call-403b44e2`): pid=1155771 07:44:53.932 → 07:44:55.708 = **~1.78 s**. Both `[pooled]`, both well under the 2 s PRD ceiling (was ~6.3 s).
- [x] **Isolation:** ✅ call 2 was served by a **DIFFERENT** parked-bot pid (1155771) than call 1 (1148964) — the refill-on-acquire spawned a fresh replacement, and each call got its own single-use process (no leftover state). Walid confirmed clean behaviour across both calls.
- [x] **Resilience:** cold-fallback path proven by the automated suite (`test_acquire_skips_dead_idle_bot`, `test_boot_timeout_discards_unready_bot`, `test_initiate_cold_spawns_when_pool_misses/raises`) + `BOT_POOL_SIZE=0` kill-switch test; the refill-between-calls (distinct pids) was observed live. NOTE: a manual on-device process-kill was not performed — resilience rests on the deterministic tests (same posture as Story 6.25's fast-double path).
- [x] **No regression:** ✅ both calls ran full multi-turn conversations (call 2: ~10 turns 07:44:55 → 07:47:06) with no errors; STT/LLM/TTS/checkpoints/hang-up unaffected. Walid: "c'est parfait".

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code)

### Approach
Warm bot-process pool (Decision A). `pipeline/bot_pool.py` keeps `BOT_POOL_SIZE` parked bots (a parked bot pre-pays the ~4.7 s import boot, then blocks reading one JSON job line from stdin). `initiate_call` hands a ready parked bot the job (room/token + per-call env) instead of cold-spawning; on an empty/disabled pool it falls back to the existing cold `Popen`. A parked bot serves exactly one call then exits (clean isolation). Pool managed in the FastAPI lifespan, mirroring the janitor pattern; refill-on-acquire + a maintainer top-up loop. `BOT_POOL_SIZE=0` disables the pool entirely (kill-switch / rollback).

### Debug Log References
- Verified the REAL parked entry end-to-end (`python -m pipeline.bot --parked`, env present): boots in **~4.4 s** then prints `BOT_PARKED_READY`, and exits cleanly (code 0) on stdin-close-without-job. Confirms (a) the ~4.7 s cold-boot diagnosis, (b) the sentinel/flush works, (c) the graceful no-job exit. NOTE: importing the bot constructs a module-level `Settings()` (`db/database.py:31`), so the parked bot needs the server's env at boot — it gets it in prod by inheriting the server process env (`env=None` on the pool spawn). The per-call values are NOT Settings fields; they're injected via the stdin job and read by `run_bot` from `os.environ` at call time.

### Completion Notes List
- **Tasks 1-6 complete; all automated gates green** (ruff check + ruff format + full `pytest` = **799 passed**, +24 net for this story). **Task 7 (deploy + Pixel 9 smoke gate) is the remaining `in-progress → review → done` gate — Walid's device.**
- **Approach A — warm pool, single-use, refill-on-grab, cold-spawn fallback.** A parked bot pre-pays the ~4.7 s import boot, blocks on a stdin job line, serves ONE call, exits (clean isolation = AC3). `BOT_POOL_SIZE` default 1, `0` = kill-switch (AC4b). Empty/disabled pool or any pool error → cold `Popen` fallback, so no call is ever dropped (AC4).
- **IPC = one JSON job line on stdin** (`{"url","room","token","env":{…}}`) — no new port/socket. Only the whitelisted per-call env keys are applied (`apply_parked_job`), so a job can't rewrite arbitrary process env (e.g. `GROQ_API_KEY`).
- **Tests drive the REAL asyncio-subprocess machinery via a lightweight stub** (`python -c …`) — spawn, readiness sentinel, stdin job delivery, dead-idle reaping, boot timeout, terminate — fast but high-fidelity (server/CLAUDE.md §1). A constant-drift guard keeps the pool's sentinel == `bot.PARKED_READY_SENTINEL`.
- **Deviation (minor):** the spec sketched `BotPool(settings, *, spawn=...)`; the implementation uses `BotPool(*, size, command=…, env=…)` (inject the *command*, not a spawn fn) — same testability goal, but lets tests drive the real spawn path with a stub command rather than mock the spawn entirely (closer to the "drive the real boundary" rule).
- **Follow-up (noted, out of scope):** pre-load Silero VAD + DTLN in the parked process to shave the remaining ~1.4 s model-load toward <1 s (needs a `run_bot` signature refactor + per-call model-reuse isolation review). The import-boot removal alone clears the PRD 2 s ceiling (~1.6 s).

### File List
- **New — server:** `server/pipeline/bot_pool.py` (the `BotPool` + `ParkedBot`); `server/tests/test_bot_pool.py`; `server/tests/test_bot_parked_mode.py`.
- **Edited — server:** `server/config.py` (+`bot_pool_size` field + validator); `server/pipeline/bot.py` (+`import sys`, `PARKED_READY_SENTINEL`, `apply_parked_job`, `_run_parked`, `--parked` flag, optional url/room/token); `server/api/app.py` (+`BotPool`/`Settings` imports, lifespan start/stop); `server/api/routes_calls.py` (`initiate_call` builds the job + tries the pool, cold-spawn fallback); `server/tests/conftest.py` (`BOT_POOL_SIZE=0` in the test env); `server/tests/test_config.py` (+4 pool-size tests); `server/tests/test_calls.py` (+4 pool-integration tests + `_FakePool`).
- **Untouched:** client (server-only story); no DB migration.

### Change Log
- 2026-06-05 — Drafted (perf-surfaced from the Story 6.24 Pixel 9 smoke gate, calls 230/231). Diagnosis: the opening blank is the per-call bot-subprocess cold boot (~4.7 s) + transport connect (~1.4 s), not the TTS (150 ms); total `Spawned`→first-audio ≈ 6.3 s. Three candidate approaches (pool / persistent worker / trim-imports) + 4 open decisions. Needs a design pass before `/bmad-dev-story`.
- 2026-06-09 — Design pass complete (Walid). D1=A (warm pool), D2=size 1 / single-use / `BOT_POOL_SIZE` env / refill-on-grab, D3=isolation by single-use, D4=under PRD 2 s (~1.6 s first cut; model-preload a noted follow-up). Firmed ACs (AC1-AC4b), added the 7-task breakdown. `ready-for-dev`, decision-complete.
- 2026-06-09 — `/bmad-dev-story` Tasks 1-6 implemented (`in-progress`). New `pipeline/bot_pool.py` (warm pool) + parked mode in `bot.py` + `BOT_POOL_SIZE` setting + lifespan wiring + `initiate_call` pool-with-cold-fallback. All gates green (ruff clean, full `pytest` **799 passed**, +24). Real parked entry verified (boots ~4.4 s, prints sentinel, clean no-job exit). Server-only, no migration, client untouched. `in-progress → review`. **Task 7 (VPS deploy with `BOT_POOL_SIZE=1` + Walid's Pixel 9 smoke gate) is the remaining `review → done` gate.**
- 2026-06-09 — **Deployed (Walid go-ahead).** Pushed `e8e847d`; CI run 27235051069 success; `/health` git_sha matches. VPS confirmed: `bot_pool ready size=1 ready=1`, a live `pipeline.bot --parked` process (~206 MB RSS), 3.0 Gi RAM available (no OOM). `BOT_POOL_SIZE` defaults to 1 (not set in `.env`; kill-switch = `BOT_POOL_SIZE=0` + restart). **Now waiting ONLY on the Pixel 9 smoke gate for `review → done`.**
- 2026-06-10 — **Pixel 9 smoke gate PASSED → `review → done`.** Walid: "ça démarre très, très vite, rien à voir qu'avant… c'est parfait." Two `[pooled]` calls measured from `journalctl`: opening (call-start → `tts_first_audio`) **~1.72 s** and **~1.78 s** (was ~6.3 s), both under the PRD 2 s ceiling. Distinct parked-bot pids across the two calls (1148964 → 1155771) proved refill + single-use isolation. Full multi-turn calls clean, no regression. Story COMPLETE.
