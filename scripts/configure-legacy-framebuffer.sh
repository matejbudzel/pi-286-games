#!/bin/sh
# Idempotently maintain the legacy HDMI/framebuffer values for the Pi 1 appliance.
set -eu
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
set_value hdmi_force_hotplug 1
set_value hdmi_drive 2
set_value hdmi_blanking 0
set_value disable_overscan 1
set_value hdmi_group 2
set_value hdmi_mode 4
set_value framebuffer_width 640
set_value framebuffer_height 480
set_value framebuffer_depth 16
set_audio() {
    if grep -Eq '^[[:space:]]*dtparam[[:space:]]*=[[:space:]]*audio=' "$boot_config"; then
        sed -i 's|^[[:space:]]*dtparam[[:space:]]*=[[:space:]]*audio=.*|dtparam=audio=on|' "$boot_config"
    else
        printf 'dtparam=audio=on\n' >> "$boot_config"
    fi
}
set_audio
echo "Configured legacy 640x480 HDMI/framebuffer settings in $boot_config. Reboot is required."
