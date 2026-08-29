import hashlib
import importlib.util
import io
import struct
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).parents[1] / "streaming/backend/pi286_stream_server.py"
SPEC = importlib.util.spec_from_file_location("pi286_stream_server", MODULE)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


class StreamBackendTests(unittest.TestCase):
    def test_relative_paths_reject_escapes(self):
        self.assertEqual(str(backend.safe_relative_path("GP/GP.EXE")), "GP/GP.EXE")
        for value in ("", "/etc/passwd", "../secret", "game/../../secret", "."):
            with self.assertRaises(ValueError):
                backend.safe_relative_path(value)

    def test_cache_upload_validates_digest_and_materializes_hardlink(self):
        payload = b"private game bytes"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            config = dict(backend.DEFAULTS, state_root=directory, max_upload_bytes="1024", dosbox="/bin/true", xvfb="/bin/true")
            state = backend.StreamState(config, "x" * 32)
            self.assertEqual(state.missing([{"sha256": digest, "size": len(payload)}]), [digest])
            state.store_blob(digest, io.BytesIO(payload), len(payload))
            self.assertEqual(state.missing([{"sha256": digest, "size": len(payload)}]), [])
            self.assertEqual(state.blob_path(digest).read_bytes(), payload)

    def test_generated_dosbox_config_is_headless_and_mounts_session(self):
        config = backend.StreamState._dosbox_config(backend.safe_relative_path("GP/GP.EXE"), 22050)
        self.assertIn("nosound=false", config)
        self.assertIn("pcspeaker=true", config)
        self.assertIn("rate=22050", config)
        self.assertIn("mount c .", config)
        self.assertIn("GP\\GP.EXE", config)

    def test_xvfb_uses_a_visual_accepted_by_debian_dosbox(self):
        source = MODULE.read_text()
        self.assertIn('"640x480x24"', source)

    def test_frame_names_are_strict_and_do_not_escape_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            state = backend.StreamState(dict(backend.DEFAULTS, state_root=directory), "x" * 32)
            captured = state.runtime / "one-0001.xwd"
            captured.write_bytes(b"frame")
            state.active["one"] = {"frames": [captured]}
            self.assertEqual(state.frame_path("one", "0001.xwd"), captured)
            with self.assertRaises(KeyError):
                state.frame_path("no-session", "../../etc/passwd")

    def test_frame_download_route_matches_xwd_not_a_literal_backslash(self):
        self.assertIn(r'frames/[0-9]{4}\.xwd', MODULE.read_text())

    def test_audio_downmixes_stereo_s16le_to_mono(self):
        with tempfile.TemporaryDirectory() as directory:
            state = backend.StreamState(dict(backend.DEFAULTS, state_root=directory), "x" * 32)
            audio = state.sessions / "audio.raw"
            audio.write_bytes(struct.pack("<hhhh", 1000, -1000, 3000, 1000))
            state.active["audio"] = {"audio": audio}
            result, next_offset = state.audio_chunk("audio", 0)
            self.assertEqual(struct.unpack("<hh", result), (0, 2000))
            self.assertEqual(next_offset, 4)

    def test_alsa_capture_is_session_local_and_uses_a_file_pcm(self):
        config = backend.StreamState._alsa_capture_config(Path("/tmp/audio.raw"))
        self.assertIn("type file", config)
        self.assertIn('slave.pcm "null"', config)
        self.assertIn('file "/tmp/audio.raw"', config)

    def test_audio_pump_rate_is_stereo_s16le(self):
        source = MODULE.read_text()
        self.assertIn("self.audio_rate * 2 * 2", source)
        self.assertIn("os.O_RDWR | os.O_NONBLOCK", source)

    def test_input_protocol_has_a_closed_key_set(self):
        self.assertEqual(backend.KEYS["UP"], "Up")
        self.assertEqual(backend.KEYS["SPACE"], "space")
        self.assertNotIn("rm -rf /", backend.KEYS)

    def test_xwd_video_conversion_crops_and_downsamples_to_rgb565(self):
        header = [100, 7, 2, 24, 640, 480, 0, 0, 32, 0, 32, 32, 640 * 4,
                  4, 0x00ff0000, 0x0000ff00, 0x000000ff, 8, 256, 0, 0, 640, 480, 0, 0]
        pixels = bytearray(640 * 480 * 4)
        # The first sampled pixel is source (0, 40): pure red.
        offset = 40 * 640 * 4
        pixels[offset:offset + 4] = bytes((0, 0, 255, 0))
        converted = backend.StreamState._xwd_to_rgb565(struct.pack(">25I", *header) + pixels)
        self.assertEqual(len(converted), 320 * 200 * 2)
        self.assertEqual(converted[:2], bytes((0x00, 0xf8)))
