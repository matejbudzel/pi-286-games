"""Small standard-library client for the Pi286 remote DOSBox backend."""
from __future__ import annotations

import json
from pathlib import Path
from urllib import error, request

class RemoteUnavailable(RuntimeError):
    """The configured server cannot be contacted or authenticated."""


class RemoteProtocolError(RuntimeError):
    """The server responded but rejected an otherwise local request."""


class RemoteBackend:
    def __init__(self, base_url: str, token: str, timeout: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        if not self.base_url.startswith("http://") or not self.token:
            raise ValueError("remote backend requires an http URL and bearer token")

    @classmethod
    def from_token_file(cls, base_url: str, token_file: Path, timeout: float = 2.0):
        return cls(base_url, token_file.read_text(encoding="utf-8"), timeout)

    def _request(self, method: str, path: str, body: bytes | None = None, content_type: str = "application/json", timeout: float | None = None):
        headers = {"Authorization": "Bearer " + self.token}
        if body is not None:
            headers["Content-Type"] = content_type
        req = request.Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            return request.urlopen(req, timeout=self.timeout if timeout is None else timeout)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RemoteProtocolError("server rejected %s %s: %s" % (method, path, detail)) from exc
        except (error.URLError, TimeoutError) as exc:
            raise RemoteUnavailable("remote DOSBox is unavailable: %s" % getattr(exc, "reason", exc)) from exc

    def json(self, method: str, path: str, payload=None, timeout: float | None = None):
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with self._request(method, path, body, timeout=timeout) as response:
            return json.loads(response.read())

    def status(self):
        status = self.json("GET", "/v1/status")
        if status.get("api") != 1:
            raise RemoteProtocolError("unsupported remote API")
        return status

    def games(self, keyboard: bool, dance_pad: bool):
        return self.json("GET", "/v1/games?keyboard=%d&dance_pad=%d" % (keyboard, dance_pad))

    def start_session(self, game_id: str, video_scaling: str = "nearest", transport: str = "poll"):
        return self.json("POST", "/v1/sessions", {"game_id": game_id, "video_scaling": video_scaling,
                                                      "transport": transport})

    def start_rainbow_cat(self, video_scaling: str = "nearest", transport: str = "poll"):
        """Start the server's asset-free video/audio/input transport check."""
        # The small server parses every POST body as JSON, including this
        # asset-free endpoint which otherwise needs no request fields.
        return self.json("POST", "/v1/diagnostics/rainbow-cat", {"video_scaling": video_scaling,
                                                                       "transport": transport})

    def stop_session(self, session_id: str):
        # Server-side process shutdown has a bounded three-second wait.
        return self.json("DELETE", "/v1/sessions/" + session_id, timeout=5.0)
