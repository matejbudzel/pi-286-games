#!/bin/sh
# Select an explicit legacy Pi 1 HDMI/framebuffer profile.  Run on the Pi.
set -eu

usage() {
    echo "Usage: $0 {640x480|854x480|720p} [--reboot]" >&2
    exit 2
}

profile=${1:-}
[ "$#" -ge 1 ] || usage
shift
reboot=0
case ${1:-} in
    '') ;;
    --reboot) reboot=1; shift ;;
    *) usage ;;
esac
[ "$#" -eq 0 ] || usage

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
host_conf=${HOST_CONF:-"$repo/config/host.conf"}
[ -f "$host_conf" ] || { echo "Missing host configuration: $host_conf" >&2; exit 1; }

set_value() {
    key=$1 value=$2
    if grep -q "^[[:space:]]*$key[[:space:]]*=" "$host_conf"; then
        sed -i "s|^[[:space:]]*$key[[:space:]]*=.*|$key=$value|" "$host_conf"
    else
        printf '%s=%s\n' "$key" "$value" >> "$host_conf"
    fi
}
remove_value() { sed -i "/^[[:space:]]*$1[[:space:]]*=/d" "$host_conf"; }

case $profile in
    640x480)
        set_value framebuffer_hdmi_group 2
        set_value framebuffer_hdmi_mode 4
        set_value framebuffer_width 640
        set_value framebuffer_height 480
        set_value framebuffer_depth 16
        set_value dosbox_sdl_fb_pillarbox 0
        remove_value framebuffer_hdmi_cvt
        ;;
    854x480)
        set_value framebuffer_hdmi_group 2
        set_value framebuffer_hdmi_mode 87
        set_value framebuffer_hdmi_cvt '854 480 60 3 0 0 0'
        set_value framebuffer_width 854
        set_value framebuffer_height 480
        set_value framebuffer_depth 16
        set_value dosbox_sdl_fb_pillarbox 1
        ;;
    720p)
        set_value framebuffer_hdmi_group 1
        set_value framebuffer_hdmi_mode 4
        set_value framebuffer_width 1280
        set_value framebuffer_height 720
        set_value framebuffer_depth 16
        set_value dosbox_sdl_fb_pillarbox 1
        remove_value framebuffer_hdmi_cvt
        ;;
    *) usage ;;
esac

# Canvas colour is solely a visual-test diagnostic.  Never leave it enabled
# for a normal DOSBox launch after changing display profiles.
remove_value dosbox_sdl_fb_canvas_color
if [ "${PI286_NO_SUDO:-0}" = 1 ]; then
    HOST_CONF="$host_conf" "$repo/scripts/configure-legacy-framebuffer.sh"
else
    sudo -n HOST_CONF="$host_conf" "$repo/scripts/configure-legacy-framebuffer.sh"
fi
echo "Selected $profile. Reboot is required."
if [ "$reboot" -eq 1 ]; then exec sudo -n reboot; fi
