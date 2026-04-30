#!/bin/bash
# Prune old release directories under /opt/survive-the-talk/releases/.
#
# Runs as root via sudoers (granted by deploy/setup-vps.sh). The deploy
# user calls this from .github/workflows/deploy-server.yml's
# "Prune old releases" step:
#
#     ssh deploy@VPS 'sudo -n /usr/local/sbin/prune-releases.sh'
#
# Why root? `pipecat.service` runs as `www-data` and (pre-fix) Python
# wrote `.pyc` files into `.venv/.../__pycache__/` owned by www-data.
# The `deploy` user is in the www-data group but group membership does
# NOT grant cross-owner deletion — `rm` checks ownership, not group.
# Running as root sidesteps the whole permission question.
#
# Why a wrapper instead of `sudo rm -rf` directly? sudoers patterns
# with `*` can be tricked by `..` (e.g. /opt/.../releases/.. matches
# `/opt/.../releases/*`). The wrapper does its own strict validation:
# each release dir name MUST be exactly 7 hex chars (the
# `${GITHUB_SHA::7}` shape baked into the workflow's `Define release id`
# step). Anything else is skipped with a warning, never deleted.
#
# Idempotent: running this twice is a no-op the second time.
# Safe to run manually for ad-hoc cleanup.

set -euo pipefail

RELEASES_DIR=/opt/survive-the-talk/releases
KEEP=3

# Defensive: refuse to run if the releases dir layout looks wrong
# (e.g. a fresh VPS that hasn't been migrated to the releases/<sha>
# scheme — `current` would not be a symlink). The deploy workflow has
# its own pre-flight for this; this is a second guard so a stray
# manual invocation can't accidentally nuke a flat install.
if [[ ! -d "$RELEASES_DIR" ]]; then
  echo "ERROR: $RELEASES_DIR does not exist" >&2
  exit 1
fi
if [[ ! -L /opt/survive-the-talk/current ]]; then
  echo "ERROR: /opt/survive-the-talk/current is not a symlink — refusing to prune" >&2
  exit 1
fi

# List release dirs newest-first. `ls -1t` orders by mtime; release
# IDs are not sortable lexicographically (they're hex SHAs), so mtime
# is the only reliable signal of "newest = most recently deployed".
mapfile -t releases < <(cd "$RELEASES_DIR" && ls -1t)

# Skip the first N — those we keep — then validate + delete the rest.
deleted=0
for ((i=KEEP; i<${#releases[@]}; i++)); do
  name="${releases[$i]}"
  # Strict shape check: 7 hex chars, nothing else. This is the path-
  # traversal guard. Names like `..`, `../etc`, `0067366/../..` all
  # fail the regex.
  if [[ ! "$name" =~ ^[0-9a-f]{7}$ ]]; then
    echo "WARN: skipping unexpected name in releases dir: $name" >&2
    continue
  fi
  target="$RELEASES_DIR/$name"
  # `realpath` defends against a malicious symlink swapped in between
  # the validation and the rm. The resolved path MUST still live under
  # the releases dir.
  resolved=$(realpath -- "$target")
  case "$resolved" in
    "$RELEASES_DIR"/*)
      ;;
    *)
      echo "WARN: $name resolves outside $RELEASES_DIR ($resolved) — skipping" >&2
      continue
      ;;
  esac
  echo "Removing old release: $name"
  # Use the validated `$resolved` path (not `$target`) so a symlink swap
  # between the realpath check and the rm cannot redirect the deletion
  # outside the releases dir.
  rm -rf -- "$resolved"
  deleted=$((deleted + 1))
done

echo "Pruned $deleted release(s); kept $(printf '%s' "${releases[@]:0:KEEP}" | tr ' ' ',')."
