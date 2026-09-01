#!/bin/sh
# Report Pi thin-client prerequisites without changing the host.
set -u
root=${HEALTH_CHECK_ROOT:-}
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
host_path() { printf '%s%s\n' "$root" "$1"; }
host_setting() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$host_conf" 2>/dev/null | tail -n 1; }
pass() { printf 'OK   %s\n' "$1"; }
warn() { printf 'WARN %s\n' "$1"; }
host_conf=${HEALTH_CHECK_HOST_CONF:-$repo/config/host.conf}

model=$(sed -n '1p' "$(host_path /proc/device-tree/model)" 2>/dev/null | tr -d '\000')
[ -n "$model" ] && printf 'INFO Raspberry Pi model: %s\n' "$model" || warn 'Raspberry Pi model unavailable'
fb0=$(host_path /dev/fb0)
if [ -c "$fb0" ]; then pass "framebuffer $fb0 is available"; else warn "$fb0 is unavailable"; fi
for pair in presenter_sdl_videodriver=fbcon presenter_sdl_fbdev=/dev/fb0 presenter_sdl_fb_broken_modes=1 presenter_ld_library_path=/opt/sdl12-fbcon/lib; do
    key=${pair%%=*}; expected=${pair#*=}; value=$(host_setting "$key")
    [ "$value" = "$expected" ] && pass "presenter setting $pair" || warn "presenter setting $key is '$value' (expected $expected)"
done
presenter=${PI286_STREAM_PRESENTER:-/opt/pi286/stream/bin/pi286-stream-presenter}
[ -x "$presenter" ] && pass "stream presenter: $presenter" || warn "stream presenter is missing: $presenter"
url=$(host_setting remote_dosbox_url)
[ -n "$url" ] && pass "remote DOSBox URL: $url" || warn 'remote DOSBox URL is not configured'
