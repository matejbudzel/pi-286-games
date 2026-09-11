# pi-286-games

DOS game streaming provider for [`pi-games-launcher`](../pi-games-launcher). This repository owns the remote DOSBox server, stream protocol, native Pi stream presenter, web presenter, DOS game catalogue/configuration, and DOS-specific input behaviour.

It no longer owns the Raspberry Pi appliance launcher, tty/framebuffer lifecycle, launcher menu, generic input discovery, systemd launcher service, or generic legacy framebuffer/audio setup. Those live in the sibling launcher repository.

## Launcher provider CLI

The launcher invokes:

```sh
bin/pi-286-games --config config/provider.conf manifest
bin/pi-286-games --config config/provider.conf run GAME-ID
```

`manifest` is the ad-hoc catalogue request: it contacts the configured remote server and emits manifest schema version 1. `run` creates the remote DOSBox session and starts the provider's presenter. It owns the streamer's F1/SELECT panic convention and game-specific DDR mappings; neither is exposed to the generic launcher.

Copy `config/provider.conf.example` to ignored `config/provider.conf`, configure the remote endpoint/token and presenter path, then add this provider command to `pi-games-launcher/config/launcher.conf`.

## Streaming server and presenter

The server setup and protocol remain documented in [remote DOS streaming](docs/remote-dos-streaming.md). Game assets are private and remain outside Git. The target remains the 286/EGA profile in [target platform notes](docs/target-platform.md).

The generic launcher supplies the classic SDL 1.2 fbcon runtime, `/dev/fb0`,
`SDL_FB_BROKEN_MODES=1`, and the HDMI ALSA default. Build and deploy this
provider's presenter after installing the launcher, as described in [Pi
presenter](docs/pi-presenter.md).
