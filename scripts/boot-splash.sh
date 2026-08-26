#!/bin/sh
# Render a small text splash directly on the appliance console.
set -eu

tty=/dev/tty1
[ -w "$tty" ] || exit 0
columns=$(stty size < "$tty" 2>/dev/null | awk '{print $2}')
columns=${columns:-80}

center() {
    text=$1
    padding=$(( (columns - ${#text}) / 2 ))
    [ "$padding" -gt 0 ] || padding=0
    printf '%*s%s\r\n' "$padding" '' "$text" > "$tty"
}

printf '\033[2J\033[H\033[?25l' > "$tty"
printf '\r\n\r\n\r\n\r\n' > "$tty"
printf '\033[31m' > "$tty"; center '+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+'
printf '\033[33m' > "$tty"; center '|       K O C K O V A N É       |'
printf '\033[32m' > "$tty"; center '|             H R Y             |'
printf '\033[36m' > "$tty"; center '+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+'
printf '\033[35m' > "$tty"; center '        načítavam arkádu...'
printf '\033[0m' > "$tty"
