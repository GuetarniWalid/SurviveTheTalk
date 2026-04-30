#!/usr/bin/env bash
# One-shot VPS provisioning for CI-driven deploys (Story 5.1 retro #2).
#
# Run ONCE on the VPS as root, after generating an SSH keypair locally for
# GitHub Actions:
#
#   scp ~/.ssh/github_deploy.pub root@167.235.63.129:/tmp/gh_pubkey.pub
#   scp deploy/prune-releases.sh root@167.235.63.129:/tmp/prune-releases.sh
#   ssh root@167.235.63.129 'bash -s' < deploy/setup-vps.sh
#
# Re-running is safe — every step below is idempotent. Re-run when:
#   - sudoers grants change (e.g. step 3 adds a new entry)
#   - deploy/prune-releases.sh changes (step 7 reinstalls it)
#   - deploy user permissions need refreshing
#
# (The two-step pattern — scp first, then bash -s — is robust against shell
#  word-splitting of the pubkey. An earlier single-line form passed the key
#  via `bash -s "$(cat pubkey)"` which split the key on whitespace and wrote
#  only "restrict ssh-ed25519" to authorized_keys. Don't go back to that.)
#
# What it does (idempotent — safe to re-run):
#   1. Creates the `deploy` user with a locked password (SSH-key-only) and
#      adds it to the `www-data` group (so deploy + www-data can co-read files).
#   2. Authorises the GitHub Actions public key for that user.
#   3. Grants `deploy` narrow sudo: systemctl (restart/status/daemon-reload),
#      journalctl read, installing a new pipecat.service unit, and running
#      the release-pruner wrapper.
#   4. Creates the `releases/`, `backups/` directories with `deploy` ownership.
#   5. Aligns `/opt/survive-the-talk/.env`, `data/`, and `data/db.sqlite` so
#      the runtime user `www-data` can read .env / read+write the DB, AND the
#      `deploy` user can read the DB for backups. This is the BLOCKER that
#      would otherwise crash pipecat at first write (service user = www-data
#      per pipecat.service; default perms don't grant www-data DB write).
#   6. Installs system tooling: sqlite3 CLI (for workflow backup step) + uv
#      (Python pkg manager — used to keep prod venv in sync with uv.lock).
#   7. Installs deploy/prune-releases.sh to /usr/local/sbin/ so the workflow
#      can prune old release dirs as root (sidestepping the cross-owner
#      `.pyc` problem from pipecat.service running as www-data).
#
# What it does NOT do:
#   - Touch the running `pipecat.service` unit (migrate-to-releases.sh does
#     the one-shot install; the CI workflow refreshes the unit on subsequent
#     deploys if deploy/pipecat.service has changed).
#   - Migrate the existing `repo/server/` to the `releases/<sha>/` layout —
#     that's `deploy/migrate-to-releases.sh`'s job, run AFTER this script.

set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: must run as root (use 'ssh root@VPS')." >&2
    exit 1
fi

# Read the GitHub Actions deploy pubkey from a known VPS path. The caller
# scp's it there first — see the docstring at the top of this file. This
# two-step pattern avoids the shell-word-splitting trap of passing the key
# via argv (the space between "ssh-ed25519" and the base64 body becomes a
# word boundary, and $1 collapses to just "ssh-ed25519").
PUBKEY_PATH=/tmp/gh_pubkey.pub
if [[ ! -f "$PUBKEY_PATH" ]]; then
    echo "ERROR: $PUBKEY_PATH not found. Copy the public key to the VPS first:" >&2
    echo "  scp ~/.ssh/github_deploy.pub root@VPS:$PUBKEY_PATH" >&2
    echo "  ssh root@VPS 'bash -s' < deploy/setup-vps.sh" >&2
    exit 1
fi
GH_PUBKEY=$(cat "$PUBKEY_PATH")
if [[ -z "${GH_PUBKEY// }" ]]; then
    echo "ERROR: $PUBKEY_PATH is empty." >&2
    exit 1
