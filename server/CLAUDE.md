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
