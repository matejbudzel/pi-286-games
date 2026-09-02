"""Authenticated HTTP and WebSocket API for the stream backend."""
from __future__ import annotations

import hmac
import json
import re
import select
import shutil
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from streaming.backend import websocket_wire
from streaming.backend.stream_models import ROOT, VIDEO_HEIGHT, VIDEO_WIDTH
from streaming.backend.stream_state import StreamState

WEB_STATIC = ROOT / "streaming" / "web" / "static"
WEB_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
             "/app.js": ("app.js", "text/javascript; charset=utf-8"),
             "/input.js": ("input.js", "text/javascript; charset=utf-8"),
             "/style.css": ("style.css", "text/css; charset=utf-8")}

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

        def _web_file(self, path: str) -> bool:
            item = WEB_FILES.get(path)
            if not item:
                return False
            name, content_type = item
            body = (WEB_STATIC / name).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True

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
                started = time.monotonic()
                state.touch_session(session_id)
                body = state.poll(session_id, request)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if body is None:
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.send_header("Content-Length", "0")
                    self.send_header("X-Pi286-Server-Poll-Ms", str(elapsed_ms))
                    self.end_headers()
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-pi286-poll-v1")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Pi286-Server-Poll-Ms", str(elapsed_ms))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # A newer Pi poll intentionally closes the older connection.
                return
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown or exited session"})
            except RuntimeError as error:
                self._json(HTTPStatus.CONFLICT, {"error": str(error)})
            except ValueError as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def _websocket(self, session_id: str):
            key = self.headers.get("Sec-WebSocket-Key", "")
            if self.headers.get("Upgrade", "").lower() != "websocket" or not key:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "websocket upgrade required"})
                return
            self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", websocket_wire.accept_key(key))
            self.end_headers()
            request = {"input_revision": 0, "video_seq": 0, "audio_offset": 0, "held_keys": []}
            state.touch_session(session_id)
            next_media = time.monotonic()
            media_requested = False
            close_session = False
            try:
                while True:
                    # A client asks for the next frame with its initial
                    # control message and then acknowledges each frame after
                    # it has rendered it.  This preserves immediate input
                    # while preventing an ARMv6 presenter from accumulating
                    # full-screen packets faster than it can draw them.
                    readable, _, _ = select.select([self.connection], [], [],
                                                    max(0, next_media - time.monotonic()) if media_requested else 1)
                    if readable:
                        opcode, payload = websocket_wire.read_frame(self.rfile, True)
                        if opcode == 8:
                            print("pi286 stream websocket session %s closed by client" % session_id, flush=True)
                            close_session = True
                            self.connection.sendall(websocket_wire.pack_frame(b"", 8))
                            return
                        if opcode == 9:
                            self.connection.sendall(websocket_wire.pack_frame(payload, 10))
                            continue
                        if opcode != 1:
                            raise ValueError("websocket control must be JSON text")
                        incoming = json.loads(payload)
                        if not isinstance(incoming, dict):
                            raise ValueError("websocket control must be an object")
                        request.update(incoming)
                        state.touch_session(session_id)
                        media_requested = True
                        continue
                    if not media_requested:
                        continue
                    if time.monotonic() < next_media:
                        continue
                    # Keep the 30 Hz deadline relative to the start of this
                    # media cycle. Scheduling it after capture would add the
                    # server's capture/encoding time to every frame period.
                    media_started = time.monotonic()
                    body = state.poll(session_id, request)
                    next_media = media_started + 1 / 30
                    if body is not None:
                        self.connection.sendall(websocket_wire.pack_frame(body))
                        media_requested = False
            except (EOFError, BrokenPipeError, ConnectionResetError) as error:
                print("pi286 stream websocket session %s disconnected: %s" % (session_id, type(error).__name__), flush=True)
                return
            except (ValueError, json.JSONDecodeError, KeyError, RuntimeError) as error:
                close_session = True
                print("pi286 stream websocket session %s failed: %s" % (session_id, error), flush=True)
                self.connection.sendall(websocket_wire.pack_frame(json.dumps({"error": str(error)}).encode(), 8))
            finally:
                # Keep an unexpectedly interrupted stream available for the
                # native Pi client to reconnect. The regular idle reaper
                # bounds that grace period; an explicit WebSocket close ends
                # the DOSBox session immediately.
                if close_session:
                    try:
                        state.stop_session(session_id)
                    except KeyError:
                        pass

        def _request_json(self):
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if length < 0 or length > 65536:
                raise ValueError("invalid request length")
            return json.loads(self.rfile.read(length))

        def _check_auth(self):
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required"})
                return False
            return True

        def do_GET(self):
            parsed = urlsplit(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if self._web_file(path):
                    return
                if path == "/web/api/games":
                    self._json(HTTPStatus.OK, state.game_catalog({"keyboard": query.get("keyboard", ["1"])[0] == "1", "dance_pad": query.get("dance_pad", ["1"])[0] == "1"}))
                elif re.fullmatch(r"/web/api/sessions/[^/]+/stream", path):
                    session_id = path.split("/")[4]
                    state.session_status(session_id)
                    self._websocket(session_id)
                elif not self._check_auth():
                    return
                elif path == "/v1/status":
                    self._json(HTTPStatus.OK, {"api": 1, "active_sessions": len(state.active),
                                                "media_transport": "not implemented"})
                elif path == "/v1/games":
                    values = parse_qs(parsed.query)
                    capabilities = {"keyboard": values.get("keyboard", ["0"])[0] == "1",
                                    "dance_pad": values.get("dance_pad", ["0"])[0] == "1"}
                    self._json(HTTPStatus.OK, state.game_catalog(capabilities))
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
                elif re.fullmatch(r"/v3/sessions/[^/]+/stream", path):
                    session_id = path.split("/")[3]
                    # Older web presenters predate the transport field. Keep
                    # their WebSocket upgrade working while new clients still
                    # declare their chosen transport at session creation.
                    state.session_status(session_id)
                    self._websocket(session_id)
                elif path.startswith("/v1/sessions/") and path.endswith("/log"):
                    session_id = path.split("/")[3]
                    self._json(HTTPStatus.NOT_IMPLEMENTED, {"error": "log retrieval is not exposed yet", "id": session_id})
                elif path.startswith("/v1/sessions/"):
                    self._json(HTTPStatus.OK, state.session_status(path.split("/")[3]))
                else: self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except KeyError: self._json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})
            except ValueError as error: self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_POST(self):
            try:
                request = self._request_json()
                if self.path == "/web/api/sessions":
                    self._json(HTTPStatus.CREATED, state.start_session(request))
                    return
                elif re.fullmatch(r"/web/api/sessions/[^/]+/poll", self.path):
                    self._poll(self.path.split("/")[4], request)
                    return
                elif re.fullmatch(r"/web/api/sessions/[^/]+/stats", self.path):
                    self._json(HTTPStatus.OK, state.record_browser_stats(self.path.split("/")[4], request))
                    return
                if not self._check_auth():
                    return
                if self.path == "/v1/sessions":
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
            except KeyError: self._json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})
            except RuntimeError as error: self._json(HTTPStatus.CONFLICT, {"error": str(error)})
            except (subprocess.SubprocessError, OSError) as error: self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

        def do_DELETE(self):
            if self.path.startswith("/web/api/sessions/") and "/" not in self.path[len("/web/api/sessions/"):]:
                session_id = self.path.rsplit("/", 1)[-1]
            elif self.path.startswith("/v1/sessions/") and "/" not in self.path[len("/v1/sessions/"):]:
                if not self._check_auth(): return
                session_id = self.path.rsplit("/", 1)[-1]
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"}); return
            try:
                state.stop_session(session_id)
                self._json(HTTPStatus.OK, {"stopped": True})
            except KeyError: self._json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})
    return Handler


class StreamHTTPServer(ThreadingHTTPServer):
    """HTTP server with a small process-lifecycle watchdog."""
    def __init__(self, address, handler, state: StreamState):
        super().__init__(address, handler)
        self.state = state

    def service_actions(self):
        self.state.reap_idle_sessions()
