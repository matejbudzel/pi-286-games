# pi-286-games

Minimal Raspberry Pi DOS gaming appliance for a small curated set of games.

The visual and performance target is a late 286/EGA DOS PC. See
[the target-platform notes](docs/target-platform.md).

The repository contains the launcher, host configuration, DOSBox configuration, input mappings, and deployment helpers. Game binaries and assets are intentionally kept outside Git.

## Runtime model

- DietPi or another minimal Linux installation boots directly into the launcher.
- The launcher discovers game definitions from `games/` and sorts them alphabetically by display name.
- A game definition points to game data stored outside this repository.
- Each game provides its own DOSBox config, keyboard mapper and DDR-pad map.
- The launcher starts DOSBox, waits for it to exit, and then returns to the menu.
- DDR SELECT is a host-level panic control that terminates DOSBox independently
  of the game's mapper.
- If a game cannot be started or DOSBox exits abnormally, the launcher shows a fullscreen Slovak error screen and waits for the normal confirm input before returning to the menu.
- `Bye bye!` powers off a Raspberry Pi and exits to the console elsewhere.

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
exit status. The shared appliance base config and generated per-launch override
are retained alongside it at `/tmp/pi-286-games-dosbox-base.conf` and
`/tmp/pi-286-games-dosbox.conf` for troubleshooting. The executable
`/tmp/pi-286-games-dosbox-command.sh` is retained too; it replays the exact
last launcher DOSBox command and its relevant appliance environment.

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

The keyboard remains fully usable. The exact WiseGroup X-PAD DDR dance pad is
also supported directly through Linux's joystick interface, with no pygame or
background input daemon. Its button 2 is menu up, button 1 menu down, button 8
is START/confirm, and button 9 is SELECT/back. Choosing a game opens a
full-screen physical pad layout first; press Space or START to launch, or Esc
or SELECT to return.

While DOSBox runs, SELECT (button 9) is permanently monitored by the launcher
and returns to the menu immediately. It is never exposed to DOSBox. Every game
has a small `ddr.conf` which maps buttons 0–8 to the same DOSBox keyboard keys
and Slovak labels shown on that screen. The normal keyboard bindings remain in
parallel. See [DDR dance pad setup and mappings](docs/ddr-dance-pad.md).

F1 always displays the first detected Ethernet or Wi-Fi IPv4 address in the
bottom-right corner when pressed in the menu. It
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
The installer adds the user to the usual `input` group so it can read the DDR
pad and use F1 as the keyboard panic fallback. Log out and back in once for
that new group membership to take effect.

On the ARMv6 256 MB Pi target, the installer builds pinned classic SDL 1.2.16
under `/opt/sdl12-fbcon` and configures DOSBox alone to use its fbcon backend.
It also manages the real 640×480 HDMI/framebuffer boot mode; reboot after
installation. This avoids Debian's SDL 1.2 compatibility layer and does not
install X11 or enable KMS/FKMS. The corresponding `dosbox_*` settings in
`config/host.conf` are fixed for this appliance. See
[the legacy framebuffer display guide](docs/legacy-fbcon-display.md).

For a monitor that forcibly stretches 4:3 HDMI to 16:9, an optional custom-SDL
pillarbox mode can send a wider physical 480-high framebuffer with a centered,
unscaled 640×480 DOS image. It is disabled by default; see the
[legacy framebuffer display guide](docs/legacy-fbcon-display.md).

The installer also enables the verified BCM2835 HDMI audio path, persists the
`snd_bcm2835` module, adds the appliance user to `audio`, and writes an ALSA
default for the detected bcm2835 HDMI card name. DOSBox is explicitly run with
SDL's ALSA backend and `AUDIODEV=plughw:0,0`, targeting the physically verified
HDMI device while allowing legacy SDL audio conversion. Log out and back in
after the new group membership, or reboot after installation.

At boot, a root-owned `pi-286-games-audio.service` explicitly loads
`snd_bcm2835` before the launcher. The launcher displays gray `Zvuk: ide` or
`Zvuk: nejde` in its top-right corner based on the live module and `/dev/snd`
access state.

The launcher service temporarily conflicts with `getty@tty1.service`. When the
launcher exits through Ctrl-C or `Bye bye!`, it starts the existing tty1 getty
again, returning to the usual autologin maintenance shell instead of launching
the application again. On physical Raspberry Pi hardware, `Bye bye!` instead
requests a shutdown; on any other machine it simply exits to the console.

### Direct console boot

Plymouth is deliberately not used. It starts too late on this Pi 1 and adds a
graphical element to an otherwise text-only appliance. DietPi boot text remains
visible until the launcher takes ownership of tty1.

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

### Console commands

The installer maintains these aliases in the appliance user's `.bashrc`:

```sh
pg-install             # Run the DietPi appliance installer.
pg-start --no-sound    # Start the launcher; any launcher option may follow.
pg-update              # Fast-forward the repository, then reinstall it.
pg-check --smoke-dosbox # Run health checks; optional smoke test.
pg-restart             # Hand tty1 back from getty to the launcher, including over SSH.
```

Open a new Bash shell after installation, or run `source ~/.bashrc` once, for
the aliases to become available.

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

To isolate the custom SDL audio backend from DOSBox, run
`sh scripts/run-sdl-audio-self-test.sh`. It plays a two-second tone through the
same verified HDMI PCM (`plughw:0,0`) and does not take over tty1.

## No-sound launch mode

Run the launcher with `--no-sound` to disable DOSBox's mixer and MIDI output
device and force SDL's dummy audio backend for audio troubleshooting:

```sh
python3 launcher/launcher.py --no-sound
```
