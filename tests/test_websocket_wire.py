import io
import unittest

from streaming import websocket_wire as wire


class WebSocketWireTests(unittest.TestCase):
    def test_rfc_handshake_example(self):
        self.assertEqual(wire.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_masked_client_frame_round_trips(self):
        packet = wire.pack_frame(b'{"held_keys":["UP"]}', opcode=1, masked=True)
        self.assertEqual(wire.read_frame(io.BytesIO(packet), True), (1, b'{"held_keys":["UP"]}'))

    def test_unmasked_server_frame_round_trips(self):
        packet = wire.pack_frame(b"P2P1", masked=False)
        self.assertEqual(wire.read_frame(io.BytesIO(packet), False), (2, b"P2P1"))
