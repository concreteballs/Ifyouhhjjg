"""Versioned spectral field metadata and exact hierarchical indexing.

The initial field uses a 10-column by 10-row grid. Physical frequency ranges
are stored as integer hertz; recursive index subdivisions use exact fractions.
"""
from fractions import Fraction
import sqlite3
from typing import Dict, List

PALETTE_VERSION = "radio-field-itu-2024-v1"

# The seven central clusters follow ITU Radio Regulations 2024, Article 2.1.
# Cluster 1 is an explicitly marked project extension below the Article 2.1
# table. Cluster 10 is ITU band 12 (which has no letter symbol in that table).
CLUSTERS = (
    (1, "LOW_SERVICE_EXTENSION", 300, 3_000, None, "service", 0,
     "Project extension following the ITU decade pattern; not a named Article 2.1 band."),
    (2, "VLF", 3_000, 30_000, 4, "service", 0,
     "ITU Radio Regulations 2024, Article 2.1, band 4."),
    (3, "LF", 30_000, 300_000, 5, "primary", 1,
     "ITU Radio Regulations 2024, Article 2.1, band 5."),
    (4, "MF", 300_000, 3_000_000, 6, "primary", 1,
     "ITU Radio Regulations 2024, Article 2.1, band 6."),
    (5, "HF", 3_000_000, 30_000_000, 7, "primary", 1,
     "ITU Radio Regulations 2024, Article 2.1, band 7."),
    (6, "VHF", 30_000_000, 300_000_000, 8, "primary", 1,
     "ITU Radio Regulations 2024, Article 2.1, band 8."),
    (7, "UHF", 300_000_000, 3_000_000_000, 9, "primary", 1,
     "ITU Radio Regulations 2024, Article 2.1, band 9."),
    (8, "SHF", 3_000_000_000, 30_000_000_000, 10, "primary", 1,
     "ITU Radio Regulations 2024, Article 2.1, band 10."),
    (9, "EHF", 30_000_000_000, 300_000_000_000, 11, "primary", 1,
     "ITU Radio Regulations 2024, Article 2.1, band 11."),
    (10, "ITU_BAND_12", 300_000_000_000, 3_000_000_000_000, 12, "service", 0,
     "ITU Radio Regulations 2024, Article 2.1, band 12; no letter symbol assigned."),
)


