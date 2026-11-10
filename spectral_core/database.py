"""SQLite-backed endpoint store with restrictive file permissions and replay receipts."""
import os
import sqlite3
import stat
import tempfile
import time
from pathlib import Path
from typing import Optional, Union
from .address import SpectralAddress
from .spectral_field import SpectralFieldStore


class SpectralDatabase:
    def __init__(self, path: Union[str, Path] = ":memory:", journal_mode: str = "DELETE"):
        self.path = str(path)
        journal_mode = str(journal_mode).upper()
        if journal_mode not in {"DELETE", "WAL"}:
            raise ValueError("journal_mode must be DELETE or WAL")
        if self.path != ":memory:":
            database_path = Path(path).expanduser()
            flags = os.O_RDWR | os.O_CREAT
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(database_path, flags, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("Database path must refer to a regular file")
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            self.path = str(database_path)
        self.connection = sqlite3.connect(self.path, timeout=30.0)
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute(f"PRAGMA journal_mode = {journal_mode}")
        self._secure_sqlite_files()
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS endpoint_data (
                spectral_id TEXT PRIMARY KEY,
                payload BLOB NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS packet_receipts (
                packet_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS packet_receipts_expiry ON packet_receipts(expires_at)"
        )
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS route_correction_nonces (
                nonce TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL
            )
        """)
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS route_correction_nonces_expiry ON route_correction_nonces(expires_at)"
        )
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS applied_route_corrections (
                previous_router TEXT NOT NULL,
                destination_id TEXT NOT NULL,
                rejected_next_hop TEXT NOT NULL,
                corrected_next_hop TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (previous_router, destination_id)
            )
        """)
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS applied_route_corrections_expiry ON applied_route_corrections(expires_at)"
        )
        # Commit the base-store schema before acquiring the spectral migration lock.
        self.connection.commit()
        self.spectral_field = SpectralFieldStore(self.connection)
        self.connection.commit()
        self._secure_sqlite_files()

    def _secure_sqlite_files(self):
        """Keep the database and SQLite sidecar files owner-only on POSIX."""
        if self.path == ":memory:" or os.name != "posix":
            return
        for candidate in (self.path, self.path + "-journal", self.path + "-wal", self.path + "-shm"):
            try:
                info = os.lstat(candidate)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("SQLite database and sidecars must be regular files")
            os.chmod(candidate, 0o600, follow_symlinks=False)

    def put(self, address: SpectralAddress, payload: bytes):
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        self.connection.execute("""
            INSERT INTO endpoint_data (spectral_id, payload) VALUES (?, ?)
            ON CONFLICT(spectral_id) DO UPDATE SET
                payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
        """, (address.value, sqlite3.Binary(payload)))
        self.connection.commit()
        self._secure_sqlite_files()

    def get(self, address: SpectralAddress) -> Optional[bytes]:
        row = self.connection.execute(
            "SELECT payload FROM endpoint_data WHERE spectral_id = ?",
            (address.value,)
        ).fetchone()
        return bytes(row[0]) if row is not None else None

    def delete(self, address: SpectralAddress):
        cursor = self.connection.execute(
            "DELETE FROM endpoint_data WHERE spectral_id = ?", (address.value,)
        )
        self.connection.commit()
        self._secure_sqlite_files()
        return cursor.rowcount > 0

    def claim_packet(self, packet_id: str, source_id: str,
                     retention_seconds: int = 86400, now: Optional[int] = None) -> bool:
        """Atomically claim a packet ID once; receipts survive process restarts.

        A failed downstream route still consumes the ID. Senders must create a
        new packet ID for a deliberate retry.
        """
        if not isinstance(packet_id, str) or not 1 <= len(packet_id) <= 128:
            raise ValueError("packet_id must be a non-empty string of at most 128 characters")
        if not isinstance(source_id, str) or not 1 <= len(source_id) <= 256:
            raise ValueError("source_id must be a non-empty string of at most 256 characters")
        if isinstance(retention_seconds, bool) or not isinstance(retention_seconds, int) or retention_seconds < 1:
            raise ValueError("retention_seconds must be a positive integer")
        current = int(time.time()) if now is None else now
        if isinstance(current, bool) or not isinstance(current, int) or current < 0:
            raise ValueError("now must be a non-negative integer")
        expires_at = current + retention_seconds
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "DELETE FROM packet_receipts WHERE expires_at <= ?", (current,)
            )
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO packet_receipts(packet_id, source_id, expires_at) VALUES (?, ?, ?)",
                (packet_id, source_id, expires_at),
            )
            accepted = cursor.rowcount == 1
            self.connection.commit()
            self._secure_sqlite_files()
            return accepted
        except Exception:
            self.connection.rollback()
            raise

    def claim_route_correction_nonce(self, nonce: str, expires_at: int,
                                     now: Optional[int] = None) -> bool:
        """Atomically consume a signed control-message nonce across restarts/processes."""
        if not isinstance(nonce, str) or not 1 <= len(nonce) <= 128:
            raise ValueError("nonce must be a non-empty string of at most 128 characters")
        if isinstance(expires_at, bool) or not isinstance(expires_at, int):
            raise ValueError("expires_at must be an integer")
        current = int(time.time()) if now is None else now
        if isinstance(current, bool) or not isinstance(current, int) or current < 0:
            raise ValueError("now must be a non-negative integer")
        if expires_at <= current:
            return False
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "DELETE FROM route_correction_nonces WHERE expires_at <= ?", (current,)
            )
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO route_correction_nonces(nonce, expires_at) VALUES (?, ?)",
                (nonce, expires_at),
            )
            accepted = cursor.rowcount == 1
            self.connection.commit()
            self._secure_sqlite_files()
            return accepted
        except Exception:
            self.connection.rollback()
            raise

    def put_route_correction(self, previous_router: str, destination_id: str,
                             rejected_next_hop: str, corrected_next_hop: str,
                             expires_at: int, now: Optional[int] = None) -> bool:
        """Persist an active correction; reject a conflicting live correction atomically."""
        values = (previous_router, destination_id, rejected_next_hop, corrected_next_hop)
        if any(not isinstance(value, str) or not value or len(value) > 256 for value in values):
            raise ValueError("route-correction identifiers must be non-empty bounded strings")
        if isinstance(expires_at, bool) or not isinstance(expires_at, int):
            raise ValueError("expires_at must be an integer")
        current = int(time.time()) if now is None else now
        if isinstance(current, bool) or not isinstance(current, int) or current < 0:
            raise ValueError("now must be a non-negative integer")
        if expires_at <= current:
            return False
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "DELETE FROM applied_route_corrections WHERE expires_at <= ?", (current,)
            )
            row = self.connection.execute(
                """SELECT corrected_next_hop FROM applied_route_corrections
                   WHERE previous_router = ? AND destination_id = ?""",
                (previous_router, destination_id),
            ).fetchone()
            if row is not None and row[0] != corrected_next_hop:
                self.connection.rollback()
                return False
            self.connection.execute(
                """INSERT INTO applied_route_corrections
                   (previous_router, destination_id, rejected_next_hop, corrected_next_hop, expires_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(previous_router, destination_id) DO UPDATE SET
                     rejected_next_hop = excluded.rejected_next_hop,
                     corrected_next_hop = excluded.corrected_next_hop,
                     expires_at = MAX(applied_route_corrections.expires_at, excluded.expires_at)""",
                (previous_router, destination_id, rejected_next_hop, corrected_next_hop, expires_at),
            )
            self.connection.commit()
            self._secure_sqlite_files()
            return True
        except Exception:
            self.connection.rollback()
            raise

    def load_route_corrections(self, now: Optional[int] = None):
        """Return unexpired persisted corrections and atomically discard expired rows."""
        current = int(time.time()) if now is None else now
        if isinstance(current, bool) or not isinstance(current, int) or current < 0:
            raise ValueError("now must be a non-negative integer")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "DELETE FROM applied_route_corrections WHERE expires_at <= ?", (current,)
            )
            rows = self.connection.execute(
                """SELECT previous_router, destination_id, rejected_next_hop,
                          corrected_next_hop, expires_at
                   FROM applied_route_corrections WHERE expires_at > ?
                   ORDER BY previous_router, destination_id""",
                (current,),
            ).fetchall()
            self.connection.commit()
            self._secure_sqlite_files()
            return rows
        except Exception:
            self.connection.rollback()
            raise

    def backup_to(self, target_path: Union[str, Path]) -> Path:
        """Create an atomic, owner-only SQLite backup at target_path."""
        target = Path(target_path).expanduser()
        if self.path != ":memory:" and target.resolve() == Path(self.path).resolve():
            raise ValueError("Backup target must differ from the live database")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.is_symlink():
            raise ValueError("Backup target must not be a symbolic link")
        fd, temporary_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
        )
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            destination = sqlite3.connect(str(temporary))
            try:
                self.connection.backup(destination)
                destination.commit()
            finally:
                destination.close()
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            os.chmod(target, 0o600)
            if hasattr(os, "O_DIRECTORY"):
                directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def restore_from(cls, backup_path: Union[str, Path],
                     target_path: Union[str, Path]) -> Path:
        """Restore a verified SQLite backup atomically to a separate database path.

        The target database must be closed/not in use. The backup is never modified.
        """
        source = Path(backup_path).expanduser()
        target = Path(target_path).expanduser()
        if source.is_symlink() or not source.is_file():
            raise ValueError("Backup source must be a regular non-symlink file")
        if source.resolve() == target.resolve():
            raise ValueError("Restore target must differ from backup source")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.is_symlink():
            raise ValueError("Restore target must not be a symbolic link")
        if target.exists() or any(Path(str(target) + suffix).exists()
                                  for suffix in ("-journal", "-wal", "-shm")):
            raise ValueError("Restore target and SQLite sidecars must not already exist")
        fd, temporary_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".restore.tmp", dir=str(target.parent)
        )
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            source_uri = source.resolve().as_uri() + "?mode=ro"
            origin = sqlite3.connect(source_uri, uri=True)
            try:
                check = origin.execute("PRAGMA integrity_check").fetchone()
                if check is None or check[0] != "ok":
                    raise ValueError("Backup failed SQLite integrity_check")
                destination = sqlite3.connect(str(temporary))
                try:
                    origin.backup(destination)
                    destination.commit()
                    restored_check = destination.execute("PRAGMA integrity_check").fetchone()
                    if restored_check is None or restored_check[0] != "ok":
                        raise ValueError("Restored database failed SQLite integrity_check")
                finally:
                    destination.close()
            finally:
                origin.close()
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            os.chmod(target, 0o600)
            if hasattr(os, "O_DIRECTORY"):
                directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    def close(self):
        self.connection.close()
