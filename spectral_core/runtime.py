"""Runtime joining endpoint addressing, packet routing and SQLite storage."""
from typing import List, Optional
from .address import SpectralAddress
from .database import SpectralDatabase
from .network import SpectralNetwork
from .packet import Packet, PacketType

class SpectralRuntime:
    def __init__(self, network: SpectralNetwork, database: Optional[SpectralDatabase] = None):
        self.network = network
        self.database = database or SpectralDatabase()

    def route(self, packet: Packet) -> List[str]:
        source_router = self.network.owner_of(packet.source)
        destination_router = self.network.owner_of(packet.destination)
        path = [source_router]
        current = source_router
        remaining = packet.hop_limit
        while current != destination_router:
            if remaining <= 1:
                raise RuntimeError("Packet hop limit exhausted")
            current = self.network.choose_next_hop(current, destination_router)
            path.append(current)
            remaining -= 1
        return path

    def write(self, source: SpectralAddress, destination: SpectralAddress, payload: bytes):
        packet = Packet(source, destination, payload)
        path = self.route(packet)
        self.database.put(destination, payload)
        return path

    def read(self, address: SpectralAddress):
        return self.database.get(address)

    def send(self, packet: Packet):
        if packet.packet_type is not PacketType.ORDINARY:
            raise PermissionError(
                "Detour/control packets require an authenticated control plane; "
                "that subsystem is not implemented in this baseline."
            )
        path = self.route(packet)
        self.database.put(packet.destination, packet.payload)
        return path
