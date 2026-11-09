# Security hardening roadmap

This document distinguishes implemented controls from work still required. A passing test suite is not a security certification.

## Implemented baseline (regression tests added; CI verification pending)

- [x] External diagnostic receiver binds to loopback only.
- [x] Bearer token is loaded from an owner-only file and must be at least 32 characters.
- [x] Diagnostic reports use strict allowlists, bounded sizes/depth, and reject sensitive fields.
- [x] External collector deduplication cache is bounded.
- [x] Diagnostic files and external spool use owner-only POSIX permissions where supported.
- [x] External forwarding rejects redirects.
- [x] Raw exception text is not written to diagnostic reports.
- [x] Detour control messages use HMAC, expiry, path validation, and in-process one-use nonces.
- [x] Route selection uses deterministic shortest-hop, then load-aware, tie-broken routing.
- [x] CI uses read-only repository permissions and pinned GitHub-maintained actions.

## Remaining work — do not treat as production-ready

### Packet security
- [ ] Define a versioned packet envelope and threat model.
- [x] Add opt-in end-to-end sender authentication and payload integrity using standard HMAC-SHA256 (application-injected source-key mapping; key lifecycle remains open).
- [ ] Define key provisioning, identity binding, rotation, revocation, and recovery.
- [x] Add persistent duplicate/replay protection with bounded retention and atomic acceptance (packet-ID receipts; 24-hour default).
- [ ] Ensure retries and legitimate retransmissions have explicit, testable semantics.
- [ ] Keep privileged detour/control authorization separate from ordinary packet authentication.

### Routing correction
- [ ] Implement authenticated correction messages to the previous router.
- [ ] Bind each correction to packet ID, destination, reporting router, rejected transition, corrected transition, expiry, and policy version.
- [ ] Reject stale, forged, conflicting, and out-of-scope corrections without changing destination identity or creating a global destination blacklist.

### Storage and operations
- [x] Apply restrictive owner-only permissions to the main file-backed SQLite database on POSIX systems; WAL/journal/backup handling still needs separate review.
- [ ] Define backup and recovery behaviour; evaluate encryption-at-rest requirements and key custody.
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
