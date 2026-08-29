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
