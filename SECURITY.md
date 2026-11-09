# Security Policy

## Project status

Spectral Core is an experimental software emulator. It is not currently a production-secure network stack, cryptographic protocol, or hardened multi-tenant service. Passing unit tests does not establish security.

## Supported baseline

- Python standard library only; no third-party Python runtime packages.
- The external diagnostic receiver binds to IPv4 loopback only.
- The receiver accepts a bounded, allowlisted JSON report schema and does not execute report content.
- Diagnostic logs are created with owner-only file permissions on POSIX systems where supported.
- CI uses read-only repository permissions and pinned GitHub-maintained actions.

## Important limitations

Do not expose the diagnostic receiver directly to an untrusted network. For remote forwarding, use a separately managed HTTPS reverse proxy and keep the receiver bound to loopback.

The current HMAC detour control plane is an in-process prototype. Its replay cache is held in memory and is not shared between processes or restarts. It is not a complete identity, role, key-rotation, or distributed authorization system.

Ordinary packets still do not have end-to-end sender authentication, payload integrity protection, or encryption. The SQLite store now records packet IDs atomically for a bounded 24-hour replay window by default; this detects repeated IDs but does not stop an attacker from forging a new packet ID. The receipt is consumed before routing, so a failed send must be retried as a new packet ID. SQLite data is not encrypted at rest by this project.

The routing correction event is diagnostic feedback in the current emulator; the complete previous-hop correction-message protocol described in the design document is not yet implemented.

## Reporting a vulnerability

Please do not publish exploit details in a public issue. Contact the repository owner through the GitHub account that maintains this project and request a private disclosure channel. Include the affected commit, reproduction steps, and impact. Do not include real secrets or personal data.
