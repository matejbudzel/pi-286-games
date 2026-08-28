#!/bin/sh
# Run a reproducible 20-second Grand Prix DOSBox baseline on the Pi console.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
duration=20
dosbox=dosbox
case "${1:-}" in
  --custom-dosbox) dosbox=${2:?Usage: $0 [--custom-dosbox PATH]}; shift 2 ;;
  --duration) duration=${2:?Usage: $0 [--duration SECONDS]}; shift 2 ;;
  '') ;;
  *) echo "Usage: $0 [--custom-dosbox PATH] [--duration SECONDS]" >&2; exit 2 ;;
esac
[ "$#" -eq 0 ] || { echo "Usage: $0 [--custom-dosbox PATH] [--duration SECONDS]" >&2; exit 2; }
case "$duration" in *[!0-9]*|'') echo "Duration must be a positive integer." >&2; exit 2;; esac
[ "$duration" -gt 0 ] || { echo "Duration must be a positive integer." >&2; exit 2; }
command -v "$dosbox" >/dev/null 2>&1 || { echo "DOSBox command not found: $dosbox" >&2; exit 1; }
host_conf=$repo/config/host.conf
value() { [ -f "$host_conf" ] && sed -n "s/^$1=//p" "$host_conf" | tail -n 1 || true; }
data_root=$(value game_data_root); data_root=${data_root:-~/pi-286-game-files}
case "$data_root" in '~/'*) data_root=$HOME/${data_root#~/};; esac
game_dir=$data_root/grand-prix
[ -d "$game_dir" ] || { echo "Grand Prix data directory is missing: $game_dir" >&2; exit 1; }
stamp=$(date +%Y%m%d-%H%M%S); out_dir=${PG_MEASURE_DIR:-$HOME/pi286-measurements}/grand-prix-$stamp
mkdir -p "$out_dir"; tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT HUP INT TERM
base=$tmp/base.conf; generated=$tmp/autoexec.conf; time_log=$out_dir/time.txt; dosbox_log=$out_dir/dosbox.log
printf '%s\n' '[sdl]' 'fullscreen=true' 'fulldouble=false' 'fullfixed=true' 'fullresolution=640x480' 'output=surface' 'usescancodes=false' '' '[render]' 'frameskip=0' 'aspect=true' 'scaler=normal2x' '' '[mixer]' 'rate=22050' 'blocksize=2048' 'prebuffer=100' '' '[sblaster]' 'sbtype=none' '' '[speaker]' 'pcspeaker=true' 'pcrate=22050' 'tandy=off' 'disney=false' '' '[midi]' 'mpu401=none' 'mididevice=none' > "$base"
printf '[sdl]\nmapperfile=%s\n\n[autoexec]\nmount c "%s"\nc:\nGPEGA.EXE\nexit\n' "$repo/games/grand-prix/mapper.txt" "$game_dir" > "$generated"
export LD_LIBRARY_PATH="$(value dosbox_ld_library_path)" SDL_VIDEODRIVER="$(value dosbox_sdl_videodriver)" SDL_FBDEV="$(value dosbox_sdl_fbdev)" SDL_FB_BROKEN_MODES="$(value dosbox_sdl_fb_broken_modes)"
export SDL_AUDIODRIVER=alsa AUDIODEV=plughw:0,0 SDL_PATH_DSP=plughw:0,0 SDL_DSP_NOSELECT=1
start=$(date +%s); /usr/bin/time -v -o "$time_log" "$dosbox" -conf "$base" -conf "$repo/games/grand-prix/dosbox.conf" -conf "$generated" > "$dosbox_log" 2>&1 & wrapper=$!
sleep 1; pid=$(pgrep -P "$wrapper" | head -n 1 || true); max_rss=0
while kill -0 "$wrapper" 2>/dev/null && [ $(( $(date +%s) - start )) -lt "$duration" ]; do
    if [ -n "$pid" ] && [ -r "/proc/$pid/status" ]; then rss=$(sed -n 's/^VmRSS:[[:space:]]*\([0-9]*\).*/\1/p' "/proc/$pid/status"); [ "${rss:-0}" -gt "$max_rss" ] && max_rss=$rss; fi
    sleep 1
done
if kill -0 "$wrapper" 2>/dev/null; then [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null || true; sleep 3; kill -0 "$wrapper" 2>/dev/null && kill -KILL "$wrapper" 2>/dev/null || true; fi
wait "$wrapper" || true
printf 'dosbox=%s\nduration_seconds=%s\nmax_observed_rss_kib=%s\nbase_config=%s\ngame_config=%s\n' "$(command -v "$dosbox")" "$duration" "$max_rss" "$base" "$repo/games/grand-prix/dosbox.conf" > "$out_dir/report.txt"
if [ -f "$time_log" ]; then
    sed -n '1,$p' "$time_log" >> "$out_dir/report.txt"
else
    printf 'GNU time did not produce %s; see %s for the DOSBox launch error.\n' "$time_log" "$dosbox_log" >> "$out_dir/report.txt"
fi
printf 'Measurement written to %s\n' "$out_dir/report.txt"
