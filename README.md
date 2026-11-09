# Spectral Core

Experimental software model of a spectral-addressed network and a configurable wave-interaction engine.

This repository starts with a **software emulator**. It does not claim that the proposed optical or photonic mechanisms have been physically demonstrated.

## Initial scope

Version 0.1 investigates two operating modes on one shared computational foundation:

- **1D routing mode** — spectral endpoint addressing, geometric direction selection, responsibility regions, local correction, monitoring and central load balancing.
- **2D adder mode** — two perpendicular input axes, wave interaction in a shared region, and detection of the strongest calibrated resonance.

Multi-pair interactions and a third spatial axis are deliberately deferred until the basic modes have been tested.

## Core addressing principles

- A destination is identified by its complete, unique spectral identifier.
- A packet carries the destination endpoint and the sender's identifier for replies. It does not carry a precomputed list of intermediate routers.
- Routers use their local spectral direction table and geometric map to choose the next suitable neighbouring router.
- Spectral identifiers are exact machine-readable identities. Human-perceived colour similarity is irrelevant.
- The logical address identity is independent of the physical scale of the field.

The initial conceptual field has ten base spectral clusters across its width. Three reserved bands are not used as ordinary address bands. The field may extend in length; width expansion, subdivision and address-space changes are future design topics.

## Packet classes

1. **Ordinary packet** — follows normal responsibility and shortest-path rules. A router that receives it outside its responsibility region may return a correction to the previous hop.
2. **Detour packet** — carries an authenticated detour instruction issued by the central control plane. Routers forward it according to the updated routing policy even when the path is not locally shortest.
3. **Control packet** — carries routing or management instructions. It may use any permitted route, but its authority must be authenticated and checked at each receiving node.

A routing correction must never blacklist or alter the destination address merely because one hop rejected a route. Route exclusions are temporary, scoped to a direction or link, and expire or are revalidated.

## Routing and responsibility

Each router has:

- a spectral direction table;
- a map of its responsibility region;
- a set of reachable neighbouring routers;
- local route and congestion observations;
- a correction mechanism for misdirected ordinary packets.

A router selects a direction toward the destination region and forwards to a suitable neighbour along that direction. The emulator will compare geometric shortest-path selection with load-aware alternatives.

## Monitoring and resilience

Each cell/router monitors its own health and load, and observes neighbouring cells where permitted. Local assistance is attempted first. Escalation to the central core occurs when local recovery is insufficient.

The central core monitors network-wide load and can issue authenticated policy updates or detour instructions to relieve hot regions. It is not intended to relay every data packet. Cold regions may receive less frequent monitoring, but monitoring is not disabled.

## Geometry scaling

The initial emulator will support a geometric length-scaling operation inspired by stretching an elastic material:

- preserve spectral identifiers;
- preserve logical adjacency and topology;
- scale geometric coordinates and distances;
- recompute geometric direction tables;
- recalibrate propagation parameters if the chosen wave model depends on physical distance.

This is a modelling rule to test, not a claim that physical wave behaviour remains unchanged under arbitrary stretching.

## Security boundary

Reserved spectral bands, protected regions and concealed administrative structure are architectural concepts, not security mechanisms by themselves. The implementation must rely on cryptographic authentication, explicit authorization, integrity checks, replay protection and least privilege.

Because this repository is public, do not commit real credentials, private keys, operational secret mappings, personal data or production security configurations.

## Planned development sequence

1. Document the data model and routing state.
2. Implement a small discrete-grid geometry and spectral identifiers.
3. Implement a single-router decision and responsibility-map test.
4. Implement multi-hop routing, corrections and loop prevention.
5. Add local monitoring and central load-aware detours.
6. Implement the 2D adder as a separate configuration of the shared interaction engine.
7. Test all 100 digit pairs against a calibrated model; do not hard-code the answer table as a substitute for the interaction model.

## Status

**Design and emulator planning.** No physical photonic implementation is implied.
