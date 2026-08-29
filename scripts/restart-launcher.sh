#!/bin/sh
# Hand tty1 back from getty to the launcher after a remote maintenance session.
set -eu

# This script temporarily stops tty1's getty.  Running it from that same
# login kills this shell before the recovery trap can execute, leaving tty1
# without an owner.  Use a maintenance console or SSH for the handoff.
if [ "$(tty 2>/dev/null || true)" = /dev/tty1 ]; then
    echo "pg-restart spustite cez SSH alebo z tty2, nie z tty1." >&2
    exit 1
fi

# The normal launcher stop hook asynchronously starts getty. Mask it before
# stopping the launcher so that queued recovery action cannot race this handoff.
sudo /usr/bin/systemctl mask --runtime --now getty@tty1.service
trap 'sudo /usr/bin/systemctl unmask --runtime getty@tty1.service >/dev/null 2>&1 || true' EXIT HUP INT TERM
if ! sudo /usr/bin/systemctl stop pi-286-games.service; then
    sudo /usr/bin/systemctl unmask --runtime getty@tty1.service
    trap - EXIT HUP INT TERM
    sudo /usr/bin/systemctl start getty@tty1.service
    exit 1
fi
if ! sudo /usr/bin/systemctl start pi-286-games.service; then
    sudo /usr/bin/systemctl unmask --runtime getty@tty1.service
    trap - EXIT HUP INT TERM
    sudo /usr/bin/systemctl start getty@tty1.service
    exit 1
fi
sudo /usr/bin/systemctl unmask --runtime getty@tty1.service
trap - EXIT HUP INT TERM
