"""Small standard-library client for the Pi286 remote DOSBox backend."""
from __future__ import annotations

import hashlib
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

    def _request(self, method: str, path: str, body: bytes | None = None, content_type: str = "application/json"):
        headers = {"Authorization": "Bearer " + self.token}
        if body is not None:
            headers["Content-Type"] = content_type
        req = request.Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            return request.urlopen(req, timeout=self.timeout)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RemoteProtocolError("server rejected %s %s: %s" % (method, path, detail)) from exc
        except error.URLError as exc:
            raise RemoteUnavailable("remote DOSBox is unavailable: %s" % exc.reason) from exc

    def json(self, method: str, path: str, payload=None):
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with self._request(method, path, body) as response:
            return json.loads(response.read())

    def status(self):
        status = self.json("GET", "/v1/status")
        if status.get("api") != 1:
            raise RemoteProtocolError("unsupported remote API")
        return status

    @staticmethod
    def manifest(directory: Path):
        files = {}
        blobs = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(directory).as_posix()
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(65536), b""):
                    digest.update(chunk)
            sha256 = digest.hexdigest()
            size = path.stat().st_size
            files[relative] = sha256
            blobs.append({"sha256": sha256, "size": size, "path": path})
        if not files:
            raise RemoteProtocolError("game data directory contains no regular files")
        return files, blobs

    def sync_directory(self, directory: Path, progress=None):
        files, blobs = self.manifest(directory)
        missing = set(self.json("POST", "/v1/manifest", {"blobs": [{"sha256": item["sha256"], "size": item["size"]} for item in blobs]}).get("missing", []))
        total = sum(item["size"] for item in blobs if item["sha256"] in missing)
        transferred = 0
        for item in blobs:
            if item["sha256"] not in missing:
                continue
            with item["path"].open("rb") as source:
                body = source.read()
            with self._request("PUT", "/v1/blobs/" + item["sha256"], body, "application/octet-stream"):
                pass
            transferred += item["size"]
            if progress:
                progress(transferred, total, item["path"].name)
        if progress:
            progress(total, total, "")
        return files, {"total": total, "transferred": transferred, "files": len(files)}

    def start_session(self, game_id: str, executable: str, files: dict[str, str]):
        return self.json("POST", "/v1/sessions", {"game_id": game_id, "executable": executable, "files": files})

    def start_rainbow_cat(self):
        """Start the server's asset-free video/audio/input transport check."""
        return self.json("POST", "/v1/diagnostics/rainbow-cat")

    def stop_session(self, session_id: str):
        return self.json("DELETE", "/v1/sessions/" + session_id)
