#!/bin/sh
# Build a deliberately small static libwebsockets for the Pi 1 presenter.
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sysroot=${PI286_SYSROOT:-$repo/.cache/pi286-sysroot}
source_dir=${LWS_SOURCE_DIR:-$repo/.cache/libwebsockets-source}
build_dir=${LWS_BUILD_DIR:-$repo/.cache/libwebsockets-armv6-build}
stage_dir=${LWS_STAGE_DIR:-$repo/.cache/libwebsockets-armv6-stage}
cc=${CROSS_COMPILE:-arm-linux-gnueabihf-}gcc
revision=ab9df9cfc39de7a49967f18387b6b76310947442

command -v cmake >/dev/null 2>&1 || { echo "Missing required tool: cmake" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "Missing required tool: git" >&2; exit 1; }
command -v "$cc" >/dev/null 2>&1 || { echo "Missing required tool: $cc" >&2; exit 1; }
[ -f "$sysroot/lib/arm-linux-gnueabihf/libc.so.6" ] || { echo "Missing Pi sysroot at $sysroot" >&2; exit 1; }

if [ ! -d "$source_dir/.git" ]; then
    git clone https://libwebsockets.org/repo/libwebsockets "$source_dir"
fi
git -C "$source_dir" fetch --depth 1 origin "$revision"
git -C "$source_dir" checkout --detach "$revision"

flags='-O2 -fomit-frame-pointer -marm -march=armv6zk -mtune=arm1176jzf-s -mfpu=vfp -mfloat-abi=hard'
rm -rf "$build_dir" "$stage_dir"
cmake -S "$source_dir" -B "$build_dir" \
    -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_C_COMPILER="$cc" -DCMAKE_SYSROOT="$sysroot" -DCMAKE_C_FLAGS="$flags" \
    -DDISABLE_WERROR=ON -DLWS_WITH_SSL=OFF -DLWS_WITH_HTTP2=OFF -DLWS_WITH_HTTP3=OFF \
    -DLWS_WITH_STATIC=ON -DLWS_WITH_SHARED=OFF -DLWS_WITH_ZLIB=OFF \
    -DLWS_WITH_LIBEV=OFF -DLWS_WITH_LIBUV=OFF -DLWS_WITH_LIBEVENT=OFF -DLWS_WITH_GLIB=OFF \
    -DLWS_WITH_MINIMAL_EXAMPLES=OFF -DLWS_WITH_TESTAPPS=OFF -DLWS_WITH_PLUGINS=OFF \
    -DLWS_WITH_SERVER=OFF -DLWS_WITH_CLIENT=ON -DCMAKE_INSTALL_PREFIX=/opt/pi286/libwebsockets
cmake --build "$build_dir" --target websockets -j"${LWS_CROSS_JOBS:-2}"
cmake --install "$build_dir" --prefix "$stage_dir/opt/pi286/libwebsockets"

library="$stage_dir/opt/pi286/libwebsockets/lib/libwebsockets.a"
[ -f "$library" ] || { echo "libwebsockets static library was not produced" >&2; exit 1; }
readelf -A "$library" | grep -Eq 'Tag_CPU_arch: v6|Tag_CPU_arch: v6KZ'
readelf -A "$library" | grep -q 'Tag_ABI_VFP_args: VFP registers'
echo "Built minimal ARMv6 libwebsockets at $stage_dir"
