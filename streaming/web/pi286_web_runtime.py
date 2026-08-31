#!/usr/bin/env python3
"""Small unauthenticated LAN web presenter for the Pi286 streaming experiment.

The browser never receives the LXC bearer token or reads private game files.
This process runs on the trusted development host, serves the UI, uploads game
assets when needed, and forwards the existing binary poll protocol.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import secrets
import shlex
import socket
import select
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launcher.launcher import discover, values, video_scaling
from streaming.client.remote_api import RemoteBackend, RemoteProtocolError, RemoteUnavailable
from streaming import websocket_wire

STATIC = Path(__file__).with_name("static")
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8")}


class WebRuntime:
    def __init__(self, config: dict[str, str], backend_url: str, token_file: Path):
        self.config = config
        self.backend = RemoteBackend.from_token_file(backend_url, token_file)
        self.games = {game.data_dir: game for game in discover()}
        self.sessions: dict[str, str] = {}

    def game_list(self) -> list[dict[str, str]]:
        return [{"id": game.data_dir, "name": game.name} for game in self.games.values()]

    def start(self, game_id: str, scaling: str, transport: str = "poll") -> dict[str, str]:
        scaling = video_scaling({"video_scaling": scaling})
        if transport not in ("poll", "websocket"):
            transport = "poll"
        if game_id == "rainbow-cat":
            remote = self.backend.start_rainbow_cat(scaling, transport)
        else:
            game = self.games.get(game_id)
            if not game:
                raise ValueError("unknown game")
            data = Path(self.config["game_data_root"]).expanduser() / game.data_dir
            files, _summary = self.backend.sync_directory(data)
            executable = self.backend.executable_in_manifest(shlex.split(game.command)[0], files)
            remote = self.backend.start_session(re.sub(r"[^a-z0-9_-]", "-", game.data_dir.lower()), executable,
                                                files, scaling, transport)
        local_id = secrets.token_urlsafe(12)
        self.sessions[local_id] = remote["id"]
        return {"id": local_id, "name": "Dúhová mačka" if game_id == "rainbow-cat" else self.games[game_id].name,
                "video_scaling": scaling}

    def poll(self, local_id: str, payload: dict) -> tuple[int, bytes, int, int]:
        remote_id = self.sessions.get(local_id)
        if not remote_id:
            raise KeyError(local_id)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.backend.token, "Content-Type": "application/json"}
        req = request.Request(self.backend.base_url + f"/v2/sessions/{remote_id}/poll", data=body,
                              method="POST", headers=headers)
        try:
            started = time.monotonic()
            with request.urlopen(req, timeout=3.0) as response:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                server_ms = int(response.headers.get("X-Pi286-Server-Poll-Ms", "-1"))
                return response.status, response.read(), elapsed_ms, server_ms
        except error.HTTPError as exc:
            if exc.code == HTTPStatus.NO_CONTENT:
                return HTTPStatus.NO_CONTENT, b"", 0, 0
            detail = exc.read().decode("utf-8", "replace")
            raise RemoteProtocolError("server rejected poll: " + detail) from exc
        except (error.URLError, TimeoutError) as exc:
            raise RemoteUnavailable("remote DOSBox is unavailable: %s" % getattr(exc, "reason", exc)) from exc

    def stop(self, local_id: str) -> None:
        remote_id = self.sessions.pop(local_id, None)
        if remote_id:
            self.backend.stop_session(remote_id)

    def stop_all(self) -> None:
        for local_id in list(self.sessions):
            try:
                self.stop(local_id)
            except (RemoteUnavailable, RemoteProtocolError):
                pass

    def websocket_backend(self, local_id: str):
        remote_id = self.sessions.get(local_id)
        if not remote_id:
            raise KeyError(local_id)
        parsed = urlsplit(self.backend.base_url)
        port = parsed.port or 80
        connection = socket.create_connection((parsed.hostname, port), timeout=3)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request_bytes = ("GET /v3/sessions/%s/stream HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         "Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: %s\r\nAuthorization: Bearer %s\r\n\r\n" %
                         (remote_id, parsed.hostname, key, self.backend.token)).encode("ascii")
        connection.sendall(request_bytes)
        reader = connection.makefile("rb")
        status = reader.readline()
        while True:
            line = reader.readline()
            if line in (b"\r\n", b""):
                break
        if b" 101 " not in status:
            reader.close(); connection.close()
            raise RemoteProtocolError("LXC websocket upgrade failed")
        return connection, reader


def make_handler(runtime: WebRuntime):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pi286-web-runtime/0.1"

        def log_message(self, format, *args):
            print("web %s - %s" % (self.address_string(), format % args), flush=True)

        def send_json(self, status: int, payload) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > 65536:
                raise ValueError("invalid request body")
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError("JSON object required")
            return value

        def _http_get(self):
            path = urlsplit(self.path).path
            if path == "/api/games":
                self.send_json(HTTPStatus.OK, {"games": runtime.game_list(), "scaling": "nearest"})
                return
            if path == "/api/status":
                try:
                    self.send_json(HTTPStatus.OK, runtime.backend.status())
                except (RemoteUnavailable, RemoteProtocolError) as exc:
                    self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
                return
            static = STATIC_FILES.get(path)
            if not static:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            name, content_type = static
            body = (STATIC / name).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            path = urlsplit(self.path).path
            try:
                payload = self.read_json()
                if path == "/api/sessions":
                    game_id = payload.get("game_id")
                    if not isinstance(game_id, str):
                        raise ValueError("game_id required")
                    self.send_json(HTTPStatus.CREATED, runtime.start(game_id, str(payload.get("video_scaling", "nearest")),
                                                                       str(payload.get("transport", "poll"))))
                    return
                prefix = "/api/sessions/"
                if path.startswith(prefix) and path.endswith("/poll"):
                    status, body, backend_ms, server_ms = runtime.poll(path[len(prefix):-len("/poll")], payload)
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("X-Pi286-Web-Backend-Ms", str(backend_ms))
                    self.send_header("X-Pi286-Server-Poll-Ms", str(server_ms))
                    if body:
                        self.send_header("Content-Type", "application/x-pi286-poll-v1")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except KeyError:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})
            except ValueError as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except (RemoteUnavailable, RemoteProtocolError) as exc:
                self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})

        def do_GET(self):
            path = urlsplit(self.path).path
            prefix = "/api/sessions/"
            if path.startswith(prefix) and path.endswith("/stream"):
                local_id = path[len(prefix):-len("/stream")]
                key = self.headers.get("Sec-WebSocket-Key", "")
                if self.headers.get("Upgrade", "").lower() != "websocket" or not key:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "websocket upgrade required"}); return
                try:
                    backend_socket, backend_reader = runtime.websocket_backend(local_id)
                except (KeyError, RemoteProtocolError, OSError) as exc:
                    self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)}); return
                self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
                self.send_header("Upgrade", "websocket"); self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", websocket_wire.accept_key(key)); self.end_headers()
                try:
                    while True:
                        readable, _, _ = select.select([self.connection, backend_socket], [], [], 1)
                        if self.connection in readable:
                            opcode, payload = websocket_wire.read_frame(self.rfile, True)
                            if opcode == 8:
                                backend_socket.sendall(websocket_wire.pack_frame(b"", 8, True)); return
                            backend_socket.sendall(websocket_wire.pack_frame(payload, opcode, True))
                        if backend_socket in readable:
                            opcode, payload = websocket_wire.read_frame(backend_reader, False)
                            if opcode == 8:
                                self.connection.sendall(websocket_wire.pack_frame(payload, 8)); return
                            self.connection.sendall(websocket_wire.pack_frame(payload, opcode))
                except (EOFError, BrokenPipeError, ConnectionResetError, ValueError):
                    return
                finally:
                    backend_reader.close(); backend_socket.close()
                return
            return self._http_get()

        def do_DELETE(self):
            prefix = "/api/sessions/"
            path = urlsplit(self.path).path
            if not path.startswith(prefix) or "/" in path[len(prefix):]:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                runtime.stop(path[len(prefix):])
                self.send_json(HTTPStatus.OK, {"stopped": True})
            except KeyError:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})
            except (RemoteUnavailable, RemoteProtocolError) as exc:
                self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Pi286 LAN web presenter")
    parser.add_argument("--host-conf", type=Path, default=ROOT / "config" / "host.conf")
    parser.add_argument("--backend-url")
    parser.add_argument("--token-file", type=Path, default=Path("~/.config/pi286-stream.token").expanduser())
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=28681)
    args = parser.parse_args()
    config = values(ROOT / "config" / "host.conf.example")
    config.update(values(args.host_conf))
    backend_url = args.backend_url or config.get("remote_dosbox_url")
    if not backend_url:
        raise SystemExit("set remote_dosbox_url or pass --backend-url")
    runtime = WebRuntime(config, backend_url, args.token_file.expanduser())
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(runtime))
    print("Pi286 web runtime: http://%s:%d" % (args.bind, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop_all()
        server.server_close()


if __name__ == "__main__":
    main()
