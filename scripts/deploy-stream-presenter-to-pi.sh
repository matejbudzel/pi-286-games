#!/bin/sh
set -eu

# Deploy only the Pi-side presenter and its private bearer token. It never
# changes distro DOSBox or copies game files.
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
"$repo/scripts/cross-build-stream-presenter.sh"
target=${PI286_STREAM_TARGET:-pi286}
proxmox=${PI286_STREAM_PROXMOX:-proxmox}
container=${PI286_STREAM_CONTAINER:-112}
binary=${STREAM_PRESENTER_OUTPUT:-$repo/dist/pi286-stream-presenter-rpi1-armv6-armhf}
ssh "$target" 'mkdir -p ~/.config; sudo -n install -d -m 0755 /opt/pi286/stream/bin'
scp "$binary" "$target":/tmp/pi286-stream-presenter
ssh "$target" 'sudo -n install -m 0755 /tmp/pi286-stream-presenter /opt/pi286/stream/bin/pi286-stream-presenter; rm -f /tmp/pi286-stream-presenter'
ssh "$proxmox" "pct exec $container -- cat /etc/pi286-stream.token" | ssh "$target" 'umask 077; cat > ~/.config/pi286-stream.token'
ssh "$target" 'chmod 600 ~/.config/pi286-stream.token'
echo "Presenter deployed. Set dosbox_backend=auto and remote_dosbox_url=http://192.168.100.194:28680 in config/host.conf; set remote_dosbox_transport=websocket to test native WebSocket mode."
