#!/bin/sh
# Pinned inputs shared by the DOSBox-X build and its repository checks.
set -eu
dosbox_x_repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dosbox_x_source_url=https://github.com/joncampbell123/dosbox-x.git
dosbox_x_source_ref=dosbox-x-v2025.10.07
dosbox_x_source_commit=0cd7c0fecb41d10152e96a63beb7001a7fdbd8e4
dosbox_x_prefix=/opt/pi286/dosbox-x
dosbox_x_patch_files="$dosbox_x_repo/patches/dosbox-x/0001-disable-libpng-when-screenshots-are-disabled.patch $dosbox_x_repo/patches/dosbox-x/0002-cross-armhf-host-is-armv6.patch $dosbox_x_repo/patches/dosbox-x/0003-armv6-use-arm-mode-dynrec-generator.patch $dosbox_x_repo/patches/dosbox-x/0004-sdl1-define-extended-mapper-keycodes.patch $dosbox_x_repo/patches/dosbox-x/0005-accept-pi286-classic-sdl1.patch $dosbox_x_repo/patches/dosbox-x/0006-disable-bios-png-logo-without-libpng.patch"
dosbox_x_configure_args='--enable-sdl --disable-sdl2 --disable-x11 --disable-opengl --disable-sdlnet --disable-freetype --disable-printer --disable-xbrz --disable-alsa-midi --disable-mt32 --disable-screenshots --disable-libslirp --disable-libfluidsynth --disable-avcodec --disable-gamelink --enable-scaler-full-line --disable-debug --enable-dynrec'
dosbox_x_apply_patches() {
    source_dir=$1
    for patch_file in $dosbox_x_patch_files; do
        if git -C "$source_dir" apply --check "$patch_file"; then git -C "$source_dir" apply "$patch_file"
        elif git -C "$source_dir" apply --reverse --check "$patch_file"; then :
        else echo "Cannot apply DOSBox-X patch cleanly: $patch_file" >&2; return 1
        fi
    done
}
