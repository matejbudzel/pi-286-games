#!/bin/sh
set -eu

# Capture a short PCM sample from the active remote presenter. This isolates
# the backend's audio content from the SDL presenter callback while using the
# appliance's normal ALSA output for playback.
output=${XDG_CACHE_HOME:-"$HOME/.cache"}/pi286-stream-audio-sample.pcm
raw_output=${XDG_CACHE_HOME:-"$HOME/.cache"}/pi286-stream-audio-source-sample.pcm
mode=${1:-}

if [ "$mode" = "--play" ]; then
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

if [ "$mode" = "--play-raw" ]; then
    if pgrep -f '/opt/pi286/stream/bin/pi286-stream-presenter ' >/dev/null 2>&1; then
        echo "Najprv ukonči vzdialenú hru klávesom F1." >&2
        exit 1
    fi
    if [ ! -s "$raw_output" ]; then
        echo "Surová vzorka zvuku ešte nebola uložená." >&2
        exit 1
    fi
    exec aplay -D default -r 22050 -f S16_LE -c 2 "$raw_output"
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
if [ "$mode" = "--raw" ]; then
    output=$raw_output
    endpoint=audio-source
else
    endpoint=audio
fi
: > "$output"

# Six bounded responses are about 8.9 seconds as mono PCM or 4.5 seconds as
# raw stereo PCM.
offset=0
while [ "$offset" -lt 393216 ]; do
    curl --fail --silent --show-error --max-time 10 \
        -H "Authorization: Bearer $token" \
        "http://$host:$port/v1/sessions/$session/$endpoint?offset=$offset" >> "$output"
    offset=$((offset + 65536))
done
echo "Vzorka uložená: $output"
echo "Ukonči hru klávesom F1 a potom spusti:"
if [ "$endpoint" = "audio-source" ]; then
    echo "  sh scripts/capture-remote-audio-sample.sh --play-raw"
else
    echo "  sh scripts/capture-remote-audio-sample.sh --play"
fi
