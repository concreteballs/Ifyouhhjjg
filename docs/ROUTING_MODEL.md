# Routing Model — Spectral Core

Status: design specification for the first software emulator.

This document records the intended routing behaviour. Where implementation details are not yet settled, they are marked as design choices to validate rather than assumed physical facts.

## 1. Addressing model

### 1.1 Destination is an endpoint, not a route

A data packet identifies its final destination using one complete, unique spectral identifier. It does not contain a precomputed list of intermediate routers, domains or hops.

The sender also includes its own endpoint identifier so that the receiver can address a reply without reconstructing the sender's address.

Conceptual packet fields:

- `destination_spectral_id` — exact identifier of the final endpoint;
- `source_spectral_id` — exact identifier of the sender;
- `packet_type` — ordinary, detour or control;
- `payload` — application data or control instruction;
- `authorization` — verifiable authority for privileged instructions, where applicable;
- `hop_limit` — safety bound against packets circulating indefinitely;
- `packet_id` — unique packet instance identifier for duplicate/replay handling.

The destination identifier remains unchanged while the packet is forwarded.

### 1.2 Exact spectral identity

Spectral identifiers are machine-readable identities, not human judgements about how similar two colours look. Two regions that appear similar to a person still represent different destinations when their complete identifiers differ.

The emulator must compare complete identifiers, not approximate visible colour names or RGB similarity.

### 1.3 Field geometry

The initial conceptual field has ten base spectral clusters across its width. The design reserves two bands on the ultraviolet side and one band on the opposite side from ordinary address use. These reserved bands are intended as concealed connection points for a higher-level security/control network. Their existence alone grants no privilege and does not automatically expand the ordinary address space.

Protected/forbidden regions may also exist within the ordinary field. Access to them requires higher authorization. Their precise encoding and physical placement remain implementation details to be specified.

The field may extend in length. Logical endpoint identifiers must remain stable if geometric length is scaled.

## 2. Router state

Each router maintains its own local view. At minimum:

- `router_id` — unique router identity;
- `position` — its location in the emulator's geometry;
- `spectral_direction_table` — mapping from destination spectral regions to preferred geometric directions;
- `responsibility_map` — the region for which this router is responsible;
- `neighbours` — reachable adjacent routers and link state;
- `local_load_state` — queue depth, link utilization and available capacity;
- `health_state` — operational state and detected faults;
- `temporary_route_exclusions` — scoped, expiring exclusions for failed or unsuitable next hops;
- `policy_version` — latest accepted central routing policy version.

The direction table uses conventional internal labels for spectral clusters; it is not a literal table of visible light values.

## 3. Direction selection

A router receives the destination endpoint identifier and determines the destination's spectral region using its local spectral direction table.

Conceptually, it draws a straight direction from its current position toward that destination region. It then selects the nearest suitable neighbouring router that advances the packet in that direction and is consistent with the routing policy.

The next hop is selected from local neighbours; the packet does not carry that next-hop address as part of its permanent destination.

The geometric line is a direction guide, not a guarantee that the packet can physically travel through every point on that line. The emulator must account for reachable links, responsibility regions, blocked areas and load.

Movement may be horizontal, vertical or diagonal. The initial objective is a short route, with load-aware alternatives where beneficial.

## 4. Responsibility regions and correction

Each intermediate router has a map of its own responsibility region.

### 4.1 Ordinary packet

For an ordinary packet:

1. The router reads the destination identifier.
2. It checks whether the packet is appropriately passing through its responsibility region.
3. It evaluates whether forwarding through this router is consistent with the current normal route.
4. If the packet has arrived at a router outside the appropriate responsibility region, and forwarding it onward would create an avoidable detour, the router returns a correction to the previous hop.
5. The correction indicates a better direction or next-hop choice. It does not change or blacklist the destination identifier.

A correction is routing feedback, not a declaration that the destination itself is forbidden.

### 4.2 Detour packet

A detour packet is explicitly marked as a centrally authorized load-balancing detour.

A router must not reject it merely because it is outside the normal shortest-path responsibility route. It forwards the packet according to the authorized detour policy and its current reachable neighbours.

The detour marker must be authenticated. A sender must not be able to label an ordinary packet as a privileged detour merely by setting a public flag.

### 4.3 Control packet

Control packets may be directed along routes that are not ordinary shortest paths. A router forwards them according to the control instruction only after verifying the sender's authority, instruction integrity, scope and freshness.

A control packet's permission to use an alternate route does not mean it can bypass link availability, safety limits or access-control checks.

## 5. Corrections, route loops and malicious feedback

A router's mistaken correction must not permanently poison the destination address.

The emulator will distinguish:

- destination identity — immutable during forwarding;
- rejected next hop or direction — a temporary, scoped route condition;
- protected destination/region — an explicit access-control rule, independent of route correction.

