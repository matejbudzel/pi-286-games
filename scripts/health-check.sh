#!/bin/sh
# Report appliance prerequisites and display diagnostics without changing host configuration.
set -u

smoke=false
if [ "${1:-}" = "--smoke-dosbox" ]; then smoke=true; fi
if [ "$#" -gt 0 ] && [ "${1:-}" != "--smoke-dosbox" ]; then
    echo "Usage: sh scripts/health-check.sh [--smoke-dosbox]" >&2
    exit 2
fi

# Test hooks; on an appliance these resolve to the real host and /tmp.
root=${HEALTH_CHECK_ROOT:-}
runtime_dir=${HEALTH_CHECK_RUNTIME_DIR:-/tmp}
host_path() { printf '%s%s\n' "$root" "$1"; }

failed=0
dosbox_path=
sdl_generation=unknown
fb_usable=false
drm_usable=false
dummy_ok=unknown
direct_probe_ok=false
pass() { printf 'OK   %s\n' "$1"; }
warn() { printf 'WARN %s\n' "$1"; }
info() { printf 'INFO %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1"; failed=1; }
yesno() { if [ "$1" = true ]; then printf yes; else printf no; fi; }

group_exists() {
    if command -v getent >/dev/null 2>&1; then getent group "$1" >/dev/null 2>&1
    else grep -q "^$1:" "$(host_path /etc/group)" 2>/dev/null; fi
}
in_group() { id -nG 2>/dev/null | tr ' ' '\n' | grep -qx "$1"; }
device_access() {
    device=$1; readable=false; writable=false
    [ -r "$device" ] && readable=true; [ -w "$device" ] && writable=true
    printf 'readable=%s writable=%s' "$(yesno "$readable")" "$(yesno "$writable")"
}

if command -v dosbox >/dev/null 2>&1; then
    dosbox_path=$(command -v dosbox)
    pass "dosbox: $(dosbox -version 2>&1 | head -n 1)"
else fail "dosbox is not installed"; fi
if command -v plymouth >/dev/null 2>&1; then pass "plymouth is installed"; else fail "plymouth is not installed"; fi

info "display environment: tty=$(tty 2>/dev/null || printf unavailable)"
if [ -n "${DISPLAY:-}" ]; then pass "DISPLAY is set to $DISPLAY"; else info "DISPLAY is not set (normal on a direct Linux console)"; fi
if [ -n "${WAYLAND_DISPLAY:-}" ]; then info "WAYLAND_DISPLAY is set to $WAYLAND_DISPLAY"; else info "WAYLAND_DISPLAY is not set"; fi
for variable in SDL_VIDEODRIVER SDL_VIDEO_DRIVER SDL_FBDEV SDL_RENDER_DRIVER SDL_RENDER_VSYNC SDL_VIDEO_FULLSCREEN_DISPLAY; do
    eval "value=\${$variable:-}"
    [ -n "$value" ] && info "$variable is set to $value"
done

fb0=$(host_path /dev/fb0)
if [ -c "$fb0" ]; then
    if [ -r "$fb0" ] && [ -w "$fb0" ]; then pass "framebuffer $fb0 is available ($(device_access "$fb0"))"; fb_usable=true
    else fail "framebuffer $fb0 exists but is not accessible by the current user ($(device_access "$fb0"))"; fi
    if command -v fbset >/dev/null 2>&1; then
        info "framebuffer metadata from fbset -i:"
        fbset -fb "$fb0" -i 2>&1 || warn "fbset could not query $fb0"
    else info "fbset is not installed; framebuffer metadata was not queried"; fi
else fail "$fb0 is unavailable"; fi

drm_found=false
for device in "$(host_path /dev/dri)"/card* "$(host_path /dev/dri)"/renderD*; do
    [ -e "$device" ] || continue
    drm_found=true
    if [ -r "$device" ] && [ -w "$device" ]; then
        pass "DRM device $device is accessible ($(device_access "$device"))"; drm_usable=true
    else warn "DRM device $device is present but not fully accessible ($(device_access "$device")); $(ls -l "$device" 2>/dev/null)"; fi
done
[ "$drm_found" = false ] && info "no /dev/dri/card* or /dev/dri/renderD* devices (acceptable with legacy framebuffer graphics)"

for group in video render; do
    if group_exists "$group"; then
        if in_group "$group"; then pass "current user belongs to $group group"
        elif [ "$group" = video ]; then fail "current user is not in video group"
        else warn "current user is not in render group"; fi
    else info "$group group does not exist"; fi
done
if in_group input; then pass "current user belongs to input group"; else fail "current user is not in input group"; fi

info "graphics stack indicators:"
if command -v lsmod >/dev/null 2>&1 && lsmod | awk 'NR > 1 { print $1 }' | grep -qx vc4; then pass "vc4 kernel module is loaded (VC4 DRM/KMS graphics is likely active)"
else info "vc4 kernel module is not listed (legacy framebuffer graphics may be active)"; fi
boot_overlay_found=false
for config in /boot/config.txt /boot/firmware/config.txt /boot/dietpiEnv.txt; do
    config_path=$(host_path "$config")
    if [ -r "$config_path" ]; then
        overlays=$(grep -E '^[[:space:]]*(dtoverlay[[:space:]]*=[[:space:]]*)?vc4-(f)?kms-v3d' "$config_path" 2>/dev/null || true)
        if [ -n "$overlays" ]; then pass "$config contains VC4 KMS/FKMS setting: $overlays"; boot_overlay_found=true
        else info "$config is readable; no vc4-kms-v3d or vc4-fkms-v3d setting found"; fi
    else info "$config is not readable or does not exist"; fi
done
[ "$drm_usable" = false ] && [ "$boot_overlay_found" = true ] && warn "VC4 KMS/FKMS is configured but no DRM device is accessible"

if [ -n "$dosbox_path" ]; then
    if command -v ldd >/dev/null 2>&1; then
        ldd_output=$(ldd "$dosbox_path" 2>&1 || true)
        case $ldd_output in *libSDL-1.2*|*libSDL\.so.1.2*) sdl_generation=1.2 ;; *libSDL2*|*libSDL2-2.0*) sdl_generation=2 ;; esac
        if [ "$sdl_generation" = 1.2 ]; then pass "DOSBox appears linked against SDL 1.2 (from ldd)"
        elif [ "$sdl_generation" = 2 ]; then pass "DOSBox appears linked against SDL2 (from ldd)"
        else warn "could not identify SDL 1.2 or SDL2 in DOSBox ldd output"; fi
        info "DOSBox display-related ldd entries:"
        printf '%s\n' "$ldd_output" | grep -Ei 'sdl|x11|wayland|drm|gbm|egl|gles|bcm_host' || info "no SDL/X11/DRM-related libraries shown by ldd"
    else warn "ldd is unavailable; cannot identify DOSBox SDL generation"; fi
