"""Router graph with tail-first responsibility regions and bounded route corrections."""
from dataclasses import dataclass, field
import heapq
import math
import time
from typing import Dict, List, Optional, Tuple
from .address import SpectralAddress
from .route_correction import RouteCorrectionAuthority, RouteCorrectionMessage

Position = Tuple[int, int]

@dataclass
class Router:
    router_id: str
    position: Position
    neighbours: List[str] = field(default_factory=list)
    responsibility: List[SpectralAddress] = field(default_factory=list)
    responsibility_prefixes: List[str] = field(default_factory=list)
    load: float = 0.0
    available: bool = True
    def __post_init__(self):
        if not self.router_id or not math.isfinite(self.load) or self.load < 0:
            raise ValueError("invalid router ID or load")
        if any(not p or any(c not in "0123456789" for c in p) for p in self.responsibility_prefixes):
            raise ValueError("responsibility prefixes must be decimal strings")

@dataclass(frozen=True)
class RoutingCorrection:
    router_id: str
    destination_id: str
    rejected_next_hop: str
    corrected_next_hop: str
    expires_at: float

class SpectralNetwork:
    def __init__(self, monitor=None, correction_ttl_seconds=30.0):
        self.routers: Dict[str, Router] = {}
        self.endpoints: Dict[SpectralAddress, str] = {}
        self.monitor = monitor
        if not math.isfinite(correction_ttl_seconds) or correction_ttl_seconds <= 0:
            raise ValueError("correction_ttl_seconds must be finite and positive")
        self.correction_ttl_seconds = correction_ttl_seconds
        self._corrections = {}
        self._authenticated_corrections = {}
        self._route_hints = {}

    def _event(self, event, **data):
        if self.monitor is not None:
            self.monitor.emit(event, **data)

    def set_monitor(self, monitor):
        self.monitor = monitor
        for rid, router in self.routers.items():
            self._event("router_added", router_id=rid, position=list(router.position))
        seen = set()
        for rid, router in self.routers.items():
            for other in router.neighbours:
                edge = tuple(sorted((rid, other)))
                if edge not in seen:
                    self._event("link_connected", first=edge[0], second=edge[1])
                    seen.add(edge)
            for prefix in router.responsibility_prefixes:
                self._event("responsibility_assigned", router_id=rid, tail_prefix=prefix)
        for address, rid in self.endpoints.items():
            self._event("endpoint_registered", spectral_id=address.value, router_id=rid)

    def add_router(self, router):
        if router.router_id in self.routers: raise ValueError(f"Duplicate router: {router.router_id}")
        self.routers[router.router_id] = router
        self._event("router_added", router_id=router.router_id, position=list(router.position))

    def connect(self, first, second):
        if first not in self.routers or second not in self.routers: raise KeyError("Both routers must exist")
        if first == second: raise ValueError("A router cannot connect to itself")
        if second not in self.routers[first].neighbours: self.routers[first].neighbours.append(second)
        if first not in self.routers[second].neighbours: self.routers[second].neighbours.append(first)
        self._event("link_connected", first=first, second=second)

    def register_endpoint(self, address, router_id):
        if router_id not in self.routers: raise KeyError(f"Unknown router: {router_id}")
        if address in self.endpoints: raise ValueError(f"Endpoint already registered: {address}")
        self.endpoints[address] = router_id
        self.routers[router_id].responsibility.append(address)
        self._event("endpoint_registered", spectral_id=address.value, router_id=router_id)

    def assign_responsibility(self, router_id, tail_prefix):
        if router_id not in self.routers: raise KeyError(f"Unknown router: {router_id}")
        if not tail_prefix or any(c not in "0123456789" for c in tail_prefix):
            raise ValueError("tail_prefix must be decimal")
        if tail_prefix not in self.routers[router_id].responsibility_prefixes:
            self.routers[router_id].responsibility_prefixes.append(tail_prefix)
            self._event("responsibility_assigned", router_id=router_id, tail_prefix=tail_prefix)

    def responsibility_owner(self, address):
        tail = address.tail_first
        matches = [(len(p), r.router_id) for r in self.routers.values() if r.available
                   for p in r.responsibility_prefixes if tail.startswith(p)]
        if matches:
            return max(matches, key=lambda item: (item[0], item[1]))[1]
        return self.owner_of(address)

    def owner_of(self, address):
        try: owner = self.endpoints[address]
        except KeyError as exc: raise KeyError(f"Unknown spectral endpoint: {address}") from exc
        if not self.routers[owner].available: raise RuntimeError(f"Endpoint owner unavailable: {owner}")
        return owner

    def set_router_availability(self, router_id, available):
        self.routers[router_id].available = bool(available)
        self._event("router_availability", router_id=router_id, available=bool(available))

    def set_load(self, router_id, load):
        if not math.isfinite(load) or load < 0: raise ValueError("router load must be finite and non-negative")
        self.routers[router_id].load = float(load)
        self._event("router_load", router_id=router_id, load=float(load))

    def set_route_hint(self, router_id, tail_prefix, next_hop):
        if router_id not in self.routers or next_hop not in self.routers[router_id].neighbours:
            raise ValueError("Route hint must point to an existing neighbour")
        if not tail_prefix or any(c not in "0123456789" for c in tail_prefix):
            raise ValueError("tail_prefix must be decimal")
        self._route_hints[(router_id, tail_prefix)] = next_hop

    def shortest_path(self, source, destination, excluded=None):
        excluded = set(excluded or ())
        if source not in self.routers or destination not in self.routers: raise KeyError("Unknown router")
        if not self.routers[source].available or not self.routers[destination].available:
            raise RuntimeError("Source or destination unavailable")
        queue, previous = [source], {source: None}
        while queue:
            current = queue.pop(0)
            if current == destination:
                path, node = [], current
                while node is not None: path.append(node); node = previous[node]
                return list(reversed(path))
            for nxt in self.routers[current].neighbours:
                if nxt not in previous and self.routers[nxt].available and frozenset((current,nxt)) not in excluded:
                    previous[nxt] = current; queue.append(nxt)
        raise RuntimeError(f"No route from {source} to {destination}")

    def shortest_paths(self, source, destination, excluded=None):
        """Compatibility helper returning one deterministic shortest path.

        Enumerating every shortest path can grow exponentially on grid-like graphs.
        Use choose_path() for load-aware deterministic selection.
        """
        return [self.shortest_path(source, destination, excluded)]

    def choose_path(self, source, destination, excluded=None):
        excluded = set(excluded or ())
        if source not in self.routers or destination not in self.routers:
            raise KeyError("Unknown router")
        if not self.routers[source].available or not self.routers[destination].available:
            raise RuntimeError("Source or destination unavailable")
        if source == destination:
            return [source]
        # Lexicographic Dijkstra: hop count first, then accumulated intermediate
        # router load, then router-ID sequence for deterministic tie breaking.
        start_key = (0, 0.0, (source,))
        best = {source: start_key}
        queue = [(start_key, source)]
        while queue:
            key, current = heapq.heappop(queue)
            if best.get(current) != key:
                continue
            if current == destination:
                return list(key[2])
            hops, load_cost, route = key
            for nxt in sorted(self.routers[current].neighbours):
                if nxt in route or not self.routers[nxt].available:
                    continue
                if frozenset((current, nxt)) in excluded:
                    continue
                next_load = load_cost + (0.0 if nxt == destination else self.routers[nxt].load)
                next_key = (hops + 1, next_load, route + (nxt,))
                if nxt not in best or next_key < best[nxt]:
                    best[nxt] = next_key
                    heapq.heappush(queue, (next_key, nxt))
        raise RuntimeError(f"No route from {source} to {destination}")

    def issue_route_correction(self, authority: RouteCorrectionAuthority, packet_id: str,
                               destination: SpectralAddress, previous_router: str,
                               reporting_router: str, ttl_seconds: int = 30):
        """Create a signed correction for the router that sent a packet here."""
        if previous_router not in self.routers or reporting_router not in self.routers:
            raise KeyError("Unknown router in route-correction request")
        if reporting_router not in self.routers[previous_router].neighbours:
            raise ValueError("Reporting router is not the previous router's neighbour")
        destination_router = self.responsibility_owner(destination)
        path = self.choose_path(previous_router, destination_router)
        if len(path) < 2 or path[1] == reporting_router:
            return None
        return authority.issue(
            packet_id=packet_id,
            destination_id=destination.value,
            previous_router=previous_router,
            reporting_router=reporting_router,
            rejected_next_hop=reporting_router,
            corrected_next_hop=path[1],
            ttl_seconds=ttl_seconds,
        )

    def apply_route_correction(self, message: RouteCorrectionMessage,
                               authority: RouteCorrectionAuthority) -> bool:
        """Validate topology and signature before caching a destination-scoped correction."""
        if not isinstance(message, RouteCorrectionMessage) or not isinstance(authority, RouteCorrectionAuthority):
            return False
        try:
            authority._validate_fields(
                message.packet_id, message.destination_id, message.previous_router,
                message.reporting_router, message.rejected_next_hop, message.corrected_next_hop,
            )
        except (TypeError, ValueError):
            return False
        previous = self.routers.get(message.previous_router)
        reporting = self.routers.get(message.reporting_router)
        corrected = self.routers.get(message.corrected_next_hop)
        if previous is None or reporting is None or corrected is None:
            return False
        if message.rejected_next_hop != message.reporting_router:
            return False
        if message.reporting_router not in previous.neighbours:
            return False
        if message.corrected_next_hop not in previous.neighbours:
            return False
        if not previous.available or not reporting.available or not corrected.available:
            return False
        try:
            destination = SpectralAddress(message.destination_id)
            destination_router = self.responsibility_owner(destination)
            corrected_path = self.choose_path(message.corrected_next_hop, destination_router)
        except (KeyError, RuntimeError, ValueError):
            return False
        if message.previous_router in corrected_path:
            return False
        correction_key = (message.previous_router, destination.value)
        existing = self._authenticated_corrections.get(correction_key)
        if existing and existing.expires_at > time.time() and existing.corrected_next_hop != message.corrected_next_hop:
            return False
        if not authority.verify_and_consume(message, packet_id=message.packet_id):
            return False
        self._authenticated_corrections[correction_key] = RoutingCorrection(
            message.previous_router, destination.value, message.reporting_router,
            message.corrected_next_hop, float(message.expires_at),
        )
        self._event(
            "route_correction", packet_id=message.packet_id,
            destination_id=destination.value, previous_router=message.previous_router,
            reporting_router=message.reporting_router,
            rejected_next_hop=message.reporting_router,
            corrected_next_hop=message.corrected_next_hop,
            ttl_seconds=max(0, message.expires_at - int(time.time())),
            authenticated=True,
        )
        return True

    def choose_next_hop(self, current, destination, address=None, previous_router=None):
        if address is not None:
            correction_key = (current, address.value)
            correction = self._authenticated_corrections.get(correction_key)
            if correction is not None:
                if correction.expires_at > time.time() and correction.corrected_next_hop in self.routers[current].neighbours and self.routers[correction.corrected_next_hop].available:
                    try:
                        target_path = self.choose_path(correction.corrected_next_hop, destination)
                        if current not in target_path:
                            return correction.corrected_next_hop
                    except (KeyError, RuntimeError):
                        pass
                self._authenticated_corrections.pop(correction_key, None)
        expected = self.choose_path(current, destination)[1] if current != destination else current
        if address is None: return expected
        key = (current, address.value, expected)
        cached = self._corrections.get(key)
        if cached and cached.expires_at > time.time(): return cached.corrected_next_hop
        hints = [(len(p), hop) for (rid,p),hop in self._route_hints.items()
                 if rid == current and address.tail_first.startswith(p)]
        if not hints: return expected
        proposed = max(hints)[1]
        if proposed == expected: return proposed
        self._corrections[key] = RoutingCorrection(current,address.value,proposed,expected,
                                                    time.time()+self.correction_ttl_seconds)
        self._event("route_correction", router_id=current, destination_id=address.value,
                    rejected_next_hop=proposed, corrected_next_hop=expected,
                    ttl_seconds=self.correction_ttl_seconds)
        return expected

    def neighbour_assistance(self, failed_router, source, destination):
        if failed_router not in self.routers: raise KeyError(f"Unknown router: {failed_router}")
        self.set_router_availability(failed_router, False)
        path = self.choose_path(source, destination)
        self._event("neighbour_assistance", failed_router=failed_router, route=path)
        return path
