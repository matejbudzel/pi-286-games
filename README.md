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
including SELECT. F1 is the fixed panic control, monitored independently via
`/dev/input/event*` (the launcher user needs the `input` group configured by the
installer). The monitor does not grab devices; apps must leave evdev accessible
and reserve F1 for return. The launcher stops the app's process group on panic,
escalates to SIGKILL after a two-second grace period, and restores the console.
Normal exit returns to the menu; an error exit shows a Slovak error message.
Launch commands must remain running until the app ends and must not daemonize.

The catalog loads at launcher startup. Restart `pg-start` after changing
entries or to reload a previously unavailable server catalog. Local entries
remain usable when the server is unavailable. `local_apps_dir` in `host.conf`
can select another directory, relative to that host file or absolute.
These entries are never sent to the server or shown in the web version.

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
