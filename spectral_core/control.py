"""Authenticated control-plane authorizations for privileged route changes."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import threading
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
    """Issues bounded, one-use HMAC authorizations inside one trusted process."""
    def __init__(self, secret: bytes, max_ttl_seconds: int = 60):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("Control-plane secret must contain at least 32 bytes")
        if isinstance(max_ttl_seconds, bool) or not isinstance(max_ttl_seconds, int) or max_ttl_seconds < 1:
            raise ValueError("max_ttl_seconds must be a positive integer")
        self._secret = secret
        self.max_ttl_seconds = max_ttl_seconds
        self._used_nonces = {}
        self._lock = threading.Lock()

    def _payload(self, packet_id, path, expires_at, nonce):
        return json.dumps({"packet_id": packet_id, "path": list(path),
                           "expires_at": expires_at, "nonce": nonce},
                          sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _validate_path(packet_id, path):
        if not isinstance(packet_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", packet_id):
            raise ValueError("Invalid packet ID")
        if not isinstance(path, (tuple, list)) or not 2 <= len(path) <= 256:
            raise ValueError("Detour path length is outside policy")
        if any(not isinstance(node, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", node) for node in path):
            raise ValueError("Invalid router ID in detour path")
        if len(set(path)) != len(path):
            raise ValueError("Detour path must not contain loops")
        return tuple(path)

    def authorize_detour(self, packet_id: str, path, ttl_seconds: int = 30):
        path = self._validate_path(packet_id, path)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise ValueError("Detour TTL must be an integer")
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
        try:
            path = self._validate_path(authorization.packet_id, authorization.path)
        except (TypeError, ValueError):
            return False
        if authorization.packet_id != packet_id:
            return False
        if isinstance(authorization.expires_at, bool) or not isinstance(authorization.expires_at, int):
            return False
        if authorization.expires_at <= int(time.time()):
            return False
        if authorization.expires_at > int(time.time()) + self.max_ttl_seconds:
            return False
        if not isinstance(authorization.nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", authorization.nonce):
            return False
        if not isinstance(authorization.signature, str) or not re.fullmatch(r"[0-9a-f]{64}", authorization.signature):
            return False
        expected = hmac.new(
            self._secret,
            self._payload(authorization.packet_id, path, authorization.expires_at, authorization.nonce),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, authorization.signature):
            return False
        now = int(time.time())
        with self._lock:
            self._used_nonces = {nonce: expiry for nonce, expiry in self._used_nonces.items() if expiry > now}
            if authorization.nonce in self._used_nonces:
                return False
            self._used_nonces[authorization.nonce] = authorization.expires_at
        return True
