#!/bin/sh
# Development-only browser viewer for a headless x86_64 DietPi/Debian host.
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
password_file=${PI_286_XPRA_PASSWORD_FILE:-"$HOME/.config/pi-286-games/xpra-password"}
bind_address=${PI_286_XPRA_BIND:-127.0.0.1:14500}

if ! command -v xpra >/dev/null 2>&1 || ! command -v xterm >/dev/null 2>&1; then
    echo "Install xpra, xpra-html5, xpra-audio-server, and xterm first." >&2
    exit 1
fi

auth_options=""
if [ "${PI_286_XPRA_TRUST_TAILSCALE:-0}" != "1" ]; then
    mkdir -p "$(dirname -- "$password_file")"
    if [ ! -s "$password_file" ]; then
        umask 077
        openssl rand -base64 24 | tr -d '\n' > "$password_file"
        echo "Xpra password written to $password_file" >&2
    fi
    auth_options="--password-file=$password_file --tcp-auth=file:filename=$password_file --ws-auth=file:filename=$password_file"
fi

exec xpra start :100 \
    --daemon=no \
    --bind-tcp="$bind_address" \
    --html=on \
    --ssh=off \
    --mdns=no \
    --webcam=no \
    --start-new-commands=no \
    $auth_options \
    --speaker=on \
    --microphone=off \
    --exit-with-children=yes \
    --start-child="xterm -fullscreen -fa 'DejaVu Sans Mono' -fs 20 -e python3 $repo/launcher/launcher.py --host-conf $repo/config/host.conf"
