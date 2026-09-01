# pi-286-games

Minimal Raspberry Pi 1 DOS gaming thin client. The Pi runs a text launcher,
SDL fbcon presenter, HDMI audio and input handling. The stream server owns
DOSBox and runs every game session.

## Runtime flow

1. The launcher asks the server for its supported game list and pre-game data.
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

The launcher uses F1 or dance-pad SELECT as its return control. Each game's
`ddr.conf` contains its pad-to-stream-key bindings and Slovak labels; SELECT
(button 9) is never sent to a game.

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
