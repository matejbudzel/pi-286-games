import unittest
from pathlib import Path


class StreamPresenterSourceTests(unittest.TestCase):
    def test_native_presenter_has_websocket_and_poll_transports(self):
        source = (Path(__file__).parents[1] / "streaming/client/pi286-stream-presenter.c").read_text()
        self.assertIn("GET /v3/sessions/%s/stream", source)
        self.assertIn("lws_client_connect_via_info", source)
        self.assertIn("lws_service", source)
        self.assertIn("LWS_CALLBACK_CLIENT_RECEIVE", source)
        self.assertIn("SDL_INIT_EVENTTHREAD", source)
        self.assertIn("Media acknowledgements carry", source)
        self.assertIn("'A' + key - SDLK_a", source)
        self.assertIn("[poll|websocket]", source)
        self.assertIn("input_devices_poll(&input_devices", source)
        self.assertNotIn("SDL_JoystickOpen", source)
        self.assertNotIn("parse_pad_map", source)
        self.assertNotIn("event.key.keysym.sym == SDLK_F8", source)

    def test_raw_keyboard_forwards_dos_keys_except_the_local_f1_panic(self):
        source = (Path(__file__).parents[1] / "streaming/client/input_devices.c").read_text()
        for key in ("KEY_ESC", "KEY_F8", "KEY_KPENTER", "KEY_LEFTMETA"):
            self.assertIn(key, source)
        self.assertIn('events[j].code == KEY_F1', source)
        self.assertIn('if (key && events[j].value != 2) held_update', source)

    def test_native_presenter_uses_the_same_normalized_input_schema_as_web(self):
        source = (Path(__file__).parents[1] / "streaming/client/presenter_protocol.c").read_text()
        self.assertIn(r'\"keyboard_held\":[', source)
        self.assertIn(r'],\"dance_pad_held\":[', source)
        self.assertIn("void pad_update", source)
