#!/bin/sh
set -eu

# Native helper for x86_64 stream servers (LXC/Zotac), never for the Pi.
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output="$repo/streaming/backend/bin/pi286-xvfb-capture"
mkdir -p "$(dirname -- "$output")"
${CC:-cc} -O2 -std=c11 -Wall -Wextra -Werror -pedantic \
    "$repo/streaming/backend/pi286_xvfb_capture.c" -o "$output"
printf 'Built native stream capture helper: %s\n' "$output"
