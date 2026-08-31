import hashlib
import importlib.util
import io
import struct
import tempfile
import unittest
from types import SimpleNamespace
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
        self.assertIn("machine=ega", config)
        self.assertIn("memsize=8", config)
        self.assertIn("core=normal", config)
        self.assertIn("cycles=fixed 3000", config)
        self.assertIn("pcspeaker=true", config)
        self.assertIn("tandy=off", config)
        self.assertIn("disney=false", config)
        self.assertIn("mpu401=none", config)
        self.assertIn("rate=22050", config)
        self.assertIn("blocksize=2048", config)
        self.assertIn("prebuffer=100", config)
        self.assertIn("mount c .", config)
        self.assertIn("cd \\GP", config)
        self.assertIn("\nGP.EXE\nexit", config)

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

    def test_audio_uses_left_channel_as_pc_speaker_mono(self):
        with tempfile.TemporaryDirectory() as directory:
            state = backend.StreamState(dict(backend.DEFAULTS, state_root=directory), "x" * 32)
            audio = state.sessions / "audio.raw"
            audio.write_bytes(struct.pack("<hhhh", 1000, -1000, 3000, 1000))
            state.active["audio"] = {"audio": audio}
            result, next_offset = state.audio_chunk("audio", 0)
            self.assertEqual(struct.unpack("<hh", result), (1000, 3000))
            self.assertEqual(next_offset, 4)

    def test_raw_audio_diagnostic_preserves_stereo_frame_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            state = backend.StreamState(dict(backend.DEFAULTS, state_root=directory), "x" * 32)
            audio = state.sessions / "source.raw"
            audio.write_bytes(b"01234567x")
            state.active["audio"] = {"audio": audio}
            result, next_offset = state.audio_source_chunk("audio", 0)
            self.assertEqual(result, b"01234567")
            self.assertEqual(next_offset, 8)

    def test_alsa_capture_is_session_local_and_uses_a_file_pcm(self):
        config = backend.StreamState._alsa_capture_config(Path("/tmp/audio.raw"))
        self.assertIn("type file", config)
        self.assertIn('slave.pcm "null"', config)
        self.assertIn('file "/tmp/audio.raw"', config)

    def test_loopback_capture_is_explicit_s16le_stereo_at_the_stream_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            state = backend.StreamState(dict(backend.DEFAULTS, state_root=directory), "x" * 32)
            command = state._arecord_command(Path("/tmp/audio.raw"))
            self.assertEqual(command, ["/usr/bin/arecord", "-q", "-D", "hw:Loopback,1,0",
                                       "-f", "S16_LE", "-c", "2", "-r", "22050", "-t", "raw", "/tmp/audio.raw"])

    def test_poll_multiplexes_media_and_uses_the_latest_held_key_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = backend.StreamState(dict(backend.DEFAULTS, state_root=directory), "x" * 32)
            state.active["one"] = {"dosbox": SimpleNamespace(poll=lambda: None), "held_keys": set(), "video_sequence": 0}
            state._sync_held_keys = lambda item, keys: item.update(held_keys=keys)
            state.video_frame = lambda session, force: (b"video", 1, 2)
            state.audio_chunk = lambda session, offset: (b"audio", offset + 5)
            packet = state.poll("one", {"input_revision": 3, "video_seq": 0, "audio_offset": 0, "held_keys": ["UP"]})
            self.assertEqual(packet, struct.pack(">4sIII", b"P2P1", 5, 5, 5) + b"videoaudio")
            self.assertEqual(state.active["one"]["held_keys"], {"UP"})
            stats = state._poll_stats_snapshot(state.active["one"]["poll_stats"])
            self.assertEqual(stats["requests"], 1)
            self.assertEqual(stats["responses"], 1)
            self.assertEqual(stats["stale"], 0)
            self.assertEqual(stats["total_ms"]["count"], 1)

    def test_empty_held_snapshot_does_not_require_dosbox_input_window(self):
        state = backend.StreamState.__new__(backend.StreamState)
        state._find_dosbox_window = lambda _display: self.fail("empty input should not search for a window")
        state._sync_held_keys({"held_keys": set(), "window": None, "display": ":1"}, set())

    def test_audio_pump_rate_is_stereo_s16le(self):
        source = MODULE.read_text()
        self.assertIn("self.audio_rate * 2 * 2", source)
        self.assertIn("os.O_RDWR | os.O_NONBLOCK", source)

    def test_input_protocol_has_a_closed_key_set(self):
        self.assertEqual(backend.KEYS["UP"], "Up")
        self.assertEqual(backend.KEYS["SPACE"], "space")
        self.assertEqual(backend.KEYS["BACKSPACE"], "BackSpace")
        self.assertEqual(backend.KEYS["F12"], "F12")
        self.assertEqual(backend.KEYS["KP_ENTER"], "KP_Enter")
        self.assertNotIn("rm -rf /", backend.KEYS)

    def test_rainbow_diagnostic_is_generated_and_does_not_need_game_assets(self):
        self.assertGreater(len(backend.RAINBOW_CAT_COM), 32)
        self.assertEqual(backend.RAINBOW_CAT_COM[:2], b"\xb0\xb6")
        frame = backend.StreamState._diagnostic_frame(1)
        self.assertEqual(len(frame), backend.VIDEO_BYTES)
        self.assertNotEqual(frame, bytes(backend.VIDEO_BYTES))
        self.assertNotEqual(frame, backend.StreamState._diagnostic_frame(1, 0))

    def test_rainbow_diagnostic_audio_is_pcm_at_the_configured_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            state = backend.StreamState({**backend.DEFAULTS, "state_root": directory}, "token")
            audio, next_offset = state._diagnostic_audio(0)
            self.assertEqual(len(audio), 8192)
            self.assertEqual(next_offset, len(audio))
            self.assertNotEqual(audio, bytes(len(audio)))

    def test_xwd_video_conversion_crops_and_downsamples_to_rgb565(self):
        header = [100, 7, 2, 24, 640, 480, 0, 0, 32, 0, 8, 24, 640 * 4,
                  4, 0x00ff0000, 0x0000ff00, 0x000000ff, 8, 256, 0, 0, 640, 480, 0, 0]
        pixels = bytearray(640 * 480 * 4)
        # Xvfb has 24-bit BGR pixels in a separately padded 2560-byte row.
        # The first two sampled pixels are source (0, 40) and (2, 40).
        offset = 40 * 640 * 4
        pixels[offset:offset + 3] = bytes((0, 0, 255))
        pixels[offset + 6:offset + 9] = bytes((255, 0, 0))
        # 320x200 to 320x240 nearest-neighbour expansion duplicates its first
        # source row before advancing to source row 42.
        next_row = 42 * 640 * 4
        pixels[next_row:next_row + 3] = bytes((0, 255, 0))
        converted = backend.StreamState._xwd_to_rgb565(struct.pack(">25I", *header) + pixels)
        self.assertEqual(len(converted), 320 * 240 * 2)
        self.assertEqual(converted[:2], bytes((0x00, 0xf8)))
        self.assertEqual(converted[2:4], bytes((0x1f, 0x00)))
        self.assertEqual(converted[320 * 2:320 * 2 + 2], bytes((0x00, 0xf8)))
        self.assertEqual(converted[320 * 4:320 * 4 + 2], bytes((0xe0, 0x07)))

    def test_video_scaling_is_deterministic_before_tile_encoding(self):
        header = [100, 7, 2, 24, 640, 480, 0, 0, 32, 0, 8, 24, 640 * 4,
                  4, 0x00ff0000, 0x0000ff00, 0x000000ff, 8, 256, 0, 0, 640, 480, 0, 0]
        pixels = bytearray(640 * 480 * 4)
        pixels[40 * 640 * 4:40 * 640 * 4 + 3] = bytes((0, 0, 255))
        pixels[42 * 640 * 4:42 * 640 * 4 + 3] = bytes((0, 255, 0))
        source = struct.pack(">25I", *header) + pixels
        nearest = backend.StreamState._xwd_to_rgb565(source, "nearest")
        linear = backend.StreamState._xwd_to_rgb565(source, "linear-v")
        crt = backend.StreamState._xwd_to_rgb565(source, "crt-lite")
        self.assertNotEqual(nearest[320 * 2:320 * 2 + 2], linear[320 * 2:320 * 2 + 2])
        self.assertNotEqual(linear[320 * 2:320 * 2 + 2], crt[320 * 2:320 * 2 + 2])
        self.assertEqual(crt, backend.StreamState._xwd_to_rgb565(source, "crt-lite"))

    def test_video_tiles_encode_only_changed_16x16_regions_and_recover_with_keyframe(self):
        previous = bytes(backend.VIDEO_BYTES)
        changed = bytearray(previous)
        changed[(16 * backend.VIDEO_WIDTH + 16) * 2] = 0xff
        delta, keyframe = backend.StreamState._video_packet(bytes(changed), previous, 7, 12, False)
        self.assertFalse(keyframe)
        self.assertEqual(delta[:8], b"P2V1\x02\x00\x00\x01")
        self.assertEqual(len(delta), backend.VIDEO_PACKET_HEADER + 2 + 16 * 16 * 2)
        full, keyframe = backend.StreamState._video_packet(bytes(changed), previous, 8, 12, True)
        self.assertTrue(keyframe)
        self.assertEqual(full[:8], b"P2V1\x01\x00\x00\x00")
        self.assertEqual(len(full), backend.VIDEO_PACKET_HEADER + backend.VIDEO_BYTES)
