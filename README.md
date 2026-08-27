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
scripts/               Installation, diagnostics, and appliance helpers
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

While DOSBox is running, a separate host-level panic input is monitored. It is configured in `config/host.conf` and is intentionally independent of DOSBox mapper files. Configure it for the appliance's dedicated dance-mat control.

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
service which owns local tty1 after DietPi boots. Normal DietPi boot messages
remain visible; this is intentionally a text-only appliance.
Configure `panic_device` to a readable `/dev/input/event*` device for panic
handling while DOSBox owns the display. The install script adds the user to the
usual `input` group; log out and back in once for that new group membership to
take effect.

On the ARMv6 256 MB Pi target, the installer builds pinned classic SDL 1.2.16
under `/opt/sdl12-fbcon` and configures DOSBox alone to use its fbcon backend.
It also manages the real 640×480 HDMI/framebuffer boot mode; reboot after
installation. This avoids Debian's SDL 1.2 compatibility layer and does not
install X11 or enable KMS/FKMS. The corresponding `dosbox_*` settings in
`config/host.conf` are fixed for this appliance. See
[the legacy framebuffer display guide](docs/legacy-fbcon-display.md).

The launcher service temporarily conflicts with `getty@tty1.service`. When the
launcher exits through Ctrl-C or the default `Bye bye!`, it starts the existing
tty1 getty again, returning to the usual autologin maintenance shell instead
of launching the application again. Set `shutdown_on_bye_bye=true` in the
appliance configuration to make that menu entry power off the host instead.

By default, selecting `Bye bye!` closes the launcher and returns to the login
shell. Set `shutdown_on_bye_bye=true` in `config/host.conf` on the Raspberry Pi
appliance to make that menu item power off the host instead.

### Direct console boot

Plymouth is deliberately not used. It starts too late on this Pi 1 and adds a
graphical element to an otherwise text-only appliance. The installer removes
the project Plymouth theme, disables related units, purges Plymouth when
installed, and removes the project-added quiet/splash kernel arguments. DietPi
boot text remains visible until the launcher takes ownership of tty1.

The launcher service deliberately does not mask `getty@tty1.service`; it
temporarily stops it while active and restores it when the launcher exits.

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

The included definitions expect `GPEGA.EXE`, `PREHISTO.COM`, and `PRINCE.EXE`.
Change `exe` in the relevant `game.conf` if your lawful copy uses another name.

## Health check

Run the read-only health check on the target to inspect DOSBox, framebuffer/DRM
permissions, console display environment, SDL linkage, boot configuration, and
latest launcher log:

```sh
sh scripts/health-check.sh
```

Add `--smoke-dosbox` for a short custom-classic-SDL fbcon DOSBox test. It uses
the same custom SDL and framebuffer environment as the appliance and retains
its output in `/tmp/pi-286-games-dosbox-smoke.log`; it may briefly take over
tty1. For an SDL-only rendering check, run
`sh scripts/run-sdl-fbcon-self-test.sh`. Neither command installs X11 nor
configures KMS/FKMS.

## No-sound launch mode

Run the launcher with `--no-sound` to disable DOSBox's mixer and MIDI output
device and force SDL's dummy audio backend while the appliance has no usable
ALSA default card:

```sh
python3 launcher/launcher.py --no-sound
```
