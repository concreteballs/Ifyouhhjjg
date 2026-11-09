"""Runtime joining endpoint addressing, packet routing, diagnostics and SQLite."""
from pathlib import Path
from typing import List, Optional
from .address import SpectralAddress
from .database import SpectralDatabase
from .monitor import DiagnosticMonitor
from .network import SpectralNetwork
from .packet import Packet, PacketType

class SpectralRuntime:
    def __init__(
        self,
        network: SpectralNetwork,
        database: Optional[SpectralDatabase] = None,
        monitor: Optional[DiagnosticMonitor] = None,
    ):
        self.network = network
        self.database = database or SpectralDatabase()
        self.monitor = monitor or DiagnosticMonitor(
            Path.home() / ".spectral-core" / "diagnostics.jsonl"
        )
        self.network.set_monitor(self.monitor)
        self.monitor.self_check(self.network, self.database)

    def route(self, packet: Packet) -> List[str]:
        try:
            source_router = self.network.owner_of(packet.source)
            destination_router = self.network.owner_of(packet.destination)
            path = [source_router]
            current = source_router
            remaining = packet.hop_limit
            self.monitor.emit(
                "route_started",
                packet_id=packet.packet_id,
                source_id=packet.source.value,
                destination_id=packet.destination.value,
                packet_type=packet.packet_type.value,
            )
            while current != destination_router:
                if remaining <= 1:
                    raise RuntimeError("Packet hop limit exhausted")
                next_hop = self.network.choose_next_hop(current, destination_router)
                self.monitor.emit(
                    "route_hop",
                    packet_id=packet.packet_id,
                    current_router=current,
                    next_router=next_hop,
                    remaining_hops=remaining - 1,
                )
                current = next_hop
                path.append(current)
                remaining -= 1
            return path
        except Exception as error:
            self.monitor.record_exception(
                "route", error,
                packet_id=packet.packet_id,
                source_id=packet.source.value,
                destination_id=packet.destination.value,
            )
            raise

    def write(self, source: SpectralAddress, destination: SpectralAddress, payload: bytes):
        packet = Packet(source, destination, payload)
        return self.send(packet)

    def read(self, address: SpectralAddress):
        value = self.database.get(address)
        self.monitor.emit(
            "database_read",
            spectral_id=address.value,
            found=value is not None,
            size_bytes=len(value) if value is not None else 0,
        )
        return value

    def send(self, packet: Packet):
        if packet.packet_type is not PacketType.ORDINARY:
            error = PermissionError(
                "Detour/control packets require an authenticated control plane; "
                "that subsystem is not implemented in this baseline."
            )
            self.monitor.emit(
                "packet_rejected",
                level="warning",
                packet_id=packet.packet_id,
                reason="unauthenticated_or_unimplemented_packet_type",
                packet_type=packet.packet_type.value,
            )
            self.monitor.record_exception(
                "send", error, packet_id=packet.packet_id,
                packet_type=packet.packet_type.value,
            )
            raise error
        path = self.route(packet)
        try:
            self.database.put(packet.destination, packet.payload)
        except Exception as error:
            self.monitor.record_exception(
                "database_write", error,
                packet_id=packet.packet_id,
                destination_id=packet.destination.value,
            )
            raise
        self.monitor.emit(
            "database_write",
            packet_id=packet.packet_id,
            destination_id=packet.destination.value,
            size_bytes=len(packet.payload),
        )
        self.monitor.emit(
            "packet_delivered",
            packet_id=packet.packet_id,
            destination_id=packet.destination.value,
            hops=max(0, len(path) - 1),
            route=path,
        )
        return path

    def diagnostics(self):
        return self.monitor.status()

    def run_diagnostics(self):
        return self.monitor.self_check(self.network, self.database)
