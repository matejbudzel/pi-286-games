#!/bin/sh
# Hand tty1 back from getty to the launcher after a remote maintenance session.
set -eu

sudo /usr/bin/systemctl stop pi-286-games.service
# The launcher stop hook deliberately starts getty asynchronously for normal
# console exits. Let that request settle before taking tty1 back for the app.
sleep 1
sudo /usr/bin/systemctl stop getty@tty1.service
sudo /usr/bin/systemctl start pi-286-games.service
