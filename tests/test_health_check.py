import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "health-check.sh"

class HealthCheckTests(unittest.TestCase):
    def write_command(self, directory, name, body):
        path = directory / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def appliance(self, temporary, with_custom=True, kms=False, resolution="640 480 640 480 16"):
        root = temporary / "host"
        (root / "dev").mkdir(parents=True); (root / "boot/firmware").mkdir(parents=True); (root / "proc/device-tree").mkdir(parents=True)
        (root / "proc/device-tree/model").write_text("Raspberry Pi Model B Rev 1")
        (root / "proc/meminfo").write_text("MemTotal:         226424 kB\n")
        (root / "dev/fb0").symlink_to("/dev/null")
        overlay = "dtoverlay=vc4-kms-v3d\n" if kms else ""
        (root / "boot/firmware/config.txt").write_text(overlay + "hdmi_force_hotplug=1\nhdmi_drive=2\nhdmi_blanking=0\ndisable_overscan=1\nhdmi_group=2\nhdmi_mode=4\nframebuffer_width=640\nframebuffer_height=480\nframebuffer_depth=16\n")
        if with_custom:
            (root / "opt/sdl12-fbcon/bin").mkdir(parents=True); (root / "opt/sdl12-fbcon/lib").mkdir()
            (root / "opt/sdl12-fbcon/lib/libSDL-1.2.so.0").touch()
            self.write_command(root / "opt/sdl12-fbcon/bin", "sdl-config", "echo 1.2.16")
        host_conf = temporary / "host.conf"
        host_conf.write_text("dosbox_ld_library_path=/opt/sdl12-fbcon/lib\ndosbox_sdl_videodriver=fbcon\ndosbox_sdl_fbdev=/dev/fb0\ndosbox_sdl_fb_broken_modes=1\n")
        commands = temporary / "bin"; commands.mkdir()
        self.write_command(commands, "dosbox", "if [ \"${1:-}\" = -version ]; then echo 'DOSBox version 0.74-3'; exit 0; fi\n[ \"${LD_LIBRARY_PATH:-}\" = \"$HEALTH_CHECK_ROOT/opt/sdl12-fbcon/lib\" ] || exit 1\n[ \"${SDL_VIDEODRIVER:-}\" = fbcon ] || exit 1\n[ \"${SDL_FBDEV:-}\" = /dev/fb0 ] || exit 1\n[ \"${SDL_FB_BROKEN_MODES:-}\" = 1 ] || exit 1\nexit 0")
        self.write_command(commands, "ldd", "if [ \"${LD_LIBRARY_PATH:-}\" = \"$HEALTH_CHECK_ROOT/opt/sdl12-fbcon/lib\" ]; then echo \"libSDL-1.2.so.0 => $HEALTH_CHECK_ROOT/opt/sdl12-fbcon/lib/libSDL-1.2.so.0\"; else echo 'libSDL-1.2.so.0 => /lib/libSDL-1.2.so.0'; echo 'libSDL2-2.0.so.0 => /lib/libSDL2-2.0.so.0'; fi")
        self.write_command(commands, "fbset", "echo '    geometry " + resolution + "'; echo '    Name        : BCM2708 FB'; echo '    LineLength  : 1280'")
        return root, host_conf, commands

    def run_check(self, temporary, **kwargs):
        root, host_conf, commands = self.appliance(temporary, **kwargs)
        runtime = temporary / "runtime"; runtime.mkdir()
        environment = os.environ | {"PATH": str(commands) + ":" + os.environ["PATH"], "HEALTH_CHECK_ROOT": str(root), "HEALTH_CHECK_HOST_CONF": str(host_conf), "HEALTH_CHECK_RUNTIME_DIR": str(runtime), "DISPLAY": "", "WAYLAND_DISPLAY": ""}
        return subprocess.run(["sh", str(SCRIPT), "--smoke-dosbox"], env=environment, text=True, capture_output=True)

    def test_classifies_the_working_legacy_framebuffer_appliance(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_check(Path(temporary))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("custom SDL fbcon DOSBox smoke test completed", result.stdout)
            self.assertIn("no /dev/dri device (expected and acceptable", result.stdout)
            self.assertIn("legacy appliance classification", result.stdout)
            self.assertIn("system SDL 1.2 ABI appears to be sdl12-compat", result.stdout)

    def test_reports_missing_custom_sdl_without_demanding_drm(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_check(Path(temporary), with_custom=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("custom classic SDL is missing", result.stdout)
            self.assertIn("skipping framebuffer smoke test", result.stdout)

    def test_warns_for_kms_without_drm_and_wrong_framebuffer_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_check(Path(temporary), kms=True, resolution="1920 1080 1920 1080 16")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("KMS/FKMS is configured", result.stdout)
            self.assertIn("KMS/FKMS is configured but no /dev/dri", result.stdout)
            self.assertIn("expected 640x480x16", result.stdout)
