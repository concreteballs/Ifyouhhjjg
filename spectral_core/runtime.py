"""Runtime joining addressing, routing, authenticated control and SQLite."""
from pathlib import Path
from typing import List, Optional
from .address import SpectralAddress
from .database import SpectralDatabase
from .monitor import DiagnosticMonitor
from .network import SpectralNetwork
from .packet import Packet, PacketType
from .control import ControlPlane


class SpectralRuntime:
    def __init__(self, network: SpectralNetwork,
                 database: Optional[SpectralDatabase] = None,
                 monitor: Optional[DiagnosticMonitor] = None,
                 control_plane: Optional[ControlPlane] = None):
        self.network = network
        self.database = database or SpectralDatabase()
        self.monitor = monitor or DiagnosticMonitor(Path.home() / ".spectral-core" / "diagnostics.jsonl")
        self.control_plane = control_plane
        self.network.set_monitor(self.monitor)
        self.monitor.self_check(self.network, self.database)

    def route(self, packet: Packet, path_override=None) -> List[str]:
        try:
            source_router = self.network.owner_of(packet.source)
            destination_router = self.network.responsibility_owner(packet.destination)
            if path_override is not None:
                path = list(path_override)
                if len(path) < 2 or path[0] != source_router or path[-1] != destination_router:
                    raise PermissionError("Authorized detour endpoints do not match packet endpoints")
                for first, second in zip(path, path[1:]):
                    if second not in self.network.routers[first].neighbours:
                        raise PermissionError("Detour contains a non-neighbour transition")
                    if not self.network.routers[first].available or not self.network.routers[second].available:
                        raise RuntimeError("Detour contains an unavailable router")
            else:
                path = [source_router]
                current = source_router
                previous = None
                remaining = packet.hop_limit
                self.monitor.emit("route_started", packet_id=packet.packet_id,
                                  source_id=packet.source.value,
                                  destination_id=packet.destination.value,
                                  packet_type=packet.packet_type.value)
                while current != destination_router:
                    if remaining <= 1:
                        raise RuntimeError("Packet hop limit exhausted")
                    next_hop = self.network.choose_next_hop(current, destination_router, packet.destination, previous)
                    self.monitor.emit("route_hop", packet_id=packet.packet_id,
                                      current_router=current, next_router=next_hop,
                                      remaining_hops=remaining - 1)
                    previous = current
                    current = next_hop
                    path.append(current)
                    remaining -= 1
            if len(path) - 1 > packet.hop_limit:
                raise RuntimeError("Packet hop limit exhausted")
            return path
        except Exception as error:
            self.monitor.record_exception("route", error, packet_id=packet.packet_id,
                                          source_id=packet.source.value,
                                          destination_id=packet.destination.value)
            raise

    def write(self, source: SpectralAddress, destination: SpectralAddress, payload: bytes):
        return self.send(Packet(source, destination, payload))

    def read(self, address: SpectralAddress):
        value = self.database.get(address)
        self.monitor.emit("database_read", spectral_id=address.value,
                          found=value is not None,
                          size_bytes=len(value) if value is not None else 0)
        return value

    def send(self, packet: Packet, authorization=None):
        path_override = None
        if packet.packet_type is PacketType.ORDINARY:
            if authorization is not None:
                raise PermissionError("Ordinary packets cannot carry privileged authorizations")
        elif packet.packet_type is PacketType.DETOUR:
            if self.control_plane is None or not self.control_plane.verify_detour(authorization, packet.packet_id):
                self.monitor.emit("packet_rejected", level="warning", packet_id=packet.packet_id,
                                  reason="invalid_detour_authorization",
                                  packet_type=packet.packet_type.value)
                raise PermissionError("Detour requires a valid one-use control-plane authorization")
            path_override = authorization.path
        else:
            self.monitor.emit("packet_rejected", level="warning", packet_id=packet.packet_id,
                              reason="unsupported_control_packet",
                              packet_type=packet.packet_type.value)
            raise PermissionError("Control packets are not data-plane packets")
        path = self.route(packet, path_override)
        try:
            self.database.put(packet.destination, packet.payload)
        except Exception as error:
            self.monitor.record_exception("database_write", error, packet_id=packet.packet_id,
                                          destination_id=packet.destination.value)
            raise
        self.monitor.emit("database_write", packet_id=packet.packet_id,
                          destination_id=packet.destination.value,
                          size_bytes=len(packet.payload))
        self.monitor.emit("packet_delivered", packet_id=packet.packet_id,
                          destination_id=packet.destination.value,
                          hops=max(0, len(path)-1), route=path)
        return path

    def diagnostics(self):
        return self.monitor.status()

    def run_diagnostics(self):
        return self.monitor.self_check(self.network, self.database)
