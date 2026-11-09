"""SQLite-backed endpoint data store; no external server is required."""
import sqlite3
from pathlib import Path
from typing import Optional, Union
from .address import SpectralAddress

class SpectralDatabase:
    def __init__(self, path: Union[str, Path] = ":memory:"):
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS endpoint_data (
                spectral_id TEXT PRIMARY KEY,
                payload BLOB NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.connection.commit()

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

    def close(self):
        self.connection.close()
