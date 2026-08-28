#!/bin/sh
# Synchronize target development files through the external SSH alias.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sysroot=${PI286_SYSROOT:-$repo/.cache/pi286-sysroot}
ssh -o BatchMode=yes pi286 true || { echo "Cannot connect to SSH alias pi286 with BatchMode enabled." >&2; exit 1; }
ssh pi286 'set -eu; printf "remote OS: "; . /etc/os-release; printf "%s %s\n" "$ID" "$VERSION_ID"; printf "remote machine: "; uname -m; printf "remote dpkg architecture: "; dpkg --print-architecture' | tee /dev/stderr | grep -Eq 'remote machine: armv6l|remote machine: armv6' || { echo "pi286 is not an ARMv6 target." >&2; exit 1; }
mkdir -p "$sysroot/lib" "$sysroot/usr/lib/arm-linux-gnueabihf/pkgconfig" "$sysroot/usr"
# SDL needs target glibc/loader, headers, and ALSA's development linker files;
# copying all of /usr/lib is several GiB and not useful for this build.
rsync -a --delete --links -e 'ssh -o BatchMode=yes' pi286:/lib/arm-linux-gnueabihf/ "$sysroot/lib/arm-linux-gnueabihf/"
rsync -a --delete --links -e 'ssh -o BatchMode=yes' pi286:/usr/include/ "$sysroot/usr/include/"
rsync -a --delete --links --include='libasound.so*' --exclude='*' -e 'ssh -o BatchMode=yes' pi286:/usr/lib/arm-linux-gnueabihf/ "$sysroot/usr/lib/arm-linux-gnueabihf/"
rsync -a --links -e 'ssh -o BatchMode=yes' pi286:/usr/lib/arm-linux-gnueabihf/pkgconfig/alsa.pc "$sysroot/usr/lib/arm-linux-gnueabihf/pkgconfig/alsa.pc"
printf 'Synced Pi ARMv6 sysroot to %s\n' "$sysroot"
