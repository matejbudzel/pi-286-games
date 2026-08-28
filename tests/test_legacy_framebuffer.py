import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HELPER = ROOT / "scripts" / "configure-legacy-framebuffer.sh"
BUILD = ROOT / "scripts" / "build-sdl12-fbcon.sh"
AUDIO = ROOT / "scripts" / "configure-appliance-audio.sh"


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
            for line in ("hdmi_mode=4", "framebuffer_width=640", "framebuffer_height=480", "framebuffer_depth=16", "dtparam=audio=on"):
                self.assertEqual(result.count(line), 1)

    def test_audio_config_uses_bcm2835_hdmi_card_id_not_card_number(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "proc/asound").mkdir(parents=True)
            (root / "proc/asound/cards").write_text(" 0 [HDMI           ]: bcm2835_hdmi - bcm2835 HDMI 1\n")
            subprocess.run(["sh", str(AUDIO)], check=True, env=os.environ | {"PI286_AUDIO_ROOT": str(root)}, capture_output=True, text=True)
            self.assertEqual((root / "etc/modules-load.d/pi-286-games-audio.conf").read_text(), "snd_bcm2835\n")
            config = (root / "etc/asound.conf").read_text()
            self.assertIn('card "HDMI"', config)
            self.assertNotIn("card 0", config)

    def test_kms_is_warned_about_but_not_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.txt"
            config.write_text("dtoverlay=vc4-kms-v3d\n")
            result = subprocess.run(["sh", str(HELPER)], env=os.environ | {"BOOT_CONFIG": str(config)}, capture_output=True, text=True)
            self.assertIn("KMS/FKMS", result.stderr)
            self.assertIn("dtoverlay=vc4-kms-v3d", config.read_text())

    def test_boot_audio_setting_replaces_only_audio_dtparam(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.txt"
            config.write_text("dtparam=audio=off\ndtparam=sd_poll_once\n")
            subprocess.run(["sh", str(HELPER)], check=True, env=os.environ | {"BOOT_CONFIG": str(config)}, capture_output=True, text=True)
            result = config.read_text()
            self.assertIn("dtparam=audio=on", result)
            self.assertIn("dtparam=sd_poll_once", result)
            self.assertNotIn("dtparam=audio=off", result)

    def test_boot_framebuffer_dimensions_come_from_host_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.txt"
            host = root / "host.conf"
            config.write_text("")
            host.write_text("framebuffer_hdmi_group=2\nframebuffer_hdmi_mode=87\nframebuffer_hdmi_cvt=854 480 60 3 0 0 0\nframebuffer_width=854\nframebuffer_height=480\nframebuffer_depth=16\n")
            subprocess.run(["sh", str(HELPER)], check=True, env=os.environ | {"BOOT_CONFIG": str(config), "HOST_CONF": str(host)}, capture_output=True, text=True)
            result = config.read_text()
            for line in ("hdmi_mode=87", "hdmi_cvt=854 480 60 3 0 0 0", "framebuffer_width=854", "framebuffer_height=480", "framebuffer_depth=16"):
                self.assertIn(line, result)

    def test_standard_720p_mode_removes_a_stale_custom_cvt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.txt"
            host = root / "host.conf"
            config.write_text("hdmi_cvt=854 480 60 3 0 0 0\n")
            host.write_text("framebuffer_hdmi_group=1\nframebuffer_hdmi_mode=4\nframebuffer_width=1280\nframebuffer_height=720\nframebuffer_depth=16\n")
            subprocess.run(["sh", str(HELPER)], check=True, env=os.environ | {"BOOT_CONFIG": str(config), "HOST_CONF": str(host)}, capture_output=True, text=True)
            result = config.read_text()
            self.assertNotIn("hdmi_cvt=", result)
            for line in ("hdmi_group=1", "hdmi_mode=4", "framebuffer_width=1280", "framebuffer_height=720", "framebuffer_depth=16"):
                self.assertIn(line, result)

    def test_build_script_pins_classic_sdl_116_and_uses_one_job(self):
        source = BUILD.read_text()
        shared = (ROOT / "scripts" / "sdl12-fbcon-common.sh").read_text()
        self.assertIn("sdl12-fbcon-common.sh", source)
        self.assertIn("--enable-video-fbcon", shared)
        self.assertIn("--disable-video-x11", shared)
        self.assertIn("sdl12_fbcon_apply_patches", source)
        self.assertIn(".pi286-sdl-fbcon-pillarbox", source)
        self.assertIn("0002-pi286-fbcon-centered-canvas-color.patch", shared)
        self.assertIn("--enable-audio", shared)
        self.assertIn("--enable-alsa", shared)
        self.assertIn("--disable-alsa-shared", shared)
        self.assertIn("libasound", source)
        self.assertNotIn("--enable-audio-alsa", shared)
        self.assertIn("make -j\"$jobs\"", source)
        self.assertNotIn("--disable-audio", source)

    def test_sdl_audio_self_test_uses_the_custom_library_and_verified_pcm(self):
        source = (ROOT / "scripts" / "sdl-audio-self-test.c").read_text()
        runner = (ROOT / "scripts" / "run-sdl-audio-self-test.sh").read_text()
        self.assertIn("SDL_INIT_AUDIO", source)
        self.assertIn("SDL_OpenAudio", source)
        self.assertIn("SDL_AUDIODRIVER=alsa", runner)
        self.assertIn("AUDIODEV=plughw:0,0", runner)
