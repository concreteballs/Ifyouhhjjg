# Provenance and dependency record

Audit baseline: 2026-11-09.

## Runtime dependencies

The repository contains no third-party Python package dependencies and has no package installer manifest. The runtime uses Python standard-library modules, including:

- `sqlite3` for the local database;
- `hashlib` and `hmac` for detour authorization signatures;
- `json`, `uuid`, `threading`, `urllib`, `http.server`, and filesystem APIs for diagnostics and transport.

These modules are supplied by the Python runtime; they are not copied into this repository as vendored source. The Python interpreter and its bundled components remain subject to their own distribution terms.

## Build and CI dependencies

The GitHub Actions workflow uses only GitHub-maintained `actions/checkout` and `actions/setup-python`. Both are pinned to full commit SHAs rather than mutable tags. They are CI-only and are not shipped as Spectral Core runtime components.

## Relationship to YJ-64

The monitoring requirements were informed by the project's separate YJ-64 work: local diagnostics, allowlisted reports, durable spooling, and separation between reports and commands. Spectral Core has its own implementation and schema. It does not import YJ-64 modules, Android components, binaries, or package dependencies.

Both repositories currently have no declared repository license. This record does not grant a license to copy code between repositories. Before any source from another repository is reused, confirm that the same rights holder controls it or obtain explicit permission.

## Generated code and originality

Some implementation text was generated with an AI assistant and reviewed/edited for this repository. OpenAI's applicable EU Terms of Use state that, as between the user and OpenAI and to the extent permitted by law, the user owns Output and OpenAI assigns any rights it may have in that Output. The terms also note that AI output may not be unique. This is not a guarantee that every generated line is novel or free of third-party claims; source review remains necessary.

## Repository license status

There is currently no `LICENSE` file. Under the default copyright rules, this does not grant the public general permission to reuse, modify, or distribute the source. GitHub users can still view and fork a public repository under GitHub's platform terms. The project owner should decide separately whether to keep all rights reserved or issue a commercial/open-source license.
