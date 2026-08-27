# pi-286-games

Minimal Raspberry Pi DOS gaming appliance for a small curated set of games.

The visual and performance target is a late 286/EGA DOS PC. See
[the target-platform notes](docs/target-platform.md).

The repository contains the launcher, host configuration, DOSBox configuration, input mappings, and deployment helpers. Game binaries and assets are intentionally kept outside Git.

## Runtime model

- DietPi or another minimal Linux installation boots directly into the launcher.
- The launcher discovers game definitions from `games/` and sorts them alphabetically by display name.
- A game definition points to game data stored outside this repository.
- Each game can provide its own DOSBox config and mapper file.
- The launcher starts DOSBox, waits for it to exit, and then returns to the menu.
- A host-level panic input can terminate DOSBox independently of the game's mapper.
- If a game cannot be started or DOSBox exits abnormally, the launcher shows a fullscreen Slovak error screen and waits for the normal confirm input before returning to the menu.
- The special `Bye bye!` menu entry exits the launcher by default and can be
  configured to power off the host.

## Repository layout

```text
launcher/              Launcher implementation
config/                Host-specific launcher configuration examples
games/                 Per-game metadata, DOSBox configs and mapper files
systemd/               Boot-time service definition
scripts/               Install and local development helpers
```

## Game data

Game binaries are not stored in this repository. The launcher uses a configurable game-data root, for example:

```text
~/pi-286-game-files/
  dizzy/
  grand-prix/
  prehistorik/
  prince-of-persia/
```

For local UTM development this default home-directory layout works directly.

### Optional first-run asset installation

A game's `game.conf` can set `asset_archive` to either an HTTPS URL or a local
ZIP or RAR path. If its configured `data_dir` is absent, the launcher downloads
or copies that archive and extracts it into the data directory. If the directory
already exists, it is always used as-is: the archive is not fetched, extracted,
or used to validate its contents.

When the launcher needs to install an archive, it first asks for Confirm on a
fullscreen Slovak screen. It then displays transfer and extraction progress,
and waits for Confirm once more before starting the game. Press Esc to cancel
before installation starts.

```ini
asset_archive=https://example.org/my-lawful-game-copy.zip
```

The archive must contain the game's files at its top level. Only configure a
source you are authorised to download and use; game data is still host-local
and must not be committed to this repository.

The launcher treats an existing or newly extracted data directory as ready to
use and does not inspect it for the configured executable before starting
DOSBox. This deliberately avoids overwriting or second-guessing a local copy.

DOSBox output is kept out of the launcher console. The latest DOSBox diagnostic
output is retained at `/tmp/pi-286-games-dosbox.log`, including after a normal
DOSBox exit, because DOS-side startup failures can still result in a zero host
exit status. The generated per-launch DOSBox override is retained alongside it
at `/tmp/pi-286-games-dosbox.conf` for troubleshooting.

ZIP support uses Python's standard library. RAR support requires Debian's
`unrar` package, which is in the `non-free` repository component:

```sh
sudo apt update
sudo apt install unrar
```

If `apt` cannot find the package, enable `non-free` in the Debian/DietPi APT
sources, run `sudo apt update`, and install it again. The launcher shows a
clear error instead of attempting a RAR extraction when `unrar` is absent.

## Input model

The launcher has three logical inputs:

- Up
- Down
- Confirm (`Space` / dance-mat middle)

While DOSBox is running, a separate host-level panic input is monitored. It is configured in `config/host.conf` and is intentionally independent of DOSBox mapper files. A development VM can use `F1`; the Raspberry Pi deployment can use a dedicated dance-mat control.

In the launcher menu, pressing that same configured panic control displays the
first detected Ethernet or Wi-Fi IPv4 address in the bottom-right corner. It
shows `offline` when neither interface has an address, and also appears after a
panic return from DOSBox.

## Game definitions

Each subdirectory in `games/` represents one game and contains metadata plus optional DOSBox-specific files. The launcher does not require the referenced executable to exist while discovering the menu. Missing game data is handled only when the user launches that title.

## DietPi / Debian setup

Run this as the autologin user after cloning the repository:

```sh
./scripts/install-dietpi.sh
```

The default installed `game_data_root` is `~/pi-286-game-files`, which is
writable by the autologin user. If an older `config/host.conf` still points to
`/opt/pi-286-games-data`, either change it to that user-owned path or create
and grant ownership of the `/opt` directory before using archive installation.

