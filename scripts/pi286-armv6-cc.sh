#!/bin/sh
# ARMv6 counterpart of pi286-armv6-cxx.sh for Autoconf and C source files.
set -eu
: "${PI286_SYSROOT:?PI286_SYSROOT is required}"
cross=${CROSS_COMPILE:-arm-linux-gnueabihf-}
arm_flags='-marm -march=armv6zk -mtune=arm1176jzf-s -mfpu=vfp -mfloat-abi=hard'
unset COMPILER_PATH
case " $* " in
  *' -c '* | *' -E '* | *' -S '*)
    exec "${cross}gcc" --sysroot="$PI286_SYSROOT" -fno-use-linker-plugin $arm_flags "$@"
    ;;
esac
runtime="$PI286_SYSROOT/lib/arm-linux-gnueabihf"
exec "${cross}gcc" --sysroot="$PI286_SYSROOT" -fno-use-linker-plugin $arm_flags -nostdlib \
  "$runtime/crt1.o" "$runtime/crti.o" "$@" \
  "$runtime/libm.so.6" "$runtime/libdl.so.2" "$runtime/libpthread.so.0" \
  "$runtime/libgcc_s.so.1" "$runtime/libc.so.6" "$runtime/crtn.o" \
  -Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3
