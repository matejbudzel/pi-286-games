#!/bin/sh
# Fast x86_64-to-Pi custom SDL development loop.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case ${1:-all} in
sync) exec "$repo/scripts/sync-pi-sysroot.sh";; build) exec "$repo/scripts/cross-build-sdl12-fbcon.sh";; deploy) exec "$repo/scripts/deploy-sdl12-to-pi.sh";; verify) exec "$repo/scripts/deploy-sdl12-to-pi.sh" --verify-only;;
all) "$repo/scripts/sync-pi-sysroot.sh"; "$repo/scripts/cross-build-sdl12-fbcon.sh"; exec "$repo/scripts/deploy-sdl12-to-pi.sh";;
visual|visual-pillarbox) test=${1#visual}; exec ssh -o BatchMode=yes pi286 "repo=\$(find \"\$HOME\" -maxdepth 4 -type f -path '*/scripts/run-sdl-fbcon-self-test.sh' -print -quit); test -n \"\$repo\"; sh \"\${repo%/scripts/run-sdl-fbcon-self-test.sh}/scripts/run-sdl-fbcon-self-test.sh\"${test:+ --pillarbox}";;
*) echo "Usage: $0 {sync|build|deploy|verify|all|visual|visual-pillarbox}" >&2; exit 2;; esac
