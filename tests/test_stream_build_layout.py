import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class StreamBuildLayoutTests(unittest.TestCase):
    def test_native_stream_builds_reuse_the_launcher_sysroot(self):
        for name in ("cross-build-libwebsockets.sh", "cross-build-stream-presenter.sh"):
            source = (ROOT / "scripts" / name).read_text()
            self.assertIn("PI_GAMES_LAUNCHER_REPO", source)
            self.assertIn("$launcher_repo/.cache/pi286-sysroot", source)
