# Implementation contract

Keep this project deliberately small. Prefer the Python standard library and direct Linux facilities over desktop environments, GUI frameworks, web stacks, databases, or configuration frameworks.

## Launcher behavior

The launcher is a fullscreen appliance UI intended to start automatically after boot.

The normal menu is text-only and visually minimal, for example:

```text
  Dizzy
  Grand Prix
> Prehistorik
  Prince of Persia
  Tetris

  Bye bye!
```

Requirements:

- Discover game definitions from immediate subdirectories of `games/`.
- Ignore helper directories whose names begin with `_`.
- Read the display name from each game's `game.conf`.
- Sort games alphabetically by display name, case-insensitively.
- Append a special `Bye bye!` menu item after a blank visual gap.
- Up and Down move the selection.
- Confirm selects the current item. The normal confirm input is Space / dance-mat middle and is host-configurable.
- `Bye bye!` performs a clean Linux shutdown.
- The launcher should remain the parent process while DOSBox is running and return to the menu after DOSBox exits.
- Do not validate game executable existence during menu discovery.

## Launching games

A game definition provides:

- display name,
- data directory relative to `game_data_root`,
- executable/command,
- DOSBox config path,
- DOSBox mapper path.

Game binaries and assets must never be committed to this repository.

On launch, resolve the configured data directory and executable. If required game data is missing, DOSBox cannot be started, or DOSBox exits abnormally, show a fullscreen Slovak error screen instead of crashing the launcher.

The error screen should clearly identify the game and explain that it could not be started. It must remain visible until the normal Confirm input is pressed, then return to the menu.

Do not treat a normal game exit as an error.

## Panic exit

While DOSBox is running, monitor a separate host-level panic input configured in `config/host.conf`.

The panic input:

- is independent of DOSBox mapper files,
- must work even if the DOS game or DOSBox mapper is misconfigured,
- should terminate the entire DOSBox process group cleanly first and force-kill it only if necessary,
- returns control to the launcher menu,
- must not itself be forwarded to the DOS guest.

For UTM development, `F1` is an acceptable panic key. The Raspberry Pi deployment will use a dedicated dance-mat control.

## Rendering

Prefer a tiny custom fullscreen renderer rather than pygame or a desktop environment.

Target concept:

- direct framebuffer or another minimal Linux display path,
- hardcoded small bitmap font is acceptable,
- text only; no game artwork or image assets,
- black background and a few deterministic colors are sufficient,
- game color may be derived deterministically from its display name,
- redraw only when needed; no animation loop is required.

Keep rendering isolated enough that a different backend can be substituted if UTM and Raspberry Pi expose different display APIs.

## Configuration

`config/host.conf` is host-local and ignored by Git. `config/host.conf.example` documents supported settings.

Do not introduce JSON/YAML unless a real requirement appears. Simple INI/key-value configuration is preferred.

## Development target

The launcher should be testable in a DietPi UTM VM before deployment to a Raspberry Pi Model B+ (ARMv6, 256 MB RAM). Avoid dependencies that make ARMv6 deployment difficult.

All code comments and documentation should be in English. User-visible launcher/error text may be Slovak.
