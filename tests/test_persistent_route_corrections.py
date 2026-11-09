import tempfile
import unittest
from pathlib import Path

from spectral_core import (
    RouteCorrectionAuthority,
    Router,
    SpectralAddress,
    SpectralDatabase,
    SpectralNetwork,
)


class PersistentRouteCorrectionTests(unittest.TestCase):
    def make_network(self, database):
        network = SpectralNetwork(database=database)
        network.add_router(Router("a", (0, 0)))
        network.add_router(Router("b", (1, 0), load=10.0))
        network.add_router(Router("c", (0, 1), load=0.0))
        network.add_router(Router("d", (1, 1)))
        network.connect("a", "b")
        network.connect("b", "d")
        network.connect("a", "c")
        network.connect("c", "d")
        destination = SpectralAddress("987")
        network.register_endpoint(destination, "d")
        return network, destination

    def test_applied_correction_and_nonce_survive_database_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spectral.sqlite3"
            database = SpectralDatabase(path)
            network, destination = self.make_network(database)
            authority = RouteCorrectionAuthority(b"x" * 32)
            message = network.issue_route_correction(
                authority, "packet-1", destination, "a", "b"
            )
            self.assertIsNotNone(message)
            self.assertEqual(message.corrected_next_hop, "c")
            self.assertTrue(network.apply_route_correction(message, authority))
            self.assertEqual(network.choose_next_hop("a", "d", destination), "c")
            database.close()

            reopened = SpectralDatabase(path)
            restored_network, restored_destination = self.make_network(reopened)
            self.assertEqual(
                restored_network.choose_next_hop("a", "d", restored_destination), "c"
            )
            restarted_authority = RouteCorrectionAuthority(b"x" * 32)
            self.assertFalse(
                restored_network.apply_route_correction(message, restarted_authority)
            )
            self.assertEqual(
                restored_network.choose_next_hop("a", "d", restored_destination), "c"
            )
            reopened.close()

    def test_nonce_claim_is_atomic_across_database_connections(self):
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "concurrent.sqlite3"

            def claim(_):
                database = SpectralDatabase(path)
                try:
                    return database.claim_route_correction_nonce(
                        "shared-nonce", 2_000_000_000
                    )
                finally:
                    database.close()

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(claim, range(8)))
            self.assertEqual(sum(results), 1)


if __name__ == "__main__":
    unittest.main()
