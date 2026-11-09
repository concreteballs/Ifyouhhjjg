# Provenance and dependency record

Audit baseline: 2026-11-09.

## Runtime dependencies

The repository contains no third-party Python package dependencies and has no package installer manifest. The runtime uses Python standard-library modules, including:

- `sqlite3` for the local database;
- `hashlib` and `hmac` for detour authorization signatures;
- `json`, `uuid`, `threading`, `urllib`, `http.server`, and filesystem APIs for diagnostics and transport.

These modules are supplied by the Python runtime; they are not copied into this repository as vendored source. The Python interpreter and its bundled components remain subject to their own distribution terms.

## Build and CI dependencies

The GitHub Actions workflow uses only GitHub-maintained `actions/checkout` and `actions/setup-python`. Both are pinned to verified full commit SHAs rather than mutable tags:

- `actions/checkout@11d5960a326750d5838078e36cf38b85af677262`
- `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065`

The referenced action source repositories declare the MIT License. These actions are CI-only and are not shipped as Spectral Core runtime components.

## Relationship to YJ-64

The monitoring requirements were informed by the project's separate YJ-64 work: local diagnostics, allowlisted reports, durable spooling, and separation between reports and commands. Spectral Core has its own implementation and schema. It does not import YJ-64 modules, Android components, binaries, or package dependencies.

Both repositories currently have no declared repository license. This record does not grant a license to copy code between repositories. Before any source from another repository is reused, confirm that the same rights holder controls it or obtain explicit permission.

## Generated code and originality

Some implementation text was generated with an AI assistant and reviewed/edited for this repository. OpenAI's applicable EU Terms of Use state that, as between the user and OpenAI and to the extent permitted by law, the user owns Output and OpenAI assigns any rights it may have in that Output. The terms also note that AI output may not be unique. This is not a guarantee that every generated line is novel or free of third-party claims; source review remains necessary.

## Repository license status

A custom source-available Personal-Use License draft is proposed in `LICENSE`. It is intended to grant free personal non-commercial use while requiring a separate written agreement for commercial use. Donations are voluntary and do not grant additional rights. Premium/Premium Pro are intended as optional product/service tiers and do not themselves grant commercial source-code rights. See `docs/COMMERCIAL_MODEL.md`.

This is not an OSI-approved open-source license: open-source licenses cannot prohibit commercial use. The draft is not legal advice and must be reviewed by qualified counsel before being treated as a final license. Confirm ownership and contributor rights before release. GitHub users can view and fork public repositories under GitHub's platform terms, but that does not provide general reuse permissions.
