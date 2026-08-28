#!/bin/sh
# Install for the local autologin DietPi/Debian user. Run as that user.
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run as the autologin user, not root." >&2; exit 1; }
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
user=$(id -un)
home_dir=$(getent passwd "$user" | cut -d: -f6)
[ "$(uname -m)" = armv6l ] || { echo "This installer supports only the ARMv6 Raspberry Pi Model B Rev 1 appliance." >&2; exit 1; }
[ -r /proc/device-tree/model ] && grep -aq 'Raspberry Pi Model B Rev 1' /proc/device-tree/model || { echo "This installer supports only Raspberry Pi Model B Rev 1." >&2; exit 1; }
if ! command -v dosbox >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y dosbox
fi
if ! command -v fbset >/dev/null 2>&1 || ! command -v aplay >/dev/null 2>&1 || ! command -v speaker-test >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y fbset alsa-utils
fi
for group in input audio; do if getent group "$group" >/dev/null 2>&1; then sudo usermod -aG "$group" "$user"; fi; done
# The Pi 1 legacy framebuffer path needs real SDL 1.2, not Debian's
# sdl12-compat. Build it before writing the host runtime environment.
"$repo/scripts/build-sdl12-fbcon.sh"
if [ ! -f "$repo/config/host.conf" ]; then
    cp "$repo/config/host.conf.example" "$repo/config/host.conf"
    sed -i "s|^game_data_root=.*|game_data_root=$home_dir/pi-286-game-files|" "$repo/config/host.conf"
fi
if [ -x /opt/sdl12-fbcon/bin/sdl-config ] && [ "$(/opt/sdl12-fbcon/bin/sdl-config --version 2>/dev/null)" = 1.2.16 ] && [ -e /opt/sdl12-fbcon/lib/libSDL-1.2.so.0 ]; then
    for setting in \
        'dosbox_ld_library_path=/opt/sdl12-fbcon/lib' \
        'dosbox_sdl_videodriver=fbcon' \
        'dosbox_sdl_fbdev=/dev/fb0' \
        'dosbox_sdl_fb_broken_modes=1'; do
        key=${setting%%=*}
        if grep -q "^$key=" "$repo/config/host.conf"; then
            sed -i "s|^$key=.*|$setting|" "$repo/config/host.conf"
        else
            printf '%s\n' "$setting" >> "$repo/config/host.conf"
        fi
    done
    grep -q '^dosbox_sdl_fb_pillarbox=' "$repo/config/host.conf" || printf '%s\n' 'dosbox_sdl_fb_pillarbox=0' >> "$repo/config/host.conf"
else
    echo "INFO: custom classic SDL is not installed; leaving DOSBox SDL settings unchanged."
fi
sudo HOST_CONF="$repo/config/host.conf" "$repo/scripts/configure-legacy-framebuffer.sh"
sudo "$repo/scripts/configure-appliance-audio.sh"
printf '%s ALL=(root) NOPASSWD: /sbin/shutdown -h now, /usr/bin/systemctl mask --runtime --now getty@tty1.service, /usr/bin/systemctl unmask --runtime getty@tty1.service, /usr/bin/systemctl stop pi-286-games.service, /usr/bin/systemctl start pi-286-games.service, /usr/bin/systemctl start getty@tty1.service\n' "$user" | sudo tee /etc/sudoers.d/pi-286-games-shutdown >/dev/null
sudo chmod 0440 /etc/sudoers.d/pi-286-games-shutdown

sudo systemctl daemon-reload
marker='# pi-286-games launcher'
# Remove the previous tty1 login-shell hook. The marker and closing fi belong
# to this installer, so this does not affect unrelated profile settings.
sed -i "/^$marker$/,/^fi$/d" "$home_dir/.profile"
# Keep the appliance maintenance commands available after every interactive
# Bash login without changing unrelated shell customisation.
bashrc="$home_dir/.bashrc"
aliases_begin='# pi-286-games aliases'
aliases_end='# end pi-286-games aliases'
touch "$bashrc"
sed -i "/^$aliases_begin$/,/^$aliases_end$/d" "$bashrc"
{
    printf '%s\n' "$aliases_begin"
    printf "alias pg-install='cd %s && ./scripts/install-dietpi.sh'\n" "$repo"
    printf "alias pg-start='cd %s && python3 launcher/launcher.py'\n" "$repo"
    printf "alias pg-update='cd %s && git pull --ff-only && ./scripts/install-dietpi.sh'\n" "$repo"
    printf "alias pg-check='cd %s && sh scripts/health-check.sh'\n" "$repo"
    printf "alias pg-restart='cd %s && ./scripts/restart-launcher.sh'\n" "$repo"
    printf "alias pg-resolution='cd %s && ./scripts/set-framebuffer-profile.sh'\n" "$repo"
    printf '%s\n' "$aliases_end"
} >> "$bashrc"
service=/etc/systemd/system/pi-286-games.service
sed -e "s|@USER@|$user|g" -e "s|@HOME@|$home_dir|g" -e "s|@REPO@|$repo|g" "$repo/systemd/pi-286-games.service.in" | sudo tee "$service" >/dev/null
sudo install -m 0644 "$repo/systemd/pi-286-games-audio.service" /etc/systemd/system/pi-286-games-audio.service
sudo systemctl daemon-reload
sudo systemctl enable pi-286-games-audio.service
sudo systemctl enable pi-286-games.service
echo "Installed. Put game data under $home_dir/pi-286-game-files and reboot for the direct DietPi-console-to-launcher handoff. Run 'source $bashrc' to use the pg-* aliases now."
