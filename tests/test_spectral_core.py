import unittest
from spectral_core import Packet, PacketType, Router, SpectralAddress, SpectralDatabase, SpectralNetwork, SpectralRuntime

class SpectralCoreTests(unittest.TestCase):
    def setUp(self):
        self.a = SpectralAddress("123")
        self.b = SpectralAddress("987")
        self.network = SpectralNetwork()
        for rid, pos in [("r0", (0, 0)), ("r1", (1, 0)), ("r2", (2, 0))]:
            self.network.add_router(Router(rid, pos))
        self.network.connect("r0", "r1")
        self.network.connect("r1", "r2")
        self.network.register_endpoint(self.a, "r0")
        self.network.register_endpoint(self.b, "r2")
        self.database = SpectralDatabase()
        self.runtime = SpectralRuntime(self.network, self.database)

    def tearDown(self):
        self.database.close()

    def test_address_is_exact_and_tail_first(self):
        self.assertEqual(self.a.tail_first, "321")
        self.assertNotEqual(self.a, self.b)

    def test_shortest_path(self):
        self.assertEqual(self.network.shortest_path("r0", "r2"), ["r0", "r1", "r2"])

    def test_packet_delivery_and_database_read(self):
        packet = Packet(self.a, self.b, b"hello")
        self.assertEqual(self.runtime.send(packet), ["r0", "r1", "r2"])
        self.assertEqual(self.runtime.read(self.b), b"hello")

    def test_unknown_endpoint_is_rejected(self):
        with self.assertRaises(KeyError):
            self.network.owner_of(SpectralAddress("555"))

    def test_privileged_packet_types_are_not_trusted_by_flag(self):
        packet = Packet(self.a, self.b, b"detour", packet_type=PacketType.DETOUR)
        with self.assertRaises(PermissionError):
            self.runtime.send(packet)

    def test_hop_limit_is_enforced(self):
        packet = Packet(self.a, self.b, b"too far", hop_limit=1)
        with self.assertRaises(RuntimeError):
            self.runtime.route(packet)

if __name__ == "__main__":
    unittest.main()
