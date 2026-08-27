# Legacy framebuffer display path

This appliance is proven on a Raspberry Pi Model B Rev 1 (ARMv6, 256 MB RAM;
about 226424 kB visible), DietPi/Raspbian trixie armhf, and the Raspberry Pi
`rpi-v6` kernel. It intentionally runs directly on the Linux console: no X11
desktop and no Wayland compositor are installed.

## Why this needs a custom SDL

Debian's DOSBox 0.74-3 is not rebuilt. It links the SDL 1.2 ABI, but the distro
`libSDL-1.2.so.0` is `sdl12-compat`, an SDL 1.2 compatibility layer implemented
on SDL2. That path tries X11, Wayland, or KMSDRM. The 256 MB Pi 1 appliance has
no X server and no `/dev/dri`; VC4 KMS/FKMS is deliberately not enabled.

The supported video path is:

```text
DOSBox → classic SDL 1.2 → fbcon → /dev/fb0 → BCM2708 framebuffer → HDMI
```

`scripts/build-sdl12-fbcon.sh` builds upstream `libsdl-org/SDL-1.2` commit
`7bf353eca59cb503f43b86e3867dc4fc4e45f2e3` (SDL 1.2.16) with fbcon and audio,
but without X11 or OpenGL. It installs only under `/opt/sdl12-fbcon`; it never
replaces Debian's SDL. It defaults to `make -j1` for Pi 1 memory pressure and
skips a valid existing 1.2.16 installation. A future ARMv6 package or release
artifact could avoid local compilation, but source builds remain authoritative.

The launcher reads the four `dosbox_*` values in `config/host.conf` and passes
them only to DOSBox: `LD_LIBRARY_PATH=/opt/sdl12-fbcon/lib`,
`SDL_VIDEODRIVER=fbcon`, `SDL_FBDEV=/dev/fb0`, and
`SDL_FB_BROKEN_MODES=1`. The last setting is essential: without it fbcon can
open and map the framebuffer yet render black.

## Boot mode and DOSBox settings

The installer invokes `scripts/configure-legacy-framebuffer.sh`, which
idempotently updates `/boot/firmware/config.txt` or `/boot/config.txt` while
preserving unrelated options. It sets a real HDMI/framebuffer mode of 640×480,
16 bpp: `hdmi_force_hotplug=1`, `hdmi_drive=2`, `hdmi_blanking=0`,
`disable_overscan=1`, `hdmi_group=2`, `hdmi_mode=4`, `framebuffer_width=640`,
`framebuffer_height=480`, and `framebuffer_depth=16`. Reboot afterwards.
It warns, without removing anything, if KMS/FKMS is already configured.

The physical HDMI signal is 640×480. A 1920×1080 monitor performs panel
scaling; the Pi does not software-scale a small DOS image inside a 1080p
framebuffer. Every generated per-game DOSBox override supplies fullscreen,
`fullresolution=640x480`, `output=surface`, `fulldouble=false`, and render
`frameskip=0`, `aspect=false`, `scaler=none`. Game configs still supply their
machine, CPU, memory, and other game-specific settings.

## Verification and diagnosis

After `./scripts/install-dietpi.sh` and reboot:

```sh
fbset -fb /dev/fb0 -i
LD_LIBRARY_PATH=/opt/sdl12-fbcon/lib ldd "$(command -v dosbox)" | grep libSDL-1.2
sh scripts/health-check.sh
sh scripts/health-check.sh --smoke-dosbox
sh scripts/run-sdl-fbcon-self-test.sh
```

The self-test compiles against `/opt/sdl12-fbcon`, fills the screen blue for
three seconds, then exits. It is intentionally manual because it takes over
the active tty. Expected framebuffer facts are `BCM2708 FB`, 640×480, 16 bpp,
stride 1280, and a 614400-byte framebuffer. `/dev/fb0` should normally be
readable and writable by the `video` group. No `/dev/dri` is expected here.

| Symptom | Diagnosis / action |
| --- | --- |
| `Can't init SDL fbcon not available` | DOSBox used distro sdl12-compat instead of `/opt/sdl12-fbcon`; check the `ldd` command and host config. |
| `Can't init SDL Unable to open a console terminal` | DOSBox has lost its controlling tty; launch through the supplied tty1 service and do not use `setsid` for DOSBox. |
| Black screen while DOSBox stays alive | Verify `SDL_FB_BROKEN_MODES=1`; run the standalone SDL self-test to separate SDL from DOSBox. |
| A small centered 640×480 image in 1080p | The actual HDMI/framebuffer remains 1080p; correct the boot settings and reboot. |
| `/dev/fb0` exists but `/dev/dri` does not | Expected for this legacy path, not an error. |
| `ALSA cannot find card '0'` / `Unknown PCM default` | Separate audio issue, not evidence of an emulation or video failure. |

Audio remains follow-up work. The observed target has `dtparam=audio=off` and
no usable default ALSA card. SDL audio must stay compiled because disabling it
makes DOSBox abort during SDL initialization, but successful video checks do
not claim HDMI audio works.
