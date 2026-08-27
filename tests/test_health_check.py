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

    def test_reports_sdl1_console_context_and_smoke_probes(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            fake_root = temporary / "host"
            (fake_root / "dev/dri").mkdir(parents=True)
            (fake_root / "boot").mkdir()
            (fake_root / "usr/share/plymouth/themes/pi-286-games").mkdir(parents=True)
            for name in ("kockovane-hry-splash.png", "pi-286-games.plymouth", "pi-286-games.script"):
                (fake_root / "usr/share/plymouth/themes/pi-286-games" / name).touch()
            (fake_root / "dev/fb0").symlink_to("/dev/null")
            (fake_root / "dev/dri/card0").symlink_to("/dev/null")
            (fake_root / "boot/config.txt").write_text("dtoverlay=vc4-kms-v3d\n")
            runtime = temporary / "runtime"
            runtime.mkdir()
            commands = temporary / "bin"
            commands.mkdir()
            self.write_command(commands, "dosbox", """
if [ "${1:-}" = -version ]; then echo 'DOSBox version 0.74'; exit 0; fi
case ${SDL_VIDEODRIVER:-} in x11) echo 'X11 unavailable' >&2; exit 1;; esac
exit 0
""")
            self.write_command(commands, "plymouth", "exit 0")
            self.write_command(commands, "plymouth-set-default-theme", "echo pi-286-games")
            self.write_command(commands, "ldd", "echo 'libSDL-1.2.so.0 => /lib/libSDL-1.2.so.0'")
            self.write_command(commands, "lsmod", "printf 'Module Size Used by\\nvc4 1 0\\n'")
            self.write_command(commands, "getent", "[ \"$1\" = group ] && { echo \"$2:x:1:test\"; exit 0; }; exit 2")
            self.write_command(commands, "id", "[ \"$1\" = -nG ] && echo 'video render input'")
            environment = os.environ | {
                "PATH": str(commands) + ":" + os.environ["PATH"],
                "HEALTH_CHECK_ROOT": str(fake_root),
                "HEALTH_CHECK_RUNTIME_DIR": str(runtime),
                "DISPLAY": "",
                "WAYLAND_DISPLAY": "",
            }
            result = subprocess.run(["sh", str(SCRIPT), "--smoke-dosbox"], env=environment, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("DOSBox appears linked against SDL 1.2", result.stdout)
            self.assertIn("SDL fbcon backend probe completed", result.stdout)
            self.assertIn("SDL x11 backend probe failed", result.stdout)
            self.assertIn("fbcon is the likely direct-console backend", result.stdout)
            self.assertTrue((runtime / "pi-286-games-dosbox-smoke-fbcon.log").exists())


if __name__ == "__main__":
    unittest.main()
