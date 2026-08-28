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
    def test_boolean_host_settings(self):
        self.assertFalse(launcher.enabled("false"))
        self.assertTrue(launcher.enabled("true"))
        self.assertTrue(launcher.enabled("ON"))

    def test_renderer_line_never_exceeds_terminal_width(self):
        self.assertEqual(launcher.Terminal.line("A very long title", True, 5), "> A v")
        self.assertLessEqual(len(launcher.Terminal.line("A very long title", True, 5)), 5)
        self.assertLessEqual(len(launcher.Terminal.line("A very long title", False, 1)), 1)

    def test_game_running_screen_names_game_and_panic_key(self):
        captured = []
        original = launcher.Terminal.draw
        launcher.Terminal.draw = lambda lines, color="\x1b[96m", corner="": captured.extend(lines)
        try:
            launcher.game_running_screen(launcher.Game("Prince of Persia", "", "", Path(), Path()), "F1")
        finally:
            launcher.Terminal.draw = original
        self.assertIn(("Je spustená hra", False), captured)
        self.assertIn(("Prince of Persia", True), captured)
        self.assertIn(("Ak ju chceš ukončiť, stlač F1.", False), captured)

    def test_console_reset_discards_a_framebuffer_games_last_frame(self):
        captured = []
        original_write, original_flush = launcher.sys.stdout.write, launcher.sys.stdout.flush
        launcher.sys.stdout.write = captured.append
        launcher.sys.stdout.flush = lambda: None
        try:
            launcher.restore_console_display()
        finally:
            launcher.sys.stdout.write, launcher.sys.stdout.flush = original_write, original_flush
        self.assertEqual(captured, ["\x1bc"])

    def test_dosbox_environment_can_select_the_rpi_fbcon_sdl_build(self):
        environment = launcher.dosbox_environment({
            "dosbox_ld_library_path": "/opt/sdl12-fbcon/lib",
            "dosbox_sdl_videodriver": "fbcon",
            "dosbox_sdl_fbdev": "/dev/fb0",
            "dosbox_sdl_fb_broken_modes": "1",
        })
        self.assertEqual(environment["LD_LIBRARY_PATH"], "/opt/sdl12-fbcon/lib")
        self.assertEqual(environment["SDL_VIDEODRIVER"], "fbcon")
        self.assertEqual(environment["SDL_FBDEV"], "/dev/fb0")
        self.assertEqual(environment["SDL_FB_BROKEN_MODES"], "1")

    def test_generated_dosbox_config_has_the_appliance_safe_video_values(self):
        config = launcher.generated_dosbox_config(Path("mapper.txt"), Path("/games/test"), "GAME.EXE")
        for line in ("fullscreen=true", "fulldouble=false", "fullfixed=true", "fullresolution=640x480", "output=surface", "usescancodes=false", "frameskip=0", "aspect=false", "scaler=none"):
            self.assertIn(line, config)

    def test_generated_dosbox_config_only_adds_overrides_to_game_config(self):
        game_config = (Path(__file__).parents[1] / "games" / "barbarian" / "dosbox.conf").read_text()
        generated = launcher.generated_dosbox_config(Path("mapper.txt"), Path("/games/test"), "GAME.EXE")
        combined = game_config + "\n" + generated
        self.assertIn("machine=ega", combined)
        self.assertIn("memsize=8", combined)
        self.assertIn("cycles=fixed 3000", combined)
        self.assertIn("scaler=none", combined)

    def test_dosbox_launch_does_not_detach_from_tty1(self):
        source = inspect.getsource(launcher.run_game)
        self.assertNotIn("preexec_fn=", source)
        self.assertNotIn("setsid", source)
        self.assertNotIn("setpgrp", source)

    def test_discovers_and_sorts_valid_non_helper_games(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dirname, name in (("z", "zebra"), ("a", "Alpha"), ("_helper", "hidden")):
                folder = root / dirname
                folder.mkdir()
                (folder / "game.conf").write_text(
                    "name=%s\ndata_dir=data\nexe=GAME.EXE\ndosbox_conf=dosbox.conf\nmapper_file=mapper.txt\n" % name
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
            game = launcher.Game("Test", "data", "GAME.EXE", Path("dosbox.conf"), Path("mapper.txt"), str(archive))
            data, command = launcher.validate(game, root)
            self.assertEqual(data, root / "data")
            self.assertEqual(command, "GAME.EXE")
            self.assertTrue((data / "GAME.EXE").is_file())

    def test_asset_zip_remains_a_supported_setting_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "game"
            folder.mkdir()
            (folder / "game.conf").write_text("name=Test\ndata_dir=data\nexe=GAME.EXE\ndosbox_conf=dosbox.conf\nmapper_file=mapper.txt\nasset_zip=legacy.zip\n")
            self.assertEqual(launcher.discover(root)[0].asset_archive, "legacy.zip")

    def test_existing_data_directory_is_used_without_executable_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            game = launcher.Game("Test", "data", "MISSING.EXE", Path("dosbox.conf"), Path("mapper.txt"), "/no/such/archive.zip")
            data, command = launcher.validate(game, root)
            self.assertEqual(data, root / "data")
            self.assertEqual(command, "MISSING.EXE")


if __name__ == "__main__":
    unittest.main()
