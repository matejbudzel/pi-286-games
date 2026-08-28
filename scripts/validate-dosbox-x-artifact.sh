#!/bin/sh
# Validate the deployable Pi 1 artifact without requiring a running Pi.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$repo/scripts/dosbox-x-common.sh"
artifact=${DOSBOX_X_ARTIFACT:-$repo/dist/dosbox-x-pi1-armv6-armhf.tar.gz}
[ -f "$artifact" ] || { echo "Missing artifact: $artifact" >&2; exit 1; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT HUP INT TERM
tar -xzf "$artifact" -C "$tmp"
root="$tmp$dosbox_x_prefix"; binary="$root/bin/dosbox-x"
[ -x "$binary" ] || { echo "Artifact install layout is incomplete." >&2; exit 1; }
[ -f "$root/etc/dosbox-x-pi1-dynrec.conf" ] && [ -f "$root/etc/dosbox-x-pi1-normal.conf" ] || { echo "Artifact configs are missing." >&2; exit 1; }
file "$binary" | grep -q 'ELF 32-bit LSB.*ARM' || { echo "DOSBox-X is not a 32-bit ARM ELF." >&2; exit 1; }
readelf -h "$binary" | grep -q 'Machine:.*ARM' || { echo "DOSBox-X ELF machine is not ARM." >&2; exit 1; }
readelf -A "$binary" | grep -Eq 'Tag_CPU_arch: v6|Tag_CPU_arch: v6KZ' || { echo "DOSBox-X is not ARMv6 compatible." >&2; exit 1; }
readelf -A "$binary" | grep -q 'Tag_ABI_VFP_args: VFP registers' || { echo "DOSBox-X lacks the hard-float ABI tag." >&2; exit 1; }
needed=$(readelf -d "$binary")
printf '%s\n' "$needed" | grep -Fq 'Shared library: [libSDL-1.2.so.0]' || { echo "DOSBox-X is not linked to SDL 1.2." >&2; exit 1; }
printf '%s\n' "$needed" | grep -Eq 'libX11|libGL|libSDL2|libSDL3|libfluidsynth|libslirp|libSDL_net|libavcodec|libpng' && { echo "DOSBox-X has an unwanted dependency." >&2; exit 1; }
grep -qx "source_commit=$dosbox_x_source_commit" "$root/share/pi286-build-info.txt" || { echo "Artifact pin metadata is wrong." >&2; exit 1; }
grep -qx 'dynrec_backend=ARMV4LE risc_armv4le' "$root/share/pi286-build-info.txt" || { echo "Artifact does not record the ARMv6 dynrec backend." >&2; exit 1; }
printf 'Validated %s\n' "$artifact"
