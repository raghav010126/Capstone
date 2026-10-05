#!/usr/bin/env bash
# Run npm/npx for the frontend with the project-local Node, keeping node_modules and .next OUTSIDE the
# OneDrive-synced repo (symlinked from ~/.cache/medishield/frontend). npm replaces the node_modules symlink with
# a real folder on install, so after any `install`/`ci` this script moves it back out and re-links it.
#   scripts/web.sh install recharts        scripts/web.sh run dev        scripts/web.sh npx shadcn@latest add button
set -euo pipefail
export PATH="$HOME/.local/node/bin:$PATH"
export NODE_OPTIONS="${NODE_OPTIONS:-} --use-system-ca"      # corporate TLS inspection: trust the OS certificate store
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$HOME/.cache/medishield/frontend"
cd "$HERE/frontend"
mkdir -p "$CACHE/node_modules" "$CACHE/next"
[ -L node_modules ] || { [ -d node_modules ] && { rm -rf "$CACHE/node_modules"; mv node_modules "$CACHE/node_modules"; }; ln -sfn "$CACHE/node_modules" node_modules; }
[ -L .next ] || { rm -rf .next; ln -sfn "$CACHE/next" .next; }
if [ "${1:-}" = "npx" ]; then shift; npx --yes "$@"; else npm "$@"; fi
STATUS=$?
if [ -d node_modules ] && [ ! -L node_modules ]; then rm -rf "$CACHE/node_modules"; mv node_modules "$CACHE/node_modules"; ln -sfn "$CACHE/node_modules" node_modules; fi
exit $STATUS
