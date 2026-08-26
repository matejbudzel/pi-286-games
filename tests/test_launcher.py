import importlib.util
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
