# Pi thin-client presenter

The Pi 1 is a thin client. It runs the text launcher and the native SDL 1.2
fbcon presenter; DOSBox and game execution run only on the remote stream
server. The display path is classic SDL 1.2 fbcon through `/dev/fb0` and the
legacy BCM2708 framebuffer. X11, Wayland, KMS, and FKMS are not supported.

## Cross-build and deployment

Build only on the development machine. Install `gcc-arm-linux-gnueabihf`,
`cmake`, `git`, `make`, `rsync`, `file`, and `binutils` there. The target's
headers and runtime libraries must come from the real Pi rather than a generic
armhf sysroot: this preserves the Pi 1 ARMv6 hard-float ABI.

```sh
scripts/sync-pi-sysroot.sh
scripts/cross-build-sdl12-fbcon.sh
scripts/cross-build-stream-presenter.sh
scripts/deploy-sdl12-to-pi.sh
scripts/deploy-stream-presenter-to-pi.sh
```

`sync-pi-sysroot.sh` copies the target loader, libraries, C/kernel headers and
ALSA headers into ignored `.cache/pi286-sysroot`. If ALSA headers are absent on
the target, install `libasound2-dev` on the Pi once, then run the sync again.
No compiler, CMake, make, or diagnostic program runs on the Pi.

The presenter artifact is ARMv6 hard-float and links the minimal static
libwebsockets build. SDL is deployed under `/opt/sdl12-fbcon`; the presenter
binary is deployed under `/opt/pi286/stream/bin`.

## Runtime settings

`config/host.conf` uses `presenter_sdl_*` settings for fbcon and
`remote_dosbox_*` settings for the authenticated stream backend. The default
transport is WebSocket; choose `poll` only explicitly for diagnosis. The
launcher uploads/checks local game assets, creates the remote DOSBox session,
then starts the presenter.