The script installs DOSBox when needed, copies the host configuration, grants
only the shutdown command through sudo, and installs a dedicated systemd
service which owns local tty1 after Plymouth exits. This avoids exposing the
DietPi login banner or shell startup text between the boot splash and launcher.
Configure `panic_device` to a readable `/dev/input/event*` device for panic
handling while DOSBox owns the display. The install script adds the user to the
usual `input` group; log out and back in once for that new group membership to
take effect.

The launcher service temporarily conflicts with `getty@tty1.service`. When the
launcher exits through Ctrl-C or the default `Bye bye!`, it starts the existing
tty1 getty again, returning to the usual autologin maintenance shell instead
of launching the application again. Set `shutdown_on_bye_bye=true` in the
appliance configuration to make that menu entry power off the host instead.

By default, selecting `Bye bye!` closes the launcher and returns to the login
shell. Set `shutdown_on_bye_bye=true` in `config/host.conf` on the Raspberry Pi
appliance to make that menu item power off the host instead.

### Boot splash

The installer installs Plymouth and activates the included static, rainbow
pixel/ASCII-art `KOCKOVANÉ HRY` PNG as the boot theme. It also rebuilds the
initramfs, so the image is available early enough to cover the normal boot
messages.

On current DietPi it adds `quiet splash plymouth.ignore-serial-consoles
loglevel=3 vt.global_cursor_default=0` to `extraargs=` in
`/boot/dietpiEnv.txt`. On systems without that file it instead updates the
first available `/boot/firmware/cmdline.txt` or `/boot/cmdline.txt`. Re-running
the installer refreshes the theme safely without duplicating the splash option.

The installer deliberately does not mask `getty@tty1.service`; it temporarily
stops it while the launcher service is active and restores it when the launcher
exits. On an existing installation it removes the obsolete `fbi` splash
service.

### Larger console font

The launcher is a Linux-console TUI, so its text size comes from the system
console font. On the local DietPi console, configure a larger persistent font:

```sh
sudo dpkg-reconfigure console-setup
sudo setupcon
```

Choose UTF-8, the `Lat2` codeset (for Slovak characters), and `TerminusBold`.
`14x28` is a good starting size; use `16x32` for a more prominent appliance
menu if the display resolution leaves enough room. This affects virtual
consoles such as tty1, not SSH terminals.

The included definitions expect `GPEGA.EXE`, `PREHIST.EXE`, and `PRINCE.EXE`.
Change `exe` in the relevant `game.conf` if your lawful copy uses another name.

## Health check

Run the read-only health check on the target to inspect the DOSBox and Plymouth
prerequisites, group membership, framebuffer/DRM permissions, console display
environment, graphics-stack indicators, SDL linkage, and latest launcher log:

```sh
sh scripts/health-check.sh
```

Add `--smoke-dosbox` to run the original immediate-exit test plus short,
SDL-version-appropriate backend probes. It retains baseline output in
`/tmp/pi-286-games-dosbox-smoke.log` and each probe in an adjacent
`pi-286-games-dosbox-smoke-<backend>.log`. This is intended for diagnosing a
blank HDMI display from tty1; it does not install or configure X11, KMS, or any
other backend.

## No-sound launch mode

Run the launcher with `--no-sound` to disable DOSBox's mixer and MIDI output
device and force SDL's dummy audio backend. This is useful for a development VM
without an ALSA sound card:

```sh
python3 launcher/launcher.py --no-sound
```

## Headless x86_64 development viewer

This is development-only and is not needed on the Raspberry Pi. On a Debian or
DietPi x86_64 VM/container, install Xpra from its official repository together
with `xpra-html5`, `xpra-audio-server`, and `xterm`. Copy
`config/host.conf.example` to the ignored `config/host.conf` and set a
user-writable `game_data_root`.

`scripts/run-xpra-dev.sh` starts the launcher in a virtual X display and serves
the Xpra HTML5 client. It forwards DOSBox video, browser keyboard input, and
speaker audio. Set `PI_286_XPRA_BIND` to the host address and start it through
the supplied `systemd/pi-286-games-xpra.service` unit after adjusting its
`User`, `WorkingDirectory`, and bind address. The runner creates a password at
`~/.config/pi-286-games/xpra-password` on first start; keep that file private.
