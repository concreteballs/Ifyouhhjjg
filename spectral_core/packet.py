"""Packet model shared by the emulator routing layer."""
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4
from .address import SpectralAddress


class PacketType(str, Enum):
    ORDINARY = "ordinary"
    DETOUR = "detour"
    CONTROL = "control"


@dataclass
class Packet:
    source: SpectralAddress
    destination: SpectralAddress
    payload: bytes
    packet_type: PacketType = PacketType.ORDINARY
    hop_limit: int = 64
    packet_id: str = field(default_factory=lambda: uuid4().hex)
    auth_tag: str | None = None

    def __post_init__(self):
        if isinstance(self.hop_limit, bool) or not isinstance(self.hop_limit, int) or self.hop_limit < 1:
            raise ValueError("hop_limit must be a positive integer")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be bytes")
        if not isinstance(self.packet_id, str) or not 1 <= len(self.packet_id) <= 128:
            raise ValueError("packet_id must be a non-empty string of at most 128 characters")
        if not isinstance(self.packet_type, PacketType):
            raise TypeError("packet_type must be a PacketType")

    def forwarded(self):
        if self.hop_limit <= 1:
            raise RuntimeError("Packet hop limit exhausted")
        return Packet(self.source, self.destination, self.payload,
                      self.packet_type, self.hop_limit - 1, self.packet_id,
                      self.auth_tag)
