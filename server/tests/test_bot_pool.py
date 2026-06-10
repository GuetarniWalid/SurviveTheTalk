"""Story 6.26 — `pipeline.bot_pool.BotPool` (warm bot-process pool).

These tests drive the REAL asyncio-subprocess machinery (spawn, readiness
sentinel on stdout, job line on stdin, terminate) — but against a LIGHTWEIGHT
stub process (`python -c ...`) instead of the heavy bot, so they run fast while
still exercising the actual IPC the production pool relies on (the project's
"drive the real thing, don't mock the boundary" rule — server/CLAUDE.md §1).

Pattern: sync test → `asyncio.run(_scenario())` (no pytest-asyncio in this repo,
mirrors `test_janitor.py`). Every pool is `stop()`-ed in a finally so no stub
process leaks. `maintain_interval` is set huge so the maintainer never fires
mid-test (refill-on-acquire is tested directly).
"""

import asyncio
import json
import os
import sys

from loguru import logger as loguru_logger

from pipeline.bot_pool import BotPool

# --- Stub parked-bot processes -------------------------------------------------

# Healthy parked bot: announce readiness, block for one stdin job line, write the
# received line to STUB_JOB_FILE (so the test can assert delivery), then exit.
_GOOD_STUB = (
    "import sys, os\n"
    "sys.stdout.write('BOT_PARKED_READY\\n'); sys.stdout.flush()\n"
    "line = sys.stdin.readline()\n"
    "if line:\n"
    "    p = os.environ.get('STUB_JOB_FILE')\n"
    "    if p:\n"
    "        open(p, 'w').write(line)\n"
)

# Becomes ready then immediately exits (simulates a parked bot that crashed while
# idle, AFTER it had been marked ready).
_DEAD_IDLE_STUB = (
    "import sys\nsys.stdout.write('BOT_PARKED_READY\\n'); sys.stdout.flush()\n"
)

# Never prints the sentinel and blocks forever — exercises the boot timeout.
_STUCK_STUB = "import time\ntime.sleep(60)\n"


def _command(stub: str) -> list[str]:
    return [sys.executable, "-c", stub]


def _stub_env(extra: dict | None = None) -> dict:
    # Inherit the full env (Windows needs PATH/SystemRoot to launch python) +
    # any test-specific keys.
    return {**os.environ, **(extra or {})}


async def _wait_until(
    predicate, *, timeout: float = 8.0, interval: float = 0.05
) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return predicate()


# --- Tests ---------------------------------------------------------------------


def test_ready_sentinel_matches_bot_constant() -> None:
    """Drift guard — the pool's hard-coded sentinel must equal the one the bot
    actually prints (`bot.PARKED_READY_SENTINEL`). The pool can't import the
    heavy bot module, so this is the single cross-check that keeps them in sync.
    """
    from pipeline.bot import PARKED_READY_SENTINEL
    from pipeline.bot_pool import _READY_SENTINEL

    assert _READY_SENTINEL == PARKED_READY_SENTINEL.encode()


def test_pool_starts_and_fills_to_size() -> None:
    async def _scenario() -> None:
        pool = BotPool(
            size=2,
            command=_command(_GOOD_STUB),
            env=_stub_env(),
            maintain_interval=3600,
        )
        await pool.start()
        try:
            assert await _wait_until(lambda: pool.ready_count() == 2)
            assert pool.ready_count() == 2
        finally:
            await pool.stop()

    asyncio.run(_scenario())


def test_acquire_delivers_job_and_refills(tmp_path) -> None:
    async def _scenario() -> None:
        job_file = tmp_path / "job.json"
        pool = BotPool(
            size=1,
            command=_command(_GOOD_STUB),
            env=_stub_env({"STUB_JOB_FILE": str(job_file)}),
            maintain_interval=3600,
        )
        await pool.start()
        try:
            assert await _wait_until(lambda: pool.ready_count() == 1)
            job = {
                "url": "wss://lk",
                "room": "call-xyz",
                "token": "agent-tok",
                "env": {"SCENARIO_ID": "waiter_easy_01", "CALL_ID": "7"},
            }
            assert await pool.acquire(job) is True

            # The acquired stub wrote the job line it received to the file.
            assert await _wait_until(lambda: job_file.exists() and job_file.read_text())
            delivered = json.loads(job_file.read_text())
            assert delivered == job

            # Refill-on-acquire restores the pool back to size.
            assert await _wait_until(lambda: pool.ready_count() == 1)
        finally:
            await pool.stop()

    asyncio.run(_scenario())


def test_acquire_on_empty_pool_returns_false() -> None:
    """No ready bot (pool never started) → acquire reports a miss so the caller
    cold-spawns. No process is spawned."""

    async def _scenario() -> None:
        pool = BotPool(size=1, command=_command(_GOOD_STUB), env=_stub_env())
        # Deliberately NOT started → ready deque empty.
        assert await pool.acquire({"url": "u", "room": "r", "token": "t"}) is False

    asyncio.run(_scenario())


