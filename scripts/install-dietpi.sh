#!/bin/sh
# Install for the local autologin DietPi/Debian user. Run as that user.
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run as the autologin user, not root." >&2; exit 1; }
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
user=$(id -un)
home_dir=$(getent passwd "$user" | cut -d: -f6)
if ! command -v dosbox >/dev/null 2>&1; then sudo apt-get update; sudo apt-get install -y dosbox; fi
if getent group input >/dev/null 2>&1; then sudo usermod -aG input "$user"; fi
if [ ! -f "$repo/config/host.conf" ]; then
    cp "$repo/config/host.conf.example" "$repo/config/host.conf"
    sed -i "s|^game_data_root=.*|game_data_root=$home_dir/pi-286-games-data|" "$repo/config/host.conf"
fi
printf '%s ALL=(root) NOPASSWD: /sbin/shutdown -h now\n' "$user" | sudo tee /etc/sudoers.d/pi-286-games-shutdown >/dev/null
sudo chmod 0440 /etc/sudoers.d/pi-286-games-shutdown
marker='# pi-286-games launcher'
if ! grep -Fqx "$marker" "$home_dir/.profile" 2>/dev/null; then
    printf '\n%s\nif [ -z "${SSH_CONNECTION:-}" ] && [ "$(tty)" = /dev/tty1 ]; then\n    exec "%s/launcher/launcher.py" --host-conf "%s/config/host.conf"\nfi\n' "$marker" "$repo" "$repo" >> "$home_dir/.profile"
fi
chmod +x "$repo/launcher/launcher.py"
echo "Installed. Put game data under $home_dir/pi-286-games-data and reboot."
