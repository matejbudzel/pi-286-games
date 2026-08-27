#!/bin/sh
# Install for the local autologin DietPi/Debian user. Run as that user.
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run as the autologin user, not root." >&2; exit 1; }
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
user=$(id -un)
home_dir=$(getent passwd "$user" | cut -d: -f6)
[ "$(uname -m)" = armv6l ] || { echo "This installer supports only the ARMv6 Raspberry Pi Model B Rev 1 appliance." >&2; exit 1; }
[ -r /proc/device-tree/model ] && grep -aq 'Raspberry Pi Model B Rev 1' /proc/device-tree/model || { echo "This installer supports only Raspberry Pi Model B Rev 1." >&2; exit 1; }
if ! command -v dosbox >/dev/null 2>&1 || { [ ! -x /usr/sbin/plymouth-set-default-theme ] && ! command -v plymouth-set-default-theme >/dev/null 2>&1; }; then
    sudo apt-get update
    sudo apt-get install -y dosbox plymouth plymouth-themes
fi
if ! command -v fbset >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y fbset
fi
if getent group input >/dev/null 2>&1; then sudo usermod -aG input "$user"; fi
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
else
    echo "INFO: custom classic SDL is not installed; leaving DOSBox SDL settings unchanged."
fi
sudo "$repo/scripts/configure-legacy-framebuffer.sh"
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
if [ -x /usr/sbin/plymouth-set-default-theme ]; then
    plymouth_theme_command=/usr/sbin/plymouth-set-default-theme
else
    plymouth_theme_command=$(command -v plymouth-set-default-theme)
fi
sudo "$plymouth_theme_command" -R pi-286-games
sudo systemctl daemon-reload
marker='# pi-286-games launcher'
# Remove the previous tty1 login-shell hook. The marker and closing fi belong
# to this installer, so this does not affect unrelated profile settings.
sed -i "/^$marker$/,/^fi$/d" "$home_dir/.profile"
service=/etc/systemd/system/pi-286-games.service
sed -e "s|@USER@|$user|g" -e "s|@HOME@|$home_dir|g" -e "s|@REPO@|$repo|g" "$repo/systemd/pi-286-games.service.in" | sudo tee "$service" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable pi-286-games.service
echo "Installed. Put game data under $home_dir/pi-286-game-files and reboot for the Plymouth-to-launcher handoff."
