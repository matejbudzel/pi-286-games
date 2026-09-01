import unittest

from streaming.client.remote_api import RemoteBackend, RemoteProtocolError


class RemoteApiTests(unittest.TestCase):

    def test_rainbow_cat_uses_the_asset_free_diagnostic_endpoint(self):
        backend = RemoteBackend("http://example.test", "token")
        calls = []
        backend.json = lambda method, path, payload=None: calls.append((method, path, payload)) or {"id": "diagnostic"}
        self.assertEqual(backend.start_rainbow_cat(), {"id": "diagnostic"})
        self.assertEqual(calls, [("POST", "/v1/diagnostics/rainbow-cat",
                                  {"video_scaling": "nearest", "transport": "poll"})])

    def test_session_and_diagnostic_send_the_requested_scaling(self):
        backend = RemoteBackend("http://example.test", "token")
        calls = []
        backend.json = lambda method, path, payload=None: calls.append((method, path, payload)) or {"id": "session"}
        backend.start_session("gp", "crt-lite")
        backend.start_rainbow_cat("linear-v")
        self.assertEqual(calls[0][2]["video_scaling"], "crt-lite")
        self.assertEqual(calls[0][2]["transport"], "poll")
        self.assertEqual(calls[1][2]["video_scaling"], "linear-v")
        self.assertEqual(calls[0][2], {"game_id": "gp", "video_scaling": "crt-lite", "transport": "poll"})

    def test_session_stop_uses_a_shutdown_timeout_longer_than_health_checks(self):
        backend = RemoteBackend("http://example.test", "token")
        calls = []
        backend.json = lambda method, path, payload=None, timeout=None: calls.append((method, path, payload, timeout)) or {"stopped": True}
        self.assertEqual(backend.stop_session("demo"), {"stopped": True})
        self.assertEqual(calls, [("DELETE", "/v1/sessions/demo", None, 5.0)])

    def test_backend_rejects_non_http_or_empty_credentials(self):
        with self.assertRaises(ValueError):
            RemoteBackend("https://server", "token")
        with self.assertRaises(ValueError):
            RemoteBackend("http://server", "")
