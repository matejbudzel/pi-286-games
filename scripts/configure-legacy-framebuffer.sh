#!/bin/sh
# Idempotently maintain the legacy HDMI/framebuffer values for the Pi 1 appliance.
set -eu
host_conf=${HOST_CONF:-}
host_setting() { if [ -n "$host_conf" ]; then sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$host_conf" 2>/dev/null | tail -n 1; fi; }
setting_or_default() { value=$(host_setting "$1"); [ -n "$value" ] && printf '%s\n' "$value" || printf '%s\n' "$2"; }
hdmi_group=$(setting_or_default framebuffer_hdmi_group 2)
hdmi_mode=$(setting_or_default framebuffer_hdmi_mode 4)
framebuffer_width=$(setting_or_default framebuffer_width 640)
framebuffer_height=$(setting_or_default framebuffer_height 480)
framebuffer_depth=$(setting_or_default framebuffer_depth 16)
hdmi_cvt=$(host_setting framebuffer_hdmi_cvt)
boot_config=${BOOT_CONFIG:-}
if [ -z "$boot_config" ]; then
    for candidate in /boot/firmware/config.txt /boot/config.txt; do
        if [ -f "$candidate" ]; then boot_config=$candidate; break; fi
    done
fi
[ -n "$boot_config" ] && [ -f "$boot_config" ] || { echo "WARNING: no Raspberry Pi config.txt found; legacy framebuffer settings were not changed." >&2; exit 0; }
if grep -Eq '^[[:space:]]*dtoverlay[[:space:]]*=[[:space:]]*vc4-(f)?kms-v3d' "$boot_config"; then
    echo "WARNING: VC4 KMS/FKMS is active in $boot_config. It is not supported by this 256 MB legacy-fbcon appliance; leaving that overlay untouched." >&2
fi
set_value() {
    key=$1 value=$2
    if grep -Eq "^[[:space:]]*$key[[:space:]]*=" "$boot_config"; then
        sed -i "s|^[[:space:]]*$key[[:space:]]*=.*|$key=$value|" "$boot_config"
    else
        grep -Fqx '# pi-286-games legacy framebuffer' "$boot_config" || printf '\n# pi-286-games legacy framebuffer\n' >> "$boot_config"
        printf '%s=%s\n' "$key" "$value" >> "$boot_config"
    fi
}
remove_value() {
    key=$1
    sed -i "/^[[:space:]]*$key[[:space:]]*=/d" "$boot_config"
}
set_value hdmi_force_hotplug 1
set_value hdmi_drive 2
set_value hdmi_blanking 0
set_value disable_overscan 1
set_value hdmi_group "$hdmi_group"
set_value hdmi_mode "$hdmi_mode"
if [ -n "$hdmi_cvt" ]; then set_value hdmi_cvt "$hdmi_cvt"; else remove_value hdmi_cvt; fi
set_value framebuffer_width "$framebuffer_width"
set_value framebuffer_height "$framebuffer_height"
set_value framebuffer_depth "$framebuffer_depth"
set_audio() {
    if grep -Eq '^[[:space:]]*dtparam[[:space:]]*=[[:space:]]*audio=' "$boot_config"; then
        sed -i 's|^[[:space:]]*dtparam[[:space:]]*=[[:space:]]*audio=.*|dtparam=audio=on|' "$boot_config"
    else
        printf 'dtparam=audio=on\n' >> "$boot_config"
    fi
}
set_audio
echo "Configured legacy ${framebuffer_width}x${framebuffer_height} HDMI/framebuffer settings in $boot_config. Reboot is required."
