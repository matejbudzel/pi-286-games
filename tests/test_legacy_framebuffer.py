import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HELPER = ROOT / "scripts" / "configure-legacy-framebuffer.sh"
BUILD = ROOT / "scripts" / "build-sdl12-fbcon.sh"


class LegacyFramebufferTests(unittest.TestCase):
    def test_boot_config_is_idempotent_and_preserves_unrelated_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.txt"
            config.write_text("gpu_mem_256=16\nenable_uart=0\nhdmi_mode=16\n")
            env = os.environ | {"BOOT_CONFIG": str(config)}
            subprocess.run(["sh", str(HELPER)], check=True, env=env, capture_output=True, text=True)
            subprocess.run(["sh", str(HELPER)], check=True, env=env, capture_output=True, text=True)
            result = config.read_text()
            self.assertIn("gpu_mem_256=16", result)
            self.assertIn("enable_uart=0", result)
            self.assertEqual(result.count("hdmi_mode="), 1)
            for line in ("hdmi_mode=4", "framebuffer_width=640", "framebuffer_height=480", "framebuffer_depth=16"):
                self.assertEqual(result.count(line), 1)

    def test_kms_is_warned_about_but_not_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.txt"
            config.write_text("dtoverlay=vc4-kms-v3d\n")
            result = subprocess.run(["sh", str(HELPER)], env=os.environ | {"BOOT_CONFIG": str(config)}, capture_output=True, text=True)
            self.assertIn("KMS/FKMS", result.stderr)
            self.assertIn("dtoverlay=vc4-kms-v3d", config.read_text())

    def test_build_script_pins_classic_sdl_116_and_uses_one_job(self):
        source = BUILD.read_text()
        self.assertIn("source_commit=7bf353eca59cb503f43b86e3867dc4fc4e45f2e3", source)
        self.assertIn("--enable-video-fbcon", source)
        self.assertIn("--disable-video-x11", source)
        self.assertIn("--enable-audio", source)
        self.assertIn("make -j\"$jobs\"", source)
        self.assertNotIn("--disable-audio", source)
