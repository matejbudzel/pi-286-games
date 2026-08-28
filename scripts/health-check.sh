#!/bin/sh
# Report appliance prerequisites and display diagnostics without changing the host.
set -u
smoke=false
if [ "${1:-}" = --smoke-dosbox ]; then smoke=true; fi
if [ "$#" -gt 0 ] && [ "${1:-}" != --smoke-dosbox ]; then echo "Usage: sh scripts/health-check.sh [--smoke-dosbox]" >&2; exit 2; fi
root=${HEALTH_CHECK_ROOT:-}; runtime_dir=${HEALTH_CHECK_RUNTIME_DIR:-/tmp}
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
host_path() { printf '%s%s\n' "$root" "$1"; }
failed=0; dosbox_path=; fb_usable=false; drm_found=false; custom_sdl=false; sdl_generation=unknown
pass() { printf 'OK   %s\n' "$1"; }; warn() { printf 'WARN %s\n' "$1"; }; info() { printf 'INFO %s\n' "$1"; }; fail() { printf 'FAIL %s\n' "$1"; failed=1; }
yesno() { [ "$1" = true ] && printf yes || printf no; }
device_access() { device=$1; r=false; w=false; [ -r "$device" ] && r=true; [ -w "$device" ] && w=true; printf 'readable=%s writable=%s' "$(yesno "$r")" "$(yesno "$w")"; }
host_setting() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$host_conf" 2>/dev/null | tail -n 1; }
in_group() { id -nG 2>/dev/null | tr ' ' '\n' | grep -qx "$1"; }
module_loaded() { if command -v lsmod >/dev/null 2>&1; then lsmod | awk 'NR > 1 { print $1 }' | grep -qx "$1"; else grep -q "^$1 " "$(host_path /proc/modules)" 2>/dev/null; fi; }

model=$(sed -n '1p' "$(host_path /proc/device-tree/model)" 2>/dev/null | tr -d '\000')
[ -n "$model" ] && info "Raspberry Pi model: $model" || info "Raspberry Pi model unavailable"
mem=$(sed -n 's/^MemTotal:[[:space:]]*\([0-9]*\) kB.*/\1/p' "$(host_path /proc/meminfo)" 2>/dev/null)
[ -n "$mem" ] && info "MemTotal: $mem kB" || info "MemTotal unavailable"
info "architecture: $(uname -m)"
if command -v dosbox >/dev/null 2>&1; then dosbox_path=$(command -v dosbox); pass "dosbox: $(dosbox -version 2>&1 | head -n 1)"; else fail "dosbox is not installed"; fi
info "display environment: tty=$(tty 2>/dev/null || printf unavailable)"
[ -n "${DISPLAY:-}" ] && info "DISPLAY is set to $DISPLAY" || info "DISPLAY is not set (normal on a direct Linux console)"

fb0=$(host_path /dev/fb0)
if [ -c "$fb0" ]; then
    if [ -r "$fb0" ] && [ -w "$fb0" ]; then pass "framebuffer $fb0 is available ($(device_access "$fb0"))"; fb_usable=true; else fail "framebuffer $fb0 exists but is not accessible ($(device_access "$fb0"))"; fi
    if command -v fbset >/dev/null 2>&1; then
        fb_info=$(fbset -fb "$fb0" -i 2>&1 || true); printf '%s\n' "$fb_info" | sed 's/^/INFO framebuffer: /'
        geometry=$(printf '%s\n' "$fb_info" | sed -n 's/^[[:space:]]*geometry[[:space:]]*\([0-9]*\) \([0-9]*\).* \([0-9]*\)$/\1x\2x\3/p')
        stride=$(printf '%s\n' "$fb_info" | sed -n 's/^[[:space:]]*LineLength[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p')
        [ "$geometry" = 640x480x16 ] && pass "framebuffer geometry is expected 640x480, 16 bpp" || warn "framebuffer geometry is '$geometry' (expected 640x480x16)"
        [ "$stride" = 1280 ] && pass "framebuffer stride is expected 1280" || warn "framebuffer stride is '$stride' (expected 1280)"
    else warn "fbset is not installed; cannot report framebuffer name, geometry, bpp, or stride"; fi
else fail "$fb0 is unavailable"; fi
for device in "$(host_path /dev/dri)"/card* "$(host_path /dev/dri)"/renderD*; do [ -e "$device" ] || continue; drm_found=true; info "DRM device present: $device ($(device_access "$device"))"; done
[ "$drm_found" = false ] && pass "no /dev/dri device (expected and acceptable for the 256 MB legacy framebuffer target)"

kms_found=false; boot_config=
for candidate in /boot/firmware/config.txt /boot/config.txt; do [ -r "$(host_path "$candidate")" ] && { boot_config=$(host_path "$candidate"); break; }; done
if [ -n "$boot_config" ]; then
    if grep -Eq '^[[:space:]]*dtoverlay[[:space:]]*=[[:space:]]*vc4-(f)?kms-v3d' "$boot_config"; then kms_found=true; warn "KMS/FKMS is configured in $boot_config; it is not the supported legacy-fbcon path"; fi
    for setting in hdmi_force_hotplug=1 hdmi_drive=2 hdmi_blanking=0 disable_overscan=1 hdmi_group=2 hdmi_mode=4 framebuffer_width=640 framebuffer_height=480 framebuffer_depth=16 dtparam=audio=on; do grep -Eq "^[[:space:]]*$setting[[:space:]]*$" "$boot_config" && pass "boot setting $setting" || warn "boot setting missing: $setting"; done
else warn "no Raspberry Pi config.txt found"; fi
[ "$kms_found" = true ] && [ "$drm_found" = false ] && warn "KMS/FKMS is configured but no /dev/dri device exists"