fi

theme_dir=$(host_path /usr/share/plymouth/themes/pi-286-games)
if [ -r "$theme_dir/kockovane-hry-splash.png" ] && [ -r "$theme_dir/pi-286-games.plymouth" ] && [ -r "$theme_dir/pi-286-games.script" ]; then pass "Plymouth splash theme files are readable"
else fail "Plymouth splash theme files are missing"; fi
if command -v plymouth-set-default-theme >/dev/null 2>&1 && [ "$(plymouth-set-default-theme 2>/dev/null)" = pi-286-games ]; then pass "pi-286-games is the active Plymouth theme"
else fail "pi-286-games is not the active Plymouth theme"; fi

latest_log=$runtime_dir/pi-286-games-dosbox.log
if [ -f "$latest_log" ]; then
    pass "latest DOSBox log: $latest_log"
    if grep -Eqi 'error|failed|cannot|invalid|not initialized' "$latest_log"; then fail "latest DOSBox log contains an error-like message"; tail -n 12 "$latest_log"; fi
else info "no launcher DOSBox log exists yet"; fi

run_probe() {
    driver=$1; probe_log=$2
    info "probing SDL $driver video backend (8 second timeout; output: $probe_log)"
    if env SDL_VIDEODRIVER="$driver" SDL_VIDEO_DRIVER="$driver" timeout -k 2s 8s "$dosbox_path" -c exit >"$probe_log" 2>&1; then
        pass "SDL $driver backend probe completed"
        if [ "$driver" = dummy ]; then dummy_ok=true; else direct_probe_ok=true; fi
    else
        warn "SDL $driver backend probe failed or timed out; unsupported backends are expected on some systems"
        tail -n 16 "$probe_log" 2>/dev/null || true; [ "$driver" = dummy ] && dummy_ok=false
    fi
}

if [ "$smoke" = true ]; then
    smoke_log=$runtime_dir/pi-286-games-dosbox-smoke.log
    rm -f "$smoke_log"
    if [ -z "$dosbox_path" ]; then fail "DOSBox smoke test cannot run because dosbox is not installed"
    elif ! command -v timeout >/dev/null 2>&1; then fail "DOSBox smoke test cannot run because timeout is not installed"
    else
        info "starting baseline DOSBox smoke test with current SDL environment; display may briefly take over the active tty"
        if timeout -k 2s 10s "$dosbox_path" -c exit >"$smoke_log" 2>&1; then pass "DOSBox baseline smoke test completed"
        else fail "DOSBox baseline smoke test failed or timed out; see $smoke_log"; tail -n 16 "$smoke_log" 2>/dev/null || true; fi
        case $sdl_generation in
            1.2) run_probe dummy "$runtime_dir/pi-286-games-dosbox-smoke-dummy.log"; run_probe fbcon "$runtime_dir/pi-286-games-dosbox-smoke-fbcon.log"; run_probe x11 "$runtime_dir/pi-286-games-dosbox-smoke-x11.log" ;;
            2) run_probe dummy "$runtime_dir/pi-286-games-dosbox-smoke-dummy.log"; run_probe kmsdrm "$runtime_dir/pi-286-games-dosbox-smoke-kmsdrm.log"; run_probe x11 "$runtime_dir/pi-286-games-dosbox-smoke-x11.log" ;;
            *) warn "SDL generation is unknown; only probing the portable dummy control backend"; run_probe dummy "$runtime_dir/pi-286-games-dosbox-smoke-dummy.log" ;;
        esac
    fi
fi

info "diagnosis summary:"
if [ "$sdl_generation" = 1.2 ] && [ -z "${DISPLAY:-}" ] && [ "$fb_usable" = true ]; then info "DOSBox appears to use SDL 1.2 with no X display and an accessible framebuffer; fbcon is the likely direct-console backend to test/use."
elif [ "$sdl_generation" = 2 ] && [ "$drm_usable" = true ]; then info "DOSBox appears to use SDL2 and an accessible DRM device is available; kmsdrm is the likely direct-console backend."
elif [ "$sdl_generation" != unknown ] && [ -z "${DISPLAY:-}" ] && [ "$fb_usable" = false ] && [ "$drm_usable" = false ]; then warn "No usable direct-console video backend was detected. DOSBox may be trying X11 without an X server."; fi
if [ "$smoke" = true ] && [ "$dummy_ok" = true ] && [ "$direct_probe_ok" = false ]; then warn "DOSBox started with the dummy backend but no tested real display backend completed; CPU usage is probably not the primary issue."; fi

exit "$failed"
