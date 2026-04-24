# Deferred Work

Items flagged during code review but postponed — each entry records where the review surfaced it and why it was not actioned at the time.

## Deferred from: code review of story 4-5-build-first-call-incoming-call-experience (2026-04-23)

- **Bot subprocess never reaped** — `server/api/routes_calls.py:63-76` fires `subprocess.Popen` and never tracks it. Real lifecycle (terminate on call-end, zombie cleanup) belongs to Epic 6.4 / 7.1 via `POST /calls/{id}/end`.
- **`CallPlaceholderScreen` has no LiveKit timeout / reconnect / disconnect-event handler** — `call_placeholder_screen.dart:34-60` silently hangs on "Connecting to Tina…" if the room never comes up. Spec scopes real call UX (including error recovery) to Epic 6.2 Story 6.2.
- **Mic permission revoked between onboarding and `/call` not user-guided** — `call_placeholder_screen.dart:44-58` catches the failure and shows a generic "Couldn't connect" without offering a path back to settings. Epic 6.2 owns the real mic-error UX.
- **No rate-limit / per-user in-flight guard on `/calls/initiate`** — `routes_calls.py:33-101` allows unbounded subprocess spawns per user. Post-MVP infrastructure concern (middleware / Redis / idempotency key).
- **Migration `002_calls.sql` has no explicit `ON DELETE` policy on `user_id` FK** — defaults to `NO ACTION`, which blocks user deletion when call rows exist. Intentional (preserves audit trail) but undocumented; re-visit when user deletion / GDPR erasure lands.

## Deferred from: code review of story 5-1-build-scenarios-api-and-database (2026-04-24)

- **`run_migrations()` + `executescript` breaks outer `BEGIN IMMEDIATE` atomicity** — `server/db/database.py:82-104` wraps each migration in `BEGIN IMMEDIATE`, re-checks `schema_migrations`, then calls `db.executescript(sql)` which silently COMMITs the outer transaction before running the script. Consequence: (1) the `INSERT INTO schema_migrations(...)` is no longer atomic with the DDL — a crash mid-script can leave the DB partially migrated with no tracking row, (2) the "workers serialise via the lock" claim in the docstring is broken for any migration whose script takes >1 statement. Pre-existing in 001/002; amplified by 003-006 which each carry their own `BEGIN;/COMMIT;`. Root fix = rework `run_migrations` to split statements instead of using `executescript`, or switch to `isolation_level=None` + explicit savepoints.
  - **When to address**: before the first migration that (a) runs multiple DDL statements that MUST be atomic with `schema_migrations` insertion (e.g. a data migration where partial application is dangerous), OR (b) deploys with >1 uvicorn worker. The current VPS runs a single worker, so the multi-worker race is latent.
  - **Trigger check**: any future story that adds a migration performing data transformation (not just schema DDL) — grep the migration for `UPDATE` / `INSERT INTO` against existing tables. Also: the day `deploy/pipecat.service` or `gunicorn/uvicorn` invocation grows a `--workers N` flag with N>1.
  - **Owner/Route**: Architecture (Winston) — plan a `server/db/database.py` refactor, verify with the `prod_snapshot` test harness added in Story 5.1 (Change Log entry 4).

- **No `PRAGMA busy_timeout` on `get_connection()`** — `server/db/database.py:28-41` opens aiosqlite connections without a busy-timeout PRAGMA. Under multi-worker uvicorn, two lifespans racing to `BEGIN IMMEDIATE` (now both `run_migrations` AND `seed_scenarios`) can raise `sqlite3.OperationalError: database is locked` immediately instead of blocking. Pre-existing; amplified by this story adding a second write-lock consumer in the lifespan. Fix = `await db.execute("PRAGMA busy_timeout = 5000")` alongside the existing `foreign_keys` pragma.
  - **When to address**: same trigger as above (multi-worker deploy). Also: as soon as ANY user-facing write path (beyond lifespan startup) is introduced that could contend with the seeder, e.g. Story 6.4 `POST /calls/{id}/end` if it updates `user_progress`.
  - **Trigger check**: any PR that (a) sets `--workers > 1` anywhere (scan `deploy/pipecat.service`, `deploy/setup-vps.sh`, README deploy docs), OR (b) adds a new lifespan-phase DB write alongside `seed_scenarios` / `run_migrations`.
  - **Owner/Route**: one-line fix; can be rolled into the first story that trips the trigger. Very cheap — `await db.execute("PRAGMA busy_timeout = 5000")` in `get_connection()`.

