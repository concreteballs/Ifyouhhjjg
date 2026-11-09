"""End-to-end packet authentication using standard-library HMAC-SHA256.

Key files are versioned JSON documents. Keep them owner-only and distribute them
through a trusted channel. This module does not encrypt key files at rest.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path


class PacketAuthenticator:
    """Verify packet origin/integrity against a source-endpoint key registry."""

    def __init__(self, source_keys: Mapping[str, bytes]):
        if not isinstance(source_keys, Mapping) or not source_keys:
            raise ValueError("At least one source endpoint key is required")
        self._keys = {}
        for source_id, key in source_keys.items():
            if not isinstance(source_id, str) or not 1 <= len(source_id) <= 256:
                raise ValueError("Source endpoint IDs must contain 1 to 256 characters")
            if not isinstance(key, bytes) or len(key) < 32:
                raise ValueError("Each packet authentication key must contain at least 32 bytes")
            self._keys[source_id] = bytes(key)

    @staticmethod
    def generate_key() -> bytes:
        """Generate a cryptographically random 256-bit HMAC key."""
        return secrets.token_bytes(32)

    @classmethod
    def from_file(cls, key_file):
        path = Path(key_file).expanduser()
        if path.is_symlink():
            raise ValueError("Packet key file must not be a symbolic link")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Packet key file must be a regular file")
            if metadata.st_size > 65536:
                raise ValueError("Packet key file exceeds 64 KiB")
            if os.name == "posix":
                if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
                    raise PermissionError("Packet key file must be owned by the current user and mode 600")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(65537)
        finally:
            os.close(fd)
        if len(raw) > 65536:
            raise ValueError("Packet key file exceeds 64 KiB")

        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate field in packet key file")
                result[key] = value
            return result

        document = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
        if not isinstance(document, dict) or set(document) != {"version", "source_keys"}:
            raise ValueError("Invalid packet key file structure")
        if isinstance(document["version"], bool) or document["version"] != 1:
            raise ValueError("Unsupported packet key file version")
        encoded_keys = document["source_keys"]
        if not isinstance(encoded_keys, dict) or not 1 <= len(encoded_keys) <= 10000:
            raise ValueError("Invalid packet key registry")
        keys = {}
        for source_id, encoded in encoded_keys.items():
            if not isinstance(source_id, str) or not isinstance(encoded, str):
                raise ValueError("Invalid packet key entry")
            try:
                keys[source_id] = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as error:
                raise ValueError("Invalid base64 packet key") from error
        return cls(keys)

    @classmethod
    def write_key_file(cls, key_file, source_keys: Mapping[str, bytes]) -> Path:
        """Atomically write a versioned owner-only key registry.

        Updating the registry replaces the active keys immediately. Coordinate
        the replacement on every participating endpoint before sending packets.
        """
        validated = cls(source_keys)
        path = Path(key_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise ValueError("Packet key file must not be a symbolic link")
        document = {
            "version": 1,
            "source_keys": {
                source_id: base64.b64encode(key).decode("ascii")
                for source_id, key in sorted(validated._keys.items())
            },
        }
        encoded = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > 65536:
            raise ValueError("Packet key registry exceeds 64 KiB")
        fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        temporary = Path(temporary_name)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            if hasattr(os, "O_DIRECTORY"):
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return path
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _message(packet) -> bytes:
        metadata = json.dumps({
            "version": 1,
            "source": packet.source.value,
            "destination": packet.destination.value,
            "packet_type": packet.packet_type.value,
            "packet_id": packet.packet_id,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return (b"SpectralCore.Packet.v1\x00" +
                len(metadata).to_bytes(4, "big") + metadata +
                len(packet.payload).to_bytes(8, "big") + packet.payload)

    def sign(self, packet) -> str:
        key = self._keys.get(packet.source.value)
        if key is None:
            raise KeyError("No authentication key is registered for packet source")
        return hmac.new(key, self._message(packet), hashlib.sha256).hexdigest()

    def verify(self, packet) -> bool:
        if not isinstance(packet.auth_tag, str) or not re.fullmatch(r"[0-9a-f]{64}", packet.auth_tag):
            return False
        key = self._keys.get(packet.source.value)
        if key is None:
            return False
        expected = hmac.new(key, self._message(packet), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, packet.auth_tag)
