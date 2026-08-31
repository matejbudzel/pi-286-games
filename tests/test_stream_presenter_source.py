import unittest
from pathlib import Path


class StreamPresenterSourceTests(unittest.TestCase):
    def test_native_presenter_has_websocket_and_poll_transports(self):
        source = (Path(__file__).parents[1] / "streaming/client/pi286-stream-presenter.c").read_text()
        self.assertIn("GET /v3/sessions/%s/stream", source)
        self.assertIn("websocket_send_text", source)
        self.assertIn("websocket_take_frame", source)
        self.assertIn("O_NONBLOCK", source)
        self.assertIn("SDL_INIT_EVENTTHREAD", source)
        self.assertIn("Media acknowledgements carry", source)
        self.assertIn("'A' + key - SDLK_a", source)
        self.assertIn("[poll|websocket]", source)