### How these items get surfaced
Both items live in `server/db/database.py` — any future story that edits that file should re-read this section first. Consider adding a comment at the top of `database.py` pointing here ("See `deferred-work.md` §Story 5-1 before touching this file") so nobody rewrites the migration runner without picking them up.

## Deferred from: code review of 5-1-CI-deploy (2026-04-24)

The CI deploy pipeline (GitHub Actions → VPS) went through adversarial review against the ten trap axes specified in the review prompt. BLOCKERs (DB write perms, `migrate-to-releases.sh` path bug, migration-guard) and MAJORs (host-key TOFU, sudoers wildcard, trigger path filter, unit auto-sync, env ownership, `/health` git_sha hardening) were fixed inline. The items below are real, but not blocking the first `gh workflow run`. Each entry records when it becomes worth doing.

- **`migrate-to-releases.sh` copies `.venv` with possibly-broken entry-point shebangs** — `cp -a /opt/.../repo/server` preserves the existing `.venv`. `.venv/bin/python` is a symlink → `/usr/bin/python3.12` ✓, so the ExecStart invocation works. But `.venv/bin/ruff`, `.venv/bin/alembic`, etc. have absolute shebangs pointing at the *old* `.venv` path. The bridge release's `.venv` is therefore a "ghost" — any code path that invokes entry-points (not just `python main.py`) would silently run the old binaries. The first real CI deploy rebuilds `.venv` from scratch via `uv sync`, so this only affects the bridge window.
  - **Fix shape**: add `sudo -u deploy ~deploy/.local/bin/uv sync --frozen --no-dev` inside `$RELEASE_DIR/server` in `migrate-to-releases.sh`, after the `chown -R` and before the symlink swap.
  - **When to address**: only if the bridge window ever runs anything beyond `python main.py`. Today it doesn't. Re-evaluate the day something in main.py imports a package that shells out to a venv-bin script.
  - **Trigger check**: if a PR introduces `subprocess.run([".venv/bin/..."])` or similar in main.py or its import chain.

- **`uv` is installed via `curl ... astral.sh/uv/install.sh | sh`, no version pinning** — `deploy/setup-vps.sh` step 6. If astral ever changes the install path (e.g. from `~/.local/bin/uv` to `~/.local/share/uv/bin/uv`), the workflow's `$HOME/.local/bin/uv` reference in the "Install Python deps" step breaks silently.
  - **Fix shape**: `curl -LsSf https://astral.sh/uv/<VERSION>/install.sh | sh` with a pinned `<VERSION>`, kept in sync with the `uv` version used in the test job (`astral-sh/setup-uv@v3` auto-picks latest).
  - **When to address**: first time a CI deploy fails with "uv: command not found" on the VPS. Also worth doing preemptively on the next major uv release if astral's changelog mentions path changes.
  - **Trigger check**: grep `astral-sh/setup-uv` in `.github/workflows/` and correlate its version with `setup-vps.sh` install script.

- **`xargs -I{} rm -rf {}` in release pruning is not safe against filenames with spaces/newlines** — `.github/workflows/deploy-server.yml` "Prune old releases" step. Release dirs are git-SHA-keyed (7 hex chars), safe today. Only a risk if someone manually creates a release dir with an unusual name.
  - **Fix shape**: replace with `find $VPS_RELEASES -mindepth 1 -maxdepth 1 -type d | sort -r | tail -n +4 | xargs -r -d '\n' rm -rf --`, or a while-read loop.
  - **When to address**: if anyone ever creates a release dir by hand (e.g. during ops recovery) — prune becomes unpredictable. Cheap one-liner to swap in pre-emptively.

- **Pruning may delete the only rollback target if a healthcheck falsely passes** — workflow's "Prune old releases" runs on `if: success()`. If a deploy swapped the symlink, healthcheck passed on the NEW release, but the release is actually buggy in a way that only manifests later (logs, batch jobs, WebRTC flow), the prune has kept only the last 3 releases including the bad one. Rollback to N-4 is impossible via symlink swap.
  - **Fix shape**: keep last 5 (or configurable via env var), or gate prune behind an "acknowledge deploy success" delay (e.g., only prune on the NEXT successful deploy, which implies the current one stayed healthy).
  - **When to address**: first post-deploy incident where rollback was needed but the target was already pruned. Or when adding real user load (Epic 7+).

