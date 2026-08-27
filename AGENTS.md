# Project conventions

This repository is a small, self-contained DOS gaming appliance for DietPi and
a Raspberry Pi Model B Rev 1 (ARMv6, 256 MB RAM). Keep changes lightweight and
deployment-friendly.

- Prefer the Python standard library and direct Linux facilities. Do not add
  desktop environments, GUI frameworks, web stacks, databases, or configuration
  frameworks without a concrete new requirement.
- The launcher is intentionally a text-only Linux-console TUI. It uses the
  system console font; prefer configuring a larger console font over adding a
  custom framebuffer, bitmap-font, or graphical renderer.
- Preserve the 286/EGA target documented in `docs/target-platform.md` unless a
  specific game demonstrably needs different hardware settings.
- Game binaries and assets are private host data and must never be committed.
- `config/host.conf` is host-local and ignored by Git. Keep
  `config/host.conf.example` accurate when adding a supported host setting.
- Use simple key/value configuration; do not introduce JSON or YAML without a
  real requirement.
- Keep user-facing launcher and error text in Slovak when changing that UI.
  Keep code comments and documentation in English.
- The appliance is intentionally target-specific. Do not add fallback display
  stacks, desktop modes, VM support, or modern-hardware abstractions unless the
  project scope is explicitly broadened.

The README documents installation and operation. Existing launcher behaviour
is implemented code, not a pending implementation checklist; do not replace or
rework it unless the requested change requires doing so.

For the 256 MB target, direct-console video is deliberately classic SDL 1.2
fbcon through `/opt/sdl12-fbcon`, `/dev/fb0`, and the legacy BCM2708
framebuffer. Do not replace it with sdl12-compat, X11, Wayland, KMS, or FKMS;
`SDL_FB_BROKEN_MODES=1` is required for the known-good display path.
