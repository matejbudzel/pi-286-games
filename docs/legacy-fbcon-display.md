# Legacy framebuffer display path

This appliance is proven on a Raspberry Pi Model B Rev 1 (ARMv6, 256 MB RAM;
about 226424 kB visible), DietPi/Raspbian trixie armhf, and the Raspberry Pi
`rpi-v6` kernel. It intentionally runs directly on the Linux console: no X11
desktop, Wayland compositor, or Plymouth boot splash is installed.

## Why this needs a custom SDL

Debian's DOSBox 0.74-3 is not rebuilt. It links the SDL 1.2 ABI, but the distro
`libSDL-1.2.so.0` is `sdl12-compat`, an SDL 1.2 compatibility layer implemented
on SDL2. That path tries X11, Wayland, or KMSDRM. The 256 MB Pi 1 appliance has
no X server and no `/dev/dri`; VC4 KMS/FKMS is deliberately not enabled.

The supported video path is:

```text
DOSBox → classic SDL 1.2 → fbcon → /dev/fb0 → BCM2708 framebuffer → HDMI
```

## Optional widescreen pillarbox compatibility

The normal appliance path remains a real 640×480 HDMI/framebuffer mode with
`dosbox_sdl_fb_pillarbox=0`. Use it whenever the monitor preserves 4:3.

Some target monitors stretch every 4:3 HDMI signal to the full 16:9 panel.
For those displays only, configure a larger supported legacy HDMI mode in
`config/host.conf`, set its `framebuffer_width`, `framebuffer_height`, and HDMI
group/mode values, then set `dosbox_sdl_fb_pillarbox=1` and rerun the installer
before rebooting. The physical mode is deliberately host-configured; 854×480
and the broadly compatible CEA 1280×720 mode are candidates, not hardcoded
requirements.

For an initial custom-timing experiment, the Pi legacy firmware's DMT custom
mode 87 with `framebuffer_hdmi_cvt=854 480 60 3 0 0 0` is a reasonable value
to validate on the specific monitor. Keep it only if the monitor accepts it
and reports the expected 854×480 framebuffer; other supported 480-high timing
values can be substituted without changing SDL.

```text
stock DOSBox logical SDL surface: 640x480
                 |
custom SDL fbcon: centered RGB565 dirty-rectangle copy
                 v
+----------------------------------+
|              canvas              |
|       +------------------+       |
|       |    640x480 DOS   |       |
|       +------------------+       |
|              canvas              |
+----------------------------------+
 physical framebuffer, for example 1280x720
                 |
 monitor displays the whole 16:9 HDMI signal
```

This is pillarboxing or letterboxing, not scaling: SDL copies logical pixels
unchanged and clears the unused canvas black. DOSBox stays the distro binary
and never sees the physical framebuffer dimensions. The custom SDL validates
unrotated RGB565 and a physical width and height at least as large as the
logical surface; otherwise `SDL_SetVideoMode` fails with a diagnostic. The
normal direct-mmap 640×480 path is unchanged when the variable is absent or
`0`.

For a wire-path diagnostic, set
`dosbox_sdl_fb_canvas_color=ff00ff` in `host.conf`. The custom SDL then fills
every unused physical pixel magenta instead of black. It accepts exactly six
RGB hex digits and defaults to black when the setting is absent. This makes it
possible to distinguish the framebuffer content SDL sends from a monitor's
own blacking, cropping, or unsupported-mode behaviour.

For a standard 720p experiment, use `framebuffer_hdmi_group=1`,
`framebuffer_hdmi_mode=4`, `framebuffer_width=1280`,
`framebuffer_height=720`, and `framebuffer_depth=16`; leave
`framebuffer_hdmi_cvt` unset. The 640×480 logical surface then has offsets
`x=320`, `y=120`. The 720p mode consumes about 1.8 MiB of RGB565 framebuffer
memory and a full logical frame still copies only about 600 KiB.

Run `sh scripts/run-sdl-fbcon-self-test.sh --pillarbox` after selecting and
rebooting into the larger physical mode. It draws a blue 640×480 area with a
white border and yellow center line; the rest of the framebuffer must be the
configured canvas color. `sh scripts/health-check.sh` reports
logical/physical geometry, stride, state, and calculated horizontal and
vertical canvas borders.

For the fixed magenta wire-path diagnostic without typing an environment
variable, run `sh scripts/run-sdl-fbcon-self-test.sh --sdl-canvas-magenta`.

`scripts/build-sdl12-fbcon.sh` builds upstream `libsdl-org/SDL-1.2` commit
`7bf353eca59cb503f43b86e3867dc4fc4e45f2e3` (SDL 1.2.16) with fbcon and audio,
but without X11 or OpenGL. Its persistent source and build directory is
`/home/dietpi/pi-286-games-sdl12-fbcon`, so later runs reuse the checkout and
compiled objects. Local SDL changes in that directory are retained. Set
`SDL12_FBCON_BUILD_DIR` to use another location. It installs only under
`/opt/sdl12-fbcon`; it never replaces Debian's SDL. It defaults to `make -j1`
for Pi 1 memory pressure. A future ARMv6 package or release artifact could
avoid local compilation, but source builds remain authoritative.

## Fast x86_64 cross-build and Pi deployment

Use the `pi286` SSH alias from the developer machine's SSH configuration; this
repository intentionally contains no Pi IP, username, port, or key details.
`scripts/dev-sdl.sh all` syncs the real Pi/Raspbian sysroot to ignored
`.cache/pi286-sysroot`, cross-builds the same pinned source and patch set with
`arm-linux-gnueabihf-gcc`, validates ARMv6 hard-float ELF attributes, writes
ignored `dist/sdl12-fbcon-rpi1-armv6-armhf.tar.gz`, deploys only to
`/opt/sdl12-fbcon`, and verifies stock DOSBox resolves that library.

