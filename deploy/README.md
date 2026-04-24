# CI Deploy Setup (one-time)

This is the setup checklist to bootstrap the GitHub Actions deploy pipeline
for the FastAPI server. After this, every push to `main` that touches
`server/` or `deploy/` runs the full test suite then deploys to the VPS via
rsync + atomic symlink swap.

You only run this **once**. After that, deploys are automatic.

---

## 0. Pre-flight (do this BEFORE running anything)

Confirm the local repo is committed + pushed and matches what's on the VPS:

```bash
git status                          # clean working tree
git log --oneline -5                # local main is up to date
ssh root@167.235.63.129 'ls /opt/survive-the-talk/repo/server/db/migrations/'
# Expect to see all 6 migrations (001 through 006). If anything is missing,
# the VPS is out of sync — back out and reconcile manually first.
```

---

## 1. Generate a dedicated SSH keypair for GitHub Actions

```bash
ssh-keygen -t ed25519 -C 'github-actions deploy@surviveTheTalk' \
    -f ~/.ssh/github_deploy -N ''
```

This creates `~/.ssh/github_deploy` (private) + `~/.ssh/github_deploy.pub`
(public). The private key is what goes into GitHub Secrets; the public key
is what the VPS authorises.

**Do NOT commit either key.** They're outside the repo by design.

---

## 2. Provision the VPS (creates `deploy` user, sudoers, dirs, installs uv)

```bash
ssh root@167.235.63.129 'bash -s' < deploy/setup-vps.sh "$(cat ~/.ssh/github_deploy.pub)"
```

Verify it worked:

```bash
ssh deploy@167.235.63.129 'whoami && sudo -n systemctl status pipecat.service | head -3'
# Expected: prints "deploy" then the service status block.
# If sudo prompts for a password, the sudoers file didn't install — re-run.
```

---

## 3. Migrate the VPS to the `releases/<sha>/` + `current` symlink layout

This is a **transitional one-shot**: it captures the current
`/opt/survive-the-talk/repo/server/` as `releases/<sha>/server/`, points
`current` at it, and switches the systemd unit to use the symlinked path.
The old `repo/server/` is left intact as a fallback.

```bash
# (a) Refresh the VPS repo's in-tree unit file. The migrate script reads
#     the new systemd unit from the VPS's /opt/survive-the-talk/repo/deploy/
#     checkout; if the VPS repo is stale, the migrate script would install
#     an outdated unit (WorkingDirectory still pointing at repo/server/).
#     Fail-safe: the script rejects a stale unit with a clear error — so
#     skipping this line just triggers a loud re-run prompt, not damage.
scp deploy/pipecat.service root@167.235.63.129:/opt/survive-the-talk/repo/deploy/pipecat.service

# (b) Run the migration.
ssh root@167.235.63.129 'bash -s' < deploy/migrate-to-releases.sh
```

Verify it worked:

```bash
ssh root@167.235.63.129 'systemctl status pipecat.service | head -10 && readlink /opt/survive-the-talk/current'
curl -s http://167.235.63.129/health | head
# Service active, current points at releases/<sha>, /health returns 200.
```

If anything looks wrong, the rollback is at the top of `migrate-to-releases.sh`.

---

## 4. Add GitHub Secrets

Two required, one strongly recommended (prevents SSH MITM on fresh runners):

```bash
gh secret set VPS_HOST --body '167.235.63.129'
gh secret set VPS_SSH_PRIVATE_KEY < ~/.ssh/github_deploy

# Host-key pinning (recommended — fall-back is ssh-keyscan TOFU).
# Capture the host key ONCE from a machine you trust (your laptop, where
# you've already SSH'd to the VPS manually and accepted its fingerprint):
ssh-keyscan -H 167.235.63.129 2>/dev/null | gh secret set VPS_SSH_HOST_KEY
```

If `VPS_SSH_HOST_KEY` is missing, the workflow still runs but prints a
`::warning::` each run and falls back to `ssh-keyscan` (Trust-On-First-Use
per fresh runner — acceptable for MVP, not for long-term hygiene).

Or via the web UI: `Settings → Secrets and variables → Actions → New repository secret`.

---

## 5. First deploy — manual via `workflow_dispatch`

```bash
gh workflow run 'Deploy server to VPS' --ref main
gh run watch  # follow the run live
```

