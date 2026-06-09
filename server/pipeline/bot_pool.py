"""Story 6.26 — warm bot-process pool (kills the opening cold-boot blank).

Each call normally spawns a brand-new bot subprocess that pays a ~4.7 s cold
import boot (torch/pipecat/livekit/soniox/onnx) on the call's critical path
before it can speak — the opening blank. This pool keeps `size` already-booted
"parked" bots idle and ready: a parked bot pre-pays the import boot, prints the
`BOT_PARKED_READY` sentinel, then blocks reading one JSON job line from stdin.
On call start the pool writes the job (url/room/token + per-call env) to a parked
bot's stdin and that bot runs the call — skipping the boot. A parked bot serves
exactly ONE call then exits (clean isolation, identical lifecycle to a cold
spawn). `initiate_call` falls back to a cold `Popen` whenever the pool is empty
or disabled (`size=0`), so no call can ever fail because of the pool.

Lifecycle / invariants:
- `start()` fills the pool to `size` and starts a maintainer loop.
- `acquire(job)` hands a ready bot the job, schedules an immediate refill, and
  returns True; it returns False when no ready bot is available (caller
  cold-spawns). Reserved-slot accounting (`_spawning`) keeps
  `ready + in-flight-spawns <= size` at all times, so the pool never overshoots.
- the maintainer loop reaps idle crashes and tops the pool back up to `size`.
- `stop()` terminates idle parked bots and cancels the maintainer.

The spawn command + readiness IO are real (asyncio subprocess), so tests drive a
lightweight stub process via the `command=` injection rather than the heavy bot
— same machinery, fast. Mirrors the janitor's bounded-teardown discipline
(`api/app.py`) so a wedged parked bot can't starve systemd's TimeoutStopSec.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import deque

from loguru import logger

# Default parked-bot command: a generic, job-less bot that waits on stdin.
_DEFAULT_PARKED_COMMAND = [sys.executable, "-m", "pipeline.bot", "--parked"]

# Match `bot.PARKED_READY_SENTINEL` WITHOUT importing the heavy bot module here
# (the pool lives in the lightweight FastAPI process and must not pull in
# torch/pipecat). Drift between the two constants is caught by
# `test_bot_pool.py::test_ready_sentinel_matches_bot_constant`, which imports
# both and asserts they agree.
_READY_SENTINEL = b"BOT_PARKED_READY"

# How long a parked bot may take to finish its import boot + print the sentinel
# before we give up on it (the cold boot is ~4.7 s; allow generous headroom for
# a loaded VPS). A timed-out spawn is killed + discarded; the maintainer retries.
_BOOT_TIMEOUT_SECONDS = 30.0

# Maintainer cadence — how often to reap idle crashes + top the pool back up to
# size. Short enough to recover an idle-crashed slot quickly, long enough to be
# cheap (refill-on-acquire is the fast path; this is the safety net).
_MAINTAIN_INTERVAL_SECONDS = 20.0

# Bound a terminate/kill→reap wait so a wedged parked bot can't starve systemd's
# TimeoutStopSec on shutdown (mirrors the janitor's bounded teardown).
_REAP_TIMEOUT_SECONDS = 5.0


class ParkedBot:
    """A booted, idle bot subprocess waiting for one job on its stdin."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc

    @property
    def pid(self) -> int:
        return self._proc.pid

    def is_alive(self) -> bool:
        return self._proc.returncode is None

    async def send_job(self, job: dict) -> None:
        """Write the one job line the parked bot is blocked reading on stdin."""
        if self._proc.stdin is None:  # pragma: no cover — defensive
            raise BrokenPipeError("parked bot has no stdin pipe")
        self._proc.stdin.write((json.dumps(job) + "\n").encode())
        await self._proc.stdin.drain()

    async def terminate(self) -> None:
        """SIGTERM an idle parked bot (blocked on stdin) and reap it, bounded."""
        await _reap(self._proc, signal="terminate")


async def _reap(proc: asyncio.subprocess.Process, *, signal: str) -> None:
    """Best-effort terminate/kill + bounded wait so we never leak a zombie."""
    if proc.returncode is not None:
        return
    try:
        getattr(proc, signal)()  # proc.terminate() | proc.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_REAP_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


