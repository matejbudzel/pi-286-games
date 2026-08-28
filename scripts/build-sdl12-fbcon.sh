#!/bin/sh
# Build the pinned classic SDL 1.2 fbcon implementation without touching system SDL.
set -eu
prefix=${SDL12_FBCON_PREFIX:-/opt/sdl12-fbcon}
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
pillarbox_patch=$repo/patches/0001-pi286-fbcon-optional-pillarbox.patch
source_url=https://github.com/libsdl-org/SDL-1.2.git
# SDL 1.2.16, pinned rather than tracking the upstream branch. This revision retains fbcon.
source_commit=7bf353eca59cb503f43b86e3867dc4fc4e45f2e3
jobs=${SDL12_FBCON_JOBS:-1}
build_dir=${SDL12_FBCON_BUILD_DIR:-/home/dietpi/pi-286-games-sdl12-fbcon}
valid_install() { [ -x "$prefix/bin/sdl-config" ] && [ -e "$prefix/lib/libSDL-1.2.so.0" ] && [ -f "$prefix/.pi286-sdl-fbcon-pillarbox" ] && [ "$("$prefix/bin/sdl-config" --version 2>/dev/null)" = 1.2.16 ] && ldd "$prefix/lib/libSDL-1.2.so.0" 2>/dev/null | grep -q 'libasound\.so'; }
if [ "$(id -u)" -eq 0 ]; then sudo_cmd=; else sudo_cmd=sudo; fi
$sudo_cmd apt-get update
$sudo_cmd apt-get install -y build-essential git autoconf automake libtool libasound2-dev
if [ -e "$build_dir" ] && [ ! -d "$build_dir/.git" ]; then
    echo "SDL build directory exists but is not a Git checkout: $build_dir" >&2
    exit 1
fi
if [ ! -e "$build_dir" ]; then
    git clone "$source_url" "$build_dir"
    cd "$build_dir"
    git checkout --detach "$source_commit"
else
    echo "Reusing persistent SDL build directory: $build_dir"
    cd "$build_dir"
fi
[ -f src/video/fbcon/SDL_fbvideo.c ] || { echo "Pinned SDL source has no fbcon backend." >&2; exit 1; }
if git apply --check "$pillarbox_patch"; then
    git apply "$pillarbox_patch"
elif git apply --reverse --check "$pillarbox_patch"; then
    : # Patch was applied by a prior build; retain local SDL customizations.
else
    echo "Cannot apply the Pi fbcon patch cleanly in $build_dir; resolve it there without discarding local changes." >&2
    exit 1
fi
./autogen.sh
./configure --prefix="$prefix" --enable-audio --enable-alsa --disable-alsa-shared --enable-video-fbcon --disable-video-x11 --disable-video-opengl
make -j"$jobs"
$sudo_cmd make install
$sudo_cmd touch "$prefix/.pi286-sdl-fbcon-pillarbox"
if ! valid_install; then echo "Classic SDL installation is missing, has the wrong version, or lacks libSDL-1.2.so.0." >&2; exit 1; fi
echo "Installed classic SDL $("$prefix/bin/sdl-config" --version) at $prefix"
echo "Library: $prefix/lib/libSDL-1.2.so.0"
