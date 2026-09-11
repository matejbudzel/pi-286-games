#!/bin/sh
# Run as root on the Proxmox host, never inside LXC 112.
set -eu

container=${PI286_STREAM_CONTAINER:-112}
service=pi286-stream-loopback.service

[ "$(id -u)" -eq 0 ] || { echo "error: run as root on the Proxmox host" >&2; exit 1; }
command -v pct >/dev/null || { echo "error: pct is required on the Proxmox host" >&2; exit 1; }

# Reserve card 0 before the physical HDA driver claims a card number.  The
# stable ALSA id is used by the backend; C0 is needed for LXC device nodes.
rm -f /etc/modules-load.d/snd-aloop.conf /etc/modules-load.d/pi286-stream-loopback.conf
printf '%s\n' 'options snd_aloop index=0 id=Loopback enable=1' > /etc/modprobe.d/pi286-stream-loopback.conf
printf '%s\n' 'snd_aloop' > /etc/modules-load.d/pi286-stream-loopback.conf

cat > "/etc/systemd/system/$service" <<EOF
[Unit]
Description=Pi286 ALSA loopback readiness
After=systemd-modules-load.service
Before=pve-container@$container.service

[Service]
Type=oneshot
ExecStart=/sbin/modprobe snd_aloop
ExecStart=/usr/bin/test -c /dev/snd/controlC0
ExecStart=/usr/bin/test -c /dev/snd/pcmC0D0p
ExecStart=/usr/bin/test -c /dev/snd/pcmC0D1c
RemainAfterExit=yes
EOF

mkdir -p "/etc/systemd/system/pve-container@$container.service.d"
cat > "/etc/systemd/system/pve-container@$container.service.d/pi286-loopback.conf" <<EOF
[Unit]
Requires=$service
After=$service
EOF

# A running container can hold the old device nodes open.  Recreate the
# module and mapping as one transaction, then start the server only after all
# required endpoints exist.
pct stop "$container" || true
modprobe -r snd_aloop 2>/dev/null || true
systemctl daemon-reload
systemctl start "$service"
pct set "$container" \
    -dev0 /dev/snd/controlC0,uid=999,gid=991,mode=0660 \
    -dev1 /dev/snd/pcmC0D0p,uid=999,gid=991,mode=0660 \
    -dev3 /dev/snd/pcmC0D1c,uid=999,gid=991,mode=0660
pct start "$container"

printf '%s\n' 'Configured snd_aloop as card 0 and passed playback/capture nodes to LXC.'
