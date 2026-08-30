#!/bin/sh
# Exercise the Pi SDL stream presenter's manual RGB565 renderer without a server.
set -eu

prefix=${PI286_STREAM_PREFIX:-/opt/pi286/stream}
sdl_prefix=${SDL12_FBCON_PREFIX:-/opt/sdl12-fbcon}
presenter=$prefix/bin/pi286-stream-presenter

[ -x "$presenter" ] || { echo "Missing stream presenter: $presenter" >&2; exit 1; }
[ -e "$sdl_prefix/lib/libSDL-1.2.so.0" ] || { echo "Missing classic SDL: $sdl_prefix" >&2; exit 1; }

exec env LD_LIBRARY_PATH="$sdl_prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 SDL_FB_BROKEN_MODES=1 \
    PI286_SDL_FB_PILLARBOX=1 \
    "$presenter" --local-pattern
