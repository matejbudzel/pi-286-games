import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class TtyServiceTests(unittest.TestCase):
    def test_installer_is_locked_to_the_known_pi1_target(self):
        installer = (ROOT / "scripts" / "install-dietpi.sh").read_text()
        self.assertIn('"$(uname -m)" = armv6l', installer)
        self.assertIn("Raspberry Pi Model B Rev 1", installer)

    def test_installer_removes_plymouth_instead_of_installing_it(self):
        installer = (ROOT / "scripts" / "install-dietpi.sh").read_text()
        self.assertIn("apt-get purge -y plymouth plymouth-themes", installer)
        self.assertNotIn("install -y dosbox plymouth", installer)

    def test_service_owns_tty1_then_restores_getty(self):
        template = (ROOT / "systemd" / "pi-286-games.service.in").read_text()
        rendered = template.replace("@USER@", "dietpi").replace("@HOME@", "/home/dietpi").replace("@REPO@", "/home/dietpi/pi-286-games")
        self.assertNotIn("plymouth", rendered)
        self.assertIn("Conflicts=getty@tty1.service", rendered)
        self.assertIn("TTYPath=/dev/tty1", rendered)
        self.assertIn("ExecStopPost=+/usr/bin/systemctl --no-block start getty@tty1.service", rendered)

    def test_installer_replaces_profile_hook_with_tty_service(self):
        installer = (ROOT / "scripts" / "install-dietpi.sh").read_text()
        self.assertIn('sed -i "/^$marker$/,/^fi$/d"', installer)
        self.assertIn("pi-286-games.service.in", installer)
        self.assertIn("systemctl enable pi-286-games.service", installer)


if __name__ == "__main__":
    unittest.main()
