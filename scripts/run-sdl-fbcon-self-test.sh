#!/bin/sh
# Compile and run a short, visible classic-SDL fbcon test on the active tty.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
prefix=${SDL12_FBCON_PREFIX:-/opt/sdl12-fbcon}
pillarbox=${PI286_SDL_FB_PILLARBOX:-0}
canvas_color=
case "${1:-}" in
    '') [ "$#" -eq 0 ] || { echo "Usage: sh scripts/run-sdl-fbcon-self-test.sh [--pillarbox|--sdl-canvas-magenta]" >&2; exit 2; } ;;
    --pillarbox) [ "$#" -eq 1 ] || { echo "Usage: sh scripts/run-sdl-fbcon-self-test.sh [--pillarbox|--sdl-canvas-magenta]" >&2; exit 2; }; pillarbox=1 ;;
    --sdl-canvas-magenta) [ "$#" -eq 1 ] || { echo "Usage: sh scripts/run-sdl-fbcon-self-test.sh [--pillarbox|--sdl-canvas-magenta]" >&2; exit 2; }; pillarbox=1; canvas_color=ff00ff ;;
    *) echo "Usage: sh scripts/run-sdl-fbcon-self-test.sh [--pillarbox|--sdl-canvas-magenta]" >&2; exit 2 ;;
esac
[ -x "$prefix/bin/sdl-config" ] || { echo "Missing $prefix/bin/sdl-config; run build-sdl12-fbcon.sh first." >&2; exit 1; }
binary=${SDL12_FBCON_SELF_TEST_BINARY:-/tmp/pi-286-games-sdl-fbcon-self-test}
cc "$repo/scripts/sdl-fbcon-self-test.c" -o "$binary" $("$prefix/bin/sdl-config" --cflags --libs)
echo "Showing a 640x480 blue test pattern with white border and yellow centre line for three seconds; this takes over the active tty."
if [ -n "$canvas_color" ]; then
    exec env LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-fbcon}" SDL_FBDEV="${SDL_FBDEV:-/dev/fb0}" SDL_FB_BROKEN_MODES="${SDL_FB_BROKEN_MODES:-1}" PI286_SDL_FB_PILLARBOX="$pillarbox" PI286_SDL_FB_CANVAS_COLOR="$canvas_color" "$binary"
fi
exec env LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-fbcon}" SDL_FBDEV="${SDL_FBDEV:-/dev/fb0}" SDL_FB_BROKEN_MODES="${SDL_FB_BROKEN_MODES:-1}" PI286_SDL_FB_PILLARBOX="$pillarbox" "$binary"
