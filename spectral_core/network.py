"""Discrete-grid router network for deterministic emulator tests."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from .address import SpectralAddress

Position = Tuple[int, int]

@dataclass
class Router:
    router_id: str
    position: Position
    neighbours: List[str] = field(default_factory=list)
    responsibility: List[SpectralAddress] = field(default_factory=list)
    load: float = 0.0

    def __post_init__(self):
        if not self.router_id:
            raise ValueError("router_id cannot be empty")
        if self.load < 0:
            raise ValueError("router load cannot be negative")

class SpectralNetwork:
    """Graph of routers with endpoint ownership and local next-hop choice."""
    def __init__(self, monitor=None):
        self.routers: Dict[str, Router] = {}
        self.endpoints: Dict[SpectralAddress, str] = {}
        self.monitor = monitor

    def set_monitor(self, monitor):
        self.monitor = monitor
        # Attach diagnostics to an already-built network: replay its current
        # topology so the monitor starts with a complete baseline snapshot.
        for router_id, router in self.routers.items():
            self._event("router_added", router_id=router_id, position=list(router.position))
        seen_links = set()
        for router_id, router in self.routers.items():
            for neighbour_id in router.neighbours:
                link = tuple(sorted((router_id, neighbour_id)))
                if link not in seen_links:
                    self._event("link_connected", first=link[0], second=link[1])
                    seen_links.add(link)
        for address, router_id in self.endpoints.items():
            self._event("endpoint_registered", spectral_id=address.value, router_id=router_id)

    def _event(self, event, **data):
        if self.monitor is not None:
            self.monitor.emit(event, **data)

    def add_router(self, router: Router):
        if router.router_id in self.routers:
            raise ValueError(f"Duplicate router: {router.router_id}")
        self.routers[router.router_id] = router
        self._event("router_added", router_id=router.router_id, position=list(router.position))

    def connect(self, first: str, second: str):
        if first not in self.routers or second not in self.routers:
            raise KeyError("Both routers must exist before connecting them")
        if first == second:
            raise ValueError("A router cannot connect to itself")
        if second not in self.routers[first].neighbours:
            self.routers[first].neighbours.append(second)
        if first not in self.routers[second].neighbours:
            self.routers[second].neighbours.append(first)
        self._event("link_connected", first=first, second=second)

    def register_endpoint(self, address: SpectralAddress, router_id: str):
        if router_id not in self.routers:
            raise KeyError(f"Unknown router: {router_id}")
        if address in self.endpoints:
            raise ValueError(f"Endpoint already registered: {address}")
        self.endpoints[address] = router_id
        self.routers[router_id].responsibility.append(address)
        self._event("endpoint_registered", spectral_id=address.value, router_id=router_id)

    def owner_of(self, address: SpectralAddress):
        try:
            return self.endpoints[address]
        except KeyError as exc:
            raise KeyError(f"Unknown spectral endpoint: {address}") from exc

    def shortest_path(self, source: str, destination: str):
        if source not in self.routers or destination not in self.routers:
            raise KeyError("Unknown source or destination router")
        frontier = [source]
        previous: Dict[str, Optional[str]] = {source: None}
        while frontier:
            current = frontier.pop(0)
            if current == destination:
                path = []
                node = current
                while node is not None:
                    path.append(node)
                    node = previous[node]
                return list(reversed(path))
            for neighbour in self.routers[current].neighbours:
                if neighbour not in previous:
                    previous[neighbour] = current
                    frontier.append(neighbour)
        raise RuntimeError(f"No route from {source} to {destination}")

    def choose_next_hop(self, current: str, destination: str):
        """Choose a shortest-path neighbour; break ties by load then router ID."""
        path = self.shortest_path(current, destination)
        if len(path) < 2:
            return current
        candidates = [
            neighbour for neighbour in self.routers[current].neighbours
            if len(self.shortest_path(neighbour, destination)) == len(path) - 1
        ]
        if not candidates:
            raise RuntimeError(f"No advancing neighbour from {current}")
        return min(candidates, key=lambda rid: (self.routers[rid].load, rid))
