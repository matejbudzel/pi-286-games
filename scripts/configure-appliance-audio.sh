#!/bin/sh
# Persist the verified Raspberry Pi HDMI ALSA path without relying on card order.
set -eu
root=${PI286_AUDIO_ROOT:-}
path() { printf '%s%s\n' "$root" "$1"; }
cards=$(path /proc/asound/cards)
card_id=$(sed -n 's/^[[:space:]]*[0-9][0-9]*[[:space:]]*\[\([^]]*\)\].*bcm2835 HDMI.*/\1/p' "$cards" 2>/dev/null | head -n 1 | tr -d '[:space:]')
case $card_id in ''|*[!A-Za-z0-9_]*) card_id=HDMI ;; esac
mkdir -p "$(path /etc/modules-load.d)"
printf 'snd_bcm2835\n' > "$(path /etc/modules-load.d/pi-286-games-audio.conf)"
printf '%s\n' \
    '# pi-286-games: verified BCM2835 HDMI audio output.' \
    'pcm.!default {' \
    '    type plug' \
    '    slave.pcm {' \
    '        type hw' \
    "        card \"$card_id\"" \
    '        device 0' \
    '    }' \
    '}' \
    'ctl.!default {' \
    '    type hw' \
    "    card \"$card_id\"" \
    '}' > "$(path /etc/asound.conf)"
echo "Configured ALSA default for bcm2835 HDMI card '$card_id'."
