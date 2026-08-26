#!/bin/sh
# Install for the local autologin DietPi/Debian user. Run as that user.
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run as the autologin user, not root." >&2; exit 1; }
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
user=$(id -un)
home_dir=$(getent passwd "$user" | cut -d: -f6)
if ! command -v dosbox >/dev/null 2>&1 || ! command -v fbi >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y dosbox fbi
fi
if getent group input >/dev/null 2>&1; then sudo usermod -aG input "$user"; fi
if [ ! -f "$repo/config/host.conf" ]; then
    cp "$repo/config/host.conf.example" "$repo/config/host.conf"
    sed -i "s|^game_data_root=.*|game_data_root=$home_dir/pi-286-games-data|" "$repo/config/host.conf"
fi
systemctl_path=$(command -v systemctl)
printf '%s ALL=(root) NOPASSWD: /sbin/shutdown -h now, %s stop pi-286-games-splash.service\n' "$user" "$systemctl_path" | sudo tee /etc/sudoers.d/pi-286-games-shutdown >/dev/null
sudo chmod 0440 /etc/sudoers.d/pi-286-games-shutdown
sudo install -d -m 0755 /usr/local/lib/pi-286-games
sudo install -d -m 0755 /usr/local/share/pi-286-games
sudo install -m 0755 "$repo/scripts/boot-splash.sh" /usr/local/lib/pi-286-games/boot-splash.sh
sudo install -m 0644 "$repo/assets/kockovane-hry-splash.png" /usr/local/share/pi-286-games/kockovane-hry-splash.png
sudo install -m 0644 "$repo/systemd/pi-286-games-splash.service" /etc/systemd/system/pi-286-games-splash.service
boot_cmdline=
for candidate in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
    if [ -f "$candidate" ]; then boot_cmdline=$candidate; break; fi
done
if [ -n "$boot_cmdline" ]; then
    for option in quiet loglevel=0 vt.global_cursor_default=0 logo.nologo; do
        grep -qw "$option" "$boot_cmdline" || sudo sed -i "1 s/$/ $option/" "$boot_cmdline"
    done
fi
sudo systemctl daemon-reload
sudo systemctl enable pi-286-games-splash.service
marker='# pi-286-games launcher'
if ! grep -Fqx "$marker" "$home_dir/.profile" 2>/dev/null; then
    printf '\n%s\nif [ -z "${SSH_CONNECTION:-}" ] && [ "$(tty)" = /dev/tty1 ]; then\n    python3 "%s/launcher/launcher.py" --host-conf "%s/config/host.conf"\nfi\n' "$marker" "$repo" "$repo" >> "$home_dir/.profile"
else
    # Upgrade profiles created by older installer versions that used exec and
    # consequently caused agetty to autologin and restart the launcher again.
    sed -i '/^[[:space:]]*exec ".*\/launcher\/launcher.py" --host-conf /s/^[[:space:]]*exec /    /' "$home_dir/.profile"
    sed -i '/launcher\/launcher.py/ s|^\([[:space:]]*\)"|\1python3 "|' "$home_dir/.profile"
fi
echo "Installed. Put game data under $home_dir/pi-286-games-data and reboot."
