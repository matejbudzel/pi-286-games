import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).parents[1] / "streaming/backend/pi286_stream_server.py"
SPEC = importlib.util.spec_from_file_location("pi286_stream_server", MODULE)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


class StreamBackendTests(unittest.TestCase):
    def test_relative_paths_reject_escapes(self):
        self.assertEqual(str(backend.safe_relative_path("GP/GP.EXE")), "GP/GP.EXE")
        for value in ("", "/etc/passwd", "../secret", "game/../../secret", "."):
            with self.assertRaises(ValueError):
                backend.safe_relative_path(value)

    def test_cache_upload_validates_digest_and_materializes_hardlink(self):
        payload = b"private game bytes"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            config = dict(backend.DEFAULTS, state_root=directory, max_upload_bytes="1024", dosbox="/bin/true", xvfb="/bin/true")
            state = backend.StreamState(config, "x" * 32)
            self.assertEqual(state.missing([{"sha256": digest, "size": len(payload)}]), [digest])
            state.store_blob(digest, io.BytesIO(payload), len(payload))
            self.assertEqual(state.missing([{"sha256": digest, "size": len(payload)}]), [])
            self.assertEqual(state.blob_path(digest).read_bytes(), payload)

    def test_generated_dosbox_config_is_headless_and_mounts_session(self):
        config = backend.StreamState._dosbox_config(backend.safe_relative_path("GP/GP.EXE"))
        self.assertIn("nosound=true", config)
        self.assertIn("mount c .", config)
        self.assertIn("GP\\GP.EXE", config)

    def test_xvfb_uses_a_visual_accepted_by_debian_dosbox(self):
        source = MODULE.read_text()
        self.assertIn('"640x480x24"', source)

    def test_frame_names_are_strict_and_do_not_escape_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            state = backend.StreamState(dict(backend.DEFAULTS, state_root=directory), "x" * 32)
            captured = state.runtime / "one-0001.xwd"
            captured.write_bytes(b"frame")
            state.active["one"] = {"frames": [captured]}
            self.assertEqual(state.frame_path("one", "0001.xwd"), captured)
            with self.assertRaises(KeyError):
                state.frame_path("no-session", "../../etc/passwd")

    def test_frame_download_route_matches_xwd_not_a_literal_backslash(self):
        self.assertIn(r'frames/[0-9]{4}\.xwd', MODULE.read_text())
