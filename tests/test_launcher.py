import importlib.util
import inspect
import tempfile
import unittest
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("launcher", Path(__file__).parents[1] / "launcher" / "launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class DiscoveryTests(unittest.TestCase):
    def test_bye_bye_shutdown_is_detected_from_raspberry_pi_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "model"
            model.write_text("Raspberry Pi Model B Rev 1\0")
            self.assertTrue(launcher.is_raspberry_pi(model))
            model.write_text("QEMU Virtual Machine\0")
            self.assertFalse(launcher.is_raspberry_pi(model))

    def test_renderer_line_never_exceeds_terminal_width(self):
        self.assertEqual(launcher.Terminal.line("A very long title", True, 5), "> A <")
        self.assertLessEqual(len(launcher.Terminal.line("A very long title", True, 5)), 5)
        self.assertLessEqual(len(launcher.Terminal.line("A very long title", False, 1)), 1)

    def test_shutdown_requires_a_second_explicit_confirmation(self):
        original_draw, original_input = launcher.Terminal.draw, launcher.next_input
        try:
            launcher.Terminal.draw = lambda *args, **kwargs: None
            launcher.next_input = lambda *args: "ESC"
            self.assertFalse(launcher.confirm_shutdown(None, None, "SPACE"))
            launcher.next_input = lambda *args: "SPACE"
            self.assertTrue(launcher.confirm_shutdown(None, None, "SPACE"))
        finally:
            launcher.Terminal.draw, launcher.next_input = original_draw, original_input

    def test_splash_uses_block_logo_only_when_it_fits_and_keeps_diacritics(self):
        self.assertEqual(launcher.Terminal.splash_lines(80), launcher.SPLASH_ART)
        self.assertEqual(launcher.Terminal.splash_lines(79), ("KOCKOVANÉ HRY",))
        self.assertEqual(launcher.SPLASH_ART[:2], ("                                                                       ▄█╗",
                                                   "                                                                       ╚═╝"))

    def test_game_running_screen_names_game_and_panic_key(self):
        captured = []
        original = launcher.Terminal.draw
        launcher.Terminal.draw = lambda lines, color="\x1b[96m", corner="": captured.extend(lines)
        try:
            launcher.game_running_screen(launcher.Game("Prince of Persia", "", ""), "F1")
        finally:
            launcher.Terminal.draw = original
        self.assertIn(("Je spustená hra", False), captured)
        self.assertIn(("Prince of Persia", True), captured)
        self.assertIn(("Ukončiť: SELECT alebo F1.", False), captured)

    def test_console_reset_discards_a_framebuffer_games_last_frame(self):
        captured = []
        original_write, original_flush = launcher.sys.stdout.write, launcher.sys.stdout.flush
        original_ioctl = launcher.fcntl.ioctl
        launcher.sys.stdout.write = captured.append
        launcher.sys.stdout.flush = lambda: None
        calls = []
        launcher.fcntl.ioctl = lambda fd, request, value: calls.append((fd, request, value))
        try:
            launcher.restore_console_display()
        finally:
            launcher.sys.stdout.write, launcher.sys.stdout.flush = original_write, original_flush
            launcher.fcntl.ioctl = original_ioctl
        self.assertEqual(captured, ["\x1bc"])
        self.assertEqual(calls[0][1:], (launcher.KDSETMODE, launcher.KD_TEXT))

    def test_sound_status_requires_module_and_accessible_sound_device(self):
        class FakePath:
            def __init__(self, value): self.value = value
            def read_text(self): return "snd_bcm2835 1 0\n" if self.value == "/proc/modules" else ""
            def glob(self, pattern): return ["/dev/snd/controlC0"] if self.value == "/dev/snd" else []
        original_path, original_access = launcher.Path, launcher.os.access
        launcher.Path, launcher.os.access = FakePath, lambda path, mode: True
        try:
            self.assertEqual(launcher.sound_status(), "Zvuk: ide")
        finally:
            launcher.Path, launcher.os.access = original_path, original_access

    def test_volume_is_clamped_persisted_and_shown_in_ten_steps(self):
        self.assertEqual(launcher.volume_percent("200"), 100)
        self.assertEqual(launcher.volume_percent("bad"), 96)
        self.assertEqual(launcher.volume_status(50), "Zvuk: [#####.....]")
        with tempfile.TemporaryDirectory() as temporary:
            host = Path(temporary) / "host.conf"
            host.write_text("game_data_root=games\n# preserved\n")
            launcher.save_value(host, launcher.AUDIO_VOLUME_KEY, 40)
            launcher.save_value(host, launcher.AUDIO_VOLUME_KEY, 50)
            self.assertEqual(host.read_text().count("audio_volume_percent="), 1)
            self.assertIn("audio_volume_percent=50", host.read_text())

    def test_video_scaling_defaults_safely_and_accepts_known_modes(self):
        self.assertEqual(launcher.video_scaling({}), "nearest")
        self.assertEqual(launcher.video_scaling({"video_scaling": "linear-v"}), "linear-v")
        self.assertEqual(launcher.video_scaling({"video_scaling": "crt-lite"}), "crt-lite")
        self.assertEqual(launcher.video_scaling({"video_scaling": "experimental"}), "nearest")

    def test_terminal_decodes_left_and_right_for_launcher_volume(self):
        self.assertEqual(launcher.Terminal.decode_key(b"\x1b[D"), "LEFT")
        self.assertEqual(launcher.Terminal.decode_key(b"\x1bOD"), "LEFT")
        self.assertEqual(launcher.Terminal.decode_key(b"\x1b[C"), "RIGHT")
        self.assertEqual(launcher.Terminal.decode_key(b"\x1bOC"), "RIGHT")

    def test_presenter_environment_can_select_the_rpi_fbcon_sdl_build(self):
        environment = launcher.presenter_environment({
            "presenter_ld_library_path": "/opt/sdl12-fbcon/lib",
            "presenter_sdl_videodriver": "fbcon",
            "presenter_sdl_fbdev": "/dev/fb0",
            "presenter_sdl_fb_broken_modes": "1",
            "presenter_sdl_fb_pillarbox": "1",
        })
        self.assertEqual(environment["LD_LIBRARY_PATH"], "/opt/sdl12-fbcon/lib")
        self.assertEqual(environment["SDL_VIDEODRIVER"], "fbcon")
        self.assertEqual(environment["SDL_FBDEV"], "/dev/fb0")
        self.assertEqual(environment["SDL_FB_BROKEN_MODES"], "1")
        self.assertEqual(environment["PI286_SDL_FB_PILLARBOX"], "1")
        self.assertEqual(environment["SDL_AUDIODRIVER"], "alsa")
        self.assertEqual(environment["AUDIODEV"], "plughw:0,0")
        self.assertEqual(environment["SDL_PATH_DSP"], launcher.HDMI_PCM)
        self.assertEqual(environment["SDL_DSP_NOSELECT"], "1")

    def test_remote_launch_has_no_local_dosbox_branch(self):
        source = inspect.getsource(launcher.run_game)
        self.assertIn("run_remote_game", source)
        self.assertNotIn("Popen", source)
        self.assertNotIn("dosbox", source.lower())

    def test_remote_transport_defaults_to_poll_and_accepts_websocket(self):
        self.assertEqual(launcher.remote_transport({}), "poll")
        self.assertEqual(launcher.remote_transport({"remote_dosbox_transport": "websocket"}), "websocket")
        with self.assertRaises(RuntimeError):
            launcher.remote_transport({"remote_dosbox_transport": "udp"})

    def test_menu_includes_the_remote_diagnostic_between_games_and_bye_bye(self):
        source = inspect.getsource(launcher.main)
        self.assertIn("RAINBOW_CAT_LABEL", source)
        self.assertIn("diagnostic_index = len(games)", source)
        self.assertIn("(\"\", False), (RAINBOW_CAT_LABEL", source)
        self.assertIn("run_rainbow_cat(config)", source)
        self.assertIn("pi286-stream-launcher-error.log", source)

    def test_remote_presenter_uses_the_same_fbcon_environment_and_keeps_a_log(self):
        source = inspect.getsource(launcher.run_remote_presenter)
        self.assertIn("presenter_environment(config)", source)
        self.assertIn('/tmp/pi286-stream-presenter.log', source)
        self.assertIn('Path(config["remote_dosbox_token_file"]).expanduser()', source)
        self.assertIn("transport", source)
        self.assertNotIn("ddr_keys", source)

    def test_ddr_button_mapping_is_the_known_pad_layout(self):
        self.assertEqual(launcher.PAD_ACTIONS, {2: "UP", 1: "DOWN", 0: "LEFT", 3: "RIGHT", 8: "START", 9: "SELECT"})
        self.assertEqual(launcher.PAD_LAYOUT[0], (6, "HORE-L"))
        self.assertEqual(launcher.PAD_LAYOUT[-1], (5, "DOLE-P"))
        self.assertTrue(launcher.pad_panic([2, 9]))
        self.assertFalse(launcher.pad_panic([8]))
        self.assertTrue(launcher.known_dance_pad(launcher.PAD_DEVICE_NAME, 2, 10))
        self.assertTrue(launcher.known_dance_pad("USB Gamepad", 2, 10))
        self.assertFalse(launcher.known_dance_pad("USB Gamepad", 2, 8))

    def test_ddr_mapping_loads_labels_for_the_stream_presenter(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            ddr = folder / "ddr.conf"
            ddr.write_text("button0_key=LEFT\nbutton0_label=Doľava\nbutton2_key=UP\nbutton2_label=Skok\nbutton8_key=SPACE\nbutton8_label=Streľba\n")
            game = launcher.Game("Test", "data", "GAME.EXE", ddr_conf=ddr)
            keys, labels = launcher.load_ddr_mapping(game)
            self.assertEqual((keys[0], labels[2], labels[8]), ("LEFT", "Skok", "Streľba"))

    def test_ddr_mapping_rejects_missing_or_select_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            game = launcher.Game("Test", "data", "GAME.EXE", ddr_conf=folder / "ddr.conf")
            with self.assertRaisesRegex(RuntimeError, "Chýba nastavenie DDR"):
                launcher.load_ddr_mapping(game)
            game.ddr_conf.write_text("button9_key=SPACE\n")
            with self.assertRaisesRegex(RuntimeError, "SELECT"):
                launcher.load_ddr_mapping(game)
            game.ddr_conf.write_text("button2_key=AXIS\n")
            with self.assertRaisesRegex(RuntimeError, "Neplatné DDR"):
                launcher.load_ddr_mapping(game)

    def test_pre_game_screen_shows_full_physical_pad_and_slovak_controls(self):
        labels = {button: "nepoužité" for button in range(9)}
        labels.update({2: "Skok", 8: "Streľba"})
        game = launcher.Game("Prehistorik", "", "")
        keys = {button: "" for button in range(9)}
        keys.update({2: "UP", 8: "SPACE"})
        text = "\n".join(line for line, _ in launcher.pre_game_lines(game, labels, keys))
        for physical in ("HORE-L", "HORE: Skok", "HORE-P", "VĽAVO", "VPRAVO", "DOLE-L", "DOLE", "DOLE-P", "TY"):
            self.assertIn(physical, text)
        self.assertIn("SELECT: späť do menu", text)
        self.assertIn("START: Streľba", text)
        self.assertIn("ŠÍPKA HORE: Skok", text)
        self.assertIn("MEDZERNÍK: Streľba", text)
        self.assertTrue(launcher.pre_game_lines(game, labels, keys)[-1][1])

    def test_pre_game_screen_adapts_to_available_input_devices(self):
        labels = {button: "nepoužité" for button in range(9)}
        labels[8] = "Streľba"
        keys = {button: "" for button in range(9)}
        keys[8] = "SPACE"
        game = launcher.Game("Test", "", "")
        pad_only = "\n".join(line for line, _ in launcher.pre_game_lines(game, labels, keys, has_pad=True, has_keyboard=False))
        keyboard_only = "\n".join(line for line, _ in launcher.pre_game_lines(game, labels, keys, has_pad=False, has_keyboard=True))
        self.assertIn("HORE-L", pad_only)
        self.assertNotIn("Klávesnica:", pad_only)
        self.assertIn("START - spustiť hru", pad_only)
        self.assertNotIn("HORE-L", keyboard_only)
        self.assertIn("Klávesnica:", keyboard_only)
        self.assertIn("SPACE - spustiť hru", keyboard_only)

    def test_keyboard_detection_uses_linux_kbd_handler_and_falls_back_on_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            devices = Path(temporary) / "devices"
            devices.write_text("I: Bus=0003\nH: Handlers=sysrq kbd event0\n")
            self.assertTrue(launcher.keyboard_available(devices))
            devices.write_text("I: Bus=0003\nH: Handlers=event1 js0\n")
            self.assertFalse(launcher.keyboard_available(devices))
            self.assertTrue(launcher.keyboard_available(Path(temporary) / "missing"))

    def test_pre_game_accepts_pad_start_without_keyboard_and_select_goes_back(self):
        class FakeTerm:
            def __init__(self, events=()): self.events = list(events)
            def key(self, timeout=None): return self.events.pop(0) if self.events else None
        class FakePad:
            def __init__(self, events): self.events = events
            @property
            def available(self): return True
            def buttons(self): return self.events.pop(0) if self.events else []
        labels = {button: "nepoužité" for button in range(9)}
        game = launcher.Game("Test", "", "")
        original = launcher.Terminal.draw
        launcher.Terminal.draw = lambda *args, **kwargs: None
        try:
            self.assertTrue(launcher.wait_for_game_start(FakeTerm(), FakePad([[8]]), game, labels))
            self.assertFalse(launcher.wait_for_game_start(FakeTerm(), FakePad([[9]]), game, labels))
            self.assertEqual(launcher.wait_for_game_start(FakeTerm(["CTRL_C"]), FakePad([]), game, labels), "exit")
        finally:
            launcher.Terminal.draw = original

    def test_menu_waits_without_redrawing_when_pad_poll_finds_no_input(self):
        source = inspect.getsource(launcher.main)
        self.assertIn("if key is None: continue", source)
        self.assertIn("if redraw:", source)

    def test_discovers_and_sorts_valid_non_helper_games(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dirname, name in (("z", "zebra"), ("a", "Alpha"), ("_helper", "hidden")):
                folder = root / dirname
                folder.mkdir()
                (folder / "game.conf").write_text(
                    "name=%s\ndata_dir=data\nexe=GAME.EXE\n" % name
                )
            self.assertEqual([game.name for game in launcher.discover(root)], ["Alpha", "zebra"])

    def test_included_games_use_the_target_archive_location(self):
        games = launcher.discover(Path(__file__).parents[1] / "games")
        expected = {"Barbarian", "Blockout", "Grand Prix Circuit: Cycles", "Tetris", "Zany Golf"}
        self.assertTrue(expected.issubset({game.name for game in games}))
        for game in games:
            if game.asset_archive:
                self.assertTrue(game.asset_archive.startswith("/home/dietpi/pi-286-game-assets/"))

    def test_discovery_does_not_require_the_executable(self):
        games = launcher.discover(Path(__file__).parents[1] / "games")
        self.assertGreaterEqual(len(games), 3)

    def test_installs_missing_data_directory_from_local_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "game.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("GAME.EXE", "test")
            game = launcher.Game("Test", "data", "GAME.EXE", str(archive))
            data, command = launcher.validate(game, root)
            self.assertEqual(data, root / "data")
            self.assertEqual(command, "GAME.EXE")
            self.assertTrue((data / "GAME.EXE").is_file())

    def test_asset_zip_remains_a_supported_setting_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "game"
            folder.mkdir()
            (folder / "game.conf").write_text("name=Test\ndata_dir=data\nexe=GAME.EXE\nasset_zip=legacy.zip\n")
            self.assertEqual(launcher.discover(root)[0].asset_archive, "legacy.zip")

    def test_existing_data_directory_is_used_without_executable_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            game = launcher.Game("Test", "data", "MISSING.EXE", "/no/such/archive.zip")
            data, command = launcher.validate(game, root)
            self.assertEqual(data, root / "data")
            self.assertEqual(command, "MISSING.EXE")


if __name__ == "__main__":
    unittest.main()
