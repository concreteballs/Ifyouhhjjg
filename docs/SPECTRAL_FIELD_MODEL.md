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

The interval endpoints are stored as exact numerator/denominator pairs; both values are persisted as decimal `TEXT` and reconstructed as Python integers. Repeated subdivision therefore remains exact and is not limited to a fixed depth. Existing parent nodes and shade IDs are retained.

## Mixing

Only the seven primary clusters create `spectral_components`. Component IDs are database identities and are not assumed to equal cluster numbers. The three service clusters never become mixing components. Mix coefficients attach to an index-node ID, including any recursively created child. Coefficients must be non-negative, may be zero, and use a positive denominator; new API writes are reduced through Python exact Fraction arithmetic, never floating point. Legacy coefficient rows are migrated without changing their stored numerator/denominator representation, while preserving their exact rational value. The database does not impose that coefficients sum to one; normalization of the total is not assumed by this schema.

## Coordinates and geometry

Coordinate systems are dimension-independent. Each system declares an ordered list of two or more named axes; the initial field uses:

- X = cluster column (zero-based), increasing from left to right;
- Y = gradient row (zero-based), with row 0 at the top and row 9 at the bottom. The gradient coordinate therefore increases from top to bottom.

The original `spectral_positions` table remains available for compatibility with existing two-dimensional consumers. Migration version 3 copies those values into `spectral_position_coordinates`, which stores one exact rational value per shade, coordinate system, and axis. New coordinate systems can define three or more dimensions without changing shade IDs or the initial 2D system.

Coordinates are represented as exact rational numerator/denominator pairs. Both values are persisted as decimal `TEXT` and returned by the API as Python integers. Integers, rational pairs, and exact fractions are accepted; floating-point coordinates are deliberately rejected to avoid rounding drift.

Affine geometry transformations use the exact equation:

`x' = Mx + b`

where `M` is a square rational matrix and `b` is a rational offset vector. Scaling is represented by a diagonal matrix. Transform definitions are persisted in `geometry_transforms`; applying a transform calculates and returns derived coordinates without overwriting source coordinates. This keeps logical shade IDs and canonical positions stable. A transform can be evaluated for one shade or for all 100 field shades.

The geometry API is available as `database.spectral_field.geometry`:
- `create_coordinate_system(...)` defines an additional N-dimensional coordinate space.
- `set_coordinates(...)` and `get_coordinates(...)` write/read exact positions.
- `create_affine_transform(...)` stores a general exact affine transform.
- `create_scale_transform(...)` stores an exact per-axis scale.
- `apply_transform(...)` and `apply_transform_to_field(...)` calculate transformed coordinates without changing canonical positions.

## Migration and compatibility

The field schema is additive and initialized automatically by `SpectralDatabase`. Existing endpoint data, packet receipts, and route-correction tables are not rewritten. The migration uses idempotent schema creation and seed inserts, and a compatibility upgrade converts earlier shade-level mix rows to root index-node rows without discarding their coefficients. Geometry migration version 3 copies existing X/Y positions into the dimension-independent coordinate table.

This milestone only establishes the spectral database model. It does not implement network routing, a meta-router, the adder, physical photonic operations, or the future guard network.


## Arbitrary-precision rational storage (migration versions 4–5)

SQLite `INTEGER` is signed 64-bit and cannot represent denominators produced by indefinitely repeated bisection. Migration version 4 converts index interval endpoints, mix coefficients, and compatibility 2D positions to decimal `TEXT`; migration version 5 does the same for dimension-independent coordinate values. Python `Fraction` remains the arithmetic representation, with exact decimal-string conversion at the database boundary. This preserves values beyond 64-bit limits without changing shade IDs, index paths, or interval mathematics. Existing integer values are copied losslessly.


## Hierarchical objects and spectral addresses (migration version 6)

The object layer is separate from network endpoint identifiers and from the recursive spectral-index tree. It adds:

- `spectral_objects`: stable object identity, type, name, parent, sibling order, and the spectral index node assigned to that hierarchy level.
- `spectral_object_addresses`: versioned active/retired snapshots of each object's complete address.
- `spectral_object_address_segments`: ordered ancestry components captured in each address version.
- `spectral_object_position_coordinates`: exact N-dimensional object positions, reusing existing coordinate systems and axes.

Each address segment is derived from the selected index node and its existing shade/cluster metadata. Its printable form is `B{ITU-band}-G{gradient-row}`, with `~{binary-index-path}` appended for recursively subdivided nodes. For example, `B05-G00~01` means ITU band 5, gradient row 0, and binary subdivision path 01. Complete object addresses join ancestry components with `/`. The three service-reserved clusters are excluded from ordinary object addresses.

An object's own index node is stored separately from its object ID. Address snapshots record the entire root-to-object chain, so resolving a terminal address returns the full object hierarchy and verifies that each segment still follows the parent relation. Address uniqueness is enforced. A duplicate active address is rejected rather than silently shared.

Coordinates use the same exact rational rules as shade coordinates: numerator and denominator are decimal TEXT, and float inputs are rejected. Object positions do not alter object IDs or spectral addresses. This milestone does not implement routing, meta-routing, the adder, or the guard network.
