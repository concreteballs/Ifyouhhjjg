import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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
            self.assertTrue(database.claim_packet("packet-1", "123", retention_seconds=5, now=100))
            self.assertFalse(database.claim_packet("packet-1", "123", now=101))
            database.close()

            reopened = SpectralDatabase(path)
            self.assertFalse(reopened.claim_packet("packet-1", "123", now=102))
            self.assertTrue(reopened.claim_packet("packet-1", "123", now=105))
            reopened.close()

    def test_concurrent_connections_accept_packet_id_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.sqlite3"
            setup = SpectralDatabase(path)
            setup.close()

            def claim(_):
                database = SpectralDatabase(path)
                try:
                    return database.claim_packet("same-packet", "123")
                finally:
                    database.close()

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(claim, range(8)))
            self.assertEqual(sum(results), 1)

    def test_file_backed_database_is_owner_only_on_posix(self):
        if os.name != "posix":
            self.skipTest("POSIX file permission semantics are not available")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.sqlite3"
            database = SpectralDatabase(path)
            database.close()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_atomic_backup_preserves_data_and_replay_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "live.sqlite3"
            backup_path = Path(directory) / "backups" / "snapshot.sqlite3"
            source = SpectralDatabase(source_path)
            address = SpectralAddress("123")
            source.put(address, b"saved-value")
            self.assertTrue(source.claim_packet("saved-packet", "123"))
            self.assertEqual(source.backup_to(backup_path), backup_path)
            source.close()

            restored = SpectralDatabase(backup_path)
            self.assertEqual(restored.get(address), b"saved-value")
            self.assertFalse(restored.claim_packet("saved-packet", "123"))
            restored.close()

            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(backup_path.stat().st_mode), 0o600)

    def test_backup_rejects_live_database_path_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            live_path = Path(directory) / "live.sqlite3"
            database = SpectralDatabase(live_path)
            with self.assertRaises(ValueError):
                database.backup_to(live_path)
            if hasattr(os, "symlink"):
                link_path = Path(directory) / "backup-link.sqlite3"
                link_path.symlink_to(Path(directory) / "target.sqlite3")
                with self.assertRaises(ValueError):
                    database.backup_to(link_path)
            database.close()

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
