# Spectral Core

Experimental software emulator of a spectral-addressed network. The first implementation runs on ordinary Python and SQLite; photonic hardware is a possible future implementation target, not a current dependency.

## Current software baseline

- Exact spectral endpoint identifiers using ten neutral symbols (0–9).
- Tail-first address view, preserving the addressing convention for future routing logic.
- Router graph with endpoint ownership and deterministic shortest-path forwarding.
- Load-aware tie-breaking between equally short next hops.
- Packet source/destination identity and hop-limit protection.
- SQLite endpoint data storage.
- Explicit rejection of unauthenticated detour/control packet types.

The initial router is a working graph-routing baseline. It does not yet implement the complete responsibility-map correction protocol, authenticated central detours, neighbour assistance, or the future photonic interaction model. Those remain later milestones.

## Run tests

Python 3.10 or newer is recommended. No third-party packages are required.

```bash
python -m unittest discover -s tests -v
```

## Minimal example

```python
from spectral_core import Router, SpectralAddress, SpectralNetwork, SpectralRuntime

network = SpectralNetwork()
network.add_router(Router("router-a", (0, 0)))
network.add_router(Router("router-b", (1, 0)))
network.connect("router-a", "router-b")

source = SpectralAddress("123")
destination = SpectralAddress("987")
network.register_endpoint(source, "router-a")
network.register_endpoint(destination, "router-b")

runtime = SpectralRuntime(network)
route = runtime.write(source, destination, b"Hello Spectral Core")
print(route)
print(runtime.read(destination))
```

## Architecture direction

The software interfaces are kept separate from the physical implementation. The first emulator uses ordinary Python objects and SQLite. A future photonic backend may replace selected cell or interaction operations without requiring application data to encode physical wavelength values.

## Next milestones

1. Responsibility-region decisions and correction messages.
2. Authenticated detour/control policy and central load balancing.
3. Local health monitoring and neighbour assistance.
4. Persistent endpoint registry and database-backed queries.
5. A separate 2D interaction/adder experiment using shared core interfaces.

Do not commit real credentials, private keys, production security mappings or personal data to this public repository.
