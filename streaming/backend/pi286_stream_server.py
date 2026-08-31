#!/usr/bin/env python3
"""Small authenticated cache and DOSBox-session service for the Pi stream POC.

This intentionally has no video, audio, or input transport yet.  It gives the
Pi client a safe way to populate a content-addressed cache and to create one
headless DOSBox process at a time.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import shutil
import signal
import subprocess
import struct
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SESSION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULTS = {
    "bind": "0.0.0.0",
    "port": "28680",
    "state_root": "/srv/pi286-stream",
    "token_file": "/etc/pi286-stream.token",
    "dosbox": "/usr/bin/dosbox",
    "xvfb": "/usr/bin/Xvfb",
    "xwd": "/usr/bin/xwd",
    "xdotool": "/usr/bin/xdotool",
    "arecord": "/usr/bin/arecord",
    "audio_capture": "file",
    "audio_playback_device": "plughw:Loopback,0,0",
    "audio_capture_device": "hw:Loopback,1,0",
    "audio_rate": "22050",
    "max_upload_bytes": str(128 * 1024 * 1024),
}

KEYS = {
    "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "ENTER": "Return", "ESC": "Escape", "SPACE": "space", "BACKSPACE": "BackSpace", "TAB": "Tab",
    "CAPSLOCK": "Caps_Lock", "NUMLOCK": "Num_Lock", "SCROLLLOCK": "Scroll_Lock", "PAUSE": "Pause",
    "PRINT": "Print", "INSERT": "Insert", "DELETE": "Delete", "HOME": "Home", "END": "End",
    "PAGEUP": "Prior", "PAGEDOWN": "Next",
    "CTRL": "Control_L", "ALT": "Alt_L", "SHIFT": "Shift_L",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4", "F5": "F5",
    "F6": "F6", "F7": "F7", "F8": "F8", "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
    "MINUS": "minus", "EQUALS": "equal", "LEFTBRACKET": "bracketleft", "RIGHTBRACKET": "bracketright",
    "BACKSLASH": "backslash", "SEMICOLON": "semicolon", "QUOTE": "apostrophe", "BACKQUOTE": "grave",
    "COMMA": "comma", "PERIOD": "period", "SLASH": "slash",
    "KP0": "KP_0", "KP1": "KP_1", "KP2": "KP_2", "KP3": "KP_3", "KP4": "KP_4",
    "KP5": "KP_5", "KP6": "KP_6", "KP7": "KP_7", "KP8": "KP_8", "KP9": "KP_9",
    "KP_PERIOD": "KP_Decimal", "KP_DIVIDE": "KP_Divide", "KP_MULTIPLY": "KP_Multiply",
    "KP_MINUS": "KP_Subtract", "KP_PLUS": "KP_Add", "KP_ENTER": "KP_Enter", "KP_EQUALS": "KP_Equal",
    **{character.upper(): character for character in "abcdefghijklmnopqrstuvwxyz0123456789"},
}
RAINBOW_CAT_COM = bytes.fromhex("b0b6e643b8a904e64288e0e642e4610c03e661b81300cd10b800a08ec031ffb003b900faf3aab401cd1674fab400cd1680fc4875f131ffb004b900faf3aaebe6")
VIDEO_WIDTH = 320
VIDEO_HEIGHT = 240
VIDEO_BYTES = VIDEO_WIDTH * VIDEO_HEIGHT * 2
VIDEO_TILE = 16
VIDEO_PACKET_HEADER = 16
VIDEO_KEYFRAME_INTERVAL = 2.0
POLL_HEADER = 16
VIDEO_SCALING_MODES = ("nearest", "linear-v", "crt-lite")


def read_config(path: Path) -> dict[str, str]:
    config = dict(DEFAULTS)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid configuration line: {line!r}")
        key, value = (item.strip() for item in line.split("=", 1))
        if key not in DEFAULTS:
            raise ValueError(f"unknown configuration key: {key}")
        config[key] = value
    return config


def safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) == ".":
        raise ValueError("file paths must be non-empty, relative POSIX paths")
    return path


def valid_digest(value: str) -> bool:
    return bool(SHA256_RE.fullmatch(value))


class StreamState:
    def __init__(self, config: dict[str, str], token: str):
        self.config = config
        self.token = token
        self.root = Path(config["state_root"])
        self.blobs = self.root / "blobs"
        self.sessions = self.root / "sessions"
        self.runtime = self.root / "runtime"
        for directory in (self.blobs, self.sessions, self.runtime):
            directory.mkdir(parents=True, exist_ok=True)
        self.max_upload_bytes = int(config["max_upload_bytes"])
        self.audio_rate = int(config["audio_rate"])
        self.lock = threading.RLock()
        # Input requests may arrive concurrently, but only one request may
        # spend CPU assembling media. Older waiters cheaply discard themselves
        # once a newer input revision has been accepted.
        self.media_lock = threading.Lock()
        self.active: dict[str, dict] = {}

    def blob_path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / digest

    def missing(self, blobs: list[dict]) -> list[str]:
        missing = []
        for entry in blobs:
            digest = entry.get("sha256") if isinstance(entry, dict) else None
            size = entry.get("size") if isinstance(entry, dict) else None
            if not isinstance(digest, str) or not valid_digest(digest):
                raise ValueError("every blob needs a lowercase SHA-256")
            if not isinstance(size, int) or size < 0 or size > self.max_upload_bytes:
                raise ValueError("invalid blob size")
            path = self.blob_path(digest)
            if not path.is_file() or path.stat().st_size != size:
                missing.append(digest)
        return missing

    def store_blob(self, digest: str, source, length: int) -> None:
        if not valid_digest(digest):
            raise ValueError("invalid SHA-256")
        if length < 0 or length > self.max_upload_bytes:
            raise ValueError("upload exceeds max_upload_bytes")
        destination = self.blob_path(digest)
        if destination.is_file() and destination.stat().st_size == length:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{digest}.{secrets.token_hex(8)}.part")
        hashed = hashlib.sha256()
        remaining = length
        try:
            with temporary.open("xb") as output:
                while remaining:
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        raise ValueError("truncated upload")
                    hashed.update(chunk)
                    output.write(chunk)
                    remaining -= len(chunk)
            if hashed.hexdigest() != digest:
                raise ValueError("upload SHA-256 does not match URL")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def start_session(self, request: dict) -> dict:
        game_id = request.get("game_id")
        executable = request.get("executable")
        files = request.get("files")
        video_scaling = request.get("video_scaling", "nearest")
        if video_scaling not in VIDEO_SCALING_MODES:
            video_scaling = "nearest"
        if not isinstance(game_id, str) or not SESSION_RE.fullmatch(game_id):
            raise ValueError("invalid game_id")
        if not isinstance(executable, str):
            raise ValueError("executable is required")
        executable_path = safe_relative_path(executable)
        if not isinstance(files, dict) or not files:
            raise ValueError("files must be a non-empty path-to-SHA-256 object")
        checked_files: dict[PurePosixPath, str] = {}
        for relative, digest in files.items():
            if not isinstance(relative, str) or not isinstance(digest, str) or not valid_digest(digest):
                raise ValueError("invalid session file manifest")
            checked_files[safe_relative_path(relative)] = digest
        if executable_path not in checked_files:
            raise ValueError("executable must be included in files")
        with self.lock:
            if self.active:
                raise RuntimeError("another DOSBox session is already active")
            unavailable = [digest for digest in checked_files.values() if not self.blob_path(digest).is_file()]
            if unavailable:
                raise ValueError("session references blobs absent from cache")
            session_id = f"{game_id}-{secrets.token_hex(6)}"
            session_dir = self.sessions / session_id
            game_dir = session_dir / "game"
            game_dir.mkdir(parents=True)
            for relative, digest in checked_files.items():
                target = game_dir.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(self.blob_path(digest), target)
                except OSError:
                    shutil.copyfile(self.blob_path(digest), target)
            config_path = session_dir / "dosbox.conf"
            config_path.write_text(self._dosbox_config(executable_path, self.audio_rate), encoding="utf-8")
            audio_path = session_dir / "audio-s16le-stereo.raw"
            audio_mode = self.config["audio_capture"]
            if audio_mode not in ("file", "loopback"):
                raise ValueError("audio_capture must be file or loopback")
            audio_fifo = session_dir / "audio-s16le-stereo.fifo"
            audio_stop = None
            audio_thread = None
            audio_process = None
            if audio_mode == "file":
                os.mkfifo(audio_fifo, 0o600)
                (session_dir / ".asoundrc").write_text(self._alsa_capture_config(audio_fifo), encoding="utf-8")
            log = (self.runtime / f"{session_id}.log").open("ab", buffering=0)
            display = self._next_display()
            # Debian's SDL 1.2 DOSBox build does not accept Xvfb's 8-bit visual.
            # This is server-only capture; the future Pi protocol remains 8-bit.
            xvfb = subprocess.Popen([self.config["xvfb"], display, "-screen", "0", "640x480x24", "-nolisten", "tcp"],
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            time.sleep(0.15)
            if xvfb.poll() is not None:
                log.close()
                raise RuntimeError("Xvfb failed to start; see session log")
            if audio_mode == "file":
                audio_stop = threading.Event()
                audio_thread = threading.Thread(target=self._audio_pump,
                                                args=(audio_fifo, audio_path, audio_stop), daemon=True)
                audio_thread.start()
            else:
                audio_process = subprocess.Popen(self._arecord_command(audio_path), stdout=log,
                                                 stderr=subprocess.STDOUT, start_new_session=True)
                time.sleep(0.05)
                if audio_process.poll() is not None:
                    log.close()
                    raise RuntimeError("ALSA loopback capture failed; see session log")
            environment = os.environ.copy()
            environment.update({"DISPLAY": display, "SDL_AUDIODRIVER": "alsa",
                                "AUDIODEV": "default" if audio_mode == "file" else self.config["audio_playback_device"],
                                "HOME": str(session_dir)})
            dosbox = subprocess.Popen([self.config["dosbox"], "-conf", str(config_path)], cwd=game_dir,
                                      env=environment, stdout=log, stderr=subprocess.STDOUT,
                                      start_new_session=True)
            self.active[session_id] = {"dosbox": dosbox, "xvfb": xvfb, "log": log,
                                       "display": display, "started": time.time(), "frames": []}
            self.active[session_id].update({"audio": audio_path, "audio_stop": audio_stop,
                                            "audio_thread": audio_thread, "audio_process": audio_process,
                                            "window": None, "held_keys": set(),
                                            "poll_stats": self._new_poll_stats(),
                                            "video_scaling": video_scaling})
            return self.session_status(session_id)

    def start_rainbow_cat(self, video_scaling: str = "nearest") -> dict:
        """Launch the built-in asset-free stream transport diagnostic."""
        digest = hashlib.sha256(RAINBOW_CAT_COM).hexdigest()
        self.store_blob(digest, io.BytesIO(RAINBOW_CAT_COM), len(RAINBOW_CAT_COM))
        status = self.start_session({"game_id": "rainbow-cat", "executable": "RAINBOW.COM",
                                     "files": {"RAINBOW.COM": digest}, "video_scaling": video_scaling})
        with self.lock:
            self.active[status["id"]]["diagnostic"] = True
        return status

    def _next_display(self) -> str:
        return f":{200 + (os.getpid() % 300)}"

    @staticmethod
    def _dosbox_config(executable: PurePosixPath, audio_rate: int) -> str:
        command = "\\".join(executable.parts)
        return """[sdl]\nfullscreen=false\noutput=surface\nusescancodes=false\n\n[dosbox]\nmachine=ega\nmemsize=8\n\n[cpu]\ncore=normal\ncycles=fixed 3000\n\n[mixer]\nnosound=false\nrate=%d\nblocksize=2048\nprebuffer=100\n\n[speaker]\npcspeaker=true\npcrate=%d\ntandy=off\ndisney=false\n\n[sblaster]\nsbtype=none\n\n[midi]\nmpu401=none\nmididevice=none\n\n[autoexec]\n@echo off\nmount c .\nc:\n%s\nexit\n""" % (audio_rate, audio_rate, command)

    @staticmethod
    def _alsa_capture_config(audio_path: Path) -> str:
        return """# Session-local, headless SDL/DOSBox audio sink.\npcm.pi286_capture {\n    type file\n    slave.pcm \"null\"\n    file \"%s\"\n    format \"raw\"\n}\npcm.!default pi286_capture\n""" % audio_path

    def _arecord_command(self, audio_path: Path) -> list[str]:
        return [self.config["arecord"], "-q", "-D", self.config["audio_capture_device"],
                "-f", "S16_LE", "-c", "2", "-r", str(self.audio_rate), "-t", "raw", str(audio_path)]

    def _audio_pump(self, fifo: Path, capture: Path, stop: threading.Event) -> None:
        """Drain the ALSA file FIFO at its actual PCM rate.

        A plain file lets the SDL audio thread run unbounded, which makes
        DOSBox race ahead and consumes disk rapidly. Keeping the FIFO reader
        paced gives the audio producer a finite kernel buffer and back-pressure.
        """
        bytes_per_second = self.audio_rate * 2 * 2  # S16LE stereo input
        descriptor = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        credit = 0.0
        previous = time.monotonic()
        try:
            with capture.open("wb") as output:
                while not stop.is_set():
                    now = time.monotonic()
                    credit += (now - previous) * bytes_per_second
                    previous = now
                    amount = min(4096, int(credit))
                    if amount < 4:
                        stop.wait(0.005)
                        continue
                    try:
                        data = os.read(descriptor, amount - amount % 4)
                    except BlockingIOError:
                        stop.wait(0.005)
                        continue
                    if data:
                        output.write(data)
                        output.flush()
                        credit -= len(data)
                    else:
                        stop.wait(0.005)
        finally:
            os.close(descriptor)

    def session_status(self, session_id: str) -> dict:
        with self.lock:
            item = self.active.get(session_id)
            if not item:
                raise KeyError(session_id)
            return {"id": session_id, "state": "running" if item["dosbox"].poll() is None else "exited",
                    "pid": item["dosbox"].pid, "frames": len(item["frames"]),
                    "audio_bytes": item["audio"].stat().st_size if item["audio"].exists() else 0,
                    "held_keys": sorted(item["held_keys"]),
                    "video_scaling": item.get("video_scaling", "nearest"),
                    "audio": f"/v1/sessions/{session_id}/audio?offset=0",
                    "log": f"/v1/sessions/{session_id}/log",
                    "poll_stats": self._poll_stats_snapshot(item["poll_stats"])}

    @staticmethod
    def _new_poll_stats() -> dict:
        return {"started_at": time.time(), "last_arrival": None, "requests": 0,
                "responses": 0, "stale": 0, "input_updates": 0, "failed": 0,
                "total_ms": [], "video_ms": [], "audio_ms": [], "arrival_gap_ms": [],
                "trace": []}

    @staticmethod
    def _poll_stats_snapshot(stats: dict) -> dict:
        def timing(name: str) -> dict:
            values = stats[name]
            return {"count": len(values), "avg": int(sum(values) / len(values)) if values else 0,
                    "min": min(values) if values else 0, "max": max(values) if values else 0}
        return {"requests": stats["requests"], "responses": stats["responses"],
                "stale": stats["stale"], "input_updates": stats["input_updates"],
                "failed": stats["failed"], "total_ms": timing("total_ms"),
                "video_ms": timing("video_ms"), "audio_ms": timing("audio_ms"),
                "arrival_gap_ms": timing("arrival_gap_ms"), "recent": list(stats["trace"])}

    def _record_poll(self, item: dict, revision: int, input_updated: bool,
                     started: float, video_started: float, audio_started: float,
                     result: str) -> None:
        """Keep a bounded timing trace for post-session transport diagnosis."""
        finished = time.monotonic()
        stats = item["poll_stats"]
        video_ms = int((audio_started - video_started) * 1000)
        audio_ms = int((finished - audio_started) * 1000)
        total_ms = int((finished - started) * 1000)
        for name, value in (("total_ms", total_ms), ("video_ms", video_ms), ("audio_ms", audio_ms)):
            stats[name].append(value)
            del stats[name][:-2048]
        if result == "response":
            stats["responses"] += 1
        elif result == "stale":
            stats["stale"] += 1
        else:
            stats["failed"] += 1
        trace = {"revision": revision, "input_updated": input_updated, "result": result,
                 "gap_ms": stats["arrival_gap_ms"][-1] if stats["arrival_gap_ms"] else 0,
                 "video_ms": video_ms, "audio_ms": audio_ms, "total_ms": total_ms}
        stats["trace"].append(trace)
        del stats["trace"][:-32]

    def _persist_poll_stats(self, session_id: str, item: dict) -> None:
        path = self.runtime / f"{session_id}-poll-stats.json"
        path.write_text(json.dumps({"session": session_id,
                                    "ended_at": time.time(),
                                    "poll_stats": self._poll_stats_snapshot(item["poll_stats"])},
                                   indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def audio_chunk(self, session_id: str, output_offset: int) -> tuple[bytes, int]:
        if output_offset < 0 or output_offset % 2:
            raise ValueError("audio offset must be a non-negative multiple of two")
        with self.lock:
            item = self.active.get(session_id)
            if not item:
                raise KeyError(session_id)
            path = item["audio"]
            diagnostic = item.get("diagnostic", False)
        if diagnostic:
            return self._diagnostic_audio(output_offset)
        if not path.exists():
            return b"", output_offset
        # SDL's ALSA backend writes DOSBox's S16LE stereo mixer stream through
        # the session-local ALSA file PCM above. PC Speaker output is mono;
        # use its left channel directly instead of averaging channels, because
        # a phase difference in a broader DOSBox mix sounds like a false echo.
        source_offset = output_offset * 2
        with path.open("rb") as source:
            source.seek(source_offset)
            raw = source.read(65536 * 2)
        raw = raw[:len(raw) // 4 * 4]
        mono = bytearray(len(raw) // 2)
        for index in range(0, len(raw), 4):
            left, _right = struct.unpack_from("<hh", raw, index)
            struct.pack_into("<h", mono, index // 2, left)
        return bytes(mono), output_offset + len(mono)

    def _diagnostic_audio(self, output_offset: int) -> tuple[bytes, int]:
        """Generate a stable audible reference independent of DOSBox audio."""
        samples = 4096
        first_sample = output_offset // 2
        output = bytearray(samples * 2)
        for index in range(samples):
            # Two soft tones make drop-outs and incorrect playback rate obvious.
            phase = (first_sample + index) / self.audio_rate
            value = int(6500 * math.sin(2 * math.pi * 440 * phase) +
                        2500 * math.sin(2 * math.pi * 660 * phase))
            struct.pack_into("<h", output, index * 2, value)
        return bytes(output), output_offset + len(output)

    def audio_source_chunk(self, session_id: str, offset: int) -> tuple[bytes, int]:
        """Return a bounded raw ALSA capture chunk for authenticated diagnostics."""
        if offset < 0 or offset % 4:
            raise ValueError("audio source offset must be a non-negative frame boundary")
        with self.lock:
            item = self.active.get(session_id)
            if not item:
                raise KeyError(session_id)
            path = item["audio"]
        if not path.exists():
            return b"", offset
        with path.open("rb") as source:
            source.seek(offset)
            raw = source.read(65536)
        raw = raw[:len(raw) // 4 * 4]
        return raw, offset + len(raw)

    def input_events(self, session_id: str, events: list[dict]) -> dict:
        if not isinstance(events, list) or not events or len(events) > 32:
            raise ValueError("events must contain between one and 32 key events")
        checked = []
        for event in events:
            if not isinstance(event, dict) or set(event) != {"key", "pressed"}:
                raise ValueError("each event must contain only key and pressed")
            key, pressed = event["key"], event["pressed"]
            if not isinstance(key, str) or key not in KEYS or not isinstance(pressed, bool):
                raise ValueError("unsupported input key or state")
            checked.append((key, pressed))
        with self.lock:
            item = self.active.get(session_id)
            if not item or item["dosbox"].poll() is not None:
                raise KeyError(session_id)
            window = item["window"] or self._find_dosbox_window(item["display"])
            if not window:
                raise RuntimeError("DOSBox input window is not ready")
            item["window"] = window
            for key, pressed in checked:
                if pressed == (key in item["held_keys"]):
                    continue
                command = "keydown" if pressed else "keyup"
                result = subprocess.run([self.config["xdotool"], command, "--window", str(window), KEYS[key]],
                                        env=dict(os.environ, DISPLAY=item["display"]), stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, timeout=2)
                if result.returncode:
                    item["window"] = None
                    raise RuntimeError("XTEST input injection failed")
                if pressed:
                    item["held_keys"].add(key)
                else:
                    item["held_keys"].discard(key)
            return {"accepted": len(checked), "held_keys": sorted(item["held_keys"])}

    def poll(self, session_id: str, request: dict) -> bytes | None:
        """Apply the newest complete input state and return multiplexed media.

        A newer request supersedes an older in-flight poll. The latter may have
        captured a frame already, but it must not send stale media to a client
        that has moved on to a newer input revision.
        """
        if not isinstance(request, dict):
            raise ValueError("poll object required")
        revision = request.get("input_revision")
        held = request.get("held_keys")
        video_seq = request.get("video_seq", 0)
        audio_offset = request.get("audio_offset", 0)
        if not isinstance(revision, int) or revision < 0 or not isinstance(video_seq, int) or video_seq < 0:
            raise ValueError("invalid poll revision")
        if not isinstance(audio_offset, int) or audio_offset < 0 or audio_offset % 2:
            raise ValueError("invalid poll audio offset")
        if not isinstance(held, list) or len(held) > 64 or any(not isinstance(key, str) or key not in KEYS for key in held):
            raise ValueError("invalid held key state")
        desired = set(held)
        started = time.monotonic()
        with self.lock:
            item = self.active.get(session_id)
            if not item or item["dosbox"].poll() is not None:
                raise KeyError(session_id)
            stats = item.setdefault("poll_stats", self._new_poll_stats())
            previous_arrival = stats["last_arrival"]
            stats["last_arrival"] = max(previous_arrival or started, started)
            stats["requests"] += 1
            if previous_arrival is not None:
                stats["arrival_gap_ms"].append(max(0, int((started - previous_arrival) * 1000)))
                del stats["arrival_gap_ms"][:-2048]
            input_updated = revision >= item.get("poll_revision", -1)
            if revision >= item.get("poll_revision", -1):
                self._sync_held_keys(item, desired)
                item["poll_revision"] = revision
                stats["input_updates"] += 1
        with self.media_lock:
            with self.lock:
                item = self.active.get(session_id)
                if not item or revision < item.get("poll_revision", -1):
                    if item:
                        now = time.monotonic()
                        self._record_poll(item, revision, input_updated, started, now, now, "stale")
                    return None
                force_keyframe = video_seq != item.get("video_sequence", 0)
            video_started = time.monotonic()
            video, _sequence, _capture_ms = self.video_frame(session_id, force_keyframe)
            audio_started = time.monotonic()
            with self.lock:
                item = self.active.get(session_id)
                if not item or revision < item.get("poll_revision", -1):
                    if item:
                        # Do not generate PCM for a response the client has already superseded.
                        self._record_poll(item, revision, input_updated, started, video_started, audio_started, "stale")
                    return None
            audio, next_audio = self.audio_chunk(session_id, audio_offset)
            with self.lock:
                item = self.active.get(session_id)
                if not item or revision < item.get("poll_revision", -1):
                    if item:
                        self._record_poll(item, revision, input_updated, started, video_started, audio_started, "stale")
                    return None
                self._record_poll(item, revision, input_updated, started, video_started, audio_started, "response")
            return struct.pack(">4sIII", b"P2P1", len(video), len(audio), next_audio) + video + audio

    def _sync_held_keys(self, item: dict, desired: set[str]) -> None:
        # The first media poll normally has an empty snapshot. It must not wait
        # for DOSBox's X window merely to confirm that no key needs changing.
        if desired == item["held_keys"]:
            return
        window = item["window"] or self._find_dosbox_window(item["display"])
        if not window:
            raise RuntimeError("DOSBox input window is not ready")
        item["window"] = window
        for key in item["held_keys"] - desired:
            self._inject_key(item, window, key, False)
        for key in desired - item["held_keys"]:
            self._inject_key(item, window, key, True)
        item["held_keys"] = desired

    def _inject_key(self, item: dict, window: str, key: str, pressed: bool) -> None:
        result = subprocess.run([self.config["xdotool"], "keydown" if pressed else "keyup", "--window", str(window), KEYS[key]],
                                env=dict(os.environ, DISPLAY=item["display"]), stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, timeout=2)
        if result.returncode:
            item["window"] = None
            raise RuntimeError("XTEST input injection failed")

    def _find_dosbox_window(self, display: str) -> str | None:
        result = subprocess.run([self.config["xdotool"], "search", "--onlyvisible", "--name", "DOSBox"],
                                env=dict(os.environ, DISPLAY=display), stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=2)
        if result.returncode:
            return None
        windows = result.stdout.split()
        return windows[-1] if windows else None

    def _release_all_keys(self, item: dict) -> None:
        window = item.get("window")
        if not window:
            return
        for key in list(item["held_keys"]):
            subprocess.run([self.config["xdotool"], "keyup", "--window", str(window), KEYS[key]],
                           env=dict(os.environ, DISPLAY=item["display"]), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=2)
        item["held_keys"].clear()

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
                                               item.get("video_scaling", "nearest"))
                keyframe = force_keyframe or not item.get("video_previous") or \
                    time.monotonic() - item.get("video_last_keyframe", 0.0) >= VIDEO_KEYFRAME_INTERVAL
                packet, keyframe = self._video_packet(frame, item.get("video_previous"),
                                                       item["video_sequence"], 0, keyframe)
                item["video_previous"] = frame
                if keyframe:
                    item["video_last_keyframe"] = time.monotonic()
                return packet, item["video_sequence"], 0
            temporary = self.runtime / f"{session_id}-video-{secrets.token_hex(4)}.xwd"
            try:
                subprocess.run([self.config["xwd"], "-silent", "-root", "-display", item["display"], "-out", str(temporary)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3, check=True)
                frame = self._xwd_to_rgb565(temporary.read_bytes(), item.get("video_scaling", "nearest"))
                item["video_sequence"] = item.get("video_sequence", 0) + 1
                capture_ms = int((time.monotonic() - started) * 1000)
                keyframe = force_keyframe or not item.get("video_previous") or \
                    time.monotonic() - item.get("video_last_keyframe", 0.0) >= VIDEO_KEYFRAME_INTERVAL
                packet, keyframe = self._video_packet(frame, item.get("video_previous"),
                                                       item["video_sequence"], capture_ms, keyframe)
                item["video_previous"] = frame
                if keyframe:
                    item["video_last_keyframe"] = time.monotonic()
                return packet, item["video_sequence"], capture_ms
            finally:
                temporary.unlink(missing_ok=True)

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
        return StreamState._apply_crt_lite(bytes(output), video_scaling)

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
        if width != 640 or height != 480 or bits_per_pixel not in (24, 32) or byte_order != 0 or bytes_per_line != 640 * 4:
            raise ValueError("unexpected Xvfb image format")
        pixels = header_size + header[19] * 12
        if pixels + bytes_per_line * height > len(source):
            raise ValueError("truncated XWD pixels")
        # Xvfb uses 24-bit TrueColor B,G,R pixels.  Its scanlines are padded to
        # 2560 bytes, but individual pixels still occupy three bytes (not four).
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
                offset = row + x * 6
                blue, green, red = source[offset], source[offset + 1], source[offset + 2]
                if video_scaling in ("linear-v", "crt-lite") and remainder:
                    next_offset = next_row + x * 6
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
    def _apply_crt_lite(frame: bytes, video_scaling: str) -> bytes:
        if video_scaling != "crt-lite":
            return frame
        output = bytearray(frame)
        for y in range(1, VIDEO_HEIGHT, 2):
            for x in range(VIDEO_WIDTH):
                offset = (y * VIDEO_WIDTH + x) * 2
                color = output[offset] | output[offset + 1] << 8
                color = ((color & 0xf800) * 7 // 8 & 0xf800) | ((color & 0x07e0) * 7 // 8 & 0x07e0) | ((color & 0x001f) * 7 // 8 & 0x001f)
                output[offset], output[offset + 1] = color & 0xff, color >> 8
        return bytes(output)

    def frame_path(self, session_id: str, frame_id: str) -> Path:
        if not re.fullmatch(r"[0-9]{4}\.xwd", frame_id):
            raise KeyError(session_id)
        with self.lock:
            item = self.active.get(session_id)
            if not item:
                raise KeyError(session_id)
            frame = self.runtime / f"{session_id}-{frame_id}"
            if frame not in item["frames"]:
                raise KeyError(session_id)
            return frame

    def stop_session(self, session_id: str) -> None:
        with self.lock:
            item = self.active.pop(session_id, None)
        if not item:
            raise KeyError(session_id)
        self._persist_poll_stats(session_id, item)
        print("pi286 stream session metrics " + json.dumps({"session": session_id,
                                                             "poll_stats": self._poll_stats_snapshot(item["poll_stats"])},
                                                            sort_keys=True), flush=True)
        self._release_all_keys(item)
        for name in ("dosbox", "xvfb", "audio_process"):
            process = item[name]
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        if item["audio_stop"]:
            item["audio_stop"].set()
        deadline = time.monotonic() + 3
        for name in ("dosbox", "xvfb", "audio_process"):
            process = item[name]
            if not process:
                continue
            remaining = deadline - time.monotonic()
            try:
                process.wait(max(0, remaining))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        if item["audio_thread"]:
            item["audio_thread"].join(timeout=1)
        item["log"].close()


def make_handler(state: StreamState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pi286-stream/0.1"

        def log_message(self, format, *args):
            print("%s - %s" % (self.address_string(), format % args), flush=True)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            return header.startswith("Bearer ") and hmac.compare_digest(header[7:], state.token)

        def _json(self, status, value):
            body = json.dumps(value, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path):
            size = path.stat().st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/x-xwindowdump")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with path.open("rb") as source:
                shutil.copyfileobj(source, self.wfile)

        def _audio(self, session_id: str, offset: int):
            body, next_offset = state.audio_chunk(session_id, offset)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"audio/L16;rate={state.audio_rate};channels=1")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Pi286-Audio-Offset", str(offset))
            self.send_header("X-Pi286-Audio-Next-Offset", str(next_offset))
            self.end_headers()
            self.wfile.write(body)

        def _audio_source(self, session_id: str, offset: int):
            body, next_offset = state.audio_source_chunk(session_id, offset)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"audio/L16;rate={state.audio_rate};channels=2")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Pi286-Audio-Source-Offset", str(offset))
            self.send_header("X-Pi286-Audio-Source-Next-Offset", str(next_offset))
            self.end_headers()
            self.wfile.write(body)

        def _video(self, session_id: str, force_keyframe: bool):
            body, sequence, capture_ms = state.video_frame(session_id, force_keyframe)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-pi286-video-v1")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Pi286-Video-Width", str(VIDEO_WIDTH))
            self.send_header("X-Pi286-Video-Height", str(VIDEO_HEIGHT))
            self.send_header("X-Pi286-Video-Sequence", str(sequence))
            self.send_header("X-Pi286-Capture-Ms", str(capture_ms))
            self.end_headers()
            self.wfile.write(body)

        def _poll(self, session_id: str, request: dict):
            try:
                body = state.poll(session_id, request)
                if body is None:
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-pi286-poll-v1")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # A newer Pi poll intentionally closes the older connection.
                return

        def _request_json(self):
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if length < 0 or length > state.max_upload_bytes:
                raise ValueError("invalid request length")
            return json.loads(self.rfile.read(length))

        def _check_auth(self):
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
                return False
            return True

        def do_GET(self):
            if not self._check_auth(): return
            parsed = urlsplit(self.path)
            path = parsed.path
            try:
                if path == "/v1/status":
                    self._json(HTTPStatus.OK, {"api": 1, "active_sessions": len(state.active),
                                                "media_transport": "not implemented"})
                elif re.fullmatch(r"/v1/sessions/[^/]+/frames/[0-9]{4}\.xwd", path):
                    parts = path.split("/")
                    self._file(state.frame_path(parts[3], parts[5]))
                elif re.fullmatch(r"/v1/sessions/[^/]+/audio", path):
                    values = parse_qs(parsed.query, strict_parsing=True)
                    offset = int(values.get("offset", ["0"])[0])
                    self._audio(path.split("/")[3], offset)
                elif re.fullmatch(r"/v1/sessions/[^/]+/audio-source", path):
                    values = parse_qs(parsed.query, strict_parsing=True)
                    offset = int(values.get("offset", ["0"])[0])
                    self._audio_source(path.split("/")[3], offset)
                elif re.fullmatch(r"/v1/sessions/[^/]+/video", path):
                    values = parse_qs(parsed.query, strict_parsing=True) if parsed.query else {}
                    force_keyframe = values.get("keyframe", ["0"])[0] == "1"
                    self._video(path.split("/")[3], force_keyframe)
                elif path.startswith("/v1/sessions/") and path.endswith("/log"):
                    session_id = path.split("/")[3]
                    self._json(HTTPStatus.NOT_IMPLEMENTED, {"error": "log retrieval is not exposed yet", "id": session_id})
                elif path.startswith("/v1/sessions/"):
                    self._json(HTTPStatus.OK, state.session_status(path.split("/")[3]))
                else: self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except KeyError: self._json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})
            except ValueError as error: self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_POST(self):
            if not self._check_auth(): return
            try:
                request = self._request_json()
                if self.path == "/v1/manifest":
                    if not isinstance(request, dict) or not isinstance(request.get("blobs"), list): raise ValueError("blobs array required")
                    self._json(HTTPStatus.OK, {"missing": state.missing(request["blobs"])})
                elif self.path == "/v1/sessions":
                    self._json(HTTPStatus.CREATED, state.start_session(request))
                elif self.path == "/v1/diagnostics/rainbow-cat":
                    self._json(HTTPStatus.CREATED, state.start_rainbow_cat(request.get("video_scaling", "nearest")))
                elif re.fullmatch(r"/v1/sessions/[^/]+/frames", self.path):
                    self._json(HTTPStatus.CREATED, state.capture_frame(self.path.split("/")[3]))
                elif re.fullmatch(r"/v1/sessions/[^/]+/input", self.path):
                    self._json(HTTPStatus.OK, state.input_events(self.path.split("/")[3], request.get("events")))
                elif re.fullmatch(r"/v2/sessions/[^/]+/poll", self.path):
                    self._poll(self.path.split("/")[3], request)
                else: self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (ValueError, json.JSONDecodeError) as error: self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except RuntimeError as error: self._json(HTTPStatus.CONFLICT, {"error": str(error)})
            except (subprocess.SubprocessError, OSError) as error: self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

        def do_PUT(self):
            if not self._check_auth(): return
            digest = self.path.removeprefix("/v1/blobs/")
            if not self.path.startswith("/v1/blobs/") or "/" in digest:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"}); return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                state.store_blob(digest, self.rfile, length)
                self._json(HTTPStatus.CREATED, {"sha256": digest})
            except (ValueError, OSError) as error: self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_DELETE(self):
            if not self._check_auth(): return
            if not self.path.startswith("/v1/sessions/") or "/" in self.path[len("/v1/sessions/"):]:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"}); return
            try:
                state.stop_session(self.path.rsplit("/", 1)[-1])
                self._json(HTTPStatus.OK, {"stopped": True})
            except KeyError: self._json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = read_config(args.config)
    token = Path(config["token_file"]).read_text(encoding="utf-8").strip()
    if len(token) < 32: raise SystemExit("token must contain at least 32 characters")
    state = StreamState(config, token)
    server = ThreadingHTTPServer((config["bind"], int(config["port"])), make_handler(state))
    print(f"pi286 stream backend listening on {config['bind']}:{config['port']}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
