# Pi thin-client presenter

The Pi 1 runs the generic text launcher and this provider's native stream
presenter; DOSBox and game execution run only on the remote stream server.
The launcher owns the classic SDL 1.2 fbcon runtime, `/dev/fb0`, and HDMI ALSA
defaults. This provider inherits that appliance setup when the launcher hands
it the console. X11, Wayland, KMS, and FKMS are not supported.

## Cross-build and deployment

Build only on the development machine. Install `gcc-arm-linux-gnueabihf`,
`cmake`, `git`, `make`, `rsync`, `file`, and `binutils` there. The target's
headers and runtime libraries must come from the real Pi rather than a generic
armhf sysroot: this preserves the Pi 1 ARMv6 hard-float ABI.

```sh
../pi-games-launcher/scripts/dev-sdl.sh build
scripts/cross-build-stream-presenter.sh
scripts/deploy-stream-presenter-to-pi.sh
```

The launcher checkout supplies the target sysroot and staged SDL headers. Its
`dev-sdl.sh build` synchronizes them from the real Pi and builds SDL. Set
`PI_GAMES_LAUNCHER_REPO` if that checkout is not beside this repository. No
compiler, CMake, make, or diagnostic program runs on the Pi.

The presenter artifact is ARMv6 hard-float and links the minimal static
libwebsockets build. The launcher deploys SDL under `/opt/sdl12-fbcon`; this
repository deploys only the presenter binary under `/opt/pi286/stream/bin`.
`deploy-stream-presenter-to-pi.sh` also clones or fast-forwards this provider
at `~/pi-286-games`, creates its ignored `config/provider.conf` when absent,
and installs the `pi-286-games` command in `/usr/local/bin`.

## Runtime settings

`config/provider.conf` contains only `remote_dosbox_*` settings for the
authenticated stream backend. The default transport is WebSocket; choose
`poll` only explicitly for diagnosis. The provider creates the remote DOSBox
session, then starts the presenter.
