#!/bin/sh
set -eu

# Deploy only the Pi-side presenter and its private bearer token. It never
# changes server DOSBox or copies game files.
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
"$repo/scripts/cross-build-stream-presenter.sh"
target=${PI286_STREAM_TARGET:-pi286}
proxmox=${PI286_STREAM_PROXMOX:-proxmox}
container=${PI286_STREAM_CONTAINER:-112}
binary=${STREAM_PRESENTER_OUTPUT:-$repo/dist/pi286-stream-presenter-rpi1-armv6-armhf}
origin=$(git -C "$repo" config --get remote.origin.url)
remote_repo=${PI286_STREAM_PI_REPO:-/home/dietpi/pi-286-games}
ssh "$target" 'mkdir -p ~/.config; sudo -n install -d -m 0755 /opt/pi286/stream/bin'
scp "$binary" "$target":/tmp/pi286-stream-presenter
ssh "$target" 'sudo -n install -m 0755 /tmp/pi286-stream-presenter /opt/pi286/stream/bin/pi286-stream-presenter; rm -f /tmp/pi286-stream-presenter'
ssh "$proxmox" "pct exec $container -- cat /etc/pi286-stream.token" | ssh "$target" 'umask 077; cat > ~/.config/pi286-stream.token'
ssh "$target" 'chmod 600 ~/.config/pi286-stream.token'
ssh "$target" "set -eu; if [ -d '$remote_repo/.git' ]; then git -C '$remote_repo' pull --ff-only; else git clone '$origin' '$remote_repo'; fi; test -f '$remote_repo/config/provider.conf' || cp '$remote_repo/config/provider.conf.example' '$remote_repo/config/provider.conf'; sudo -n ln -sfn '$remote_repo/bin/pi-286-games' /usr/local/bin/pi-286-games"
echo "Presenter and provider deployed. Add 'manifest_command=pi-286-games manifest' to pi-games-launcher/config/launcher.conf."
