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
if command -v fbi >/dev/null 2>&1; then pass "fbi is installed"; else fail "fbi is not installed"; fi
if [ -c /dev/fb0 ]; then pass "framebuffer: $(ls -l /dev/fb0)"; else fail "/dev/fb0 is unavailable"; fi
if [ -r /usr/local/share/pi-286-games/kockovane-hry-splash.png ]; then pass "installed splash image is readable"; else fail "installed splash image is missing"; fi

if id -nG | tr ' ' '\n' | grep -qx video; then pass "current user belongs to video group"; else fail "current user is not in video group"; fi
if id -nG | tr ' ' '\n' | grep -qx input; then pass "current user belongs to input group"; else fail "current user is not in input group"; fi

if systemctl is-enabled --quiet pi-286-games-splash.service 2>/dev/null; then
    pass "splash service is enabled"
else
    fail "splash service is not enabled"
fi
if systemctl is-active --quiet pi-286-games-splash.service 2>/dev/null; then
    pass "splash service is active"
elif systemctl is-failed --quiet pi-286-games-splash.service 2>/dev/null; then
    fail "splash service failed; inspect: sudo journalctl -u pi-286-games-splash.service -b"
else
    echo "INFO splash service is inactive (normal after the launcher has started)"
fi

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
