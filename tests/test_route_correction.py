import unittest
from dataclasses import replace

from spectral_core.address import SpectralAddress
from spectral_core.network import Router, SpectralNetwork
from spectral_core.route_correction import RouteCorrectionAuthority


class AuthenticatedRouteCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.network = SpectralNetwork()
        for router_id, position in (
            ("r0", (0, 0)), ("r1", (1, 0)),
            ("r2", (0, 1)), ("r3", (1, 1)),
        ):
            self.network.add_router(Router(router_id, position))
        self.network.connect("r0", "r1")
        self.network.connect("r0", "r2")
        self.network.connect("r1", "r3")
        self.network.connect("r2", "r3")
        self.network.set_load("r1", 10)
        self.source = SpectralAddress("123")
        self.destination = SpectralAddress("987")
        self.network.register_endpoint(self.source, "r0")
        self.network.register_endpoint(self.destination, "r3")
        self.authority = RouteCorrectionAuthority(b"c" * 32)

    def test_authenticated_correction_is_applied_to_previous_router(self):
        message = self.network.issue_route_correction(
            self.authority, "packet-42", self.destination, "r0", "r1"
        )
        self.assertIsNotNone(message)
        self.assertTrue(self.network.apply_route_correction(message, self.authority))
        self.assertEqual(self.network.choose_next_hop("r0", "r3", self.destination), "r2")
        self.assertFalse(self.network.apply_route_correction(message, self.authority))

    def test_tampered_and_non_neighbour_corrections_are_rejected(self):
        valid = self.network.issue_route_correction(
            self.authority, "packet-43", self.destination, "r0", "r1"
        )
        tampered = replace(valid, corrected_next_hop="r1", signature="0" * 64)
        self.assertFalse(self.network.apply_route_correction(tampered, self.authority))

        invalid_topology = self.authority.issue(
            packet_id="packet-44", destination_id=self.destination.value,
            previous_router="r0", reporting_router="r1",
            rejected_next_hop="r1", corrected_next_hop="r3",
        )
        self.assertFalse(self.network.apply_route_correction(invalid_topology, self.authority))

    def test_correction_is_scoped_to_packet_destination_and_topology(self):
        message = self.network.issue_route_correction(
            self.authority, "packet-45", self.destination, "r0", "r1"
        )
        self.assertTrue(self.network.apply_route_correction(message, self.authority))
        other_destination = SpectralAddress("111")
        self.assertEqual(self.network.choose_next_hop("r0", "r3", other_destination), "r2")


if __name__ == "__main__":
    unittest.main()