def test_zero_size_pool_is_noop() -> None:
    """AC4b kill-switch — size 0 spawns nothing, always reports a miss, and
    stop() is a clean no-op."""

    async def _scenario() -> None:
        pool = BotPool(size=0, command=_command(_GOOD_STUB), env=_stub_env())
        await pool.start()
        try:
            assert pool.ready_count() == 0
            assert await pool.acquire({"url": "u", "room": "r", "token": "t"}) is False
        finally:
            await pool.stop()

    asyncio.run(_scenario())


def test_acquire_skips_dead_idle_bot() -> None:
    """A parked bot that died while idle is reaped (not handed a call) — acquire
    reports a miss → caller cold-spawns. AC4 resilience."""

    async def _scenario() -> None:
        pool = BotPool(
            size=1,
            command=_command(_DEAD_IDLE_STUB),
            env=_stub_env(),
            maintain_interval=3600,
        )
        await pool.start()
        try:
            # It was marked ready, then exited — wait for it to actually die.
            assert await _wait_until(lambda: pool.ready_count() == 0)
            assert await pool.acquire({"url": "u", "room": "r", "token": "t"}) is False
        finally:
            await pool.stop()

    asyncio.run(_scenario())


def test_boot_timeout_discards_unready_bot() -> None:
    """A parked bot that never signals ready within the boot timeout is killed +
    discarded (not added to the pool). AC4 — a wedged boot can't poison the pool."""

    async def _scenario() -> None:
        pool = BotPool(
            size=1,
            command=_command(_STUCK_STUB),
            env=_stub_env(),
            boot_timeout=0.5,
            maintain_interval=3600,
        )
        await pool.start()
        try:
            assert pool.ready_count() == 0
        finally:
            await pool.stop()

    asyncio.run(_scenario())


def test_acquire_send_job_midflight_death_reports_miss() -> None:
    """Story 6.26 review — the trickiest race in the module: the parked bot
    passes the liveness check but its stdin breaks at the job write (it died
    mid-flight). `acquire` must swallow the pipe error, WARN, and report a miss
    so the caller cold-spawns — never drop the call, never re-queue that bot."""

    async def _scenario() -> None:
        pool = BotPool(
            size=1,
            command=_command(_GOOD_STUB),
            env=_stub_env(),
            maintain_interval=3600,
        )
        await pool.start()
        try:
            assert await _wait_until(lambda: pool.ready_count() == 1)
            bot = pool._ready[0]  # noqa: SLF001 — white-box: fault-inject the write

            async def _broken_send(job: dict) -> None:
                raise BrokenPipeError("stdin gone mid-flight")

            bot.send_job = _broken_send

            captured: list[str] = []
            sink_id = loguru_logger.add(captured.append, level="WARNING")
            try:
                assert (
                    await pool.acquire({"url": "u", "room": "r", "token": "t"}) is False
                )
            finally:
                loguru_logger.remove(sink_id)
            assert any("died before job" in entry for entry in captured)
            # The dead-at-write bot was popped and must NOT be back in the deque.
            assert bot not in pool._ready  # noqa: SLF001
            await bot.terminate()  # the stub is actually alive — reap it
        finally:
            await pool.stop()

    asyncio.run(_scenario())


def test_concurrent_fills_never_overshoot_size() -> None:
    """Story 6.26 review — the module's headline `_spawning` reserved-slot
    invariant: N concurrent fills (acquire refills racing the maintainer) must
    together spawn EXACTLY the deficit, never overshoot `size`."""

    async def _scenario() -> None:
        pool = BotPool(
            size=2,
            command=_command(_GOOD_STUB),
            env=_stub_env(),
            maintain_interval=3600,
        )
        spawned = 0
        real_spawn_one = pool._spawn_one  # noqa: SLF001 — count the real spawns

        async def _counting_spawn_one():
            nonlocal spawned
            spawned += 1
            return await real_spawn_one()

        pool._spawn_one = _counting_spawn_one  # noqa: SLF001
        try:
            await asyncio.gather(*(pool._ensure_full() for _ in range(5)))  # noqa: SLF001
            assert pool.ready_count() == 2
            assert spawned == 2  # exactly the deficit — no overshoot
        finally:
            await pool.stop()

    asyncio.run(_scenario())


def test_stop_terminates_idle_bots() -> None:
    """stop() terminates the idle parked bots so they don't outlive the server."""

    async def _scenario() -> None:
        pool = BotPool(
            size=2,
            command=_command(_GOOD_STUB),
            env=_stub_env(),
            maintain_interval=3600,
        )
        await pool.start()
        assert await _wait_until(lambda: pool.ready_count() == 2)
        # Grab the live handles before stop() clears the deque.
        bots = list(pool._ready)  # noqa: SLF001 — white-box assertion on teardown
        assert len(bots) == 2

        await pool.stop()

        assert await _wait_until(lambda: all(not b.is_alive() for b in bots))
        assert all(not b.is_alive() for b in bots)
        assert pool.ready_count() == 0

    asyncio.run(_scenario())