fi

echo "==> 1/7 Creating deploy user"
if ! id -u deploy >/dev/null 2>&1; then
    useradd -m -s /bin/bash deploy
    passwd -l deploy  # SSH-key-only, no password login
    echo "    created"
else
    echo "    already exists, skipping"
fi
# deploy must be in www-data group so it can READ the DB (owned by www-data,
# mode 660) when the workflow runs `sqlite3 .backup`. www-data is the runtime
# service user; this gives us a clean dual-access model without world-perms.
usermod -aG www-data deploy
echo "    deploy is in groups: $(id -Gn deploy)"
# Pin umask so rsync'd files are group+world readable. Prevents a silent
# regression if /etc/login.defs or deploy's shell profile ever sets umask 027
# — that would strip o+r from new release files and lock out www-data.
if ! grep -q '^umask 022' /home/deploy/.profile 2>/dev/null; then
    echo 'umask 022' >> /home/deploy/.profile
    echo "    pinned umask 022 in /home/deploy/.profile"
fi

echo "==> 2/7 Authorising GitHub Actions SSH key for deploy"
mkdir -p /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
# `restrict` disables port forwarding, agent forwarding, etc. — least privilege.
AUTH_LINE="restrict $GH_PUBKEY"
touch /home/deploy/.ssh/authorized_keys
if ! grep -qF "$GH_PUBKEY" /home/deploy/.ssh/authorized_keys; then
    echo "$AUTH_LINE" >> /home/deploy/.ssh/authorized_keys
    echo "    pubkey added"
else
    echo "    pubkey already present, skipping"
fi
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

echo "==> 3/7 Granting narrow sudo on pipecat.service + prune wrapper"
cat > /etc/sudoers.d/deploy <<'EOF'
# CI deploy user — minimum privileges for service mgmt + log inspection.
# Story 5.1 retro #2 (GitHub Actions deploy pipeline).
#
# journalctl is pinned to the exact invocation used by the workflow's
# failure-path log dump. A trailing `*` glob would let `journalctl -u
# pipecat.service -u other.service` through (sudoers `*` absorbs any args,
# including a second -u) — small read-only priv-esc, but real.
deploy ALL=(root) NOPASSWD: /bin/systemctl restart pipecat.service
deploy ALL=(root) NOPASSWD: /bin/systemctl status pipecat.service
deploy ALL=(root) NOPASSWD: /bin/systemctl daemon-reload
deploy ALL=(root) NOPASSWD: /usr/bin/journalctl -u pipecat.service -n 80 --no-pager
# Lets the workflow refresh /etc/systemd/system/pipecat.service from the
# checked-in copy when deploy/pipecat.service changes. Source path is fixed
# to /tmp/pipecat.service.new (workflow scps there); mode is fixed to 0644.
deploy ALL=(root) NOPASSWD: /usr/bin/install -m 0644 /tmp/pipecat.service.new /etc/systemd/system/pipecat.service
# Release pruner — wrapper does its own arg validation (7-hex SHA shape),
# so no sudoers glob is needed and `..` traversal is impossible. Source:
# deploy/prune-releases.sh in the repo, installed by step 7 of this script.
deploy ALL=(root) NOPASSWD: /usr/local/sbin/prune-releases.sh
EOF
chmod 440 /etc/sudoers.d/deploy
visudo -cf /etc/sudoers.d/deploy >/dev/null
echo "    sudoers installed + validated"

echo "==> 4/7 Creating releases/ and backups/ dirs"
mkdir -p /opt/survive-the-talk/releases /opt/survive-the-talk/backups
chown deploy:deploy /opt/survive-the-talk /opt/survive-the-talk/releases /opt/survive-the-talk/backups
echo "    /opt/survive-the-talk/{releases,backups} owned by deploy"