```sh
ssh -o BatchMode=yes pi286 true
scripts/dev-sdl.sh all
```

Install `gcc-arm-linux-gnueabihf` on the development machine first. The real
target sysroot is preferred to generic Debian armhf files because Pi 1 needs
ARMv6-compatible userspace. Normal deployment does not reboot, change boot
configuration, rebuild DOSBox, or take over `/dev/fb0`. Use
`scripts/dev-sdl.sh visual` or `scripts/dev-sdl.sh visual-pillarbox` only for
an explicit manual display test. The native Pi fallback consumes the same
shared pin, patch list, configure flags, and `/opt/sdl12-fbcon` prefix.

The launcher reads the `dosbox_*` values in `config/host.conf` and passes
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
framebuffer. The launcher writes a shared appliance base config at
`/tmp/pi-286-games-dosbox-base.conf` and invokes DOSBox with it first, then the
game's `dosbox.conf`, then the generated mapper/mount/autoexec config. The base
forces the 640×480 fullscreen surface (`fullfixed=true`), sets
`usescancodes=false` for the fbcon keyboard, and supplies `fulldouble=false`,
`output=surface`, `frameskip=0`, `aspect=true`, and `scaler=normal2x`.

This expands normal 320×200 DOS modes to 640×400 before aspect correction in
the real 640×480 framebuffer. DOSBox 0.74-3 otherwise misinterprets
Linux-console scancodes as X11-style scancodes, causing incorrect key mappings
such as Space producing a letter. A game may deliberately override an SDL or
render value in its own `dosbox.conf`; its machine, CPU, memory, and other
game-specific settings remain unchanged.

## Verification and diagnosis

After `./scripts/install-dietpi.sh` and reboot:

```sh
fbset -fb /dev/fb0 -i
LD_LIBRARY_PATH=/opt/sdl12-fbcon/lib ldd "$(command -v dosbox)" | grep libSDL-1.2
sh scripts/health-check.sh
sh scripts/health-check.sh --smoke-dosbox
sh scripts/run-sdl-fbcon-self-test.sh
sh scripts/run-sdl-audio-self-test.sh
```

The self-test compiles against `/opt/sdl12-fbcon`, fills the screen blue for
three seconds, then exits. It is intentionally manual because it takes over
the active tty. Expected framebuffer facts are `BCM2708 FB`, 640×480, 16 bpp,
stride 1280, and a 614400-byte framebuffer. `/dev/fb0` should normally be
readable and writable by the `video` group. No `/dev/dri` is expected here.

The audio self-test uses the same `/opt/sdl12-fbcon` library and explicit
`plughw:0,0` ALSA variables as DOSBox, but does not initialise video. This is
the verified HDMI hardware PCM with ALSA format/rate conversion, which legacy
SDL needs instead of the strict raw `hw:0,0` interface. It emits a two-second
tone and prints the selected SDL audio driver. This separates a working ALSA
device from a working classic-SDL audio backend.

| Symptom | Diagnosis / action |
| --- | --- |
| `Can't init SDL fbcon not available` | DOSBox used distro sdl12-compat instead of `/opt/sdl12-fbcon`; check the `ldd` command and host config. |
| `Can't init SDL Unable to open a console terminal` | DOSBox has lost its controlling tty or foreground tty process group; launch through the supplied tty1 service and do not detach or isolate DOSBox with `setsid`/`setpgrp`. |
| Last game frame remains after DOSBox exits | The launcher monitors the child PID and forces tty1 back to Linux text mode before redrawing; update the launcher if the old frame remains. |
| Black screen while DOSBox stays alive | Verify `SDL_FB_BROKEN_MODES=1`; run the standalone SDL self-test to separate SDL from DOSBox. |
| A small centered 640×480 image in 1080p | The actual HDMI/framebuffer remains 1080p; correct the boot settings and reboot. |
| `/dev/fb0` exists but `/dev/dri` does not | Expected for this legacy path, not an error. |
| `ALSA cannot find card '0'` / `Unknown PCM default` | Check `snd_bcm2835`, `/dev/snd`, audio-group membership, and `/etc/asound.conf`; this is separate from video. |
| `SDL_OpenAudio: ...` from the SDL audio self-test | The custom classic SDL audio backend cannot open the verified PCM; inspect or rebuild `/opt/sdl12-fbcon` before changing DOSBox. |

## HDMI audio

HDMI audio is verified through the monitor speakers with:

```sh
speaker-test -D hw:0,0 -c 2 -t sine
```

The appliance boot configuration sets `dtparam=audio=on`; the installer
persists `snd_bcm2835` in `/etc/modules-load.d/pi-286-games-audio.conf`, adds
the user to `audio`, and writes `/etc/asound.conf`. The latter selects the
detected bcm2835 HDMI ALSA card identifier (normally `HDMI`) rather than
assuming a particular card number. Audio health warnings remain separate from
framebuffer/video success, and speaker-test is never run automatically. The
root-owned `pi-286-games-audio.service` also runs `modprobe snd_bcm2835` before
the launcher as a boot-time recovery path; the launcher shows its live audio
state in the top-right corner. DOSBox's classic SDL 1.2 ALSA backend is also
given `AUDIODEV=plughw:0,0` and `SDL_PATH_DSP=plughw:0,0` explicitly. Card
0/device 0 is the physically verified HDMI PCM on this fixed Pi 1 appliance;
the `plug` layer adapts legacy SDL's audio format while `/etc/asound.conf`
remains card-name based.
