import os
import stat
import tempfile
import unittest
from pathlib import Path

from spectral_core.address import SpectralAddress
from spectral_core.database import SpectralDatabase
from spectral_core.monitor import DiagnosticMonitor
from spectral_core.network import Router, SpectralNetwork
from spectral_core.packet import Packet
from spectral_core.runtime import SpectralRuntime


class PersistentReplayProtectionTests(unittest.TestCase):
    def test_packet_receipt_is_atomic_and_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.sqlite3"
            database = SpectralDatabase(path)
            self.assertTrue(database.claim_packet("packet-1", "123", now=100))
            self.assertFalse(database.claim_packet("packet-1", "123", now=101))
            database.close()

            reopened = SpectralDatabase(path)
            self.assertFalse(reopened.claim_packet("packet-1", "123", now=102))
            self.assertTrue(reopened.claim_packet("packet-1", "123", now=105))
            reopened.close()

    def test_file_backed_database_is_owner_only_on_posix(self):
        if os.name != "posix":
            self.skipTest("POSIX file permission semantics are not available")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.sqlite3"
            database = SpectralDatabase(path)
            database.close()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_runtime_rejects_duplicate_packet_id(self):
        with tempfile.TemporaryDirectory() as directory:
            database = SpectralDatabase(Path(directory) / "core.sqlite3")
            network = SpectralNetwork()
            network.add_router(Router("r1", (0, 0)))
            network.add_router(Router("r2", (1, 0)))
            network.connect("r1", "r2")
            source = SpectralAddress("123")
            destination = SpectralAddress("987")
            network.register_endpoint(source, "r1")
            network.register_endpoint(destination, "r2")
            runtime = SpectralRuntime(network, database=database,
                                      monitor=DiagnosticMonitor())
            packet = Packet(source, destination, b"payload")

            self.assertEqual(runtime.send(packet), ["r1", "r2"])
            with self.assertRaises(PermissionError):
                runtime.send(packet)
            self.assertEqual(database.get(destination), b"payload")
            database.close()


if __name__ == "__main__":
    unittest.main()
