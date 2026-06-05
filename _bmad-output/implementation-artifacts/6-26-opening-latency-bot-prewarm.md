# Story 6.26: Opening-latency — kill the per-call bot cold-boot (bot pre-warm / pool)

Status: ready-for-dev

> **Perf-surfaced story (2026-06-05).** Spun off from the Story 6.24 smoke gate (Pixel 9, calls 230/231). Story 6.24's TTS warm-up was confirmed working (TTS first-audio ~150 ms, ZERO `cartesia_tts_watchdog_fired` — the call_id=226 stall is dead), yet Walid **still perceived a blank on the opening line**. Reconstructing the full call-230 timeline showed the blank is **not** the TTS: it is the **per-call bot-subprocess cold boot**. A fresh Python process is spawned for every call and pays the full cold import (torch / pipecat / livekit / soniox / onnxruntime) + model loads (Silero VAD, DTLN) before it can connect and speak.
>
> **⚠️ DESIGN DECISIONS OPEN — run a design pass / get Walid's decision on the approach before `/bmad-dev-story`.** This file is the diagnosis + candidate approaches, not a decision-complete spec.

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

## Open Decisions (resolve before `/bmad-dev-story`)

- **D1 — approach:** A (pool), B (persistent worker), or C (trim) — or C-now + A/B-later.
- **D2 — pool sizing & lifecycle** (if A/B): how many warm, recycle policy, crash/refill, idle-cost ceiling on the single VPS, per-call env/secret + room-token injection into an already-booted process.
- **D3 — isolation:** confirm a reused/pre-forked process carries NO state across calls (scenario, context, meter, sockets) — must be as clean as a fresh spawn.
- **D4 — target budget:** the perceived opening (call-start → first audio) target. PRD ceiling is 2 s; pick the concrete number this story must hit.

## Acceptance Criteria (BDD — provisional, firm up after D1)

### AC1 — Opening latency under target
Given a fresh call on the default scenario, when the call connects, then the character's first audio lands within **the D4 budget** (target: well under the PRD 2 s perceived ceiling; today ≈ 6.3 s), measured `Spawned`/call-start → `tts_first_audio`.

### AC2 — No per-call cold boot on the critical path
Given the chosen approach, when a call starts, then the heavy import + model-load cost is NOT paid on that call's critical path (a warmed process/worker is used, or the cost is moved off-path).

### AC3 — Clean isolation between calls
Given a reused/pooled process, when a new call uses it, then it carries no leaked state from a prior call (scenario, LLM context, checkpoint meter, transports) — behavior identical to a cold spawn.

### AC4 — Resilience
Given a warmed process crashes or the pool is exhausted, then the system fails safe (refills / falls back to a cold spawn) without dropping the call; idle cost stays within the VPS budget.

### AC5 — No regression
Given the change is to process lifecycle only, then the in-call pipeline (STT/LLM/TTS, checkpoints, patience, hang-up, the 6.13/6.24 warm-ups) behaves exactly as before once a call is running.

### AC6 — Gates
`ruff check . && ruff format --check . && pytest` green. Client untouched (server-only).

### AC7 — Smoke gate (device)
On a fresh call right after deploy, the opening line speaks within the target with no perceptible "connecting" blank; measured via `latency_probe` + the `Spawned`→first-audio delta in `journalctl`.

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

- [ ] **Deployed** to the VPS (`deploy-server.yml` git_sha match).
- [ ] **Opening latency:** fresh call → character speaks within the D4 budget, no perceptible connecting-blank. _Proof:_ device + `journalctl` `Spawned`→`tts_first_audio` delta under target.
- [ ] **Isolation:** a second call on a reused/pooled process behaves like a cold spawn (right scenario/voice, clean meter).
- [ ] **Resilience:** kill a warmed process / exhaust the pool → call still connects (refill or cold fallback), no crash.
- [ ] **No regression:** in-call STT/LLM/TTS/checkpoints/hang-up unaffected.

## Change Log
- 2026-06-05 — Drafted (perf-surfaced from the Story 6.24 Pixel 9 smoke gate, calls 230/231). Diagnosis: the opening blank is the per-call bot-subprocess cold boot (~4.7 s) + transport connect (~1.4 s), not the TTS (150 ms); total `Spawned`→first-audio ≈ 6.3 s. Three candidate approaches (pool / persistent worker / trim-imports) + 4 open decisions. Needs a design pass before `/bmad-dev-story`.
