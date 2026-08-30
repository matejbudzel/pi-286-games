#!/bin/sh
set -eu

# Capture a short PCM sample from the active remote presenter. This isolates
# the backend's audio content from the SDL presenter callback while using the
# appliance's normal ALSA output for playback.
output=${XDG_CACHE_HOME:-"$HOME/.cache"}/pi286-stream-audio-sample.pcm

if [ "${1:-}" = "--play" ]; then
    if pgrep -f '/opt/pi286/stream/bin/pi286-stream-presenter ' >/dev/null 2>&1; then
        echo "Najprv ukonči vzdialenú hru klávesom F1." >&2
        exit 1
    fi
    if [ ! -s "$output" ]; then
        echo "Vzorka zvuku ešte nebola uložená." >&2
        exit 1
    fi
    exec aplay -D default -r 22050 -f S16_LE -c 1 "$output"
fi

pid=$(pgrep -fo '/opt/pi286/stream/bin/pi286-stream-presenter ' || true)
if [ -z "$pid" ]; then
    echo "Vzdialená hra práve nebeží." >&2
    exit 1
fi
set -- $(tr '\000' ' ' < "/proc/$pid/cmdline")
host=$2
port=$3
token_file=$4
session=$5
token=$(tr -d '\r\n' < "$token_file")
mkdir -p "$(dirname "$output")"
: > "$output"

# Six bounded responses are about 8.9 seconds of 22050 Hz S16LE mono PCM.
offset=0
while [ "$offset" -lt 393216 ]; do
    curl --fail --silent --show-error --max-time 10 \
        -H "Authorization: Bearer $token" \
        "http://$host:$port/v1/sessions/$session/audio?offset=$offset" >> "$output"
    offset=$((offset + 65536))
done
echo "Vzorka uložená: $output"
echo "Ukonči hru klávesom F1 a potom spusti:"
echo "  sh scripts/capture-remote-audio-sample.sh --play"
