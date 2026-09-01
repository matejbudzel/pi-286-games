# Target platform

The intended experience is a late 286 PC with EGA graphics, reflecting the
original family hardware rather than the most capable mode DOSBox can emulate.

The launcher runs only on a Raspberry Pi Model B Rev 1 (ARMv6, single-core 700 MHz,
256 MB RAM). Per-game DOSBox profiles therefore use `machine=ega` and a fixed,
modest cycle count instead of SVGA and unconstrained automatic cycles. This
keeps the emulation workload predictable and is appropriate for this curated
set of early DOS games.

The remote backend owns the common DOSBox profile; change it only when a title
demonstrably requires a different graphics adapter or CPU speed.
The appliance defaults to low-rate PC-speaker audio: Sound Blaster, AdLib/FM,
MIDI, Tandy, and Disney Sound Source are disabled. DOSBox mixes the PC speaker
at 22050 Hz with a 2048-sample block and 100 ms prebuffer, reducing audio load
and underruns on the single-core Pi 1. A game may deliberately override these
defaults only after physical testing.
