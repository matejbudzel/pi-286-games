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
        self.assertEqual(calls, [("POST", "/v1/diagnostics/rainbow-cat",
                                  {"video_scaling": "nearest", "transport": "poll"})])

    def test_session_and_diagnostic_send_the_requested_scaling(self):
        backend = RemoteBackend("http://example.test", "token")
        calls = []
        backend.json = lambda method, path, payload=None: calls.append((method, path, payload)) or {"id": "session"}
        backend.start_session("gp", "GP.EXE", {"GP.EXE": "a" * 64}, "crt-lite")
        backend.start_rainbow_cat("linear-v")
        self.assertEqual(calls[0][2]["video_scaling"], "crt-lite")
        self.assertEqual(calls[0][2]["transport"], "poll")
        self.assertEqual(calls[1][2]["video_scaling"], "linear-v")

    def test_session_stop_uses_a_shutdown_timeout_longer_than_health_checks(self):
        backend = RemoteBackend("http://example.test", "token")
        calls = []
        backend.json = lambda method, path, payload=None, timeout=None: calls.append((method, path, payload, timeout)) or {"stopped": True}
        self.assertEqual(backend.stop_session("demo"), {"stopped": True})
        self.assertEqual(calls, [("DELETE", "/v1/sessions/demo", None, 5.0)])

    def test_sync_uses_a_long_timeout_without_slowing_health_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "GAME.EXE").write_bytes(b"game")
            backend = RemoteBackend("http://example.test", "token")
            calls = []
            backend.json = lambda method, path, payload=None, timeout=None: calls.append((method, path, timeout)) or {"missing": []}
            backend.sync_directory(root)
            self.assertEqual(calls, [("POST", "/v1/manifest", 60.0)])
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

    def test_executable_is_resolved_from_a_single_archive_wrapper_directory(self):
        files = {"GRANDPRIX/GPEGA.EXE": "a" * 64, "GRANDPRIX/README.TXT": "b" * 64}
        self.assertEqual(RemoteBackend.executable_in_manifest("GPEGA.EXE", files), "GRANDPRIX/GPEGA.EXE")

    def test_executable_resolution_keeps_an_explicit_relative_path(self):
        files = {"GP/GPEGA.EXE": "a" * 64}
        self.assertEqual(RemoteBackend.executable_in_manifest("GP\\GPEGA.EXE", files), "GP/GPEGA.EXE")

    def test_executable_resolution_rejects_ambiguous_basename(self):
        files = {"A/GAME.EXE": "a" * 64, "B/GAME.EXE": "b" * 64}
        with self.assertRaises(RemoteProtocolError):
            RemoteBackend.executable_in_manifest("GAME.EXE", files)

    def test_empty_directory_is_not_a_valid_remote_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RemoteProtocolError):
                RemoteBackend.manifest(Path(temporary))

    def test_backend_rejects_non_http_or_empty_credentials(self):
        with self.assertRaises(ValueError):
            RemoteBackend("https://server", "token")
        with self.assertRaises(ValueError):
            RemoteBackend("http://server", "")
