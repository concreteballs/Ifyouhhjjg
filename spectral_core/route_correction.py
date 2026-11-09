"""Authenticated, expiring route-correction messages for the emulator."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import threading
import time
import uuid


@dataclass(frozen=True)
class RouteCorrectionMessage:
    packet_id: str
    destination_id: str
    previous_router: str
    reporting_router: str
    rejected_next_hop: str
    corrected_next_hop: str
    expires_at: int
    nonce: str
    policy_version: int
    signature: str


class RouteCorrectionAuthority:
    """Signs correction messages and prevents in-process nonce replay."""

    MAX_USED_NONCES = 50000

    def __init__(self, secret: bytes, max_ttl_seconds: int = 60, database=None):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("Route-correction secret must contain at least 32 bytes")
        if isinstance(max_ttl_seconds, bool) or not isinstance(max_ttl_seconds, int) or max_ttl_seconds < 1:
            raise ValueError("max_ttl_seconds must be a positive integer")
        self._secret = bytes(secret)
        self.max_ttl_seconds = max_ttl_seconds
        self.database = database
        self._used_nonces = {}
        self._lock = threading.Lock()

    @staticmethod
    def _validate_fields(packet_id, destination_id, previous_router,
                         reporting_router, rejected_next_hop, corrected_next_hop):
        if not isinstance(packet_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", packet_id):
            raise ValueError("Invalid packet ID")
        if not isinstance(destination_id, str) or not re.fullmatch(r"[0-9]{1,256}", destination_id):
            raise ValueError("Invalid spectral destination ID")
        for value in (previous_router, reporting_router, rejected_next_hop, corrected_next_hop):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
                raise ValueError("Invalid router ID")
        if rejected_next_hop != reporting_router:
            raise ValueError("Rejected next hop must identify the reporting router")
        if corrected_next_hop == rejected_next_hop:
            raise ValueError("Corrected next hop must differ from rejected next hop")

    @staticmethod
    def _payload(message_fields) -> bytes:
        return (
            b"SpectralCore.RouteCorrection.v1\x00" +
            json.dumps(message_fields, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True).encode("ascii")
        )

    def issue(self, packet_id, destination_id, previous_router, reporting_router,
              rejected_next_hop, corrected_next_hop, ttl_seconds=30,
              policy_version=1) -> RouteCorrectionMessage:
        self._validate_fields(packet_id, destination_id, previous_router,
                              reporting_router, rejected_next_hop, corrected_next_hop)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise ValueError("Correction TTL must be an integer")
        if not 1 <= ttl_seconds <= self.max_ttl_seconds:
            raise ValueError("Correction TTL is outside policy")
        if isinstance(policy_version, bool) or not isinstance(policy_version, int) or policy_version != 1:
            raise ValueError("Unsupported route-correction policy version")
        expires_at = int(time.time()) + ttl_seconds
        nonce = uuid.uuid4().hex
        fields = {
            "version": 1, "packet_id": packet_id, "destination_id": destination_id,
            "previous_router": previous_router, "reporting_router": reporting_router,
            "rejected_next_hop": rejected_next_hop, "corrected_next_hop": corrected_next_hop,
            "expires_at": expires_at, "nonce": nonce, "policy_version": policy_version,
        }
        signature = hmac.new(self._secret, self._payload(fields), hashlib.sha256).hexdigest()
        return RouteCorrectionMessage(
            packet_id, destination_id, previous_router, reporting_router,
            rejected_next_hop, corrected_next_hop, expires_at, nonce,
            policy_version, signature,
        )

    def verify_and_consume(self, message, packet_id=None, database=None) -> bool:
        if not isinstance(message, RouteCorrectionMessage):
            return False
        try:
            self._validate_fields(
                message.packet_id, message.destination_id, message.previous_router,
                message.reporting_router, message.rejected_next_hop, message.corrected_next_hop,
            )
        except (TypeError, ValueError):
            return False
        if packet_id is not None and message.packet_id != packet_id:
            return False
        if isinstance(message.expires_at, bool) or not isinstance(message.expires_at, int):
            return False
        now = int(time.time())
        if message.expires_at <= now or message.expires_at > now + self.max_ttl_seconds:
            return False
        if message.policy_version != 1 or isinstance(message.policy_version, bool):
            return False
        if not isinstance(message.nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", message.nonce):
            return False
        if not isinstance(message.signature, str) or not re.fullmatch(r"[0-9a-f]{64}", message.signature):
            return False
        fields = {
            "version": 1, "packet_id": message.packet_id,
            "destination_id": message.destination_id,
            "previous_router": message.previous_router,
            "reporting_router": message.reporting_router,
            "rejected_next_hop": message.rejected_next_hop,
            "corrected_next_hop": message.corrected_next_hop,
            "expires_at": message.expires_at, "nonce": message.nonce,
            "policy_version": message.policy_version,
        }
        expected = hmac.new(self._secret, self._payload(fields), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, message.signature):
            return False
        nonce_store = database if database is not None else self.database
        if nonce_store is not None:
            try:
                return nonce_store.claim_route_correction_nonce(
                    message.nonce, message.expires_at, now=now
                )
            except (OSError, RuntimeError, ValueError):
                return False
        with self._lock:
            self._used_nonces = {
                nonce: expiry for nonce, expiry in self._used_nonces.items() if expiry > now
            }
            if message.nonce in self._used_nonces or len(self._used_nonces) >= self.MAX_USED_NONCES:
                return False
            self._used_nonces[message.nonce] = message.expires_at
        return True
