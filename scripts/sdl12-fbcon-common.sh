#!/bin/sh
# Shared pinned SDL inputs for native Pi and cross builds.
set -eu
sdl12_fbcon_repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sdl12_fbcon_prefix=/opt/sdl12-fbcon
sdl12_fbcon_source_url=https://github.com/libsdl-org/SDL-1.2.git
sdl12_fbcon_source_commit=7bf353eca59cb503f43b86e3867dc4fc4e45f2e3
sdl12_fbcon_version=1.2.16
sdl12_fbcon_patch_files="$sdl12_fbcon_repo/patches/0001-pi286-fbcon-optional-pillarbox.patch $sdl12_fbcon_repo/patches/0002-pi286-fbcon-centered-canvas-color.patch"
sdl12_fbcon_configure_args='--enable-audio --enable-alsa --disable-alsa-shared --enable-video-fbcon --disable-video-x11 --disable-video-opengl'
sdl12_fbcon_apply_patches() {
    source_dir=$1
    for patch_file in $sdl12_fbcon_patch_files; do
        if git -C "$source_dir" apply --check "$patch_file"; then git -C "$source_dir" apply "$patch_file";
        elif git -C "$source_dir" apply --reverse --check "$patch_file"; then :;
        else echo "Cannot apply SDL patch cleanly: $patch_file" >&2; return 1; fi
    done
}