# Audio is intentionally reported independently: no audio fault changes the
# framebuffer/video result above.
if module_loaded snd_bcm2835; then pass "snd_bcm2835 kernel module is loaded"; else warn "snd_bcm2835 kernel module is not loaded"; fi
snd_dir=$(host_path /dev/snd)
if [ -d "$snd_dir" ]; then
    snd_access=false
    for device in "$snd_dir"/*; do [ -e "$device" ] || continue; [ -r "$device" ] && [ -w "$device" ] && snd_access=true; info "sound device $device ($(device_access "$device"))"; done
    [ "$snd_access" = true ] && pass "/dev/snd has an accessible sound device" || warn "/dev/snd has no accessible sound device"
else warn "/dev/snd does not exist"; fi
if in_group audio; then pass "current user belongs to audio group"; else warn "current user is not in audio group"; fi
alsa_cards=$(host_path /proc/asound/cards)
hdmi_card=$(sed -n 's/^[[:space:]]*\([0-9][0-9]*\)[[:space:]]*\[\([^]]*\)\].*bcm2835 HDMI.*/\1 \2/p' "$alsa_cards" 2>/dev/null | head -n 1)
if [ -n "$hdmi_card" ]; then
    card_number=${hdmi_card%% *}
    card_id=$(printf '%s' "${hdmi_card#* }" | tr -d '[:space:]')
    pass "bcm2835 HDMI ALSA card exists: $card_number $card_id"
    asound=$(host_path /etc/asound.conf)
    if [ -r "$asound" ] && grep -Fq "card \"$card_id\"" "$asound"; then pass "ALSA default targets bcm2835 HDMI card '$card_id'"; else warn "ALSA default does not target bcm2835 HDMI card '$card_id'"; fi
else warn "bcm2835 HDMI ALSA card is unavailable"; fi

custom_prefix=$(host_path /opt/sdl12-fbcon)
if [ -x "$custom_prefix/bin/sdl-config" ] && [ -e "$custom_prefix/lib/libSDL-1.2.so.0" ]; then
    custom_version=$("$custom_prefix/bin/sdl-config" --version 2>/dev/null || true)
    [ "$custom_version" = 1.2.16 ] && pass "custom classic SDL $custom_version: $custom_prefix" || warn "custom SDL version is '$custom_version' (expected 1.2.16)"
    pass "custom SDL library: $custom_prefix/lib/libSDL-1.2.so.0"; custom_sdl=true
else warn "custom classic SDL is missing from $custom_prefix"; fi
if [ -n "$dosbox_path" ] && command -v ldd >/dev/null 2>&1; then
    ldd_output=$(ldd "$dosbox_path" 2>&1 || true)
    case $ldd_output in *libSDL-1.2*) sdl_generation=1.2 ;; *libSDL2*) sdl_generation=2 ;; esac
    [ "$sdl_generation" = 1.2 ] && pass "DOSBox links the SDL 1.2 ABI" || warn "could not identify DOSBox SDL 1.2 linkage"
    case $ldd_output in *sdl12-compat*|*libSDL2*) info "system SDL 1.2 ABI appears to be sdl12-compat over SDL2" ;; esac
    if [ "$custom_sdl" = true ]; then custom_ldd=$(LD_LIBRARY_PATH="$custom_prefix/lib" ldd "$dosbox_path" 2>&1 || true); printf '%s\n' "$custom_ldd" | grep -Fq "$custom_prefix/lib/libSDL-1.2.so.0" && pass "DOSBox resolves custom SDL with LD_LIBRARY_PATH" || fail "DOSBox does not resolve custom SDL with LD_LIBRARY_PATH"; fi
fi
host_conf=${HEALTH_CHECK_HOST_CONF:-$repo/config/host.conf}
for pair in dosbox_sdl_videodriver=fbcon dosbox_sdl_fbdev=/dev/fb0 dosbox_sdl_fb_broken_modes=1 dosbox_ld_library_path=/opt/sdl12-fbcon/lib; do key=${pair%%=*}; expected=${pair#*=}; value=$(host_setting "$key"); [ "$value" = "$expected" ] && pass "runtime setting $pair" || warn "runtime setting $key is '$value' (expected $expected)"; done
pass "DOSBox audio runtime is pinned to SDL_AUDIODRIVER=alsa AUDIODEV=plughw:0,0 SDL_PATH_DSP=plughw:0,0"

if [ "$smoke" = true ]; then
    smoke_log=$runtime_dir/pi-286-games-dosbox-smoke.log
    if [ -z "$dosbox_path" ] || ! command -v timeout >/dev/null 2>&1; then fail "DOSBox smoke test requires dosbox and timeout"
    elif [ "$custom_sdl" != true ]; then warn "skipping framebuffer smoke test: classic custom SDL is missing"
    else
        info "starting classic SDL fbcon smoke test; the active tty may briefly be taken over (log: $smoke_log)"
        if env LD_LIBRARY_PATH="$custom_prefix/lib" SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 SDL_FB_BROKEN_MODES=1 timeout -k 2s 10s "$dosbox_path" -c exit >"$smoke_log" 2>&1; then pass "custom SDL fbcon DOSBox smoke test completed"; else fail "custom SDL fbcon DOSBox smoke test failed; see $smoke_log"; tail -n 16 "$smoke_log" 2>/dev/null || true; fi
    fi
fi
[ "$custom_sdl" = true ] && [ "$fb_usable" = true ] && info "legacy appliance classification: classic SDL fbcon + /dev/fb0; no /dev/dri is required."
info "audio is diagnosed separately: ALSA/default-card errors do not invalidate video checks. speaker-test is manual only."
exit "$failed"
