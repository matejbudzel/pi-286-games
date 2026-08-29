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
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

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
    "max_upload_bytes": str(128 * 1024 * 1024),
}


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
        self.lock = threading.RLock()
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
            config_path.write_text(self._dosbox_config(executable_path), encoding="utf-8")
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
            environment = os.environ.copy()
            environment.update({"DISPLAY": display, "SDL_AUDIODRIVER": "dummy", "HOME": str(session_dir)})
            dosbox = subprocess.Popen([self.config["dosbox"], "-conf", str(config_path)], cwd=game_dir,
                                      env=environment, stdout=log, stderr=subprocess.STDOUT,
                                      start_new_session=True)
            self.active[session_id] = {"dosbox": dosbox, "xvfb": xvfb, "log": log,
                                       "display": display, "started": time.time(), "frames": []}
            return self.session_status(session_id)

    def _next_display(self) -> str:
        return f":{200 + (os.getpid() % 300)}"

    @staticmethod
    def _dosbox_config(executable: PurePosixPath) -> str:
        command = "\\".join(executable.parts)
        return """[sdl]\nfullscreen=false\noutput=surface\nusescancodes=true\n\n[mixer]\nnosound=true\n\n[autoexec]\n@echo off\nmount c .\nc:\n%s\nexit\n""" % command

    def session_status(self, session_id: str) -> dict:
        with self.lock:
            item = self.active.get(session_id)
            if not item:
                raise KeyError(session_id)
            return {"id": session_id, "state": "running" if item["dosbox"].poll() is None else "exited",
                    "pid": item["dosbox"].pid, "frames": len(item["frames"]),
                    "log": f"/v1/sessions/{session_id}/log"}

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

    def frame_path(self, session_id: str, frame_id: str) -> Path:
        if not re.fullmatch(r"[0-9]{4}\\.xwd", frame_id):
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
        for name in ("dosbox", "xvfb"):
            process = item[name]
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + 3
        for name in ("dosbox", "xvfb"):
            process = item[name]
            remaining = deadline - time.monotonic()
            try:
                process.wait(max(0, remaining))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
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
            try:
                if self.path == "/v1/status":
                    self._json(HTTPStatus.OK, {"api": 1, "active_sessions": len(state.active),
                                                "media_transport": "not implemented"})
                elif re.fullmatch(r"/v1/sessions/[^/]+/frames/[0-9]{4}\.xwd", self.path):
                    parts = self.path.split("/")
                    self._file(state.frame_path(parts[3], parts[5]))
                elif self.path.startswith("/v1/sessions/") and self.path.endswith("/log"):
                    session_id = self.path.split("/")[3]
                    self._json(HTTPStatus.NOT_IMPLEMENTED, {"error": "log retrieval is not exposed yet", "id": session_id})
                elif self.path.startswith("/v1/sessions/"):
                    self._json(HTTPStatus.OK, state.session_status(self.path.split("/")[3]))
                else: self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except KeyError: self._json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})

        def do_POST(self):
            if not self._check_auth(): return
            try:
                request = self._request_json()
                if self.path == "/v1/manifest":
                    if not isinstance(request, dict) or not isinstance(request.get("blobs"), list): raise ValueError("blobs array required")
                    self._json(HTTPStatus.OK, {"missing": state.missing(request["blobs"])})
                elif self.path == "/v1/sessions":
                    self._json(HTTPStatus.CREATED, state.start_session(request))
                elif re.fullmatch(r"/v1/sessions/[^/]+/frames", self.path):
                    self._json(HTTPStatus.CREATED, state.capture_frame(self.path.split("/")[3]))
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
