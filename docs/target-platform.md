# Target platform

The intended experience is a late 286 PC with EGA graphics, reflecting the
original family hardware rather than the most capable mode DOSBox can emulate.

The launcher runs only on a Raspberry Pi Model B Rev 1 (ARMv6, single-core 700 MHz,
256 MB RAM). Per-game DOSBox profiles therefore use `machine=ega` and a fixed,
modest cycle count instead of SVGA and unconstrained automatic cycles. This
keeps the emulation workload predictable and is appropriate for this curated
set of early DOS games.

Use a game's `dosbox.conf` to make a title-specific adjustment only when its
original release genuinely requires a different graphics adapter or CPU speed.
Grand Prix also uses a 22050 Hz mixer rate and 60 ms prebuffer to reduce audio
underruns on the single-core Pi 1; do not apply that override to other games
without physical testing.
