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

No game files, streaming listener, or automatic game session are installed
yet. The next change must define the authenticated control/video/audio protocol
and cache manifest/upload flow before any port is opened to the Pi.
