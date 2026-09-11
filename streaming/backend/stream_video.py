"""Framebuffer capture and RGB565 packet encoding for stream sessions."""
from __future__ import annotations

import os
import secrets
import struct
import subprocess
import time
import zlib
from pathlib import Path

from streaming.backend.stream_models import (VIDEO_BYTES, VIDEO_HEIGHT, VIDEO_KEYFRAME_INTERVAL,
                                             VIDEO_PACKET_HEADER, VIDEO_TILE, VIDEO_WIDTH)

VIDEO_2X_WIDTH = 640
VIDEO_2X_HEIGHT = 480
VIDEO_2X_BYTES = VIDEO_2X_WIDTH * VIDEO_2X_HEIGHT * 2
VIDEO_2X_TILE = 16
VIDEO_2X_MAX_TILES = 112
VIDEO_HASH_HISTORY = 150


class VideoMixin:
    def capture_frame(self, session_id: str) -> dict:
        with self.lock:
            item = self.active.get(session_id)
            if not item:
                raise KeyError(session_id)
            if item["dosbox"].poll() is not None:
                raise RuntimeError("DOSBox has already exited")
            frame_id = f"{len(item['frames']) + 1:04d}.xwd"
            frame = self.runtime / f"{session_id}-{frame_id}"
            subprocess.run([self.config["xwd"], "-silent", "-root", "-display", item["display"], "-out", str(frame)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3, check=True)
            item["frames"].append(frame)
            return {"id": frame_id, "bytes": frame.stat().st_size,
                    "path": f"/v1/sessions/{session_id}/frames/{frame_id}"}

    def video_frame(self, session_id: str, force_keyframe: bool = False) -> tuple[bytes, int, int]:
        """Return an aspect-correct, recoverable RGB565 video packet for the Pi."""
        with self.lock:
            item = self.active.get(session_id)
            if not item:
                raise KeyError(session_id)
            if item["dosbox"].poll() is not None:
                raise RuntimeError("DOSBox has already exited")
            started = time.monotonic()
            if item.get("diagnostic"):
                item["video_sequence"] = item.get("video_sequence", 0) + 1
                cat_y = item.setdefault("diagnostic_cat_y", 104)
                if "UP" in item["held_keys"]:
                    cat_y -= 3
                if "DOWN" in item["held_keys"]:
                    cat_y += 3
                item["diagnostic_cat_y"] = max(0, min(VIDEO_HEIGHT - 40, cat_y))
                frame = self._diagnostic_frame(item["video_sequence"], item["diagnostic_cat_y"],
                                               "nearest" if item.get("compression") == "zlib-2x" else item.get("video_scaling", "nearest"))
                if item.get("compression") == "zlib-2x":
                    frame = self._scale_frame_2x(frame, item.get("video_scaling", "nearest"))
                    capture_ms = 0
                    keyframe = force_keyframe or not item.get("video_delivered")
                    packet, keyframe, delivered, cursor = self._video_2x_packet(frame, item.get("video_delivered"),
                                                                                item["video_sequence"], capture_ms, keyframe,
                                                                                item.get("video_tile_cursor", 0))
                    item["video_delivered"] = delivered
                    item["video_tile_cursor"] = cursor
                    self._remember_video_hash(item, item["video_sequence"], delivered)
                    return packet, item["video_sequence"], capture_ms
                keyframe = force_keyframe or not item.get("video_previous") or \
                    time.monotonic() - item.get("video_last_keyframe", 0.0) >= VIDEO_KEYFRAME_INTERVAL
                packet, keyframe = self._video_packet(frame, item.get("video_previous"),
                                                       item["video_sequence"], 0, keyframe)
                item["video_previous"] = frame
                if keyframe:
                    item["video_last_keyframe"] = time.monotonic()
                return self._compress_keyframe(packet, item), item["video_sequence"], 0
            temporary = self.runtime / f"{session_id}-video-{secrets.token_hex(4)}.xwd"
            try:
                two_x = item.get("compression") == "zlib-2x"
                frame = self._native_frame(item["framebuffer"], item.get("video_scaling", "nearest"), two_x)
                source = None if frame is not None else self._stable_xvfb_frame(item["framebuffer"])
                if source is None and frame is None:
                    # Direct Xvfb memory reads are much faster than running xwd
                    # per frame. The direct check is heuristic, not a locking
                    # protocol. If it observes a concurrent update, use a
                    # server-serialized XGetImage snapshot instead.
                    subprocess.run([self.config["xwd"], "-silent", "-root", "-display", item["display"], "-out", str(temporary)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3, check=True)
                    source = temporary.read_bytes()
                if frame is None:
                    frame = (self._xwd_to_rgb565_2x(source, item.get("video_scaling", "nearest")) if two_x
                             else self._xwd_to_rgb565(source, item.get("video_scaling", "nearest")))
                item["video_sequence"] = item.get("video_sequence", 0) + 1
                capture_ms = int((time.monotonic() - started) * 1000)
                if two_x:
                    keyframe = force_keyframe or not item.get("video_delivered")
                    packet, keyframe, delivered, cursor = self._video_2x_packet(frame, item.get("video_delivered"),
                                                                                item["video_sequence"], capture_ms, keyframe,
                                                                                item.get("video_tile_cursor", 0))
                    item["video_delivered"] = delivered
                    item["video_tile_cursor"] = cursor
                    self._remember_video_hash(item, item["video_sequence"], delivered)
                    return packet, item["video_sequence"], capture_ms
                keyframe = force_keyframe or not item.get("video_previous") or \
                    time.monotonic() - item.get("video_last_keyframe", 0.0) >= VIDEO_KEYFRAME_INTERVAL
                packet, keyframe = self._video_packet(frame, item.get("video_previous"),
                                                       item["video_sequence"], capture_ms, keyframe)
                item["video_previous"] = frame
                if keyframe:
                    item["video_last_keyframe"] = time.monotonic()
                return self._compress_keyframe(packet, item), item["video_sequence"], capture_ms
            finally:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _stable_xvfb_frame(path: Path) -> bytes | None:
        """Read an Xvfb `-fbdir` XWD image only when two copies agree.

        The file is shared memory exposed as an XWD file and has no reader
        lock. Consecutive identical complete copies catch common concurrent
        updates but are not a formal atomic snapshot. Callers fall back to
        XGetImage when the check stays unstable.
        """
        for _ in range(3):
            try:
                first = path.read_bytes()
                second = path.read_bytes()
            except FileNotFoundError:
                return None
            if first == second:
                return second
        return None

    def _native_frame(self, framebuffer: Path, scaling: str, two_x: bool = False) -> bytes | None:
        """Use the optional native server helper, preserving Python fallback."""
        helper = Path(self.config.get("capture_helper", ""))
        if not helper.is_file() or not os.access(helper, os.X_OK):
            return None
        try:
            command = [str(helper), str(framebuffer), scaling]
            if two_x:
                command.append("2x")
            result = subprocess.run(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=2, check=False)
        except OSError:
            return None
        expected = VIDEO_2X_BYTES if two_x else VIDEO_BYTES
        if result.returncode == 0 and len(result.stdout) == expected:
            return result.stdout
        return None

    @staticmethod
    def _diagnostic_frame(sequence: int, cat_y: int = 104, video_scaling: str = "nearest") -> bytes:
        """Return a deliberately vivid RGB565 transport reference frame."""
        colors = (0xf800, 0xfd20, 0xffe0, 0x07e0, 0x07ff, 0x001f, 0x781f)
        output = bytearray(VIDEO_BYTES)
        for y in range(VIDEO_HEIGHT):
            for x in range(VIDEO_WIDTH):
                color = colors[(x // 24 + y // 40) % len(colors)]
                struct.pack_into("<H", output, (y * VIDEO_WIDTH + x) * 2, color)
        # A small moving white/pink cat-like block makes tile updates visible.
        cat_x = 128 + (sequence // 2) % 48
        for y in range(cat_y, cat_y + 40):
            for x in range(cat_x, cat_x + 64):
                edge = x in (cat_x, cat_x + 63) or y in (cat_y, cat_y + 39)
                color = 0x0000 if edge else 0xfdb7
                struct.pack_into("<H", output, (y * VIDEO_WIDTH + x) * 2, color)
        return VideoMixin._apply_crt_lite(bytes(output), video_scaling)

    @staticmethod
    def _compress_keyframe(packet: bytes, item: dict) -> bytes:
        if item.get("compression") != "zlib" or packet[4] != 1:
            return packet
        compressed = zlib.compress(packet[16:], 1)
        if len(compressed) >= len(packet) - 16:
            return packet
        return packet[:4] + bytes((3, 0, 0, 0)) + packet[8:16] + compressed

    @staticmethod
    def _video_2x_packet(frame: bytes, delivered: bytearray | None, sequence: int, capture_ms: int,
                         keyframe: bool, cursor: int = 0) -> tuple[bytes, bool, bytearray, int]:
        """Encode a recoverable 2x keyframe or raw 16x16 changed tiles.

        Kind 4 is a zlib keyframe. Kind 5 has raw tiles: avoiding a 614 KiB
        inflate for each moving frame is essential on the ARMv6 Pi.
        """
        if len(frame) != VIDEO_2X_BYTES:
            raise ValueError("invalid 2x RGB565 frame size")
        if keyframe or delivered is None or len(delivered) != VIDEO_2X_BYTES:
            return (struct.pack(">4sBBHII", b"P2V1", 4, 0, 0, sequence, capture_ms) + zlib.compress(frame, 1),
                    True, bytearray(frame), 0)
        tiles = bytearray()
        count = 0
        columns = VIDEO_2X_WIDTH // VIDEO_2X_TILE
        total = columns * (VIDEO_2X_HEIGHT // VIDEO_2X_TILE)
        for step in range(total):
            index = (cursor + step) % total
            tile_x, tile_y = index % columns, index // columns
            changed = False
            for row in range(VIDEO_2X_TILE):
                offset = ((tile_y * VIDEO_2X_TILE + row) * VIDEO_2X_WIDTH + tile_x * VIDEO_2X_TILE) * 2
                width = VIDEO_2X_TILE * 2
                if frame[offset:offset + width] != delivered[offset:offset + width]:
                    changed = True
                    break
            if changed:
                tiles.extend((tile_x, tile_y))
                for row in range(VIDEO_2X_TILE):
                    offset = ((tile_y * VIDEO_2X_TILE + row) * VIDEO_2X_WIDTH + tile_x * VIDEO_2X_TILE) * 2
                    tiles.extend(frame[offset:offset + VIDEO_2X_TILE * 2])
                    delivered[offset:offset + VIDEO_2X_TILE * 2] = frame[offset:offset + VIDEO_2X_TILE * 2]
                count += 1
                if count >= VIDEO_2X_MAX_TILES:
                    return (struct.pack(">4sBBHII", b"P2V1", 5, 0, count, sequence, capture_ms) + tiles,
                            False, delivered, (index + 1) % total)
        return struct.pack(">4sBBHII", b"P2V1", 5, 0, count, sequence, capture_ms) + tiles, False, delivered, cursor

    @staticmethod
    def _remember_video_hash(item: dict, sequence: int, frame: bytearray) -> None:
        hashes = item.setdefault("video_hashes", {})
        hashes[sequence] = zlib.crc32(frame) & 0xffffffff
        while len(hashes) > VIDEO_HASH_HISTORY:
            del hashes[next(iter(hashes))]

    @staticmethod
    def _video_packet(frame: bytes, previous: bytes | None, sequence: int, capture_ms: int,
                      keyframe: bool) -> tuple[bytes, bool]:
        """Encode a full keyframe or changed 16x16 RGB565 tiles.

        The packet is intentionally uncompressed: tiles remove EGA's static
        areas without adding a codec or a fragile cross-platform dependency.
        """
        if len(frame) != VIDEO_BYTES:
            raise ValueError("invalid RGB565 frame size")
        if keyframe or previous is None or len(previous) != VIDEO_BYTES:
            return struct.pack(">4sBBHII", b"P2V1", 1, 0, 0, sequence, capture_ms) + frame, True
        tiles = bytearray()
        count = 0
        for tile_y in range(VIDEO_HEIGHT // VIDEO_TILE):
            for tile_x in range(VIDEO_WIDTH // VIDEO_TILE):
                changed = False
                for row in range(VIDEO_TILE):
                    offset = ((tile_y * VIDEO_TILE + row) * VIDEO_WIDTH + tile_x * VIDEO_TILE) * 2
                    width = VIDEO_TILE * 2
                    if frame[offset:offset + width] != previous[offset:offset + width]:
                        changed = True
                        break
                if changed:
                    tiles.extend((tile_x, tile_y))
                    for row in range(VIDEO_TILE):
                        offset = ((tile_y * VIDEO_TILE + row) * VIDEO_WIDTH + tile_x * VIDEO_TILE) * 2
                        tiles.extend(frame[offset:offset + VIDEO_TILE * 2])
                    count += 1
        if VIDEO_PACKET_HEADER + len(tiles) >= VIDEO_PACKET_HEADER + VIDEO_BYTES:
            return struct.pack(">4sBBHII", b"P2V1", 1, 0, 0, sequence, capture_ms) + frame, True
        return struct.pack(">4sBBHII", b"P2V1", 2, 0, count, sequence, capture_ms) + tiles, False

    @staticmethod
    def _xwd_to_rgb565(source: bytes, video_scaling: str = "nearest") -> bytes:
        if len(source) < 100:
            raise ValueError("truncated XWD header")
        header = struct.unpack_from(">25I", source)
        header_size, width, height = header[0], header[4], header[5]
        byte_order, bits_per_pixel, bytes_per_line = header[7], header[11], header[12]
        if bits_per_pixel not in (24, 32) or byte_order != 0:
            raise ValueError("unexpected Xvfb image format")
        pixels = header_size + header[19] * 12
        if pixels + bytes_per_line * height > len(source):
            raise ValueError("truncated XWD pixels")
        if width == VIDEO_WIDTH and height == VIDEO_HEIGHT and bytes_per_line == VIDEO_WIDTH * 4:
            return VideoMixin._xwd_direct_to_rgb565(source, pixels, bytes_per_line)
        if width != 640 or height != 480 or bytes_per_line != 640 * 4:
            raise ValueError("unexpected Xvfb image dimensions")
        # Xvfb's 24-bit TrueColor visual is stored as B,G,R,padding in this
        # 32-bits-per-pixel XWD image.
        # Crop the 640x400 DOS region centred in 640x480.  Horizontally sample
        # 2x, then expand the original 320x200's 6:5 pixels to square pixels
        # using a 320x240 frame. The Pi can therefore use a cheap exact 2x
        # copy to its 640x480 SDL surface.
        output = bytearray(VIDEO_BYTES)
        destination = 0
        for y in range(VIDEO_HEIGHT):
            source_row = y * 200 // VIDEO_HEIGHT
            remainder = (y * 200) % VIDEO_HEIGHT
            row = pixels + (40 + 2 * source_row) * bytes_per_line
            next_row = pixels + (40 + 2 * min(199, source_row + 1)) * bytes_per_line
            for x in range(VIDEO_WIDTH):
                offset = row + x * 8
                blue, green, red = source[offset], source[offset + 1], source[offset + 2]
                if video_scaling in ("linear-v", "crt-lite") and remainder:
                    next_offset = next_row + x * 8
                    next_blue, next_green, next_red = source[next_offset], source[next_offset + 1], source[next_offset + 2]
                    blue = (blue * (VIDEO_HEIGHT - remainder) + next_blue * remainder) // VIDEO_HEIGHT
                    green = (green * (VIDEO_HEIGHT - remainder) + next_green * remainder) // VIDEO_HEIGHT
                    red = (red * (VIDEO_HEIGHT - remainder) + next_red * remainder) // VIDEO_HEIGHT
                color = ((red & 0xf8) << 8) | ((green & 0xfc) << 3) | (blue >> 3)
                if video_scaling == "crt-lite" and y % 2:
                    color = ((color & 0xf800) * 7 // 8 & 0xf800) | ((color & 0x07e0) * 7 // 8 & 0x07e0) | ((color & 0x001f) * 7 // 8 & 0x001f)
                output[destination] = color & 0xff
                output[destination + 1] = color >> 8
                destination += 2
        return bytes(output)

    @staticmethod
    def _xwd_direct_to_rgb565(source: bytes, pixels: int, bytes_per_line: int) -> bytes:
        """Convert the native 320x240 Xvfb BGR image without resampling."""
        output = bytearray(VIDEO_BYTES)
        destination = 0
        red = [(value & 0xf8) << 8 for value in range(256)]
        green = [(value & 0xfc) << 3 for value in range(256)]
        blue = [value >> 3 for value in range(256)]
        for y in range(VIDEO_HEIGHT):
            row = pixels + y * bytes_per_line
            for offset in range(row, row + VIDEO_WIDTH * 4, 4):
                color = red[source[offset + 2]] | green[source[offset + 1]] | blue[source[offset]]
                output[destination], output[destination + 1] = color & 0xff, color >> 8
                destination += 2
        return bytes(output)

    @staticmethod
    def _xwd_to_rgb565_2x(source: bytes, video_scaling: str = "nearest") -> bytes:
        """Convert the complete native 640x480 Xvfb root without resampling."""
        if len(source) < 100:
            raise ValueError("truncated XWD header")
        header = struct.unpack_from(">25I", source)
        header_size, width, height = header[0], header[4], header[5]
        byte_order, bits_per_pixel, bytes_per_line = header[7], header[11], header[12]
        pixels = header_size + header[19] * 12
        if (width, height, byte_order, bytes_per_line) != (640, 480, 0, 640 * 4) or bits_per_pixel not in (24, 32):
            raise ValueError("unexpected 2x Xvfb image dimensions")
        if pixels + bytes_per_line * height > len(source):
            raise ValueError("truncated XWD pixels")
        output = bytearray(VIDEO_2X_BYTES)
        destination = 0
        for y in range(VIDEO_2X_HEIGHT):
            row = pixels + y * bytes_per_line
            for offset in range(row, row + VIDEO_2X_WIDTH * 4, 4):
                color = ((source[offset + 2] & 0xf8) << 8) | ((source[offset + 1] & 0xfc) << 3) | (source[offset] >> 3)
                output[destination], output[destination + 1] = color & 0xff, color >> 8
                destination += 2
        return VideoMixin._apply_crt_lite_sized(bytes(output), video_scaling, VIDEO_2X_WIDTH, VIDEO_2X_HEIGHT)

    @staticmethod
    def _scale_frame_2x(frame: bytes, video_scaling: str) -> bytes:
        output = bytearray(VIDEO_2X_BYTES)
        for y in range(VIDEO_HEIGHT):
            source = frame[y * VIDEO_WIDTH * 2:(y + 1) * VIDEO_WIDTH * 2]
            expanded = b"".join(pixel * 2 for pixel in (source[offset:offset + 2] for offset in range(0, len(source), 2)))
            output[(y * 2) * VIDEO_2X_WIDTH * 2:(y * 2 + 1) * VIDEO_2X_WIDTH * 2] = expanded
            output[(y * 2 + 1) * VIDEO_2X_WIDTH * 2:(y * 2 + 2) * VIDEO_2X_WIDTH * 2] = expanded
        return VideoMixin._apply_crt_lite_sized(bytes(output), video_scaling, VIDEO_2X_WIDTH, VIDEO_2X_HEIGHT)

    @staticmethod
    def _apply_crt_lite(frame: bytes, video_scaling: str) -> bytes:
        return VideoMixin._apply_crt_lite_sized(frame, video_scaling, VIDEO_WIDTH, VIDEO_HEIGHT)

    @staticmethod
    def _apply_crt_lite_sized(frame: bytes, video_scaling: str, width: int, height: int) -> bytes:
        if video_scaling != "crt-lite":
            return frame
        output = bytearray(frame)
        for y in range(1, height, 2):
            for x in range(width):
                offset = (y * width + x) * 2
                color = output[offset] | output[offset + 1] << 8
                color = ((color & 0xf800) * 7 // 8 & 0xf800) | ((color & 0x07e0) * 7 // 8 & 0x07e0) | ((color & 0x001f) * 7 // 8 & 0x001f)
                output[offset], output[offset + 1] = color & 0xff, color >> 8
        return bytes(output)
