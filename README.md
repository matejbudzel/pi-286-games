# pi-286-games

Minimal Raspberry Pi 1 DOS gaming thin client. The Pi runs a text launcher,
SDL fbcon presenter, HDMI audio and input handling. The stream server owns
DOSBox and runs DOS game sessions. Native applications run locally on the Pi.

## Runtime flow

1. The launcher asks the server for its supported game list and pre-game data,
   then merges it alphabetically with host-local application entries.
2. Selecting a game asks the server to validate its already-provisioned private
   game directory and start a DOSBox session.
3. The native presenter shows the video/audio stream and forwards keyboard and
   dance-pad input using WebSocket by default (or explicit HTTP polling).

There is no local DOSBox fallback and no native compilation on the Pi.

Game assets remain outside Git in the server's `game_data_root`. Per-game
metadata contains the display name, server data directory, executable and DDR
map. The remote backend applies
the shared 286/EGA DOSBox profile documented in [target-platform notes](docs/target-platform.md).

## Pi setup

Deploy cross-built SDL and presenter artifacts first, then run as the DietPi
autologin user:

```sh
./scripts/install-dietpi.sh
```

The installer configures framebuffer, HDMI PCM audio, launcher service and
input permissions. It installs no DOSBox and builds nothing. Copy
`config/host.conf.example` to ignored `config/host.conf`, then set
`remote_dosbox_url` and `remote_dosbox_token_file`.

For DOS games, the launcher uses F1 or dance-pad SELECT as its return control. Each game's
`ddr.conf` contains its pad-to-stream-key bindings and Slovak labels; SELECT
(button 9) is never sent to DOSBox.

## Local Pi applications

Create one key/value `.conf` file per application in `config/local-apps/`
(ignored by Git). For example:

```sh
mkdir -p config/local-apps
cp config/local-app.conf.example config/local-apps/pi-dance.conf
```

Adjust the paths for the Pi installation:

```ini
name=Pi Dance
command=./.venv/bin/pi-dance
working_dir=~/work/own/pi-dance
```

`name` and `command` are required. `working_dir` defaults to the launcher's
home directory; relative working directories resolve beside the entry file.
Commands use shell-style argument quoting, but run directly without a shell:
no pipes, redirects, variable expansion or background operators. `~` expands
in arguments and paths. Use a wrapper script for more involved startup.
The app inherits the console and environment, without the DOS presenter's SDL
settings. Configure pi-dance's own `pi-dance.ini` with `backend = fbdev` and
`framebuffer = /dev/fb0` in its `[display]` section, and install its dependencies
and private songs separately.

Local apps start directly from the menu and own keyboard and pad input,
including SELECT. Their normal termination flow returns to the menu; launch
commands must remain running until the app ends and must not daemonize. F1 is a
keyboard-only emergency return for a hung local app, monitored independently
via `/dev/input/event*` (the launcher user needs the `input` group configured
by the installer). It never consumes SELECT or other pad input. The launcher
stops the app's process group on F1, escalates to SIGKILL after a two-second
grace period, and restores the console. An error exit shows a Slovak error
message. Ctrl-C is the only normal launcher-to-shell escape; systemd restarts
the launcher after an unexpected failure.

The catalog loads at launcher startup. Restart `pg-start` after changing
entries or to reload a previously unavailable server catalog. Local entries
remain usable when the server is unavailable. `local_apps_dir` in `host.conf`
can select another directory, relative to that host file or absolute.
These entries are never sent to the server or shown in the web version.

## Disconnect recovery on the Pi

The launcher and DOS presenter rediscover input devices every two seconds.
Removing the pad or keyboard does not end or pause a game. The presenter clears
held buttons/keys when their device disappears, so a missing release does not
leave movement stuck. Reconnecting restores input; joystick initialization
packets do not activate START or SELECT. The console keyboard remains usable
after USB reconnection, and the local-app F1 monitor reopens keyboard devices.
A keyboard need not be connected when starting a local app.

During remote DOS games and the remote diagnostic, the launcher checks legacy
HDMI status with `tvservice -s` in a background worker. A confirmed disconnect
stops the presenter, restores console keyboard/text mode, and deletes the remote
DOSBox session. It returns to the menu without waiting for an error acknowledgement;
reconnecting HDMI shows the console again. Each new session starts with a fresh
monitor. Missing tools, probe errors and unknown statuses do not end a session.
Audio status is independent of HDMI detection.

Forced HDMI hotplug can hide cable removal or TV standby from `tvservice`.
For TVs supporting HDMI-CEC, install `cec-utils` and set `display_cec=1` in
`config/host.conf`. This queries `pow 0` without sending power or source-selection
commands; explicit standby also ends a remote session. Checks run roughly every
two seconds, with a three-second timeout per command, so detection is not instant.
The TV's reported status must be verified on the actual appliance.

Monitoring ownership follows the application: the launcher's HDMI worker exists
only while its remote presenter runs, and is joined before returning to the menu.
It never queries CEC, changes display mode, or kills a local app because HDMI or
an input device disappeared while that app is running. `pi-dance` keeps its own
pause/reconnect policy and `[display] cec` setting. F1 remains the
keyboard-only emergency return control; SELECT belongs to the local app.

After deploying the updated launcher **and rebuilding/deploying the presenter**,
check on the Pi: unplug/replug each controller while holding a movement key or
panel, reconnect with START/SELECT held, disconnect HDMI during a DOS game, and
repeat while running pi-dance. Verify that DOS returns to the menu on detected
HDMI loss, pi-dance retains its own recovery, and F1 works after keyboard
reconnection. Presenter input events are logged in
`/tmp/pi286-stream-presenter.log`.

## Build and deploy

Use the real Pi as the source of ARMv6 headers and runtime libraries, then
cross-build on the development machine. Full instructions are in
[Pi thin-client presenter](docs/pi-presenter.md).

```sh
scripts/sync-pi-sysroot.sh
scripts/cross-build-sdl12-fbcon.sh
scripts/cross-build-stream-presenter.sh
scripts/deploy-sdl12-to-pi.sh
scripts/deploy-stream-presenter-to-pi.sh
```

## Web runtime

The LXC stream server serves its trusted-LAN browser presenter directly on its
configured port. Open its root URL (for example `http://192.168.100.194:28680`)
to use the same direct session and transport protocol as the Pi client. The
browser never receives the bearer token or accesses private game data.
