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
- The special `Bye bye!` menu entry powers off the host.

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
/opt/pi-286-games-data/
  dizzy/
  grand-prix/
  prehistorik/
  prince-of-persia/
```

For local UTM development the same layout can live anywhere convenient, for example `~/pi-286-games-data/`.

## Input model

The launcher has three logical inputs:

- Up
- Down
- Confirm (`Space` / dance-mat middle)

While DOSBox is running, a separate host-level panic input is monitored. It is configured in `config/host.conf` and is intentionally independent of DOSBox mapper files. A development VM can use `F1`; the Raspberry Pi deployment can use a dedicated dance-mat control.

## Game definitions

Each subdirectory in `games/` represents one game and contains metadata plus optional DOSBox-specific files. The launcher does not require the referenced executable to exist while discovering the menu. Missing game data is handled only when the user launches that title.

## DietPi / Debian setup

Run this as the autologin user after cloning the repository:

```sh
./scripts/install-dietpi.sh
```

The script installs DOSBox when needed, copies the host configuration, grants
only the shutdown command through sudo, and starts the launcher on local tty1
when that user logs in (never over SSH). Configure `panic_device` to a readable
`/dev/input/event*` device for panic handling while DOSBox owns the display.
The install script adds the user to the usual `input` group; log out and back
in once for that new group membership to take effect.

The included definitions expect `GPEGA.EXE`, `PREHIST.EXE`, and `PRINCE.EXE`.
Change `exe` in the relevant `game.conf` if your lawful copy uses another name.
