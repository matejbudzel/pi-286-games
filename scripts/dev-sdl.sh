#!/bin/sh
# Fast x86_64-to-Pi custom SDL development loop.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case ${1:-all} in
sync) exec "$repo/scripts/sync-pi-sysroot.sh";; build) exec "$repo/scripts/cross-build-sdl12-fbcon.sh";; deploy) exec "$repo/scripts/deploy-sdl12-to-pi.sh";; verify) exec "$repo/scripts/deploy-sdl12-to-pi.sh" --verify-only;;
all) "$repo/scripts/sync-pi-sysroot.sh"; "$repo/scripts/cross-build-sdl12-fbcon.sh"; exec "$repo/scripts/deploy-sdl12-to-pi.sh";;
*) echo "Usage: $0 {sync|build|deploy|verify|all}" >&2; exit 2;; esac