You should see two jobs: `test` (ruff + pytest including
`test_migrations.py` against `prod_snapshot.sqlite`) and `deploy` (rsync to
`releases/<sha>/`, `uv sync`, atomic symlink swap, restart, healthcheck).

Once the run is green, every subsequent push to `main` touching
`server/**` or `deploy/**` deploys automatically.

---

## What happens on each deploy

1. **Test job** runs ruff + full pytest (~30s).
2. **Deploy job** (only if test passes):
   - **Verifies the VPS is migrated** (symlink `current` exists and the
     systemd unit points at `current/server`). Aborts loudly if not — this
     guards against silent-ghost deploys on an un-migrated VPS.
   - Backs up the prod DB to `/opt/survive-the-talk/backups/db.pre-<sha>.sqlite`
     using `sqlite3 .backup` (live-safe). Backups older than 14 days are
     pruned automatically.
   - rsyncs `server/` (excluding `.venv/`, `__pycache__/`, `tests/`,
     `scripts/refresh_prod_snapshot.py`) into a fresh
     `releases/<sha>/server/` on the VPS.
   - Runs `uv sync --frozen --no-dev` inside the new release dir to install
     Python deps (pinned by `uv.lock`).
   - **If `deploy/pipecat.service` changed** (sha256 diff against live unit):
     copies the new unit + `daemon-reload`. No-op otherwise.
   - Atomically swaps `current` → `releases/<sha>` (POSIX rename guarantees
     no broken-link window).
   - Restarts `pipecat.service` (which now resolves the symlink to the new
     code), then polls `/health` 5× before declaring success.
   - On success: prunes everything but the last 3 releases.
3. **On failure**: the symlink is NOT swapped (if the failure is in test or
   rsync). If the failure is post-restart (healthcheck), the symlink IS
   already swapped — manual rollback by SSHing to VPS and pointing `current`
   at the previous release dir, then restarting.

## Rollback (manual, one liner)

```bash
ssh deploy@167.235.63.129 \
  'PREV=$(ls -1t /opt/survive-the-talk/releases | sed -n 2p) && \
   ln -sfn /opt/survive-the-talk/releases/$PREV /opt/survive-the-talk/current.new && \
   mv -Tf /opt/survive-the-talk/current.new /opt/survive-the-talk/current && \
   sudo -n /bin/systemctl restart pipecat.service'
```

That's 2-second rollback **for the code** — but see the caveat below.

### Rollback caveat: forward-only DB migrations

Migrations in `server/db/migrations/` are forward-only (`run_migrations` has
no down step). If release N applied a destructive migration (e.g. dropped a
column, added NOT NULL without default), release N-1 may crash at boot or
behave incorrectly against the migrated schema.

The `/opt/survive-the-talk/backups/db.pre-<sha>.sqlite` snapshot is your
real escape hatch in that case — but restoring it is a manual operation
(stop service, `cp backup → db.sqlite`, restart), not the 2-second
symlink-swap rollback above.

**Rule of thumb** : before deploying a PR that introduces an irreversible
migration, accept that rollback-to-previous-release is no longer a clean
option. Plan ahead (dual-write, soft-drop, ship in two passes).

---

## Known gaps (separate stories)

These are deliberate scope limits — Plan agent flagged them as worth doing,
but they don't block the core CI pipeline. Pick up in their own story:

- **No `PRAGMA journal_mode=WAL`.** Currently a write-during-restart can
  block the migration. WAL mode would let reads continue. Trivial change in
  `db/database.py::get_connection`.
- **systemd unit now runs as `www-data`** (this pipeline switched it from
  the prior root pattern — Review 1). DB perms aligned by `setup-vps.sh`
  step 5. Further hardening (seccomp, `NoNewPrivileges=yes`, capability
  drop, `ProtectSystem=strict`) deferred to a sysd-hardening story.
- **No business smoke test in CI.** `/health` 200 ≠ login works. A future
  story can add a `curl POST /auth/request-code` step that asserts the auth
  flow round-trips.
- **SSH key rotation.** The `github_deploy` key in GitHub Secrets should be
  rotated every ~6 months. Set a reminder.
- **`VPS_SSH_HOST_KEY` fallback.** If the secret is missing, the workflow
  warns and falls back to TOFU `ssh-keyscan`. Set the secret once (see §4)
  to silence it.
