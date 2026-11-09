import tempfile
import unittest
from pathlib import Path

from spectral_core.address import SpectralAddress
from spectral_core.database import SpectralDatabase
from spectral_core.monitor import DiagnosticMonitor
from spectral_core.network import Router, SpectralNetwork
from spectral_core.packet import Packet, PacketType
from spectral_core.packet_auth import PacketAuthenticator
from spectral_core.runtime import SpectralRuntime


class PacketAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.source = SpectralAddress("123")
        self.destination = SpectralAddress("987")
        self.authenticator = PacketAuthenticator({"123": b"s" * 32})

    def test_hmac_verifies_and_survives_mutable_hop_limit(self):
        packet = Packet(self.source, self.destination, b"hello", hop_limit=8)
        packet.auth_tag = self.authenticator.sign(packet)
        self.assertTrue(self.authenticator.verify(packet))
        forwarded = packet.forwarded()
        self.assertEqual(forwarded.hop_limit, 7)
        self.assertTrue(self.authenticator.verify(forwarded))

    def test_payload_destination_and_type_tampering_are_rejected(self):
        packet = Packet(self.source, self.destination, b"hello")
        packet.auth_tag = self.authenticator.sign(packet)

        altered_payload = Packet(self.source, self.destination, b"changed",
                                 auth_tag=packet.auth_tag)
        altered_destination = Packet(self.source, SpectralAddress("111"), b"hello",
                                     auth_tag=packet.auth_tag)
        altered_type = Packet(self.source, self.destination, b"hello",
                              packet_type=PacketType.DETOUR, auth_tag=packet.auth_tag)
        altered_id = Packet(self.source, self.destination, b"hello", packet_id="different-id",
                            auth_tag=packet.auth_tag)

        self.assertFalse(self.authenticator.verify(altered_payload))
        self.assertFalse(self.authenticator.verify(altered_destination))
        self.assertFalse(self.authenticator.verify(altered_type))
        self.assertFalse(self.authenticator.verify(altered_id))

    def test_unsigned_packet_is_rejected_when_authenticator_is_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            database = SpectralDatabase(Path(directory) / "core.sqlite3")
            network = SpectralNetwork()
            network.add_router(Router("r1", (0, 0)))
            network.add_router(Router("r2", (1, 0)))
            network.connect("r1", "r2")
            network.register_endpoint(self.source, "r1")
            network.register_endpoint(self.destination, "r2")
            runtime = SpectralRuntime(
                network, database=database, monitor=DiagnosticMonitor(),
                packet_authenticator=self.authenticator,
            )
            with self.assertRaises(PermissionError):
                runtime.send(Packet(self.source, self.destination, b"unsigned"))
            self.assertIsNone(database.get(self.destination))
            database.close()

    def test_runtime_write_signs_packet_in_configured_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            database = SpectralDatabase(Path(directory) / "core.sqlite3")
            network = SpectralNetwork()
            network.add_router(Router("r1", (0, 0)))
            network.add_router(Router("r2", (1, 0)))
            network.connect("r1", "r2")
            network.register_endpoint(self.source, "r1")
            network.register_endpoint(self.destination, "r2")
            runtime = SpectralRuntime(
                network, database=database, monitor=DiagnosticMonitor(),
                packet_authenticator=self.authenticator,
            )
            self.assertEqual(runtime.write(self.source, self.destination, b"signed"),
                             ["r1", "r2"])
            self.assertEqual(database.get(self.destination), b"signed")
            database.close()


if __name__ == "__main__":
    unittest.main()
