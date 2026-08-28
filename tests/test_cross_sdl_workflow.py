import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]

class CrossSdlWorkflowTests(unittest.TestCase):
    def test_scripts_use_fixed_ssh_alias_and_batch_mode(self):
        for name in ("sync-pi-sysroot.sh", "deploy-sdl12-to-pi.sh"):
            source = (ROOT / "scripts" / name).read_text()
            self.assertIn("ssh -o BatchMode=yes pi286 true", source)
            self.assertNotIn("StrictHostKeyChecking=no", source)

    def test_cross_build_is_armv6_hard_float_and_staged(self):
        source = (ROOT / "scripts" / "cross-build-sdl12-fbcon.sh").read_text()
        for flag in ("-marm", "-march=armv6zk", "-mtune=arm1176jzf-s", "-mfpu=vfp", "-mfloat-abi=hard", "--host=arm-linux-gnueabihf", "DESTDIR=\"$stage_dir\"", "Tag_ABI_VFP_args"):
            self.assertIn(flag, source)
        self.assertIn("sdl12-fbcon-rpi1-armv6-armhf.tar.gz", source)

    def test_wrapper_has_nonvisual_all_and_explicit_visual_commands(self):
        source = (ROOT / "scripts" / "dev-sdl.sh").read_text()
        self.assertIn("sync-pi-sysroot.sh", source)
        self.assertIn("cross-build-sdl12-fbcon.sh", source)
        self.assertIn("deploy-sdl12-to-pi.sh", source)
        self.assertIn("visual-pillarbox", source)
