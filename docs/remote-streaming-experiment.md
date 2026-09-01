# Remote DOS game streaming experiment

The Raspberry Pi 1 remains responsible for the native text launcher, direct
framebuffer display, local audio playback, game controls, and private game
files. A separate Proxmox LXC may run DOSBox on faster hardware and stream one
active DOS game to the Pi over the local network.

## Why this experiment exists

The ARMv6 DOSBox-X experiment was retired. Its ARM dynamic recompiler built
and started, but Grand Prix was subjectively slower than the stock Debian
DOSBox build, required substantially more resident memory, and did not behave
reliably with the appliance's classic SDL 1.2 fbcon path. Maintaining a
cross-compiled alternative DOSBox is therefore not a productive route for
this appliance. Stock `/usr/bin/dosbox` remains the local fallback.

## Intended design

```text
Pi launcher -> key press/release packets -> dedicated DOSBox LXC
Pi framebuffer <- indexed dirty tiles    <- dedicated DOSBox LXC
Pi ALSA        <- mono PCM packets       <- dedicated DOSBox LXC
```

The first implementation should be deliberately narrow:

- one game session at a time;
- 320x200 indexed video, palette updates, and changed 16x16 tiles only;
- local Pi scaling through the existing SDL 1.2 fbcon path;
- 22050 Hz mono PCM for PC Speaker audio, initially uncompressed;
- immediate key press/release packets plus an all-keys-released heartbeat;
- no desktop stack, browser, or general-purpose remote desktop client on the
  Pi.

The Pi is the authoritative game-data source. Before launching a session it
will send a manifest and upload only files absent from, or different in, the
LXC's private cache. The LXC may retain that cache between sessions to avoid
re-uploading unchanged assets, but it must not be provisioned with game files
or treated as their owner.

The LXC may use a convenient server-side display backend during the prototype;
that backend must not become a requirement on the Pi.

## First proof of concept

Before integrating the launcher or audio, prove these facts with Grand Prix:

1. The LXC starts and stops a headless DOSBox session on request.
2. The Pi receives and displays video with acceptable control latency.
3. Pi key events reliably reach the game, including key release.
4. The session failure path returns the Pi to its normal launcher screen.

Only after that should mono audio, launcher selection, authentication, and
network-loss handling be added.

## Prepared server container

The initial prototype container is Proxmox LXC `112` (`pi286-dos-stream`). It
is an unprivileged Debian 13 amd64 guest with 2 vCPU, 1 GiB RAM, 512 MiB swap,
an 8 GiB `local-lvm` disk, DHCP on `vmbr0`, and `onboot=0`. At provisioning it
received only `dosbox` (Debian 0.74-3), `xvfb`, `openssh-server`, and Python 3.
The non-login `pi286stream` account owns `/srv/pi286-stream/{sessions,runtime}`.

`/etc/pi286-stream.conf` is created from the example only on first install.
Later backend deployments preserve its local choices, including
`audio_capture=loopback` on hosts configured with `snd-aloop`.

No game files are installed in the container. The backend is implemented in
`streaming/backend/pi286_stream_server.py` and installed with
`scripts/install-stream-backend-lxc.sh`. It listens on TCP 28680 with a
per-container bearer token stored only in `/etc/pi286-stream.token`.

For the hot video conversion path the installer also builds the small native
amd64 helper `pi286-xvfb-capture` from this repository. It is used only by
server containers such as this LXC or the Zotac, never by the ARMv6 Pi. If it
is missing or rejects an unstable Xvfb frame, the backend safely falls back to
its Python/XGetImage path.

The initial HTTP API is deliberately limited:

- `POST /v1/manifest` reports which SHA-256 blobs are absent from the LXC cache;
- `PUT /v1/blobs/<sha256>` verifies and atomically stores an uploaded blob;
- `POST /v1/sessions` materializes a cached game into a new private session and
  launches one headless DOSBox instance under Xvfb;
- `POST /v1/sessions/<id>/frames` saves an Xvfb root-window frame as XWD and
  `GET /v1/sessions/<id>/frames/<frame>.xwd` downloads it;
- `GET /v1/sessions/<id>/video` returns an aspect-correct 320×240 RGB565
  packet, generated from the 320×200 DOS image. The launcher passes its
  `video_scaling` preference with every new session: `nearest` is the safe
  default, `linear-v` interpolates only vertically, and `crt-lite` adds fixed
  scanline darkening to that interpolation. The server applies this before
  tile comparison; all modes are deterministic, so static content stays static
  for delta encoding. It uses a complete keyframe on startup/recovery and
  roughly every two seconds; intervening packets contain only changed 16×16
  tiles. The Pi performs only an exact 2× copy to its 640×480 SDL surface. If
  a packet fails, the client asks for a fresh keyframe rather than applying
  uncertain deltas;
