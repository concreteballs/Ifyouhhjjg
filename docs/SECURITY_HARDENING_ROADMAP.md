# Security hardening roadmap

This document distinguishes implemented controls from work still required. A passing test suite is not a security certification.

## Implemented baseline (PR CI passed; independent security review pending)

- [x] External diagnostic receiver binds to loopback only.
- [x] Bearer token is loaded from an owner-only file and must be at least 32 characters.
- [x] Diagnostic reports use strict allowlists, bounded sizes/depth, and reject sensitive fields.
- [x] External collector deduplication cache is bounded.
- [x] Diagnostic files and external spool use owner-only POSIX permissions where supported.
- [x] External forwarding rejects redirects.
- [x] Raw exception text is not written to diagnostic reports.
- [x] Detour control messages use HMAC, expiry, path validation, and in-process one-use nonces.
- [x] Route selection uses deterministic shortest-hop, then load-aware, tie-broken routing.
- [x] CI uses read-only repository permissions and pinned GitHub-maintained actions.\n- [x] GitHub Actions unit-test job passed for PR #3 head `0f6d433` (run `42693512667`); independent review remains pending.

## Remaining work — do not treat as production-ready

### Packet security
- [x] Define the versioned HMAC-SHA256 signing envelope v1 for packet metadata and payload integrity.\n- [ ] Define the full serialized wire-packet format and complete threat model.
- [x] Add opt-in end-to-end sender authentication and payload integrity using standard HMAC-SHA256 (application-injected source-key mapping; key lifecycle remains open).
- [x] Add versioned owner-only key-file provisioning, rotation and revocation; bind source endpoint IDs to configured keys.
- [ ] Add coordinated dual-key rotation/recovery and stronger endpoint identity provisioning; key files remain unencrypted at rest and must be distributed out of band.
- [x] Add persistent duplicate/replay protection with bounded retention and atomic acceptance (packet-ID receipts; 24-hour default).
- [ ] Ensure retries and legitimate retransmissions have explicit, testable semantics.
- [x] Keep privileged detour/control authorization separate from ordinary packet authentication; detour packets require both packet integrity verification and a separate control-plane authorization.

### Routing correction
- [x] Implement authenticated, expiring HMAC correction messages to the previous router.
- [x] Bind corrections to packet ID, destination, previous/reporting routers, rejected/corrected next hops, expiry, and policy version.
- [x] Reject stale, forged, conflicting, non-neighbour and looping corrections without changing destination identity or creating a global destination blacklist.
- [ ] Persist correction nonce/replay state across process restarts and coordinate correction policy versions across routers.

### Storage and operations
- [x] Apply restrictive owner-only permissions to the main file-backed SQLite database on POSIX systems; WAL/journal sidecar permissions still need separate review.
- [x] Add atomic SQLite backup creation with owner-only file permissions and replay-receipt preservation tests.
- [ ] Define restore/recovery procedure and evaluate encryption-at-rest requirements and key custody.
- [x] Add bounded JSONL rotation for internal and external diagnostic archives, plus a hard-capped external spool with an explicit dropped-report counter.
- [ ] Add stress tests for slow/unavailable collectors, disk-full conditions, concurrent writes, and restart recovery.
- [ ] Review SQLite transaction and thread-safety assumptions before multi-threaded deployment.

### Verification
- [ ] Add property-based/fuzz-style tests using standard-library deterministic generators initially.
- [ ] Run static analysis and dependency/license checks when the toolchain is available.
- [ ] Perform independent security review before any production or multi-tenant deployment.
- [ ] Re-test all security boundaries after every protocol or persistence change.

## Release gate

Do not advertise Spectral Core as production-secure until packet authentication, replay protection, key lifecycle, storage handling, operational limits, and independent review have been completed. Do not expose the built-in diagnostic HTTP receiver to the public internet.
