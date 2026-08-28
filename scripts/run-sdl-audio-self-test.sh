#!/bin/sh
# Compile and run a short classic-SDL ALSA test without taking over the tty.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
prefix=${SDL12_FBCON_PREFIX:-/opt/sdl12-fbcon}
[ -x "$prefix/bin/sdl-config" ] || { echo "Missing $prefix/bin/sdl-config; run build-sdl12-fbcon.sh first." >&2; exit 1; }
binary=${SDL12_AUDIO_SELF_TEST_BINARY:-/tmp/pi-286-games-sdl-audio-self-test}
cc "$repo/scripts/sdl-audio-self-test.c" -o "$binary" $("$prefix/bin/sdl-config" --cflags --libs)
echo "Playing a two-second SDL 1.2 square-wave tone through plughw:0,0."
exec env LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" SDL_AUDIODRIVER=alsa AUDIODEV=plughw:0,0 SDL_PATH_DSP=plughw:0,0 "$binary"