- **Backup disk growth** — workflow creates `db.pre-<sha>.sqlite` each deploy, retains 14 days. At today's ~50KB DB × 30 deploys/day × 14 days = 21MB ✓. When DB reaches 100MB (realistic post-MVP), same cadence = 42GB, which approaches Hetzner small-VPS disk budget.
  - **Fix shape**: replace `-mtime +14` with `ls -1t | tail -n +N` (keep last N regardless of age), OR add a size-cap (keep backups under X GB total).
  - **When to address**: when `du -sh /opt/survive-the-talk/backups` crosses 1GB, OR before a growth story (e.g., call transcripts in DB).
  - **Trigger check**: any migration that adds a new large table (transcripts, audio metadata, call logs).

- **pipecat.service has no `StartLimitBurst` / `StartLimitIntervalSec`** — `Restart=on-failure RestartSec=5s` without burst limit means a boot-broken service crashes-loops forever. The workflow's 5-attempt healthcheck window (15s) can coincidentally catch a "starting" window before the next crash and report green.
  - **Fix shape**: add `StartLimitBurst=5` and `StartLimitIntervalSec=60` under `[Service]`, plus `StartLimitAction=none`. Combined with the healthcheck step, a repeatedly-failing service cleanly signals "down".
  - **When to address**: first incident where a buggy release crash-looped and healthcheck passed ambiguously. Also: cheap, can be in the same PR as the `/health` `git_sha` hardening.
  - **Trigger check**: any PR that edits `deploy/pipecat.service` should pick this up opportunistically.

- **No SSH connection multiplexing in the workflow** — the deploy job opens 6+ separate SSH sessions (verify guard, backup, rsync, deps-install, unit-sync, swap, restart, journalctl-on-fail). Each pays ~2s handshake. OpenSSH `ControlMaster=auto` + `ControlPersist=10m` would cut ~10s off each deploy.
  - **Fix shape**: add an `~/.ssh/config` step that sets `ControlMaster=auto ControlPath=/tmp/cm-%r@%h:%p ControlPersist=10m` for the VPS host, early in the job.
  - **When to address**: when deploy latency becomes a developer-experience pain (probably once per-push cadence > a few per hour, or when Epic 6+ has many rapid iteration cycles).

- **`deploy/backup.sh` is an unused placeholder** — predates the CI workflow's inline `sqlite3 .backup`. Not called by anything, not on cron.
  - **Fix shape**: either delete the file, or wire it up to a systemd timer for a nightly non-deploy backup (orthogonal to the pre-deploy backup done by the workflow).
  - **When to address**: during a cleanup pass, OR when a "daily cold backup independent of deploy cadence" becomes a real need (e.g., for GDPR 30-day retention).

- **`deploy/Caddyfile` / `deploy/caddy.service` are not part of the CI pipeline** — the narrower path filter in the workflow trigger (§MAJOR #7 fix) excludes them correctly, but that also means Caddy changes require manual SSH + `systemctl reload caddy`. Not currently documented.
  - **Fix shape**: either (a) add a one-sentence note in `deploy/README.md` "How Caddy changes are applied", OR (b) extend the pipeline to scp+reload Caddy similarly to pipecat.service.
  - **When to address**: first time someone edits `Caddyfile` and forgets to reload Caddy on the VPS.

- **Deploy summary step has no context when healthcheck fails** — `Deploy summary` runs `if: always()`, prints release id and commit. But when the healthcheck fails, the user sees the journalctl dump inline AND the summary separately; ordering in the GH UI can be confusing.
  - **Fix shape**: fold the journalctl dump into a `if: failure()` "Deploy diagnostics" step AFTER the healthcheck, and always print `systemctl status pipecat.service | head -10` in the summary for success-path visibility.
  - **When to address**: first time a deploy fails and the GH UI is hard to read. Cheap UX polish.

### How these items get surfaced
Most of these live in `.github/workflows/deploy-server.yml`, `deploy/setup-vps.sh`, or `deploy/pipecat.service` — any future story that edits deploy infrastructure should re-read this section first. If the "Known gaps" section in `deploy/README.md` grows, sync it here (or inversely — the README "Known gaps" is already a bridge to this file).
