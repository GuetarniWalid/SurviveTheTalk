#!/usr/bin/env bash
# Bridge the current `repo/server/` layout to the `releases/<sha>/` + `current`
# symlink layout used by the GitHub Actions CI deploy. Run ONCE on the VPS,
# AFTER setup-vps.sh has prepared the `deploy` user + dirs.
#
# Run as root (it touches systemd units):
#   ssh root@167.235.63.129 'bash -s' < deploy/migrate-to-releases.sh
#
# What it does:
#   1. Captures the current state (`/opt/survive-the-talk/repo/server/`) into
#      a release dir keyed by the current git HEAD.
#   2. Atomically points `current` → that release.
#   3. Installs the new pipecat.service unit (which references `current/server`).
#   4. daemon-reload + restart, then waits + curls /health.
#
# Rollback if anything breaks:
#   1. `rm /opt/survive-the-talk/current`
#   2. Restore the old systemd unit pointing at `repo/server/`:
#      `cat > /etc/systemd/system/pipecat.service <<EOF` (paste old WorkingDirectory)
#   3. `systemctl daemon-reload && systemctl restart pipecat.service`
# (Old `repo/server/` is untouched throughout; the migration is non-destructive.)

set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: must run as root." >&2
    exit 1
fi

SOURCE_DIR=/opt/survive-the-talk/repo/server
RELEASES_DIR=/opt/survive-the-talk/releases
CURRENT_LINK=/opt/survive-the-talk/current

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "ERROR: source $SOURCE_DIR not found. Aborting." >&2
    exit 1
fi
if [[ ! -d "$RELEASES_DIR" ]]; then
    echo "ERROR: $RELEASES_DIR not found. Run setup-vps.sh first." >&2
    exit 1
fi

# Use the source repo's git HEAD as the release id. Falls back to a timestamp
# if the repo is detached / shallow.
RELEASE_ID=$(
    cd /opt/survive-the-talk/repo \
        && git rev-parse --short HEAD 2>/dev/null \
        || date +%Y%m%d-%H%M%S
)
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"

echo "==> 1/4 Copying $SOURCE_DIR → $RELEASE_DIR/server"
if [[ -d "$RELEASE_DIR" ]]; then
    echo "    $RELEASE_DIR already exists — overwriting in place"
fi
mkdir -p "$RELEASE_DIR"
# `-a` preserves perms + symlinks (incl. the .venv contents). `--reflink=auto`
# uses copy-on-write where the FS supports it (negligible disk).
cp -a "$SOURCE_DIR" "$RELEASE_DIR/server"
chown -R deploy:deploy "$RELEASE_DIR"
echo "    done — $(du -sh "$RELEASE_DIR" | cut -f1)"

echo "==> 2/4 Atomic symlink swap: current → $RELEASE_DIR"
# `ln -sfn` then `mv -Tf` is the POSIX-portable atomic-rename idiom: the
# kernel guarantees `current` always points somewhere valid, never to a
# broken / partial target.
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK.new"
mv -Tf "$CURRENT_LINK.new" "$CURRENT_LINK"
echo "    $CURRENT_LINK → $(readlink "$CURRENT_LINK")"

echo "==> 3/4 Installing updated pipecat.service unit"
# This script is invoked via `ssh root@VPS 'bash -s' < migrate-to-releases.sh`
# (see deploy/README.md step 3). When bash reads from stdin, BASH_SOURCE[0]
# does NOT resolve to the local file path — SCRIPT_DIR would fall back to
# $HOME (/root). We instead read from the in-tree copy inside the VPS's git
# repo at /opt/survive-the-talk/repo (pre-existing checkout).
#
# Pre-flight check: the VPS repo might be stale and contain the OLD unit
# (WorkingDirectory=repo/server instead of current/server). README step 3
# tells you to scp the fresh unit first — we verify it here.
UNIT_SOURCE="/opt/survive-the-talk/repo/deploy/pipecat.service"
if [[ ! -f "$UNIT_SOURCE" ]]; then
    echo "ERROR: cannot locate pipecat.service unit file at $UNIT_SOURCE" >&2
    echo "       Copy the checked-in unit to the VPS first:" >&2
    echo "         scp deploy/pipecat.service root@VPS:$UNIT_SOURCE" >&2
    exit 1
fi
if ! grep -qF 'WorkingDirectory=/opt/survive-the-talk/current/server' "$UNIT_SOURCE"; then
    echo "ERROR: $UNIT_SOURCE has a pre-CI WorkingDirectory — the VPS repo is stale." >&2
    echo "       Refresh it from your local checkout before running this script:" >&2
    echo "         scp deploy/pipecat.service root@VPS:$UNIT_SOURCE" >&2
    echo "       Then re-run migrate-to-releases.sh." >&2
    # NOTE: the symlink swap at step 2/4 is non-destructive (old layout at
    # /opt/.../repo/server is intact) — just don't touch /etc/systemd yet.
    exit 1
fi
cp "$UNIT_SOURCE" /etc/systemd/system/pipecat.service
systemctl daemon-reload
echo "    unit installed — WorkingDirectory now /opt/survive-the-talk/current/server"

echo "==> 4/4 Restarting pipecat.service + healthcheck"
systemctl restart pipecat.service
sleep 4
systemctl is-active pipecat.service || {
    echo "ERROR: service did not come back up. Last 30 log lines:" >&2
    journalctl -u pipecat.service -n 30 --no-pager >&2
    exit 1
}

if command -v curl >/dev/null 2>&1; then
    for i in 1 2 3 4 5; do
        if curl -sS -f http://127.0.0.1:8000/health >/dev/null 2>&1; then
            echo "    /health OK on attempt $i"
            break
        fi
        sleep 2
        if [[ $i -eq 5 ]]; then
            echo "WARN: /health did not respond in 10s — service running but unhealthy?" >&2
        fi
    done
fi

echo
echo "==> Done. Verify:"
echo "  systemctl status pipecat.service"
echo "  ls -la /opt/survive-the-talk/current"
echo
echo "If anything looks wrong, the old layout is intact at $SOURCE_DIR."
echo "Rollback: see the comment block at the top of this script."
