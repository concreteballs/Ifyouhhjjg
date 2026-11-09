"""End-to-end packet authentication using standard-library HMAC-SHA256.

Keys are injected by the application and must be provisioned out of band.
This prototype deliberately does not persist, distribute, rotate, or revoke keys.
"""
import hashlib
import hmac
import json
import re
from collections.abc import Mapping


class PacketAuthenticator:
    """Verify packet origin/integrity against a source-endpoint key registry."""

    def __init__(self, source_keys: Mapping[str, bytes]):
        if not isinstance(source_keys, Mapping) or not source_keys:
            raise ValueError("At least one source endpoint key is required")
        self._keys = {}
        for source_id, key in source_keys.items():
            if not isinstance(source_id, str) or not source_id:
                raise ValueError("Source endpoint IDs must be non-empty strings")
            if not isinstance(key, bytes) or len(key) < 32:
                raise ValueError("Each packet authentication key must contain at least 32 bytes")
            self._keys[source_id] = bytes(key)

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
