#!/bin/sh
# Internal cross-link wrapper. The Debian cross toolchain startup objects are
# ARMv7, while the Pi-synced sysroot supplies ARMv6 hard-float startup/runtime
# objects. It is used only by cross-build-dosbox-x.sh.
set -eu
: "${PI286_SYSROOT:?PI286_SYSROOT is required}"
cross=${CROSS_COMPILE:-arm-linux-gnueabihf-}
arm_flags='-marm -march=armv6zk -mtune=arm1176jzf-s -mfpu=vfp -mfloat-abi=hard'
tool_bin=/usr/lib/gcc-cross/arm-linux-gnueabihf/14/../../../../arm-linux-gnueabihf/bin
unset COMPILER_PATH
case " $* " in
  *' -c '* | *' -E '* | *' -S '*)
    exec "${cross}g++" --sysroot="$PI286_SYSROOT" -B"$tool_bin" -fno-use-linker-plugin $arm_flags "$@"
    ;;
esac
runtime="$PI286_SYSROOT/lib/arm-linux-gnueabihf"
gcc_runtime="$PI286_SYSROOT/usr/lib/gcc/arm-linux-gnueabihf/14"
exec "${cross}g++" --sysroot="$PI286_SYSROOT" -B"$tool_bin" -fno-use-linker-plugin $arm_flags -nostdlib \
  "$runtime/crt1.o" "$runtime/crti.o" "$gcc_runtime/crtbeginS.o" "$@" \
  "$runtime/libstdc++.so.6" "$runtime/libm.so.6" "$runtime/libdl.so.2" \
  "$runtime/libpthread.so.0" "$runtime/libgcc_s.so.1" "$runtime/libc.so.6" \
  "$gcc_runtime/crtendS.o" "$runtime/crtn.o" -Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3
