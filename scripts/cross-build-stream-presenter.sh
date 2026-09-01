#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sysroot=${PI286_SYSROOT:-$repo/.cache/pi286-sysroot}
stage=${SDL12_FBCON_STAGE_DIR:-$repo/.cache/sdl12-fbcon-stage}
out=${STREAM_PRESENTER_OUTPUT:-$repo/dist/pi286-stream-presenter-rpi1-armv6-armhf}
cc=${CROSS_COMPILE:-arm-linux-gnueabihf-}gcc
"$repo/scripts/cross-build-libwebsockets.sh"
lws_stage=${LWS_STAGE_DIR:-$repo/.cache/libwebsockets-armv6-stage}
test -f "$sysroot/usr/include/alsa/asoundlib.h" && test -f "$stage/opt/sdl12-fbcon/include/SDL/SDL.h" || { echo "missing Pi sysroot or staged SDL" >&2; exit 1; }
mkdir -p "$(dirname "$out")"
flags='-O2 -fomit-frame-pointer -marm -march=armv6zk -mtune=arm1176jzf-s -mfpu=vfp -mfloat-abi=hard'
object=${out}.o
"$cc" --sysroot="$sysroot" $flags -I"$stage/opt/sdl12-fbcon/include/SDL" -I"$lws_stage/opt/pi286/libwebsockets/include" -c "$repo/streaming/client/pi286-stream-presenter.c" -o "$object"
# Debian's cross GCC supplies ARMv7 crt objects. Link explicitly with the
# ARMv6 startup objects synced from pi286, just as the custom SDL build does.
runtime="$sysroot/lib/arm-linux-gnueabihf"
gcc_runtime="$sysroot/usr/lib/gcc/arm-linux-gnueabihf/14"
"$cc" --sysroot="$sysroot" $flags -pie -nostartfiles -nodefaultlibs \
  "$runtime/Scrt1.o" "$runtime/crti.o" "$gcc_runtime/crtbeginS.o" "$object" \
  -L"$stage/opt/sdl12-fbcon/lib" -Wl,-rpath,/opt/sdl12-fbcon/lib -lSDL "$lws_stage/opt/pi286/libwebsockets/lib/libwebsockets.a" "$runtime/libpthread.so.0" \
  "$runtime/libc.so.6" "$runtime/libgcc_s.so.1" "$gcc_runtime/crtendS.o" "$runtime/crtn.o" -o "$out"
rm -f "$object"
file "$out" | grep -q ARM && readelf -A "$out" | grep -Eq 'Tag_CPU_arch: v6|Tag_CPU_arch: v6KZ' && readelf -A "$out" | grep -q 'Tag_ABI_VFP_args: VFP registers'
