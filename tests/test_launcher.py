import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("launcher", Path(__file__).parents[1] / "launcher" / "launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class DiscoveryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