echo "==> 5/7 Aligning ownership so www-data (runtime) + deploy (CI) coexist"
# pipecat.service runs as User=www-data (see deploy/pipecat.service). That
# user must be able to:
#   - read /opt/survive-the-talk/.env  (systemd reads it as root, but some
#     setups read it as the service user — defensive: www-data-readable)
#   - read+write /opt/survive-the-talk/data/db.sqlite AND create -wal / -shm
#     siblings in /opt/survive-the-talk/data/
# deploy (the CI user) must be able to:
#   - read db.sqlite for the workflow's `sqlite3 .backup` step
#   - write into /opt/survive-the-talk/backups/
# Solution: own data/ + db.sqlite as www-data:www-data, mode group-rw; deploy
# is in the www-data group (step 1) so it reads via group. Setgid on the dir
# so WAL/SHM files inherit group=www-data.
if [[ -f /opt/survive-the-talk/.env ]]; then
    chown www-data:www-data /opt/survive-the-talk/.env
    chmod 600 /opt/survive-the-talk/.env
    echo "    .env owner=www-data:www-data mode=600"
fi
if [[ -d /opt/survive-the-talk/data ]]; then
    chown www-data:www-data /opt/survive-the-talk/data
    chmod 2770 /opt/survive-the-talk/data   # setgid + rwx(owner) + rwx(group)
    if [[ -f /opt/survive-the-talk/data/db.sqlite ]]; then
        chown www-data:www-data /opt/survive-the-talk/data/db.sqlite
        chmod 660 /opt/survive-the-talk/data/db.sqlite
        echo "    db.sqlite owner=www-data:www-data mode=660 (deploy reads via www-data group)"
    fi
else
    echo "    /opt/survive-the-talk/data/ does not exist yet — skipping"
fi

echo "==> 6/7 Installing system tooling (sqlite3 CLI, uv)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq sqlite3 curl >/dev/null
echo "    apt: sqlite3 + curl ok"
if ! sudo -u deploy bash -c 'command -v uv' >/dev/null 2>&1; then
    sudo -u deploy bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' >/dev/null
    echo "    uv installed for deploy user"
else
    echo "    uv already installed for deploy user, skipping"
fi

echo "==> 7/7 Installing prune-releases.sh wrapper"
# The wrapper runs as root via the sudoers entry granted in step 3. Source
# of truth is `deploy/prune-releases.sh` in the repo; the caller scp's it
# to /tmp/ before invoking this script (see header). Owner=root mode=0755
# so no other user can edit it (would be a priv-esc — `deploy` runs it
# as root via NOPASSWD). Re-running this script overwrites with the latest
# repo content, so updating the wrapper is just a re-run away.
PRUNE_SRC=/tmp/prune-releases.sh
if [[ ! -f "$PRUNE_SRC" ]]; then
    echo "ERROR: $PRUNE_SRC not found. Copy the wrapper to the VPS first:" >&2
    echo "  scp deploy/prune-releases.sh root@VPS:$PRUNE_SRC" >&2
    echo "  ssh root@VPS 'bash -s' < deploy/setup-vps.sh" >&2
    exit 1
fi
install -m 0755 -o root -g root "$PRUNE_SRC" /usr/local/sbin/prune-releases.sh
echo "    /usr/local/sbin/prune-releases.sh installed (root:root mode 0755)"
rm -f "$PRUNE_SRC"

# Clean up the staged pubkey — authorized_keys already holds the canonical
# copy, and /tmp is world-readable so the uploaded file is a weak info leak.
rm -f "$PUBKEY_PATH"

echo
echo "==> Done. Verify:"
echo "  ssh deploy@$(hostname -I | awk '{print $1}') 'whoami && sudo -n systemctl status pipecat.service'"
echo
echo "Next: run deploy/migrate-to-releases.sh on the VPS to convert the"
echo "current repo/server/ layout to releases/<sha>/ + current symlink."
