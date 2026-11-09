"""SQLite-backed endpoint store with restrictive file permissions and replay receipts."""
import os
import sqlite3
import stat
import tempfile
import time
from pathlib import Path
from typing import Optional, Union
from .address import SpectralAddress


class SpectralDatabase:
    def __init__(self, path: Union[str, Path] = ":memory:"):
        self.path = str(path)
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
        self.connection = sqlite3.connect(self.path)
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
        self.connection.commit()
        if self.path != ":memory:" and hasattr(os, "chmod"):
            os.chmod(self.path, 0o600)

    def put(self, address: SpectralAddress, payload: bytes):
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        self.connection.execute("""
            INSERT INTO endpoint_data (spectral_id, payload) VALUES (?, ?)
            ON CONFLICT(spectral_id) DO UPDATE SET
                payload = excluded.payload, updated_at = CURRENT_TIMESTAMP
        """, (address.value, sqlite3.Binary(payload)))
        self.connection.commit()

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
            return accepted
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

    def close(self):
        self.connection.close()