To reduce routing loops without storing the complete route in every packet:

- include a hop limit;
- use packet identifiers to detect duplicate processing;
- keep short-lived local records of recently rejected next hops or directions;
- attach an expiry and scope to route corrections;
- validate corrections before applying them to shared routing state;
- allow a different route when a particular direction is temporarily excluded.

A malicious or compromised router must not be able to add an arbitrary destination to a network-wide forbidden list merely by returning a correction. Network-wide policy changes require authenticated authority and independent validation.

The emulator implements a v1 correction message signed with HMAC-SHA256. It binds the packet ID, destination, previous router, reporting router, rejected next hop, corrected next hop, expiry and policy version. The previous router accepts it only if both next hops are valid neighbours, the corrected route is reachable without looping back through the previous router, the signature and nonce are valid, and no conflicting correction is already active for that destination. The correction is temporary and destination-scoped; it never modifies or blacklists the destination identifier. Nonce and correction state are currently in-memory only and are not synchronized across router processes.

## 6. Local monitoring and neighbour assistance

Each cell/router has a self-monitoring function. Measurements may include:

- local temperature, when meaningful and available;
- queue depth and waiting time;
- link or bus utilization;
- processing load;
- error rate, retries and failed transmissions;
- health of neighbouring cells/routers.

A router also observes neighbouring cells within its permitted monitoring scope. It may assist a neighbour with local recovery or load relief, but neighbour assistance does not grant unrestricted administrative control over that neighbour.

Escalation sequence:

1. detect and classify a local problem;
2. attempt permitted local correction;
3. coordinate assistance with neighbouring cells;
4. notify the central core if local recovery is insufficient or the event exceeds local authority.

The emulator should initially use measurable software proxies such as queue depth, utilization, latency and error counts. Temperature can be represented as an optional simulated sensor, not treated as a mandatory property of software routers.

## 7. Central monitoring and load balancing

The central core monitors network-wide state and identifies heavily loaded regions ("hot" areas) and lightly loaded regions ("cold" areas).

It may:

- send updated routing policy to selected routers;
- instruct authorized detours around overloaded areas;
- adjust monitoring frequency according to observed risk and load;
- request additional local diagnostics;
- coordinate recovery when local neighbour assistance is insufficient.

Cold regions may receive less frequent attention, but monitoring is not disabled.

The central core is a control-plane coordinator, not a mandatory relay for every data packet. Routers continue forwarding packets locally using their current valid policy if the central core is temporarily unreachable.

Policy updates should be versioned, authenticated, scoped and reversible.

## 8. Security architecture

Reserved spectral bands and hidden gateway locations are not security controls by themselves. The software implementation must separately enforce:

- cryptographic identity and authentication;
- authorization by role and scope;
- packet integrity;
- replay protection and freshness;
- least privilege;
- audit records for privileged actions;
- separation between ordinary routing corrections and administrative policy changes.

The higher-level security network may have authority above ordinary internal administrators, but that hierarchy must be enforced cryptographically. Concealing its existence from ordinary network participants is not a substitute for access control.

No real keys, credentials, secret colour-to-identifier mappings or production security details belong in this public repository.

## 9. Length scaling

The emulator may scale the field's length in a manner analogous to stretching an elastic sheet.

Initial modelling rule:

- preserve endpoint spectral identifiers;
- preserve logical adjacency and topology;
- scale geometric coordinates and distances;
- recompute geometric direction tables;
- re-evaluate link costs and propagation parameters if they depend on distance.

This is a coordinate/geometry transformation in the first emulator. It does not assume that physical wave behaviour remains invariant under arbitrary stretching.

## 10. First routing tests

The initial tests should be small and deterministic:

1. A packet travels directly toward a destination through the expected neighbouring routers.
2. A packet is delivered to a router outside its responsibility region; that router returns a correction.
3. The corrected packet takes the alternate route without changing its destination identifier.
4. A centrally marked detour packet is forwarded even when it is not on the normal shortest path.
5. An ordinary packet cannot gain detour privileges by forging a marker.
6. A control packet is accepted only with valid authority and a current instruction.
7. A failed link or overloaded neighbour causes local route selection to choose another reachable path.
8. Repeated corrections cannot create an infinite loop.
9. A malicious correction cannot add the destination itself to a global forbidden list.
10. A temporary route exclusion expires and does not permanently damage future routing.

## 11. Open design questions

These points should be resolved through emulator experiments rather than guessed:

- exact mathematical representation of spectral identifiers;
- exact geometry and adjacency rules for the 10-cluster-wide field;
- how responsibility regions are partitioned and updated;
- how a router determines that a packet is outside its responsibility region;
- how correction messages are authenticated and reconciled;
- how central policy balances shortest distance, congestion, reliability and fairness;
- how much neighbour monitoring is useful without creating excessive overhead;
- how geometric length scaling affects simulated propagation.

