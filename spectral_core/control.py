"""Authenticated control-plane authorizations for privileged route changes."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import time
import uuid


@dataclass(frozen=True)
class DetourAuthorization:
    packet_id: str
    path: tuple[str, ...]
    expires_at: int
    nonce: str
    signature: str


class ControlPlane:
    """Issues one-use HMAC authorizations; packet flags alone grant no privilege."""
    def __init__(self, secret: bytes, max_ttl_seconds: int = 60):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("Control-plane secret must contain at least 32 bytes")
        if max_ttl_seconds < 1:
            raise ValueError("max_ttl_seconds must be positive")
        self._secret = secret
        self.max_ttl_seconds = max_ttl_seconds
        self._used_nonces = set()

    def _payload(self, packet_id, path, expires_at, nonce):
        return json.dumps({"packet_id": packet_id, "path": list(path),
                           "expires_at": expires_at, "nonce": nonce},
                          sort_keys=True, separators=(",", ":")).encode()

    def authorize_detour(self, packet_id: str, path, ttl_seconds: int = 30):
        path = tuple(path)
        if not packet_id or len(path) < 2 or len(set(path)) != len(path):
            raise ValueError("Detour requires a packet ID and a simple path")
        if ttl_seconds < 1 or ttl_seconds > self.max_ttl_seconds:
            raise ValueError("Detour authorization TTL is outside policy")
        expires = int(time.time()) + ttl_seconds
        nonce = uuid.uuid4().hex
        signature = hmac.new(self._secret, self._payload(packet_id,path,expires,nonce),
                             hashlib.sha256).hexdigest()
        return DetourAuthorization(packet_id,path,expires,nonce,signature)

    def verify_detour(self, authorization, packet_id: str):
        if not isinstance(authorization, DetourAuthorization):
            return False
        if authorization.packet_id != packet_id or authorization.expires_at < int(time.time()):
            return False
        if authorization.nonce in self._used_nonces:
            return False
        expected = hmac.new(
            self._secret,
            self._payload(authorization.packet_id, authorization.path,
                          authorization.expires_at, authorization.nonce),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, authorization.signature):
            return False
        self._used_nonces.add(authorization.nonce)
        return True
