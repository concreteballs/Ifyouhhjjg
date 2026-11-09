import os
import stat
import tempfile
import unittest
from pathlib import Path

from spectral_core import SpectralAddress, SpectralDatabase


@unittest.skipUnless(os.name == "posix", "POSIX permission checks")
class SQLiteRecoveryAndPermissionsTests(unittest.TestCase):
    def test_backup_restore_recovers_application_and_security_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live_path = root / "live.sqlite3"
            backup_path = root / "backup.sqlite3"
            restored_path = root / "restored.sqlite3"
            database = SpectralDatabase(live_path)
            address = SpectralAddress("123")
            database.put(address, b"endpoint-payload")
            self.assertTrue(database.claim_packet("packet-1", "source-1", now=100))
            self.assertTrue(database.claim_route_correction_nonce("nonce-1", 500, now=100))
            self.assertTrue(database.put_route_correction(
                "router-a", "destination-1", "router-b", "router-c", 500, now=100
            ))

            database.backup_to(backup_path)
            self.assertEqual(stat.S_IMODE(backup_path.stat().st_mode), 0o600)
            database.close()

            SpectralDatabase.restore_from(backup_path, restored_path)
            self.assertEqual(stat.S_IMODE(restored_path.stat().st_mode), 0o600)
            restored = SpectralDatabase(restored_path)
            self.assertEqual(restored.get(address), b"endpoint-payload")
            self.assertFalse(restored.claim_packet("packet-1", "source-1", now=101))
            self.assertFalse(restored.claim_route_correction_nonce("nonce-1", 500, now=101))
            self.assertEqual(
                restored.load_route_corrections(now=101),
                [("router-a", "destination-1", "router-b", "router-c", 500)],
            )
            self.assertEqual(
                restored.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )
            restored.close()

    def test_wal_and_shm_sidecars_are_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wal.sqlite3"
            database = SpectralDatabase(path, journal_mode="WAL")
            database.put(SpectralAddress("456"), b"wal-payload")
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(path) + suffix)
                self.assertTrue(sidecar.exists(), suffix)
                self.assertTrue(stat.S_ISREG(sidecar.stat().st_mode))
                self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600, suffix)
            database.close()

    def test_rollback_journal_is_owner_only_while_transaction_is_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delete.sqlite3"
            database = SpectralDatabase(path, journal_mode="DELETE")
            database.connection.execute("BEGIN IMMEDIATE")
            database.connection.execute(
                "INSERT INTO endpoint_data(spectral_id, payload) VALUES (?, ?)",
                ("789", b"journal-payload"),
            )
            journal = Path(str(path) + "-journal")
            self.assertTrue(journal.exists())
            self.assertTrue(stat.S_ISREG(journal.stat().st_mode))
            self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
            database.connection.rollback()
            database.close()


if __name__ == "__main__":
    unittest.main()
