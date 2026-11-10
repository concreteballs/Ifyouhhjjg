# Spectral Core

Experimental software emulator of a spectral-addressed network. The first implementation runs on ordinary Python and SQLite; photonic hardware is a possible future implementation target, not a current dependency.

## Current software baseline

- Exact spectral endpoint identifiers using ten neutral symbols (0–9).
- Tail-first address view, preserving the addressing convention for future routing logic.
- Router graph with endpoint ownership and deterministic shortest-path forwarding.
- Tail-first responsibility prefixes with longest-prefix ownership resolution.
- Load-aware selection across equal-length paths.
- Local route-hint validation plus authenticated, expiring previous-hop route corrections.
- Neighbour-assisted rerouting around unavailable routers.
- HMAC-authenticated, expiring, one-use detour authorizations.
- SQLite-persistent route-correction nonce replay protection and active correction recovery across process restarts.
- Packet source/destination identity and hop-limit protection.
- Optional HMAC-SHA256 packet origin and payload-integrity checks with owner-only versioned key-file provisioning.
- SQLite endpoint data storage with owner-only file permissions on POSIX systems.
- Persistent, atomic packet-ID replay receipts with a 24-hour default retention window.
- Atomic SQLite backup API that preserves endpoint data and replay receipts.
- Embedded diagnostic monitor connected to the live runtime.
- Structured JSONL reports with bounded rotation, capped external forwarding spool, health checks, error events and atomic status snapshots.
- Diagnostic event allowlist and rejection of payload/secret fields.
- Explicit rejection of unauthenticated detour/control packet types.
- Optional standalone external diagnostic collector with allowlisted report ingestion, durable acknowledgements and a loopback-only HTTP bridge.

## Spectral field database

The SQLite database initializes a versioned 10×10 spectral field: ten ordered frequency clusters, seven primary mixing clusters, and three service-reserved clusters. Physical boundaries are stored in integer hertz; shade IDs remain independent of RGB/HEX values. Initial gradient indices can be recursively divided into exact rational halves. See [docs/SPECTRAL_FIELD_MODEL.md](docs/SPECTRAL_FIELD_MODEL.md) for the approved field layout and migration details.

## Internal diagnostic monitor

The monitor starts automatically with `SpectralRuntime`.

It records router creation, link changes, endpoint registration, route starts, individual hops, packet delivery, database reads/writes and rejected packets. Runtime errors are recorded with operation and exception metadata.

The monitor never records packet payloads. It rejects unknown event types and sensitive field names. Reports use schema `spectral-core.diagnostic.v1`. External forwarding is disabled by default. When enabled, reports are sent only to HTTPS or loopback HTTP with a bearer token; failed deliveries are spooled locally and can be retried with `runtime.monitor.flush_external_spool()`.

By default, persistent reports are written locally to:

```text
~/.spectral-core/diagnostics.jsonl
```

The monitor can also run in memory for tests:

```python
from spectral_core import DiagnosticMonitor
monitor = DiagnosticMonitor()
```

Inspect current status and export reports:

```python
status = runtime.diagnostics()
jsonl = runtime.monitor.export_jsonl()
runtime.monitor.write_status("diagnostics/status.json")
health_report = runtime.run_diagnostics()
```

Reports remain local. There is no automatic upload to GitHub or another network service.


## External diagnostic monitor

The external collector runs independently from the core process and accepts only allowlisted diagnostic reports. It never interprets reports as commands, rejects sensitive fields, deduplicates report IDs and acknowledges only after durable JSONL persistence. The optional HTTP receiver binds to loopback by default:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))" > monitor.token
chmod 600 monitor.token
python -m spectral_monitor.server --token-file monitor.token --path external-diagnostics.jsonl
```

To enable forwarding from the internal monitor, construct it with an HTTPS endpoint (or the loopback receiver URL) and a bearer token:

```python
import os
from spectral_core import DiagnosticMonitor

monitor = DiagnosticMonitor(
    "~/.spectral-core/diagnostics.jsonl",
    external_endpoint="http://127.0.0.1:8765/v1/reports",
    external_token=os.environ["SPECTRAL_MONITOR_TOKEN"],
)
```

The receiver binds only to `127.0.0.1`; it cannot be configured to listen publicly. Its token must be stored in an owner-only file with at least 32 characters. The receiver exposes read-only health at `GET /health` and report ingestion at `POST /v1/reports`. It has no command, file-path or arbitrary action endpoint. For remote forwarding, place a separately managed HTTPS reverse proxy in front of the loopback service; do not expose the built-in HTTP server directly.

## Security and provenance

See [SECURITY.md](SECURITY.md) for the current security boundary and known limitations, and [PROVENANCE.md](PROVENANCE.md) for the runtime/CI dependency and licensing record. The repository uses a custom source-available personal-use license draft; see [LICENSE](LICENSE) and [docs/COMMERCIAL_MODEL.md](docs/COMMERCIAL_MODEL.md). It is not an OSI-approved open-source license and must receive legal review before release.

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
print(runtime.diagnostics())
```

## Architecture direction

The software interfaces are kept separate from the physical implementation. The first emulator uses ordinary Python objects and SQLite. A future photonic backend may replace selected cell or interaction operations without requiring application data to encode physical wavelength values.

The current router implements graph routing, neighbour-assisted rerouting and authenticated previous-hop correction messages. Durable distributed correction state, central policy distribution and the future photonic interaction model remain future work.

## Approved implementation roadmap

The database work is organized into three packages. Each package includes SQLite schema/migrations, working programmatic APIs, tests for real operations and recovery, and documentation updates.

1. **Spectral foundation — complete.** Ten base clusters, 100 initial shades, stable spectral indices, exact mixing and gradients, universal coordinate storage, and geometry transforms that do not change logical IDs.
2. **Objects and multidimensional structure — complete.** Hierarchical objects and parent relations, reconstruction of the full hierarchy from a terminal spectral address, N-dimensional coordinate systems, exact mathematical transformations, and extensible coordinate spaces.
3. **Extension and integrity — complete (database migration 8).** Reserved regions and guard-network placeholders, future connection points, semantic and interspace links, hierarchy snapshots, checksum verification, discrepancy detection, and non-destructive recovery.

The database packages do not implement network routing, the meta-router, or the spectral adder. Those remain separate workstreams.

Do not commit real credentials, private keys, production security mappings or personal data to this public repository.


Package 3 adds reserved-region metadata, future extension points, semantic and interspace object links, immutable hierarchy snapshots, discrepancy reports, integrity-event history and non-destructive recovery. Missing object identities are not silently recreated, and objects added after a snapshot are preserved. These database records do not implement the guard network or any routing/forwarding behavior. See [docs/SPECTRAL_FIELD_MODEL.md](docs/SPECTRAL_FIELD_MODEL.md) for the schema and recovery boundary.