- `GET /v1/sessions/<id>/audio?offset=<bytes>` returns the next bounded
  snapshot as signed 16-bit little-endian, 22050 Hz mono PCM. The caller polls
  using the response's `X-Pi286-Audio-Next-Offset` header. The LXC uses ALSA's
  local `file` PCM plugin backed by a paced FIFO reader, so it has no audio
  hardware dependency and does not let DOSBox run unbounded;
- `POST /v1/sessions/<id>/input` accepts up to 32 normalized key press/release
  events and injects them directly into that session's DOSBox X window.
- `POST /v1/diagnostics/rainbow-cat` starts an asset-free transport diagnostic.
  It keeps a small DOSBox instance for input-path coverage, but its visible
  rainbow reference frame and clean two-tone PCM reference are generated by
  the service. Hold the up/down arrows to move its pink reference block. It is
  intended for checking video/audio/input transport before uploading any
  private game data.
- `GET`/`DELETE /v1/sessions/<id>` inspect or terminate that instance.

New sessions declare either `poll` or `websocket` at creation and record their
selected media transport. The backend also accepts a WebSocket
upgrade from an older client which predates that field. WebSocket carries both media
and complete held-key snapshots on one connection: input is consumed eagerly,
while media generation is capped at 30 Hz. This avoids a second input protocol
and keeps key ordering reliable. A WebSocket session is stopped as soon as its
connection closes. HTTP-poll sessions have an eight-second activity watchdog
(`session_idle_seconds`); a tab/client which disappears without DELETE therefore
cannot leave DOSBox running indefinitely. There is intentionally no automatic
session reconnection: reconnecting starts a fresh game session.

The ARMv6 SDL presenter supports both transports. Set
`remote_dosbox_transport=websocket` in the Pi's host-local configuration to
use its native RFC 6455 client; omit it or set `poll` for the HTTP
fallback. The presenter uses a small statically linked libwebsockets build for
the HTTP upgrade, RFC 6455 framing, masking, and fragmented receives; its
application protocol remains JSON control messages and binary `P2P1` media
frames.

## Pi development overlay

While a remote game is running, `F8` toggles a small local presenter overlay.
It is never forwarded to DOSBox. The three lines show respectively video
frames per second, end-to-end/latest server capture time and failures; local
audio queue depth, underruns and failures; and input HTTP round-trip time,
input failures and received payload throughput. These figures are development
diagnostics rather than an input-to-game-response measurement.
For **Dúhová mačka** the HUD is enabled by default and starts with `TEST: A/V`, so
the menu label can remain short while the screen itself explains the purpose.

When the presenter returns through `F1` or the dance-pad SELECT button, it
writes the complete current-run summary to
`~/.cache/pi286-stream/last-session-stats.txt` and appends one compact row to
`~/.cache/pi286-stream/session-history.tsv`. The summary preserves the HUD
measurements after the framebuffer has returned to the launcher, including
request timing ranges, audio queue/underruns, input RTT, failures, and bytes.
It also separates completed polls from locally cancelled and server-stale
polls, so intentional supersession is not reported as a media failure. The
backend persists a bounded per-session request trace in
`/srv/pi286-stream/runtime/<session>-poll-stats.json` and emits the same
summary to its service log; it includes request arrival gaps and response,
video, and audio assembly timings.

The physical keyboard otherwise passes its normal letters, digits,
punctuation, navigation keys, function keys, and numeric keypad directly to
the remote game. `F1` remains the appliance panic/return control. The dance
pad is deliberately separate: its per-game button bindings stay in `ddr.conf`.

The experimental v2 poll transport combines the current video packet, PCM
chunk, last applied video/audio acknowledgements, and a complete held-key
snapshot in one request/reply. While waiting, the Pi checks input every few
milliseconds. A new held-key revision closes the older request and immediately
starts a replacement poll; the server discards a superseded reply. This keeps
the protocol recoverable without a permanent custom socket yet.

`scripts/smoke-stream-backend.py` exercises cache-miss/**failed start**/upload/
successful start/PCM transport capture/two-frame capture/stop using a
generated, disposable DOS COM program. Run it inside the LXC after
installation. The generated direct-PC-Speaker tone is currently silent in the
Debian DOSBox mixer, so PC Speaker content must be validated with a real game
before treating audio emulation as proven. The smoke program uses DOS BIOS
keyboard reads and verifies that an injected `UP` press changes its captured framebuffer. Pi joystick/button
handling will stay client-side and emit these normalized game keys. That separation is intentional: the
cache and process lifecycle can be verified without exposing game assets in the
repository or prematurely choosing a video/audio protocol.