class SpectralFieldStore:
    """Create and access the additive spectral-field database schema."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._migrate_and_seed()

    def _migrate_and_seed(self):
        db = self.connection
        owns_transaction = not db.in_transaction
        if owns_transaction:
            db.execute("PRAGMA foreign_keys = OFF")
            db.execute("PRAGMA legacy_alter_table = ON")
        db.execute("PRAGMA busy_timeout = 30000")
        if owns_transaction:
            # Acquire the write reservation before reading schema state. This avoids
            # deferred-transaction lock-up when several connections initialize at once.
            db.execute("BEGIN IMMEDIATE")
        db.execute("SAVEPOINT spectral_field_v1")
        try:
            # Upgrade the earlier additive schema without discarding stored mix data.
            old_mix_columns = {
                row[1] for row in db.execute("PRAGMA table_info(spectral_mix_components)")
            }
            legacy_mix = "shade_id" in old_mix_columns and "index_node_id" not in old_mix_columns
            if legacy_mix:
                db.execute(
                    "ALTER TABLE spectral_mix_components RENAME TO spectral_mix_components_legacy_v1"
                )

            cluster_columns = {
                row[1] for row in db.execute("PRAGMA table_info(spectral_clusters)")
            }
            if cluster_columns and "visual_order" not in cluster_columns:
                db.execute("ALTER TABLE spectral_clusters ADD COLUMN visual_order INTEGER")
                db.execute(
                    """UPDATE spectral_clusters SET visual_order = cluster_order - 2
                       WHERE role = 'primary'"""
                )

            statements = (
                """CREATE TABLE IF NOT EXISTS spectral_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_palette_versions (
                    palette_version_id INTEGER PRIMARY KEY,
                    version_key TEXT NOT NULL UNIQUE,
                    standard_reference TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_clusters (
                    cluster_id INTEGER PRIMARY KEY,
                    cluster_order INTEGER NOT NULL UNIQUE CHECK(cluster_order BETWEEN 1 AND 10),
                    designation TEXT NOT NULL UNIQUE,
                    lower_hz INTEGER NOT NULL CHECK(lower_hz >= 0),
                    upper_hz INTEGER NOT NULL CHECK(upper_hz > lower_hz),
                    standard_band_number INTEGER,
                    role TEXT NOT NULL CHECK(role IN ('primary', 'service')),
                    mixing_enabled INTEGER NOT NULL CHECK(mixing_enabled IN (0, 1)),
                    visual_order INTEGER UNIQUE CHECK(visual_order BETWEEN 1 AND 7),
                    source_note TEXT NOT NULL,
                    CHECK((role = 'primary' AND mixing_enabled = 1 AND visual_order IS NOT NULL) OR
                          (role = 'service' AND mixing_enabled = 0 AND visual_order IS NULL))
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_components (
                    component_id INTEGER PRIMARY KEY,
                    cluster_id INTEGER NOT NULL UNIQUE REFERENCES spectral_clusters(cluster_id),
                    component_key TEXT NOT NULL UNIQUE
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_shades (
                    shade_id TEXT PRIMARY KEY,
                    cluster_id INTEGER NOT NULL REFERENCES spectral_clusters(cluster_id),
                    grid_column INTEGER NOT NULL CHECK(grid_column BETWEEN 1 AND 10),
                    grid_row INTEGER NOT NULL CHECK(grid_row BETWEEN 0 AND 9),
                    UNIQUE(cluster_id, grid_row),
                    UNIQUE(grid_column, grid_row)
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_shade_versions (
                    palette_version_id INTEGER NOT NULL REFERENCES spectral_palette_versions(palette_version_id),
                    shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
                    rgb_hex TEXT,
                    visual_code_system TEXT,
                    PRIMARY KEY(palette_version_id, shade_id)
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_mix_components (
                    index_node_id TEXT NOT NULL REFERENCES spectral_index_nodes(node_id),
                    component_id INTEGER NOT NULL REFERENCES spectral_components(component_id),
                    coefficient_numerator TEXT NOT NULL,
                    coefficient_denominator TEXT NOT NULL,
                    PRIMARY KEY(index_node_id, component_id)
                )""",
                """CREATE TABLE IF NOT EXISTS coordinate_systems (
                    coordinate_system_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    dimension_count INTEGER NOT NULL CHECK(dimension_count >= 2),
                    unit_name TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS coordinate_axes (
                    coordinate_system_id TEXT NOT NULL REFERENCES coordinate_systems(coordinate_system_id),
                    axis_order INTEGER NOT NULL CHECK(axis_order >= 0),
                    axis_name TEXT NOT NULL,
                    PRIMARY KEY(coordinate_system_id, axis_order),
                    UNIQUE(coordinate_system_id, axis_name)
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_positions (
                    shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
                    coordinate_system_id TEXT NOT NULL REFERENCES coordinate_systems(coordinate_system_id),
                    x_numerator TEXT NOT NULL,
                    x_denominator TEXT NOT NULL,
                    y_numerator TEXT NOT NULL,
                    y_denominator TEXT NOT NULL,
                    PRIMARY KEY(shade_id, coordinate_system_id)
                )""",
                """CREATE TABLE IF NOT EXISTS geometry_transforms (
                    transform_id TEXT PRIMARY KEY,
                    coordinate_system_id TEXT NOT NULL REFERENCES coordinate_systems(coordinate_system_id),
                    transform_type TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_index_nodes (
                    node_id TEXT PRIMARY KEY,
                    shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
                    parent_node_id TEXT REFERENCES spectral_index_nodes(node_id),
                    branch TEXT NOT NULL CHECK(branch IN ('root', 'left', 'right')),
                    path TEXT NOT NULL,
                    depth INTEGER NOT NULL CHECK(depth >= 0),
                    lower_numerator TEXT NOT NULL,
                    lower_denominator TEXT NOT NULL,
                    upper_numerator TEXT NOT NULL,
                    upper_denominator TEXT NOT NULL,
                    UNIQUE(shade_id, path)
                )""",
                "CREATE INDEX IF NOT EXISTS spectral_index_nodes_parent ON spectral_index_nodes(parent_node_id)",
                "CREATE INDEX IF NOT EXISTS spectral_shades_cluster ON spectral_shades(cluster_id, grid_row)",
            )
            for statement in statements:
                db.execute(statement)

            db.execute(
                """INSERT OR IGNORE INTO spectral_palette_versions(version_key, standard_reference)
                   VALUES (?, ?)""",
                (PALETTE_VERSION, "ITU Radio Regulations 2024, Article 2.1; explicitly marked project extension for 300–3,000 Hz"),
            )
            palette_id = db.execute(
                "SELECT palette_version_id FROM spectral_palette_versions WHERE version_key = ?",
                (PALETTE_VERSION,),
            ).fetchone()[0]

            for order, designation, lower, upper, band_no, role, mixing, note in CLUSTERS:
                db.execute(
                    """INSERT OR IGNORE INTO spectral_clusters
                       (cluster_id, cluster_order, designation, lower_hz, upper_hz,
                        standard_band_number, role, mixing_enabled, visual_order, source_note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order, order, designation, lower, upper, band_no, role, mixing,
                     order - 2 if role == "primary" else None, note),
                )
                if mixing:
                    db.execute(
                        """INSERT OR IGNORE INTO spectral_components
                           (cluster_id, component_key) VALUES (?, ?)""",
                        (order, f"cluster-{order:02d}"),
                    )
                for row in range(10):
                    shade_id = f"SC{order:02d}-G{row:02d}"
                    db.execute(
                        """INSERT OR IGNORE INTO spectral_shades
                           (shade_id, cluster_id, grid_column, grid_row) VALUES (?, ?, ?, ?)""",
                        (shade_id, order, order, row),
                    )
                    db.execute(
                        """INSERT OR IGNORE INTO spectral_shade_versions
                           (palette_version_id, shade_id, rgb_hex, visual_code_system)
                           VALUES (?, ?, NULL, NULL)""",
                        (palette_id, shade_id),
                    )
                    db.execute(
                        """INSERT OR IGNORE INTO spectral_index_nodes
                           (node_id, shade_id, parent_node_id, branch, path, depth,
                            lower_numerator, lower_denominator, upper_numerator, upper_denominator)
                           VALUES (?, ?, NULL, 'root', '', 0, ?, 10, ?, 10)""",
                        (f"{shade_id}:", shade_id, row, row + 1),
                    )

            db.execute(
                """INSERT OR IGNORE INTO coordinate_systems
                   (coordinate_system_id, name, dimension_count, unit_name)
                   VALUES ('spectral-grid-2d-v1', 'Initial spectral field grid', 2, 'grid-cell')"""
            )
            db.execute(
                """INSERT OR IGNORE INTO coordinate_axes
                   (coordinate_system_id, axis_order, axis_name) VALUES
                   ('spectral-grid-2d-v1', 0, 'cluster-column'),
                   ('spectral-grid-2d-v1', 1, 'gradient-row')"""
            )
            for order, designation, *_ in CLUSTERS:
                for row in range(10):
                    shade_id = f"SC{order:02d}-G{row:02d}"
                    db.execute(
                        """INSERT OR IGNORE INTO spectral_positions
                           (shade_id, coordinate_system_id, x_numerator, x_denominator,
                            y_numerator, y_denominator)
                           VALUES (?, 'spectral-grid-2d-v1', ?, 1, ?, 1)""",
                        (shade_id, order - 1, row),
                    )
            if legacy_mix:
                db.execute(
                    """INSERT OR IGNORE INTO spectral_mix_components
                       (index_node_id, component_id, coefficient_numerator, coefficient_denominator)
                       SELECT old.shade_id || ':', old.component_id,
                              old.coefficient_numerator, old.coefficient_denominator
                       FROM spectral_mix_components_legacy_v1 old
                       JOIN spectral_index_nodes node
                         ON node.shade_id = old.shade_id AND node.path = ''"""
                )
                db.execute("DROP TABLE spectral_mix_components_legacy_v1")

            # Version 4: SQLite INTEGER is signed 64-bit; rational values use decimal TEXT.
            rational_tables = (
                ("spectral_index_nodes", {"lower_numerator", "lower_denominator", "upper_numerator", "upper_denominator"}),
                ("spectral_mix_components", {"coefficient_numerator", "coefficient_denominator"}),
                ("spectral_positions", {"x_numerator", "x_denominator", "y_numerator", "y_denominator"}),
            )
            needs_exact_upgrade = False
            for table_name, columns_needed in rational_tables:
                info = {row[1]: row[2].upper() for row in db.execute(f"PRAGMA table_info({table_name})")}
                if info and any(info.get(column) != "TEXT" for column in columns_needed):
                    needs_exact_upgrade = True
            if needs_exact_upgrade:
                if not owns_transaction:
                    raise RuntimeError("exact rational storage migration requires its own transaction")
                db.execute("DROP INDEX IF EXISTS spectral_index_nodes_parent")
                db.execute("ALTER TABLE spectral_mix_components RENAME TO spectral_mix_components_legacy_exact_v4")
                db.execute("ALTER TABLE spectral_index_nodes RENAME TO spectral_index_nodes_legacy_exact_v4")
                db.execute("ALTER TABLE spectral_positions RENAME TO spectral_positions_legacy_exact_v4")
                db.execute("""CREATE TABLE spectral_index_nodes (
                    node_id TEXT PRIMARY KEY, shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
                    parent_node_id TEXT REFERENCES spectral_index_nodes(node_id),
                    branch TEXT NOT NULL CHECK(branch IN ('root', 'left', 'right')),
                    path TEXT NOT NULL, depth INTEGER NOT NULL CHECK(depth >= 0),
                    lower_numerator TEXT NOT NULL, lower_denominator TEXT NOT NULL,
                    upper_numerator TEXT NOT NULL, upper_denominator TEXT NOT NULL,
                    UNIQUE(shade_id, path))""")
                db.execute("""INSERT INTO spectral_index_nodes
                    SELECT node_id, shade_id, parent_node_id, branch, path, depth,
                           CAST(lower_numerator AS TEXT), CAST(lower_denominator AS TEXT),
                           CAST(upper_numerator AS TEXT), CAST(upper_denominator AS TEXT)
                    FROM spectral_index_nodes_legacy_exact_v4""")
                db.execute("""CREATE TABLE spectral_mix_components (
                    index_node_id TEXT NOT NULL REFERENCES spectral_index_nodes(node_id),
                    component_id INTEGER NOT NULL REFERENCES spectral_components(component_id),
                    coefficient_numerator TEXT NOT NULL, coefficient_denominator TEXT NOT NULL,
                    PRIMARY KEY(index_node_id, component_id))""")
                db.execute("""INSERT INTO spectral_mix_components
                    SELECT index_node_id, component_id, CAST(coefficient_numerator AS TEXT),
                           CAST(coefficient_denominator AS TEXT)
                    FROM spectral_mix_components_legacy_exact_v4""")
                db.execute("""CREATE TABLE spectral_positions (
                    shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
                    coordinate_system_id TEXT NOT NULL REFERENCES coordinate_systems(coordinate_system_id),
                    x_numerator TEXT NOT NULL, x_denominator TEXT NOT NULL,
                    y_numerator TEXT NOT NULL, y_denominator TEXT NOT NULL,
                    PRIMARY KEY(shade_id, coordinate_system_id))""")
                db.execute("""INSERT INTO spectral_positions
                    SELECT shade_id, coordinate_system_id, CAST(x_numerator AS TEXT),
                           CAST(x_denominator AS TEXT), CAST(y_numerator AS TEXT),
                           CAST(y_denominator AS TEXT) FROM spectral_positions_legacy_exact_v4""")
                db.execute("DROP TABLE spectral_mix_components_legacy_exact_v4")
                db.execute("DROP TABLE spectral_index_nodes_legacy_exact_v4")
                db.execute("DROP TABLE spectral_positions_legacy_exact_v4")
                db.execute("CREATE INDEX spectral_index_nodes_parent ON spectral_index_nodes(parent_node_id)")
            db.execute("INSERT OR IGNORE INTO spectral_schema_migrations(version) VALUES (4)")

            db.execute("INSERT OR IGNORE INTO spectral_schema_migrations(version) VALUES (1), (2)")
            db.execute("RELEASE SAVEPOINT spectral_field_v1")
            if owns_transaction:
                db.commit()
                db.execute("PRAGMA legacy_alter_table = OFF")
                db.execute("PRAGMA foreign_keys = ON")
                violations = db.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(f"foreign-key violations after spectral migration: {violations[:5]}")
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT spectral_field_v1")
            db.execute("RELEASE SAVEPOINT spectral_field_v1")
            if owns_transaction:
                db.rollback()
                db.execute("PRAGMA legacy_alter_table = OFF")
                db.execute("PRAGMA foreign_keys = ON")
            raise

    def clusters(self) -> List[Dict]:
        cursor = self.connection.execute(
            "SELECT * FROM spectral_clusters ORDER BY cluster_order"
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def split_index(self, shade_id: str, path: str = "") -> List[Dict]:
        """Split one existing interval into two exact equal rational halves."""
        if not isinstance(shade_id, str) or not shade_id:
            raise ValueError("shade_id must be a non-empty string")
        if not isinstance(path, str) or any(ch not in "01" for ch in path):
            raise ValueError("path must contain only 0 and 1")
        db = self.connection
        db.execute("SAVEPOINT split_spectral_index")
        try:
            parent = db.execute(
                """SELECT n.node_id, n.depth, n.lower_numerator, n.lower_denominator,
                          n.upper_numerator, n.upper_denominator, c.mixing_enabled
                   FROM spectral_index_nodes n
                   JOIN spectral_shades s ON s.shade_id = n.shade_id
                   JOIN spectral_clusters c ON c.cluster_id = s.cluster_id
                   WHERE n.shade_id = ? AND n.path = ?""",
                (shade_id, path),
            ).fetchone()
            if parent is None:
                raise KeyError("spectral index node does not exist")
            if not parent[6]:
                raise PermissionError("service clusters are reserved and cannot be subdivided for mixing")
            existing = db.execute(
                "SELECT 1 FROM spectral_index_nodes WHERE parent_node_id = ? LIMIT 1",
                (parent[0],),
            ).fetchone()
            if existing:
                raise ValueError("index node has already been split")
            lower = Fraction(int(parent[2]), int(parent[3]))
            upper = Fraction(int(parent[4]), int(parent[5]))
            midpoint = (lower + upper) / 2
            children = (
                ("left", path + "0", lower, midpoint),
                ("right", path + "1", midpoint, upper),
            )
            result = []
            for branch, child_path, start, end in children:
                node_id = f"{shade_id}:{child_path}"
                db.execute(
                    """INSERT INTO spectral_index_nodes
                       (node_id, shade_id, parent_node_id, branch, path, depth,
                        lower_numerator, lower_denominator, upper_numerator, upper_denominator)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (node_id, shade_id, parent[0], branch, child_path, parent[1] + 1,
                     str(start.numerator), str(start.denominator),
                     str(end.numerator), str(end.denominator)),
                )
                result.append({
                    "node_id": node_id, "shade_id": shade_id, "path": child_path,
                    "branch": branch, "depth": parent[1] + 1,
                    "lower": (start.numerator, start.denominator),
                    "upper": (end.numerator, end.denominator),
                })
            db.execute("RELEASE SAVEPOINT split_spectral_index")
            return result
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT split_spectral_index")
            db.execute("RELEASE SAVEPOINT split_spectral_index")
            raise

    def set_mix_component(self, index_node_id: str, component_id: int,
                          numerator: int, denominator: int):
        """Store an exact non-negative rational coefficient without forced normalization."""
        if isinstance(numerator, bool) or not isinstance(numerator, int) or numerator < 0:
            raise ValueError("numerator must be a non-negative integer")
        if isinstance(denominator, bool) or not isinstance(denominator, int) or denominator < 1:
            raise ValueError("denominator must be a positive integer")
        fraction = Fraction(numerator, denominator)
        row = self.connection.execute(
            """SELECT c.mixing_enabled FROM spectral_index_nodes n
               JOIN spectral_shades s ON s.shade_id = n.shade_id
               JOIN spectral_clusters c ON c.cluster_id = s.cluster_id
               WHERE n.node_id = ?""",
            (index_node_id,),
        ).fetchone()
        if row is None:
            raise KeyError("spectral index node does not exist")
        if not row[0]:
            raise PermissionError("service clusters cannot participate in mixing")
        component = self.connection.execute(
            """SELECT c.mixing_enabled FROM spectral_components p
               JOIN spectral_clusters c ON c.cluster_id = p.cluster_id
               WHERE p.component_id = ?""",
            (component_id,),
        ).fetchone()
        if component is None:
            raise KeyError("mixing component does not exist")
        if not component[0]:
            raise PermissionError("service clusters cannot participate in mixing")
        db = self.connection
        owns_transaction = not db.in_transaction
        db.execute("SAVEPOINT set_spectral_mix_component")
        try:
            db.execute(
                """INSERT INTO spectral_mix_components
                   (index_node_id, component_id, coefficient_numerator, coefficient_denominator)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(index_node_id, component_id) DO UPDATE SET
                     coefficient_numerator = excluded.coefficient_numerator,
                     coefficient_denominator = excluded.coefficient_denominator""",
                (index_node_id, component_id, str(fraction.numerator), str(fraction.denominator)),
            )
            db.execute("RELEASE SAVEPOINT set_spectral_mix_component")
            if owns_transaction:
                db.commit()
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT set_spectral_mix_component")
            db.execute("RELEASE SAVEPOINT set_spectral_mix_component")
            if owns_transaction:
                db.rollback()
            raise

    def mix_components(self, index_node_id: str) -> List[Dict]:
        rows = self.connection.execute(
            """SELECT p.component_id, p.component_key, m.coefficient_numerator,
                      m.coefficient_denominator
               FROM spectral_mix_components m
               JOIN spectral_components p ON p.component_id = m.component_id
               WHERE m.index_node_id = ? ORDER BY p.component_id""",
            (index_node_id,),
        ).fetchall()
        return [
            {"component_id": row[0], "component_key": row[1],
             "numerator": int(row[2]), "denominator": int(row[3])}
            for row in rows
        ]

    def validate_initial_field(self) -> Dict[str, int]:
        counts = {
            "clusters": self.connection.execute("SELECT COUNT(*) FROM spectral_clusters").fetchone()[0],
            "primary_clusters": self.connection.execute("SELECT COUNT(*) FROM spectral_clusters WHERE role = 'primary'").fetchone()[0],
            "service_clusters": self.connection.execute("SELECT COUNT(*) FROM spectral_clusters WHERE role = 'service'").fetchone()[0],
            "mixing_components": self.connection.execute("SELECT COUNT(*) FROM spectral_components").fetchone()[0],
            "shades": self.connection.execute("SELECT COUNT(*) FROM spectral_shades").fetchone()[0],
            "index_roots": self.connection.execute("SELECT COUNT(*) FROM spectral_index_nodes WHERE depth = 0").fetchone()[0],
        }
        expected = {"clusters": 10, "primary_clusters": 7, "service_clusters": 3,
                    "mixing_components": 7, "shades": 100, "index_roots": 100}
        if counts != expected:
            raise RuntimeError(f"spectral field integrity mismatch: expected {expected}, got {counts}")
        return counts
