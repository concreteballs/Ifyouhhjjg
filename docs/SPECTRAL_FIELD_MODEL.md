# Spectral field database model — version 1

## Approved field layout

The database initializes a 10-column × 10-row spectral field:

- 10 columns are the ten ordered frequency clusters.
- 10 rows are the ten initial gradient positions within each cluster.
- 100 stable shade IDs are created.
- Columns 3–9 are the seven primary clusters and may participate in mixing.
- Columns 1–2 and 10 are service-reserved clusters. They are stored and addressable as field regions, but are not available as mixing components and cannot be subdivided through the primary mixing-index API.

The seven primary clusters are an abstract seven-position analogue of the seven visible-spectrum colour positions. This is a project-level mapping, not a claim that radio frequencies have physical colours. RGB/HEX values are intentionally left unset.

## Frequency basis

All physical boundaries are stored as integer hertz.

| Cluster column | Role | Range | Designation / reference |
|---:|---|---:|---|
| 1 | Service | 300 Hz–3 kHz | Project extension below the Article 2.1 table |
| 2 | Service | 3–30 kHz | VLF, ITU band 4 |
| 3 | Primary | 30–300 kHz | LF, ITU band 5 |
| 4 | Primary | 300 kHz–3 MHz | MF, ITU band 6 |
| 5 | Primary | 3–30 MHz | HF, ITU band 7 |
| 6 | Primary | 30–300 MHz | VHF, ITU band 8 |
| 7 | Primary | 300 MHz–3 GHz | UHF, ITU band 9 |
| 8 | Primary | 3–30 GHz | SHF, ITU band 10 |
| 9 | Primary | 30–300 GHz | EHF, ITU band 11 |
| 10 | Service | 300 GHz–3 THz | ITU band 12; no letter symbol in Article 2.1 |

ITU Radio Regulations 2024, Article 2.1, lists bands 4–12. Cluster 1 is explicitly marked as a project extension following the same decade pattern; it is not represented as an additional officially named Article 2.1 band. The official table uses exclusive lower and inclusive upper limits. The database stores adjacent numerical boundaries once; applications interpreting physical allocations must preserve the standard's boundary convention.

Reference: [ITU Radio Regulations, 2024 edition, Volume 1, Article 2](https://search.itu.int/history/HistoryDigitalCollectionDocLibrary/1.49.48.en.101.pdf).

## Stable identities and exact subdivision

Shade IDs use the form `SC{column}-G{row}`, for example `SC03-G00`. They are stable logical identifiers, not RGB/HEX values and not router addresses.

Each initial gradient cell has a root index interval represented by an exact rational range. When an unused finer index is needed, the selected interval is split into equal halves. Children are identified by binary paths:

- root: empty path;
- left half: append `0`;
- right half: append `1`.

The interval endpoints are stored as integer numerator/denominator pairs. Repeated subdivision therefore remains exact and is not limited to a fixed depth. Existing parent nodes and shade IDs are retained.

## Mixing

Only the seven primary clusters create `spectral_components`. The three service clusters never become mixing components. Mix coefficients attach to an index-node ID, including any recursively created child, and are stored as reduced exact rational numbers, never floating-point values. The database does not impose that coefficients sum to one; normalization is not assumed by this schema.

## Coordinates and transformations

The initial coordinate system is two-dimensional:

- X = cluster column (zero-based);
- Y = gradient row (zero-based).

Coordinates are stored as exact rational pairs. Geometry transformations are versioned records and do not alter shade IDs. The schema can add axes and coordinate systems later without changing existing identities.

## Migration and compatibility

The field schema is additive and initialized automatically by `SpectralDatabase`. Existing endpoint data, packet receipts, and route-correction tables are not rewritten. The migration uses `CREATE TABLE IF NOT EXISTS` and idempotent seed inserts.

This milestone only establishes the spectral database model. It does not implement network routing, a meta-router, the adder, physical photonic operations, or the future guard network.
