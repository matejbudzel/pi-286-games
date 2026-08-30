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

No game files are installed in the container. The backend is implemented in
`streaming/backend/pi286_stream_server.py` and installed with
`scripts/install-stream-backend-lxc.sh`. It listens on TCP 28680 with a
per-container bearer token stored only in `/etc/pi286-stream.token`.

The initial HTTP API is deliberately limited:

- `POST /v1/manifest` reports which SHA-256 blobs are absent from the LXC cache;
- `PUT /v1/blobs/<sha256>` verifies and atomically stores an uploaded blob;
- `POST /v1/sessions` materializes a cached game into a new private session and
  launches one headless DOSBox instance under Xvfb;
- `POST /v1/sessions/<id>/frames` saves an Xvfb root-window frame as XWD and
  `GET /v1/sessions/<id>/frames/<frame>.xwd` downloads it;
- `GET /v1/sessions/<id>/video` returns an aspect-correct 320×240 RGB565
  packet, generated from the 320×200 DOS image with vertical nearest-neighbour
  expansion. It uses a complete keyframe on startup/recovery and roughly every
  two seconds; intervening packets contain only changed 16×16 tiles. The Pi
  performs only an exact 2× copy to its 640×480 SDL surface. If a packet fails,
  the client asks for a fresh keyframe rather than applying uncertain deltas;
- `GET /v1/sessions/<id>/audio?offset=<bytes>` returns the next bounded
  snapshot as signed 16-bit little-endian, 22050 Hz mono PCM. The caller polls
  using the response's `X-Pi286-Audio-Next-Offset` header. The LXC uses ALSA's
  local `file` PCM plugin backed by a paced FIFO reader, so it has no audio
  hardware dependency and does not let DOSBox run unbounded;
- `POST /v1/sessions/<id>/input` accepts up to 32 normalized key press/release
  events and injects them directly into that session's DOSBox X window.
- `POST /v1/diagnostics/rainbow-cat` starts an asset-free generated DOSBox
  diagnostic. It is intended for checking video/audio/input transport before
  uploading any private game data.
- `GET`/`DELETE /v1/sessions/<id>` inspect or terminate that instance.

## Pi development overlay

While a remote game is running, `F8` toggles a small local presenter overlay.
It is never forwarded to DOSBox. The three lines show respectively video
frames per second, end-to-end/latest server capture time and failures; local
audio queue depth, underruns and failures; and input HTTP round-trip time,
input failures and received payload throughput. These figures are development
diagnostics rather than an input-to-game-response measurement.

The physical keyboard otherwise passes its normal letters, digits,
punctuation, navigation keys, function keys, and numeric keypad directly to
the remote game. `F1` remains the appliance panic/return control. The dance
pad is deliberately separate: its per-game button bindings stay in `ddr.conf`.

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
