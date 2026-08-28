#!/bin/sh
# Cross-build pinned custom SDL for Pi 1 without touching local /opt.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$repo/scripts/sdl12-fbcon-common.sh"
sysroot=${PI286_SYSROOT:-$repo/.cache/pi286-sysroot}; source_dir=${SDL12_FBCON_CROSS_SOURCE_DIR:-$repo/.cache/sdl12-fbcon-source}; work_dir=${SDL12_FBCON_CROSS_WORK_DIR:-$repo/.cache/sdl12-fbcon-armv6-build}; stage_dir=${SDL12_FBCON_STAGE_DIR:-$repo/.cache/sdl12-fbcon-stage}; dist_dir=${SDL12_FBCON_DIST_DIR:-$repo/dist}; artifact=${SDL12_FBCON_ARTIFACT:-$dist_dir/sdl12-fbcon-rpi1-armv6-armhf.tar.gz}
cross=${CROSS_COMPILE:-arm-linux-gnueabihf-}; cc=${cross}gcc
for command in "$cc" "${cross}ar" "${cross}ranlib" "${cross}strip" git tar readelf file strings; do command -v "$command" >/dev/null 2>&1 || { echo "Missing required tool: $command" >&2; exit 1; }; done
[ -f "$sysroot/usr/include/alsa/asoundlib.h" ] && [ -e "$sysroot/lib/arm-linux-gnueabihf/ld-linux-armhf.so.3" ] || { echo "Missing Pi sysroot at $sysroot; run scripts/sync-pi-sysroot.sh first." >&2; exit 1; }
if [ ! -d "$source_dir/.git" ]; then git clone "$sdl12_fbcon_source_url" "$source_dir"; fi
git -C "$source_dir" fetch --depth 1 origin "$sdl12_fbcon_source_commit"; git -C "$source_dir" checkout --detach "$sdl12_fbcon_source_commit"; git -C "$source_dir" reset --hard "$sdl12_fbcon_source_commit"; sdl12_fbcon_apply_patches "$source_dir"
rm -rf "$work_dir" "$stage_dir"; mkdir -p "$work_dir" "$stage_dir" "$dist_dir"
arm_flags='-marm -march=armv6zk -mtune=arm1176jzf-s -mfpu=vfp -mfloat-abi=hard'
cd "$work_dir"
CC="$cc --sysroot=$sysroot" AR="${cross}ar" RANLIB="${cross}ranlib" STRIP="${cross}strip" CFLAGS="--sysroot=$sysroot $arm_flags" CPPFLAGS="--sysroot=$sysroot" LDFLAGS="--sysroot=$sysroot $arm_flags" "$source_dir/configure" --build="$(gcc -dumpmachine)" --host=arm-linux-gnueabihf --prefix="$sdl12_fbcon_prefix" $sdl12_fbcon_configure_args
make -j"${SDL12_FBCON_CROSS_JOBS:-$(getconf _NPROCESSORS_ONLN)}"
# Debian's arm-linux-gnueabihf GCC ships ARMv7 startup objects. Re-link this
# shared library with Pi-synced ARMv6 runtime libraries instead; SDL itself is
# C-only and all compiled objects have already been checked as ARMv6.
target_libdir="$sysroot/lib/arm-linux-gnueabihf"
"$cc" --sysroot="$sysroot" $arm_flags -shared -nostartfiles -nodefaultlibs -Wl,-soname,libSDL-1.2.so.0 "$work_dir"/build/.libs/*.o "$sysroot/usr/lib/arm-linux-gnueabihf/libasound.so.2.0.0" "$target_libdir/libm.so.6" "$target_libdir/libc.so.6" "$target_libdir/libgcc_s.so.1" -o "$work_dir/build/.libs/libSDL-1.2.so.0.11.5"
make DESTDIR="$stage_dir" install; touch "$stage_dir$sdl12_fbcon_prefix/.pi286-sdl-fbcon-pillarbox"
library="$stage_dir$sdl12_fbcon_prefix/lib/libSDL-1.2.so.0"; [ -e "$library" ] && [ -x "$stage_dir$sdl12_fbcon_prefix/bin/sdl-config" ] || { echo "SDL staging install is incomplete." >&2; exit 1; }
file -L "$library" | grep -q ARM || { echo "Cross build produced a non-ARM SDL library." >&2; exit 1; }; readelf -A "$library" | grep -Eq 'Tag_CPU_arch: v6|Tag_CPU_arch: v6KZ' || { echo "SDL library is not ARMv6." >&2; exit 1; }; readelf -A "$library" | grep -q 'Tag_ABI_VFP_args: VFP registers' || { echo "SDL library lacks hard-float ABI tagging." >&2; exit 1; }; strings "$library" | grep -q fbcon || { echo "SDL library lacks fbcon." >&2; exit 1; }
tar -C "$stage_dir" -czf "$artifact" opt/sdl12-fbcon; printf 'Built and validated %s\n' "$artifact"
