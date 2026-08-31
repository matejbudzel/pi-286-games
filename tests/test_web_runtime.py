import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).parents[1] / "streaming/web/pi286_web_runtime.py"
SPEC = importlib.util.spec_from_file_location("pi286_web_runtime", MODULE)
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


class WebRuntimeTests(unittest.TestCase):
    def test_static_ui_contains_only_expected_public_files(self):
        self.assertEqual(set(web.STATIC_FILES), {"/", "/app.js", "/style.css"})
        for name, _content_type in web.STATIC_FILES.values():
            self.assertTrue((web.STATIC / name).is_file())

    def test_browser_player_has_a_visible_transport_hud(self):
        page = (web.STATIC / "index.html").read_text(encoding="utf-8")
        script = (web.STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="hud"', page)
        self.assertIn("updateHud()", script)
        self.assertIn('event.key === "F8"', script)
        self.assertIn("X-Pi286-Web-Backend-Ms", script)

    def test_diagnostic_session_keeps_lxc_credentials_server_side(self):
        calls = []

        class Backend:
            def start_rainbow_cat(self, scaling):
                calls.append(scaling)
                return {"id": "remote-id"}

        runtime = web.WebRuntime.__new__(web.WebRuntime)
        runtime.backend, runtime.games, runtime.sessions = Backend(), {}, {}
        result = runtime.start("rainbow-cat", "not-a-mode")
        self.assertEqual(calls, ["nearest"])
        self.assertEqual(result["video_scaling"], "nearest")
        self.assertEqual(runtime.sessions[result["id"]], "remote-id")
