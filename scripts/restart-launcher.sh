#!/bin/sh
# Hand tty1 back from getty to the launcher after a remote maintenance session.
set -eu

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
