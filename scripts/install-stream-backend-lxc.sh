#!/bin/sh
set -eu

# Run as root inside the dedicated LXC after cloning this public repository to
# /opt/pi286-stream/repo. This installs no game data.
if [ "$(id -u)" -ne 0 ]; then
    echo "error: run as root inside the stream LXC" >&2
    exit 1
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
apt-get update
apt-get install -y --no-install-recommends alsa-utils dosbox xvfb x11-apps xdotool python3 ca-certificates git
id -u pi286stream >/dev/null 2>&1 || useradd --system --home /srv/pi286-stream --shell /usr/sbin/nologin pi286stream
install -d -o pi286stream -g pi286stream -m 0750 /srv/pi286-stream/blobs /srv/pi286-stream/sessions /srv/pi286-stream/runtime
install -o root -g pi286stream -m 0640 "$repo_root/config/pi286-stream.conf.example" /etc/pi286-stream.conf
if [ ! -s /etc/pi286-stream.token ]; then
    umask 077
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))' >/etc/pi286-stream.token
fi
chown root:pi286stream /etc/pi286-stream.token
chmod 0640 /etc/pi286-stream.token
install -o root -g root -m 0644 "$repo_root/systemd/pi286-stream.service" /etc/systemd/system/pi286-stream.service
systemctl daemon-reload
systemctl enable pi286-stream.service
systemctl restart pi286-stream.service
echo "Backend installed. Read the token only on the LXC: /etc/pi286-stream.token"
