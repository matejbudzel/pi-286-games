#!/bin/sh
# Deploy the validated Pi 1 DOSBox-X experiment without touching distro DOSBox.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$repo/scripts/dosbox-x-common.sh"
artifact=${DOSBOX_X_ARTIFACT:-$repo/dist/dosbox-x-pi1-armv6-armhf.tar.gz}
verify_only=false; [ "${1:-}" != --verify-only ] || verify_only=true
[ "$#" -le 1 ] || { echo "Usage: $0 [--verify-only]" >&2; exit 2; }

verify_remote() {
    ssh pi286 'set -eu
        [ "$(uname -m)" = armv6l ]
        [ "$(dpkg --print-architecture)" = armhf ]
        binary=/opt/pi286/dosbox-x/bin/dosbox-x
        [ -x "$binary" ]
        file "$binary" | grep -q "ELF 32-bit LSB.*ARM"
        readelf -h "$binary" | grep -q "Machine:.*ARM"
        readelf -A "$binary" | grep -Eq "Tag_CPU_arch: v6|Tag_CPU_arch: v6KZ"
        readelf -A "$binary" | grep -q "Tag_ABI_VFP_args: VFP registers"
        readelf -d "$binary" | grep -Fq "Shared library: [libSDL-1.2.so.0]"
        ! readelf -d "$binary" | grep -Eq "libX11|libGL|libSDL2|libSDL3|libfluidsynth|libslirp|libSDL_net|libavcodec|libpng"
        LD_LIBRARY_PATH=/opt/sdl12-fbcon/lib ldd "$binary" | grep -Fq "/opt/sdl12-fbcon/lib/libSDL-1.2.so.0"
        test -f /opt/pi286/dosbox-x/etc/dosbox-x-pi1-dynrec.conf
        test -f /opt/pi286/dosbox-x/etc/dosbox-x-pi1-normal.conf'
}

ssh -o BatchMode=yes pi286 true || { echo "Cannot connect to SSH alias pi286 with BatchMode enabled." >&2; exit 1; }
if [ "$verify_only" = true ]; then verify_remote; exit 0; fi
[ -f "$artifact" ] || { echo "Missing artifact: $artifact" >&2; exit 1; }
DOSBOX_X_ARTIFACT="$artifact" "$repo/scripts/validate-dosbox-x-artifact.sh"
remote_tar=/tmp/pi286-dosbox-x.tar.gz
command -v rsync >/dev/null 2>&1 || { echo "Missing required tool: rsync" >&2; exit 1; }
# Use rsync's remote-shell mode rather than scp's SFTP mode: the Pi alias
# deliberately probes two possible addresses and its SFTP stat reply is flaky.
rsync -a --partial -e 'ssh -o BatchMode=yes' "$artifact" "pi286:$remote_tar"
ssh pi286 "set -eu; stage=\$(mktemp -d /tmp/pi286-dosbox-x.XXXXXX); trap 'rm -rf \"\$stage\" $remote_tar' EXIT; tar -xzf $remote_tar -C \"\$stage\"; test -x \"\$stage$dosbox_x_prefix/bin/dosbox-x\"; sudo -n mkdir -p /opt/pi286; sudo -n rm -rf $dosbox_x_prefix; sudo -n mv \"\$stage$dosbox_x_prefix\" $dosbox_x_prefix; sudo -n chown -R root:root $dosbox_x_prefix"
verify_remote
printf 'Deployed and verified %s on pi286 at %s\n' "$artifact" "$dosbox_x_prefix"
