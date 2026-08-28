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
valid_install() { [ -x "$prefix/bin/sdl-config" ] && [ -e "$prefix/lib/libSDL-1.2.so.0" ] && [ -f "$prefix/.pi286-sdl-fbcon-pillarbox" ] && [ "$("$prefix/bin/sdl-config" --version 2>/dev/null)" = 1.2.16 ] && ldd "$prefix/lib/libSDL-1.2.so.0" 2>/dev/null | grep -q 'libasound\.so'; }
if valid_install; then echo "Classic SDL $("$prefix/bin/sdl-config" --version) already installed at $prefix."; exit 0; fi
if [ "$(id -u)" -eq 0 ]; then sudo_cmd=; else sudo_cmd=sudo; fi
$sudo_cmd apt-get update
$sudo_cmd apt-get install -y build-essential git autoconf automake libtool libasound2-dev
build_dir=$(mktemp -d /tmp/pi-286-games-sdl12-fbcon.XXXXXX)
trap 'rm -rf "$build_dir"' EXIT HUP INT TERM
git clone "$source_url" "$build_dir"
cd "$build_dir"
git checkout --detach "$source_commit"
[ -f src/video/fbcon/SDL_fbvideo.c ] || { echo "Pinned SDL source has no fbcon backend." >&2; exit 1; }
git apply "$pillarbox_patch"
./autogen.sh
./configure --prefix="$prefix" --enable-audio --enable-alsa --disable-alsa-shared --enable-video-fbcon --disable-video-x11 --disable-video-opengl
make -j"$jobs"
$sudo_cmd make install
$sudo_cmd touch "$prefix/.pi286-sdl-fbcon-pillarbox"
if ! valid_install; then echo "Classic SDL installation is missing, has the wrong version, or lacks libSDL-1.2.so.0." >&2; exit 1; fi
echo "Installed classic SDL $("$prefix/bin/sdl-config" --version) at $prefix"
echo "Library: $prefix/lib/libSDL-1.2.so.0"
