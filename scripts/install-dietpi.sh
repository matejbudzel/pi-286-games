#!/bin/sh
# Install for the local autologin DietPi/Debian user. Run as that user.
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run as the autologin user, not root." >&2; exit 1; }
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
user=$(id -un)
home_dir=$(getent passwd "$user" | cut -d: -f6)
if ! command -v dosbox >/dev/null 2>&1 || ! command -v plymouth-set-default-theme >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y dosbox plymouth plymouth-themes
fi
if getent group input >/dev/null 2>&1; then sudo usermod -aG input "$user"; fi
if [ ! -f "$repo/config/host.conf" ]; then
    cp "$repo/config/host.conf.example" "$repo/config/host.conf"
    sed -i "s|^game_data_root=.*|game_data_root=$home_dir/pi-286-game-files|" "$repo/config/host.conf"
fi
printf '%s ALL=(root) NOPASSWD: /sbin/shutdown -h now\n' "$user" | sudo tee /etc/sudoers.d/pi-286-games-shutdown >/dev/null
sudo chmod 0440 /etc/sudoers.d/pi-286-games-shutdown

# Remove the old fbi-based splash when upgrading an existing installation.
sudo systemctl disable --now pi-286-games-splash.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/pi-286-games-splash.service /usr/local/lib/pi-286-games/boot-splash.sh

theme_dir=/usr/share/plymouth/themes/pi-286-games
sudo install -d -m 0755 "$theme_dir"
sudo install -m 0644 "$repo/assets/kockovane-hry-splash.png" "$theme_dir/kockovane-hry-splash.png"
sudo install -m 0644 "$repo/plymouth/pi-286-games/pi-286-games.plymouth" "$theme_dir/pi-286-games.plymouth"
sudo install -m 0644 "$repo/plymouth/pi-286-games/pi-286-games.script" "$theme_dir/pi-286-games.script"

boot_args='quiet splash plymouth.ignore-serial-consoles loglevel=3 vt.global_cursor_default=0'
if [ -f /boot/dietpiEnv.txt ]; then
    if grep -q '^extraargs=' /boot/dietpiEnv.txt; then
        for option in $boot_args; do
            if ! sed -n 's/^extraargs=//p' /boot/dietpiEnv.txt | tr ' ' '\n' | grep -Fxq "$option"; then
                sudo sed -i "/^extraargs=/ s/$/ $option/" /boot/dietpiEnv.txt
            fi
        done
    else
        printf 'extraargs=%s\n' "$boot_args" | sudo tee -a /boot/dietpiEnv.txt >/dev/null
    fi
else
    boot_cmdline=
    for candidate in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
        if [ -f "$candidate" ]; then boot_cmdline=$candidate; break; fi
    done
    if [ -n "$boot_cmdline" ]; then
        for option in $boot_args; do
            grep -qw "$option" "$boot_cmdline" || sudo sed -i "1 s/$/ $option/" "$boot_cmdline"
        done
    else
        echo "WARNING: no DietPi boot configuration was found; add '$boot_args' manually." >&2
    fi
fi
sudo plymouth-set-default-theme -R pi-286-games
sudo systemctl daemon-reload
marker='# pi-286-games launcher'
if ! grep -Fqx "$marker" "$home_dir/.profile" 2>/dev/null; then
    printf '\n%s\nif [ -z "${SSH_CONNECTION:-}" ] && [ "$(tty)" = /dev/tty1 ]; then\n    python3 "%s/launcher/launcher.py" --host-conf "%s/config/host.conf"\nfi\n' "$marker" "$repo" "$repo" >> "$home_dir/.profile"
else
    # Upgrade profiles created by older installer versions that used exec and
    # consequently caused agetty to autologin and restart the launcher again.
    sed -i '/^[[:space:]]*exec ".*\/launcher\/launcher.py" --host-conf /s/^[[:space:]]*exec /    /' "$home_dir/.profile"
    sed -i '/launcher\/launcher.py/ s|^\([[:space:]]*\)"|\1python3 "|' "$home_dir/.profile"
fi
echo "Installed. Put game data under $home_dir/pi-286-game-files and reboot to see the Plymouth splash."
