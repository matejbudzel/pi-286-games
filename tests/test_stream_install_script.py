import unittest
from pathlib import Path


class StreamInstallScriptTests(unittest.TestCase):
    def test_update_preserves_host_local_stream_configuration(self):
        script = (Path(__file__).parents[1] / "scripts/install-stream-backend-lxc.sh").read_text()
        self.assertIn("if [ ! -e /etc/pi286-stream.conf ]; then", script)
        self.assertIn("must not silently regress", script)
        self.assertIn("chown root:pi286stream /etc/pi286-stream.conf", script)

    def test_loopback_install_requires_all_passed_through_alsa_nodes(self):
        script = (Path(__file__).parents[1] / "scripts/install-stream-backend-lxc.sh").read_text()
        self.assertIn("audio_capture=loopback", script)
        self.assertIn("/dev/snd/controlC1 /dev/snd/pcmC1D0p /dev/snd/pcmC1D1c", script)
        self.assertIn("configure the Proxmox snd_aloop device pass-through first", script)
