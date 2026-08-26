#!/bin/sh
# Keep the framebuffer splash visible until the launcher takes over tty1.
set -eu

exec /usr/bin/fbi -T 1 -a -noverbose /usr/local/share/pi-286-games/kockovane-hry-splash.png
