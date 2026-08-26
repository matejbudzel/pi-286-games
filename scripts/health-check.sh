#!/bin/sh
# Report appliance prerequisites without changing host configuration.
set -u

smoke=false
if [ "${1:-}" = "--smoke-dosbox" ]; then smoke=true; fi
if [ "$#" -gt 0 ] && [ "${1:-}" != "--smoke-dosbox" ]; then
    echo "Usage: sh scripts/health-check.sh [--smoke-dosbox]" >&2
    exit 2
fi

failed=0
pass() { printf 'OK   %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1"; failed=1; }

if command -v dosbox >/dev/null 2>&1; then pass "dosbox: $(dosbox -version 2>&1 | head -n 1)"; else fail "dosbox is not installed"; fi
if command -v plymouth >/dev/null 2>&1; then pass "plymouth is installed"; else fail "plymouth is not installed"; fi
if [ -c /dev/fb0 ]; then pass "framebuffer: $(ls -l /dev/fb0)"; else fail "/dev/fb0 is unavailable"; fi
theme_dir=/usr/share/plymouth/themes/pi-286-games
if [ -r "$theme_dir/kockovane-hry-splash.png" ] && [ -r "$theme_dir/pi-286-games.plymouth" ] && [ -r "$theme_dir/pi-286-games.script" ]; then
    pass "Plymouth splash theme files are readable"
else
    fail "Plymouth splash theme files are missing"
fi
if command -v plymouth-set-default-theme >/dev/null 2>&1 && [ "$(plymouth-set-default-theme 2>/dev/null)" = pi-286-games ]; then
    pass "pi-286-games is the active Plymouth theme"
else
    fail "pi-286-games is not the active Plymouth theme"
fi

if id -nG | tr ' ' '\n' | grep -qx video; then pass "current user belongs to video group"; else fail "current user is not in video group"; fi
if id -nG | tr ' ' '\n' | grep -qx input; then pass "current user belongs to input group"; else fail "current user is not in input group"; fi

latest_log=/tmp/pi-286-games-dosbox.log
if [ -f "$latest_log" ]; then
    pass "latest DOSBox log: $latest_log"
    if grep -Eqi 'error|failed|cannot|invalid|not initialized' "$latest_log"; then
        fail "latest DOSBox log contains an error-like message"
        tail -n 12 "$latest_log"
    fi
else
    echo "INFO no launcher DOSBox log exists yet"
fi

if [ "$smoke" = true ]; then
    smoke_log=/tmp/pi-286-games-dosbox-smoke.log
    rm -f "$smoke_log"
    echo "INFO starting DOSBox smoke test; its display may briefly take over tty1"
    if timeout 10s dosbox -c exit >"$smoke_log" 2>&1; then
        pass "DOSBox smoke test completed"
    else
        fail "DOSBox smoke test failed; see $smoke_log"
        tail -n 12 "$smoke_log"
    fi
fi

exit "$failed"
