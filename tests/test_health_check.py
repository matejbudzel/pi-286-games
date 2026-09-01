import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "health-check.sh"

class HealthCheckTests(unittest.TestCase):
    def test_reports_thin_client_settings_without_dosbox(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            host = root / "host.conf"
            host.write_text("presenter_ld_library_path=/opt/sdl12-fbcon/lib\npresenter_sdl_videodriver=fbcon\npresenter_sdl_fbdev=/dev/fb0\npresenter_sdl_fb_broken_modes=1\nremote_dosbox_url=http://server:28680\n")
            result = subprocess.run(["sh", str(SCRIPT)], text=True, capture_output=True,
                                    env=os.environ | {"HEALTH_CHECK_ROOT": str(root), "HEALTH_CHECK_HOST_CONF": str(host)})
            self.assertEqual(result.returncode, 0)
            self.assertIn("presenter setting presenter_sdl_videodriver=fbcon", result.stdout)
            self.assertNotIn("DOSBox smoke", result.stdout)
