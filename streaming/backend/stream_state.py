"""DOSBox session lifecycle, audio transport, input, and polling."""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import signal
import struct
import subprocess
import threading
import time
from pathlib import Path, PurePosixPath

from streaming.backend.stream_models import (DEFAULTS, KEYS, PCM_CHUNK_BYTES, RAINBOW_CAT_COM, VIDEO_HEIGHT, VIDEO_SCALING_MODES, load_games, safe_relative_path, GameDefinition)
from streaming.backend.stream_video import VideoMixin


class StreamState(VideoMixin):
    def __init__(self, config: dict[str, str], token: str):
        self.config = config
        self.token = token
        self.root = Path(config["state_root"])
        self.sessions = self.root / "sessions"
        self.runtime = self.root / "runtime"
        for directory in (self.sessions, self.runtime):
            directory.mkdir(parents=True, exist_ok=True)
        self.audio_rate = int(config["audio_rate"])
        self.session_idle_seconds = float(config["session_idle_seconds"])
        if self.session_idle_seconds <= 0:
            raise ValueError("session_idle_seconds must be positive")
        self.lock = threading.RLock()
        # Input requests may arrive concurrently, but only one request may
        # spend CPU assembling media. Older waiters cheaply discard themselves
        # once a newer input revision has been accepted.
        self.media_lock = threading.Lock()
        self.active: dict[str, dict] = {}
        self.games = load_games(Path(config["game_definitions_root"]))

    def game_catalog(self, capabilities: dict | None = None) -> dict:
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        keyboard = bool(capabilities.get("keyboard"))
        dance_pad = bool(capabilities.get("dance_pad"))
        def pre_game(game: GameDefinition) -> dict:
            return {"pad_keys": list(game.pad_keys), "pad_labels": list(game.pad_labels),
                    "keyboard": keyboard, "dance_pad": dance_pad,
                    "launch_hint": "Stlač SPACE alebo START pre spustenie" if keyboard and dance_pad else
                                   "Stlač SPACE pre spustenie" if keyboard else "Stlač START pre spustenie" if dance_pad else
                                   "Pripoj klávesnicu alebo dance pad"}
        return {"games": [{"id": game.game_id, "name": game.name, "pre_game": pre_game(game)}
                          for game in sorted(self.games.values(), key=lambda item: item.name.casefold())]}

    def start_session(self, request: dict) -> dict:
        game_id = request.get("game_id")
        video_scaling = request.get("video_scaling", "nearest")
        transport = request.get("transport", "poll")
        if video_scaling not in VIDEO_SCALING_MODES:
            video_scaling = "nearest"
        if transport not in ("poll", "websocket"):
            raise ValueError("transport must be poll or websocket")
        diagnostic = game_id == "rainbow-cat"
        if diagnostic:
            game = GameDefinition("rainbow-cat", "Dúhová mačka", "", "RAINBOW.COM",
                                  Path(), ("LEFT", "DOWN", "UP", "RIGHT", "", "", "", "", "ENTER"),
                                  ("", "", "", "", "", "", "", "", ""))
            game_dir = self.runtime / "rainbow-cat"
            game_dir.mkdir(exist_ok=True)
            (game_dir / "RAINBOW.COM").write_bytes(RAINBOW_CAT_COM)
            executable_path = PurePosixPath("RAINBOW.COM")
        else:
            if not isinstance(game_id, str) or game_id not in self.games:
                raise ValueError("neznáma hra")
            game = self.games[game_id]
            game_dir = Path(self.config["game_data_root"]) / game.data_dir
            executable_path = self._find_game_executable(game_dir, game.executable)
            if executable_path is None:
                raise RuntimeError("Herné dáta pre túto hru nie sú na serveri pripravené.")
        with self.lock:
            if self.active:
                raise RuntimeError("another DOSBox session is already active")
            session_id = f"{game_id}-{secrets.token_hex(6)}"
            session_dir = self.sessions / session_id
            session_dir.mkdir(parents=True)
            config_path = session_dir / "dosbox.conf"
            config_path.write_text(self._dosbox_config(executable_path, self.audio_rate, game), encoding="utf-8")
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
            framebuffer_directory = session_dir / self.config["xvfb_fbdir"]
            framebuffer_directory.mkdir(mode=0o700)
            # SDL 1.2 DOSBox 0.74 requires a 640x480 X root. Its smaller
            # window mode is positioned outside the root by its legacy scaler.
            xvfb = subprocess.Popen([self.config["xvfb"], display, "-screen", "0", "640x480x24",
                                     "-fbdir", str(framebuffer_directory), "-nolisten", "tcp"],
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
                                            "game": game,
                                            "diagnostic": diagnostic,
                                            "poll_stats": self._new_poll_stats(),
                                            "video_scaling": video_scaling,
                                            "transport": transport,
                                            "last_client_activity": time.monotonic(),
                                            "framebuffer": framebuffer_directory / "Xvfb_screen0"})
            return self.session_status(session_id)

    @staticmethod
    def _find_game_executable(game_dir: Path, configured: str) -> PurePosixPath | None:
        """Find a configured DOS executable, including one archive wrapper level.

        The server owns the extracted game data.  Accepting a single matching
        basename keeps game.conf concise while still supporting the common
        ``GAME/GAME.EXE`` archive layout.  Ambiguous layouts are rejected.
        """
        expected = safe_relative_path(configured.replace("\\", "/"))
        direct = game_dir.joinpath(*expected.parts)
        if direct.is_file():
            return expected
        if len(expected.parts) != 1 or not game_dir.is_dir():
            return None
        matches = [path for path in game_dir.rglob("*")
                   if path.is_file() and path.name.casefold() == expected.name.casefold()]
        if len(matches) != 1:
            return None
        return PurePosixPath(matches[0].relative_to(game_dir).as_posix())

    def start_rainbow_cat(self, video_scaling: str = "nearest", transport: str = "poll") -> dict:
        """Launch the built-in asset-free stream transport diagnostic."""
        return self.start_session({"game_id": "rainbow-cat", "video_scaling": video_scaling,
                                   "transport": transport})

    def _next_display(self) -> str:
        return f":{200 + (os.getpid() % 300)}"

    @staticmethod
    def _dosbox_config(executable: PurePosixPath, audio_rate: int, game: GameDefinition | None = None) -> str:
        # Archives commonly wrap a game in one directory. DOS programs often
        # load data relative to the current DOS directory, so entering that
        # directory is required before launching the executable.
        directory = "\\".join(executable.parent.parts)
        change_directory = "cd \\%s\n" % directory if directory else ""
        command = executable.name
        game_config = game.dosbox_conf.read_text(encoding="utf-8") if game and game.dosbox_conf.is_file() else ""
        return """[sdl]\nfullscreen=false\noutput=surface\nusescancodes=false\n\n[dosbox]\nmachine=ega\nmemsize=8\n\n[cpu]\ncore=normal\ncycles=fixed 3000\n\n[mixer]\nnosound=false\nrate=%d\nblocksize=2048\nprebuffer=100\n\n[speaker]\npcspeaker=true\npcrate=%d\ntandy=off\ndisney=false\n\n[sblaster]\nsbtype=none\n\n[midi]\nmpu401=none\nmididevice=none\n\n%s\n[autoexec]\n@echo off\nmount c .\nc:\n%s%s\nexit\n""" % (audio_rate, audio_rate, game_config, change_directory, command)

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
                    "transport": item.get("transport", "poll"),
                    "audio": f"/v1/sessions/{session_id}/audio?offset=0",
                    "log": f"/v1/sessions/{session_id}/log",
                    "poll_stats": self._poll_stats_snapshot(item["poll_stats"])}

    def touch_session(self, session_id: str) -> None:
        """Record real client activity, rather than internal media work."""
        with self.lock:
            item = self.active.get(session_id)
            if not item:
                raise KeyError(session_id)
            item["last_client_activity"] = time.monotonic()

    def reap_idle_sessions(self) -> None:
        """Bound sessions whose client disappeared without a clean DELETE."""
        now = time.monotonic()
        with self.lock:
            expired = [session_id for session_id, item in self.active.items()
                       if now - item.get("last_client_activity", now) >= self.session_idle_seconds]
        for session_id in expired:
            print(f"pi286 stream session idle timeout: {session_id}", flush=True)
            try:
                self.stop_session(session_id)
            except KeyError:
                pass

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

    def record_browser_stats(self, session_id: str, stats: dict) -> dict:
        """Persist bounded client-side timing aggregates beside server metrics."""
        if not isinstance(stats, dict):
            raise ValueError("browser statistics must be an object")
        try:
            encoded = json.dumps(stats, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            raise ValueError("browser statistics must be JSON values") from error
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError("browser statistics are too large")
        with self.lock:
            item = self.active.get(session_id)
            # `pagehide` can race the WebSocket close. A session that has just
            # stopped already has its server metrics persisted, so still pair
            # this late browser report with that known session.
            if item is None and not (self.runtime / f"{session_id}-poll-stats.json").is_file():
                raise KeyError(session_id)
            if item is not None:
                item["last_client_activity"] = time.monotonic()
        path = self.runtime / f"{session_id}-browser-stats.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"session": session_id, "received_at": time.time(),
                                         "browser_stats": stats}, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        temporary.replace(path)
        return {"stored": True}

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
            # Keep media packets short enough that the client can acknowledge
            # PCM consumption precisely. A multi-second chunk combined with a
            # small browser audio queue makes discarded data sound like gaps.
            raw = source.read(PCM_CHUNK_BYTES * 2)
        raw = raw[:len(raw) // 4 * 4]
        mono = bytearray(len(raw) // 2)
        for index in range(0, len(raw), 4):
            left, _right = struct.unpack_from("<hh", raw, index)
            struct.pack_into("<h", mono, index // 2, left)
        return bytes(mono), output_offset + len(mono)

    def _diagnostic_audio(self, output_offset: int) -> tuple[bytes, int]:
        """Generate a stable audible reference independent of DOSBox audio."""
        # Match normal transport packet duration (~93 ms at 22.05 kHz) so the
        # diagnostic exercises the same browser jitter-buffer behaviour.
        samples = PCM_CHUNK_BYTES // 2
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
        held = request.get("keyboard_held", request.get("held_keys"))
        pad_held = request.get("dance_pad_held", [])
        video_seq = request.get("video_seq", 0)
        audio_offset = request.get("audio_offset", 0)
        if not isinstance(revision, int) or revision < 0 or not isinstance(video_seq, int) or video_seq < 0:
            raise ValueError("invalid poll revision")
        if not isinstance(audio_offset, int) or audio_offset < 0 or audio_offset % 2:
            raise ValueError("invalid poll audio offset")
        if not isinstance(held, list) or len(held) > 64 or any(not isinstance(key, str) or key not in KEYS for key in held):
            raise ValueError("invalid held key state")
        if not isinstance(pad_held, list) or any(not isinstance(button, int) or button < 0 or button > 8 for button in pad_held):
            raise ValueError("invalid dance pad state")
        started = time.monotonic()
        with self.lock:
            item = self.active.get(session_id)
            if not item or item["dosbox"].poll() is not None:
                raise KeyError(session_id)
            stats = item.setdefault("poll_stats", self._new_poll_stats())
            desired = set(held)
            game = item.get("game")
            if game:
                desired.update(game.pad_keys[button] for button in pad_held if game.pad_keys[button])
            previous_arrival = stats["last_arrival"]
            stats["last_arrival"] = max(previous_arrival or started, started)
            stats["requests"] += 1
            if previous_arrival is not None:
                stats["arrival_gap_ms"].append(max(0, int((started - previous_arrival) * 1000)))
                del stats["arrival_gap_ms"][:-2048]
            input_updated = revision >= item.get("poll_revision", -1)
            if revision >= item.get("poll_revision", -1):
                try:
                    self._sync_held_keys(item, desired)
                except RuntimeError as error:
                    # A first pad/keyboard press can beat DOSBox publishing
                    # its X window. Keep the session alive and retry its
                    # complete held snapshot on the next client update.
                    if str(error) != "DOSBox input window is not ready":
                        raise
                    now = time.monotonic()
                    self._record_poll(item, revision, input_updated, started, now, now, "input-wait")
                    return None
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
