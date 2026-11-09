import unittest
from spectral_core import (
    DiagnosticMonitor, Packet, PacketType, Router, SpectralAddress,
    SpectralDatabase, SpectralNetwork, SpectralRuntime,
)

class SpectralCoreTests(unittest.TestCase):
    def setUp(self):
        self.a = SpectralAddress("123")
        self.b = SpectralAddress("987")
        self.monitor = DiagnosticMonitor()
        self.network = SpectralNetwork()
        for rid, pos in [("r0", (0, 0)), ("r1", (1, 0)), ("r2", (2, 0))]:
            self.network.add_router(Router(rid, pos))
        self.network.connect("r0", "r1")
        self.network.connect("r1", "r2")
        self.network.register_endpoint(self.a, "r0")
        self.network.register_endpoint(self.b, "r2")
        self.database = SpectralDatabase()
        self.runtime = SpectralRuntime(self.network, self.database, self.monitor)

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

    def test_monitor_records_real_packet_lifecycle_without_payload(self):
        packet = Packet(self.a, self.b, b"PRIVATE-DATA-MUST-NOT-BE-LOGGED")
        self.runtime.send(packet)
        report = self.monitor.export_jsonl()
        self.assertIn('"event": "route_started"', report)
        self.assertIn('"event": "route_hop"', report)
        self.assertIn('"event": "packet_delivered"', report)
        self.assertNotIn("PRIVATE-DATA-MUST-NOT-BE-LOGGED", report)

    def test_monitor_records_rejected_packet(self):
        packet = Packet(self.a, self.b, b"blocked", packet_type=PacketType.CONTROL)
        with self.assertRaises(PermissionError):
            self.runtime.send(packet)
        self.assertTrue(any(e["event"] == "packet_rejected" for e in self.monitor.events()))

    def test_monitor_health_check(self):
        result = self.runtime.run_diagnostics()
        self.assertTrue(result["data"]["healthy"])
        self.assertEqual(result["data"]["checks"]["topology"], "ok")

if __name__ == "__main__":
    unittest.main()
