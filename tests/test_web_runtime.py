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
        self.assertIn('id="panic"', page)
        self.assertIn('id="hud-toggle"', page)
        self.assertIn('id="virtual-pad"', page)
        self.assertIn('data-pad-button="6"', page)
        self.assertIn('id="pad-select"', page)
        self.assertIn('id="pad-start"', page)
        self.assertIn('value="crt-lite" selected', page)
        self.assertIn('value="websocket" selected', page)
        self.assertIn("updateHud()", script)
        self.assertIn('event.key === "F8"', script)
        self.assertIn("X-Pi286-Web-Backend-Ms", script)
        self.assertIn("Do not acknowledge data", script)
        self.assertIn("nextAudioOffset", script)
        self.assertIn("never queue that PCM", script)
        self.assertIn("audio: zaradené", script)
        self.assertIn('querySelector("#panic")', script)
        self.assertIn("function toggleHud()", script)
        self.assertIn("keyboard_held", script)
        self.assertIn("dance_pad_held", script)
        self.assertIn('NumpadEnter: "KP_ENTER"', script)
        self.assertIn('querySelector("#pad-select")', script)
        self.assertIn("setHeldSource", script)
        self.assertIn("pointerdown", script)
        self.assertIn("audioBufferTarget = .35", script)

    def test_session_uses_only_the_server_game_id(self):
        calls = []

        class Backend:
            def start_session(self, game_id, scaling, transport):
                calls.append((game_id, scaling, transport))
                return {"id": "remote-id"}

        runtime = web.WebRuntime.__new__(web.WebRuntime)
        runtime.backend, runtime.sessions = Backend(), {}
        result = runtime.start("grand-prix", "not-a-mode")
        self.assertEqual(calls, [("grand-prix", "nearest", "poll")])
        self.assertEqual(result["video_scaling"], "nearest")
        self.assertEqual(runtime.sessions[result["id"]], "remote-id")
