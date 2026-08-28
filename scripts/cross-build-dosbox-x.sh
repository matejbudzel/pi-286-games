#!/bin/sh
# Build the deliberately small Pi 1 DOSBox-X experiment; no SSH is needed.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$repo/scripts/dosbox-x-common.sh"
sysroot=${PI286_SYSROOT:-$repo/.cache/pi286-sysroot}
source_dir=${DOSBOX_X_SOURCE_DIR:-$repo/.cache/dosbox-x-source}
stage_dir=${DOSBOX_X_STAGE_DIR:-$repo/.cache/dosbox-x-stage}
dist_dir=${DOSBOX_X_DIST_DIR:-$repo/dist}
artifact=${DOSBOX_X_ARTIFACT:-$dist_dir/dosbox-x-pi1-armv6-armhf.tar.gz}
sdl_stage=${SDL12_FBCON_STAGE_DIR:-$repo/.cache/sdl12-fbcon-stage}
sdl_prefix=$sdl_stage/opt/sdl12-fbcon
cross=${CROSS_COMPILE:-arm-linux-gnueabihf-}; cc=${cross}gcc
if ! command -v "${cross}g++" >/dev/null 2>&1 && [ -x "$repo/.cache/cross-cxx/usr/bin/${cross}g++" ]; then
    PATH="$repo/.cache/cross-cxx/usr/bin:$PATH"
    export PATH
fi
for command in "$cc" "${cross}g++" "${cross}strip" git tar readelf file strings autoconf automake aclocal autoheader; do command -v "$command" >/dev/null 2>&1 || { echo "Missing required tool: $command" >&2; exit 1; }; done
[ -f "$sysroot/lib/arm-linux-gnueabihf/crt1.o" ] && [ -f "$sysroot/lib/arm-linux-gnueabihf/libstdc++.so.6.0.33" ] || { echo "Pi sysroot lacks ARMv6 C++ runtime objects; sync it when pi286 is online." >&2; exit 1; }
[ -x "$sdl_prefix/bin/sdl-config" ] && [ -e "$sdl_prefix/lib/libSDL-1.2.so.0" ] || { echo "Missing staged custom SDL; run scripts/cross-build-sdl12-fbcon.sh first." >&2; exit 1; }
if [ ! -d "$source_dir/.git" ]; then git clone "$dosbox_x_source_url" "$source_dir"; fi
git -C "$source_dir" fetch --depth 1 origin "$dosbox_x_source_commit"
git -C "$source_dir" checkout --detach "$dosbox_x_source_commit"
git -C "$source_dir" reset --hard "$dosbox_x_source_commit"
git -C "$source_dir" clean -fdx
dosbox_x_apply_patches "$source_dir"
rm -rf "$stage_dir"; mkdir -p "$stage_dir$dosbox_x_prefix/etc" "$stage_dir$dosbox_x_prefix/share" "$dist_dir"
arm_flags='-O2 -fomit-frame-pointer -marm -march=armv6zk -mtune=arm1176jzf-s -mfpu=vfp -mfloat-abi=hard'
cd "$source_dir"
./autogen.sh
PATH="$sdl_prefix/bin:$PATH"
export PATH
PI286_SYSROOT="$sysroot" \
CC="$repo/scripts/pi286-armv6-cc.sh" CXX="$repo/scripts/pi286-armv6-cxx.sh" AR="${cross}ar" RANLIB="${cross}ranlib" STRIP="${cross}strip" \
CFLAGS="$arm_flags -I$sdl_prefix/include/SDL" CXXFLAGS="$arm_flags -I$sdl_prefix/include/SDL" CPPFLAGS="-I$sdl_prefix/include/SDL" LDFLAGS="-L$sdl_prefix/lib" \
./configure --build="$(gcc -dumpmachine)" --host=arm-linux-gnueabihf --prefix="$dosbox_x_prefix" --with-sdl-prefix="$sdl_prefix" --disable-sdltest --disable-alsatest $dosbox_x_configure_args
make -j"${DOSBOX_X_CROSS_JOBS:-$(getconf _NPROCESSORS_ONLN)}"
make DESTDIR="$stage_dir" install
"${cross}strip" --strip-unneeded "$stage_dir$dosbox_x_prefix/bin/dosbox-x"
install -m 0644 "$repo/config/dosbox-x-pi1-dynrec.conf" "$stage_dir$dosbox_x_prefix/etc/dosbox-x-pi1-dynrec.conf"
install -m 0644 "$repo/config/dosbox-x-pi1-normal.conf" "$stage_dir$dosbox_x_prefix/etc/dosbox-x-pi1-normal.conf"
install -m 0644 "$repo/config/dosbox-x-pi1-build-info.txt" "$stage_dir$dosbox_x_prefix/share/pi286-build-info.txt"
tar -C "$stage_dir" -czf "$artifact" opt/pi286/dosbox-x
DOSBOX_X_ARTIFACT="$artifact" "$repo/scripts/validate-dosbox-x-artifact.sh"
printf 'Built and validated %s\n' "$artifact"
