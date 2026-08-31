"""Small standard-library client for the Pi286 remote DOSBox backend."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib import error, request

SYNC_TIMEOUT_SECONDS = 60.0


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
        missing = set(self.json("POST", "/v1/manifest", {"blobs": [{"sha256": item["sha256"], "size": item["size"]} for item in blobs]},
                                timeout=SYNC_TIMEOUT_SECONDS).get("missing", []))
        total = sum(item["size"] for item in blobs if item["sha256"] in missing)
        transferred = 0
        for item in blobs:
            if item["sha256"] not in missing:
                continue
            with item["path"].open("rb") as source:
                body = source.read()
            with self._request("PUT", "/v1/blobs/" + item["sha256"], body, "application/octet-stream", SYNC_TIMEOUT_SECONDS):
                pass
            transferred += item["size"]
            if progress:
                progress(transferred, total, item["path"].name)
        if progress:
            progress(total, total, "")
        return files, {"total": total, "transferred": transferred, "files": len(files)}

    @staticmethod
    def executable_in_manifest(command: str, files: dict[str, str]) -> str:
        """Return the manifest path corresponding to a DOS launch command.

        Game archives sometimes contain a single top-level directory. Local
        DOSBox happens to find a bare executable name in that layout, whereas
        the remote session manifest must name the file exactly. Prefer the
        requested relative path, then an unambiguous basename match.
        """
        executable = command.replace("\\", "/")
        if executable in files:
            return executable
        folded = executable.casefold()
        exact_casefold = [path for path in files if path.casefold() == folded]
        if len(exact_casefold) == 1:
            return exact_casefold[0]
        basename = executable.rsplit("/", 1)[-1].casefold()
        basename_matches = [path for path in files if path.rsplit("/", 1)[-1].casefold() == basename]
        if len(basename_matches) == 1:
            return basename_matches[0]
        if not basename_matches:
            raise RemoteProtocolError("spúšťací súbor %s nie je medzi hernými dátami" % executable)
        raise RemoteProtocolError("spúšťací súbor %s nie je jednoznačný v herných dátach" % executable)

    def start_session(self, game_id: str, executable: str, files: dict[str, str], video_scaling: str = "nearest",
                      transport: str = "poll"):
        return self.json("POST", "/v1/sessions", {"game_id": game_id, "executable": executable,
                                                      "files": files, "video_scaling": video_scaling,
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
