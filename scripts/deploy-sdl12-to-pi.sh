#!/bin/sh
# Deploy a validated artifact through SSH alias pi286; never touch system SDL.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$repo/scripts/sdl12-fbcon-common.sh"
artifact=${SDL12_FBCON_ARTIFACT:-$repo/dist/sdl12-fbcon-rpi1-armv6-armhf.tar.gz}
verify_only=false; [ "${1:-}" != --verify-only ] || verify_only=true
[ "$#" -le 1 ] || { echo "Usage: $0 [--verify-only]" >&2; exit 2; }
verify_remote() {
    ssh pi286 'set -eu; [ "$(uname -m)" = armv6l ]; [ "$(dpkg --print-architecture)" = armhf ]; /opt/sdl12-fbcon/bin/sdl-config --version | grep -qx 1.2.16; file -L /opt/sdl12-fbcon/lib/libSDL-1.2.so.0 | grep -q ARM; readelf -A /opt/sdl12-fbcon/lib/libSDL-1.2.so.0 | grep -Eq "Tag_CPU_arch: v6|Tag_CPU_arch: v6KZ"; readelf -A /opt/sdl12-fbcon/lib/libSDL-1.2.so.0 | grep -q "Tag_ABI_VFP_args: VFP registers"; LD_LIBRARY_PATH=/opt/sdl12-fbcon/lib ldd "$(command -v dosbox)" | grep -Fq /opt/sdl12-fbcon/lib/libSDL-1.2.so.0; health=$(find "$HOME" -maxdepth 4 -type f -path "*/scripts/health-check.sh" -print -quit); [ -z "$health" ] || sh "${health%/scripts/health-check.sh}/scripts/health-check.sh"'
}
ssh -o BatchMode=yes pi286 true || { echo "Cannot connect to SSH alias pi286 with BatchMode enabled." >&2; exit 1; }
if [ "$verify_only" = true ]; then verify_remote; exit 0; fi
[ -f "$artifact" ] || { echo "Missing artifact: $artifact" >&2; exit 1; }
tar -tzf "$artifact" | grep -qx opt/sdl12-fbcon/lib/libSDL-1.2.so.0 || { echo "Artifact lacks custom SDL library." >&2; exit 1; }
validate_dir=$(mktemp -d); trap 'rm -rf "$validate_dir"' EXIT HUP INT TERM
tar -xzf "$artifact" -C "$validate_dir"
library="$validate_dir/opt/sdl12-fbcon/lib/libSDL-1.2.so.0"
file -L "$library" | grep -q ARM || { echo "Artifact SDL library is not ARM." >&2; exit 1; }
readelf -A "$library" | grep -Eq 'Tag_CPU_arch: v6|Tag_CPU_arch: v6KZ' || { echo "Artifact SDL library is not ARMv6." >&2; exit 1; }
readelf -A "$library" | grep -q 'Tag_ABI_VFP_args: VFP registers' || { echo "Artifact SDL library lacks hard-float ABI tagging." >&2; exit 1; }
remote_tar=/tmp/pi286-sdl12-fbcon.tar.gz
scp -o BatchMode=yes "$artifact" "pi286:$remote_tar"
ssh pi286 "set -eu; stage=\$(mktemp -d /tmp/pi286-sdl12-fbcon.XXXXXX); trap 'rm -rf \"\$stage\" $remote_tar' EXIT; tar -xzf $remote_tar -C \"\$stage\"; test -x \"\$stage/opt/sdl12-fbcon/bin/sdl-config\"; sudo -n rm -rf /opt/sdl12-fbcon; sudo -n mv \"\$stage/opt/sdl12-fbcon\" /opt/sdl12-fbcon; sudo -n chown -R root:root /opt/sdl12-fbcon"
verify_remote; printf 'Deployed and verified %s on pi286\n' "$artifact"
