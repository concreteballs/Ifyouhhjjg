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

    def __post_init__(self):
        if self.hop_limit < 1:
            raise ValueError("hop_limit must be at least 1")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be bytes")

    def forwarded(self):
        if self.hop_limit <= 1:
            raise RuntimeError("Packet hop limit exhausted")
        return Packet(self.source, self.destination, self.payload,
                      self.packet_type, self.hop_limit - 1, self.packet_id)