class BotPool:
    """Keeps `size` warm parked bots ready to adopt a call (Story 6.26)."""

    def __init__(
        self,
        *,
        size: int,
        command: list[str] | None = None,
        env: dict | None = None,
        boot_timeout: float = _BOOT_TIMEOUT_SECONDS,
        maintain_interval: float = _MAINTAIN_INTERVAL_SECONDS,
    ) -> None:
        self._size = max(0, size)
        self._command = command or _DEFAULT_PARKED_COMMAND
        self._env = env
        self._boot_timeout = boot_timeout
        self._maintain_interval = maintain_interval
        self._ready: deque[ParkedBot] = deque()
        # Slots reserved by an in-flight `_spawn_one` (counted toward capacity so
        # concurrent fills can't overshoot `size`).
        self._spawning = 0
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._maintainer: asyncio.Task | None = None

    @property
    def size(self) -> int:
        return self._size

    def ready_count(self) -> int:
        """Number of alive, idle parked bots currently ready to be acquired."""
        return sum(1 for b in self._ready if b.is_alive())

    async def start(self) -> None:
        """Fill the pool to `size` and start the maintainer (no-op when size=0)."""
        if self._size == 0:
            logger.info("bot_pool disabled (BOT_POOL_SIZE=0) — every call cold-spawns")
            return
        await self._ensure_full()
        self._maintainer = asyncio.create_task(self._maintain_loop())
        logger.info(f"bot_pool ready size={self._size} ready={self.ready_count()}")

    async def acquire(self, job: dict) -> bool:
        """Hand a ready parked bot the job + refill. False ⇒ caller cold-spawns."""
        async with self._lock:
            bot = self._pop_alive_locked()
            if bot is None:
                return False
            try:
                await bot.send_job(job)
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                # The parked bot died between our liveness check and the write.
                # Treat as a miss so the caller cold-spawns (never drop a call).
                logger.warning(
                    f"bot_pool: parked bot pid={bot.pid} died before job ({exc}); "
                    "reporting pool miss → cold spawn"
                )
                return False
        # Refill outside the lock — spawning pays the full ~4.7 s boot.
        asyncio.create_task(self._ensure_full())
        logger.info(
            f"bot_pool acquired parked bot pid={bot.pid} ready={self.ready_count()}"
        )
        return True

    def _pop_alive_locked(self) -> ParkedBot | None:
        """Pop the next alive ready bot, discarding any that died while idle."""
        while self._ready:
            bot = self._ready.popleft()
            if bot.is_alive():
                return bot
            logger.warning(f"bot_pool reaped dead idle parked bot pid={bot.pid}")
        return None

    async def _ensure_full(self) -> None:
        """Spawn until `ready + spawning == size`, reserving slots under the lock.

        Reserving (`self._spawning += deficit`) BEFORE releasing the lock to do
        the slow spawn is what keeps two concurrent fills (e.g. an acquire refill
        racing the maintainer) from together overshooting `size`.
        """
        if self._stop.is_set():
            return
        async with self._lock:
            self._reap_idle_locked()
            deficit = self._size - (len(self._ready) + self._spawning)
            if deficit <= 0:
                return
            self._spawning += deficit
        # `_spawn_one` never raises (it maps every failure to None), so `gather`
        # resolves to a list of `ParkedBot | None`. Init `bots` first so the
        # finally always has it bound even if the gather is cancelled.
        bots: list[ParkedBot | None] = []
        try:
            bots = list(
                await asyncio.gather(*(self._spawn_one() for _ in range(deficit)))
            )
        finally:
            async with self._lock:
                self._spawning -= deficit
                for bot in bots:
                    if bot is None:
                        continue
                    if self._stop.is_set():
                        # Stopped mid-spawn — don't leak the freshly booted bot.
                        asyncio.create_task(bot.terminate())
                    else:
                        self._ready.append(bot)

    def _reap_idle_locked(self) -> None:
        """Drop dead idle bots from the ready deque (caller holds the lock)."""
        self._ready = deque(b for b in self._ready if b.is_alive())

    async def _spawn_one(self) -> ParkedBot | None:
        """Spawn one parked bot and await its readiness sentinel.

        Returns the handle once the boot completes, or None on spawn error /
        boot timeout / the process dying during boot (caller's slot accounting
        already released; the maintainer will retry).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                env=self._env,
            )
        except OSError:
            logger.exception("bot_pool failed to spawn a parked bot")
            return None
        try:
            ready = await asyncio.wait_for(
                self._await_ready(proc), timeout=self._boot_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                "bot_pool parked bot did not signal ready within "
                f"{self._boot_timeout}s; discarding"
            )
            ready = False
        if not ready:
            await _reap(proc, signal="kill")
            return None
        return ParkedBot(proc)

    async def _await_ready(self, proc: asyncio.subprocess.Process) -> bool:
        """Read stdout lines until the readiness sentinel (True) or EOF (False)."""
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:  # EOF — the process died during boot
                return False
            if _READY_SENTINEL in line:
                return True

    async def _maintain_loop(self) -> None:
        """Periodic safety net: reap idle crashes + top the pool back up."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._maintain_interval
                )
                return  # stop signalled — exit the loop
            except asyncio.TimeoutError:
                pass
            try:
                await self._ensure_full()
            except Exception:
                logger.exception("bot_pool maintainer top-up failed; will retry")

    async def stop(self) -> None:
        """Signal stop, cancel the maintainer, terminate idle parked bots."""
        self._stop.set()
        if self._maintainer is not None:
            self._maintainer.cancel()
            try:
                await self._maintainer
            except (asyncio.CancelledError, Exception):
                pass
            self._maintainer = None
        async with self._lock:
            idle = list(self._ready)
            self._ready.clear()
        for bot in idle:
            await bot.terminate()
