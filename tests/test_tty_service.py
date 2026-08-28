import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class TtyServiceTests(unittest.TestCase):
    def test_installer_is_locked_to_the_known_pi1_target(self):
        installer = (ROOT / "scripts" / "install-dietpi.sh").read_text()
        self.assertIn('"$(uname -m)" = armv6l', installer)
        self.assertIn("Raspberry Pi Model B Rev 1", installer)

    def test_installer_does_not_manage_plymouth(self):
        installer = (ROOT / "scripts" / "install-dietpi.sh").read_text()
        self.assertNotIn("plymouth", installer.lower())

    def test_service_owns_tty1_then_restores_getty(self):
        template = (ROOT / "systemd" / "pi-286-games.service.in").read_text()
        rendered = template.replace("@USER@", "dietpi").replace("@HOME@", "/home/dietpi").replace("@REPO@", "/home/dietpi/pi-286-games")
        self.assertNotIn("plymouth", rendered)
        self.assertIn("Wants=pi-286-games-audio.service", rendered)
        self.assertIn("Conflicts=getty@tty1.service", rendered)
        self.assertIn("TTYPath=/dev/tty1", rendered)
        self.assertIn("ExecStopPost=+/usr/bin/systemctl --no-block start getty@tty1.service", rendered)

    def test_installer_replaces_profile_hook_with_tty_service(self):
        installer = (ROOT / "scripts" / "install-dietpi.sh").read_text()
        self.assertIn('sed -i "/^$marker$/,/^fi$/d"', installer)
        self.assertIn("pi-286-games.service.in", installer)
        self.assertIn("systemctl enable pi-286-games.service", installer)
        self.assertIn("systemctl enable pi-286-games-audio.service", installer)

    def test_installer_maintains_the_console_command_aliases(self):
        installer = (ROOT / "scripts" / "install-dietpi.sh").read_text()
        self.assertIn("# pi-286-games aliases", installer)
        for alias in ("pg-install", "pg-start", "pg-update", "pg-check", "pg-restart"):
            self.assertIn("alias " + alias + "=", installer)
        self.assertIn("git pull --ff-only", installer)
        self.assertIn("restart-launcher.sh", installer)
        self.assertIn("systemctl stop getty@tty1.service", installer)

    def test_remote_restart_hands_tty1_from_getty_back_to_launcher(self):
        restart = (ROOT / "scripts" / "restart-launcher.sh").read_text()
        self.assertIn("systemctl stop pi-286-games.service", restart)
        self.assertIn("systemctl stop getty@tty1.service", restart)
        self.assertIn("systemctl start pi-286-games.service", restart)

    def test_audio_service_loads_the_target_module_before_launcher(self):
        audio_service = (ROOT / "systemd" / "pi-286-games-audio.service").read_text()
        self.assertIn("ExecStart=/sbin/modprobe snd_bcm2835", audio_service)
        self.assertIn("Before=pi-286-games.service", audio_service)


if __name__ == "__main__":
    unittest.main()
