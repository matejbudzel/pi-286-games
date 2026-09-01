# Remote DOS streaming

Pi286 runs DOS games on a dedicated Proxmox LXC and uses lightweight
presenters on the Raspberry Pi and in a browser. The Pi is a remote-only
client; it never launches a local DOSBox session.

## Architecture

```text
Pi native presenter  -- authenticated /v1 API and WebSocket --> LXC DOSBox
Browser              -- same-origin /web/api and WebSocket --> LXC DOSBox
```

The LXC owns the already-extracted private game directories in
`/srv/pi286-games`. Game definitions, DOSBox configurations, mapper files and
dance-pad mappings live in `games/` in the repository. At session start the
presenter supplies a game ID, selected transport, scaling mode and complete
input snapshots; it does not upload, download or interpret game assets.

The server validates that the selected game's `data_dir` and executable are
available. A missing or malformed installation produces a launch error that a
presenter displays to the user. Archive wrapper directories are supported when
they contain exactly one configured executable.

Only one DOSBox session may be active at once. It uses headless Xvfb and sends
320×240 RGB565 video packets plus 22050 Hz mono PCM audio. Video begins with a
keyframe and normally uses changed 16×16 tiles thereafter. `nearest`,
`linear-v`, and `crt-lite` scaling are applied server-side before tile
comparison. Sessions use either HTTP polling or a WebSocket transport; neither
transport silently falls back to the other.

## Server container

The current server is Proxmox LXC `112` (`pi286-dos-stream`). Its source
checkout is `/opt/pi286-stream/repo`, service configuration is
`/etc/pi286-stream.conf`, and per-session state is under `/srv/pi286-stream`.
The `pi286-stream` systemd service reads the bearer token from
`/etc/pi286-stream.token`.

The server's private game data root is configured with `game_data_root` and
defaults to `/srv/pi286-games`. Administrators provision game files there in
their final extracted form; the service never downloads or unpacks them.

`pi286-xvfb-capture` is a small native amd64 capture helper built on the server
host. It is optional: if unavailable or an Xvfb frame is unstable, the backend
uses its safe Python/XWD path instead.

## Presenters and input

The Pi presenter authenticates to the token-protected `/v1` endpoints. It
draws through classic SDL 1.2 fbcon and plays audio locally. Its normal
keyboard keys are forwarded directly, apart from F1 which returns to the
launcher and F8 which toggles the local HUD.

The LXC serves the browser UI itself at its root URL. The browser uses the
unauthenticated, trusted-LAN `/web/api` namespace on the same origin, so it
does not receive the bearer token and needs no devbox relay. It provides the
same keyboard handling and virtual dance pad as the Pi presenter. F1/SELECT
and F8 remain presenter-local; all other input is sent as raw keyboard or
dance-pad button state. The server maps dance-pad buttons using the selected
game's `ddr.conf`.

For every presenter the server supplies the game list and pre-game data,
tailored to keyboard and dance-pad capabilities. This includes Slovak labels
for all nine dance-pad positions. Game-specific actions such as GP's gear
mapping are therefore server-side and identical for web and Pi clients.
Both presenters send normalized `keyboard_held` names and raw
`dance_pad_held` button positions; the server is the only layer that applies
the selected game's `ddr.conf`. DOSBox receives only injected keyboard input,
so game definitions do not use DOSBox `mapperfile` mappings.

## Diagnostics and session history

The Pi HUD is local and is toggled with F8. Dúhová mačka starts with its HUD
enabled. When the presenter leaves a session with F1 or SELECT it records a
summary under `~/.cache/pi286-stream/`; the backend also writes bounded poll
statistics under `/srv/pi286-stream/runtime/` and emits them to its service
log. These diagnostics cover media timing, audio queueing and input request
behaviour.
