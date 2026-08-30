import hashlib
import tempfile
import unittest
from pathlib import Path

from streaming.client.remote_api import RemoteBackend, RemoteProtocolError


class RemoteApiTests(unittest.TestCase):

    def test_rainbow_cat_uses_the_asset_free_diagnostic_endpoint(self):
        backend = RemoteBackend("http://example.test", "token")
        calls = []
        backend.json = lambda method, path, payload=None: calls.append((method, path, payload)) or {"id": "diagnostic"}
        self.assertEqual(backend.start_rainbow_cat(), {"id": "diagnostic"})
        self.assertEqual(calls, [("POST", "/v1/diagnostics/rainbow-cat", {})])

    def test_session_stop_uses_a_shutdown_timeout_longer_than_health_checks(self):
        backend = RemoteBackend("http://example.test", "token")
        calls = []
        backend.json = lambda method, path, payload=None, timeout=None: calls.append((method, path, payload, timeout)) or {"stopped": True}
        self.assertEqual(backend.stop_session("demo"), {"stopped": True})
        self.assertEqual(calls, [("DELETE", "/v1/sessions/demo", None, 5.0)])
    def test_manifest_hashes_regular_files_with_safe_posix_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "GP").mkdir()
            payload = b"game"
            (root / "GP" / "GAME.EXE").write_bytes(payload)
            files, blobs = RemoteBackend.manifest(root)
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(files, {"GP/GAME.EXE": digest})
        self.assertEqual(blobs[0]["size"], len(payload))

    def test_empty_directory_is_not_a_valid_remote_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RemoteProtocolError):
                RemoteBackend.manifest(Path(temporary))

    def test_backend_rejects_non_http_or_empty_credentials(self):
        with self.assertRaises(ValueError):
            RemoteBackend("https://server", "token")
        with self.assertRaises(ValueError):
            RemoteBackend("http://server", "")
