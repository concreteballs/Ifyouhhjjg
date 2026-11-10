"""Hierarchical spectral objects and reconstructable spectral addresses."""
import sqlite3
from fractions import Fraction


class SpectralObjectStore:
    """Store object hierarchy, versioned spectral addresses, and exact positions."""

    ADDRESS_VERSION = 1

    def __init__(self, connection, geometry):
        self.connection = connection
        self.geometry = geometry
        self._migrate()

    def _migrate(self):
        db = self.connection
        owns = not db.in_transaction
        if owns:
            db.execute("BEGIN IMMEDIATE")
        db.execute("SAVEPOINT spectral_objects_v1")
        try:
            statements = (
                """CREATE TABLE IF NOT EXISTS spectral_objects (
                    object_id TEXT PRIMARY KEY,
                    object_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    parent_object_id TEXT REFERENCES spectral_objects(object_id),
                    hierarchy_order INTEGER NOT NULL DEFAULT 0,
                    index_node_id TEXT NOT NULL REFERENCES spectral_index_nodes(node_id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK(parent_object_id IS NULL OR parent_object_id <> object_id)
                )""",
                """CREATE INDEX IF NOT EXISTS spectral_objects_parent
                   ON spectral_objects(parent_object_id, hierarchy_order, object_id)""",
                """CREATE TABLE IF NOT EXISTS spectral_object_addresses (
                    address_id INTEGER PRIMARY KEY,
                    object_id TEXT NOT NULL REFERENCES spectral_objects(object_id),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    address_value TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('active', 'retired')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(object_id, version)
                )""",
                """CREATE UNIQUE INDEX IF NOT EXISTS spectral_object_one_active_address
                   ON spectral_object_addresses(object_id) WHERE status = 'active'""",
                """CREATE TABLE IF NOT EXISTS spectral_object_address_segments (
                    address_id INTEGER NOT NULL REFERENCES spectral_object_addresses(address_id) ON DELETE CASCADE,
                    segment_order INTEGER NOT NULL CHECK(segment_order >= 0),
                    object_id TEXT NOT NULL REFERENCES spectral_objects(object_id),
                    index_node_id TEXT NOT NULL REFERENCES spectral_index_nodes(node_id),
                    PRIMARY KEY(address_id, segment_order),
                    UNIQUE(address_id, object_id)
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_object_position_coordinates (
                    object_id TEXT NOT NULL REFERENCES spectral_objects(object_id) ON DELETE CASCADE,
                    coordinate_system_id TEXT NOT NULL,
                    axis_order INTEGER NOT NULL,
                    numerator TEXT NOT NULL,
                    denominator TEXT NOT NULL,
                    PRIMARY KEY(object_id, coordinate_system_id, axis_order),
                    FOREIGN KEY(coordinate_system_id, axis_order)
                        REFERENCES coordinate_axes(coordinate_system_id, axis_order)
                )""",
                """CREATE INDEX IF NOT EXISTS spectral_object_coordinates_system
                   ON spectral_object_position_coordinates(coordinate_system_id, object_id)""",
            )
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT OR IGNORE INTO spectral_schema_migrations(version) VALUES (6)")

            migrated_v7 = db.execute(
                "SELECT 1 FROM spectral_schema_migrations WHERE version = 7"
            ).fetchone()
            if not migrated_v7:
                db.execute("""CREATE TABLE spectral_object_addresses_v7 (
                    address_id INTEGER PRIMARY KEY,
                    object_id TEXT NOT NULL REFERENCES spectral_objects(object_id),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    address_value TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'retired')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(object_id, version)
                )""")
                db.execute("""INSERT INTO spectral_object_addresses_v7
                    SELECT address_id, object_id, version, address_value, status, created_at
                    FROM spectral_object_addresses""")
                db.execute("""CREATE TABLE spectral_object_address_segments_v7 (
                    address_id INTEGER NOT NULL REFERENCES spectral_object_addresses_v7(address_id) ON DELETE CASCADE,
                    segment_order INTEGER NOT NULL CHECK(segment_order >= 0),
                    object_id TEXT NOT NULL REFERENCES spectral_objects(object_id),
                    index_node_id TEXT NOT NULL REFERENCES spectral_index_nodes(node_id),
                    PRIMARY KEY(address_id, segment_order),
                    UNIQUE(address_id, object_id)
                )""")
                db.execute("""INSERT INTO spectral_object_address_segments_v7
                    SELECT address_id, segment_order, object_id, index_node_id
                    FROM spectral_object_address_segments""")
                db.execute("DROP TABLE spectral_object_address_segments")
                db.execute("DROP TABLE spectral_object_addresses")
                db.execute("ALTER TABLE spectral_object_addresses_v7 RENAME TO spectral_object_addresses")
                db.execute("ALTER TABLE spectral_object_address_segments_v7 RENAME TO spectral_object_address_segments")
                db.execute("""CREATE UNIQUE INDEX spectral_object_one_active_address
                    ON spectral_object_addresses(object_id) WHERE status = 'active'""")
                db.execute("""CREATE UNIQUE INDEX spectral_object_active_address_value
                    ON spectral_object_addresses(address_value) WHERE status = 'active'""")
                db.execute("INSERT INTO spectral_schema_migrations(version) VALUES (7)")
            else:
                db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS spectral_object_active_address_value
                    ON spectral_object_addresses(address_value) WHERE status = 'active'""")
            violations = db.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"foreign-key violations after object migration: {violations[:5]}")
            db.execute("RELEASE SAVEPOINT spectral_objects_v1")
            if owns:
                db.commit()
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT spectral_objects_v1")
            db.execute("RELEASE SAVEPOINT spectral_objects_v1")
            if owns:
                db.rollback()
            raise

    @staticmethod
    def _required(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string")
        return value.strip()

    def _index_component(self, node_id):
        row = self.connection.execute(
            """SELECT c.standard_band_number, s.grid_row, n.path, c.role
               FROM spectral_index_nodes n
               JOIN spectral_shades s ON s.shade_id = n.shade_id
               JOIN spectral_clusters c ON c.cluster_id = s.cluster_id
               WHERE n.node_id = ?""", (node_id,)
        ).fetchone()
        if row is None:
            raise KeyError("spectral index node does not exist")
        band, gradient, path, role = row
        if role != "primary" or band is None:
            raise PermissionError("service-reserved frequency bands cannot be used in ordinary object addresses")
        component = f"B{int(band):02d}-G{int(gradient):02d}"
        if path:
            component += f"~{path}"
        return component

    def _parent_chain(self, object_id):
        chain = []
        seen = set()
        current = object_id
        while current is not None:
            if current in seen:
                raise ValueError("object hierarchy contains a cycle")
            seen.add(current)
            row = self.connection.execute(
                "SELECT object_id, parent_object_id, index_node_id FROM spectral_objects WHERE object_id = ?",
                (current,)
            ).fetchone()
            if row is None:
                raise KeyError("object does not exist")
            chain.append(row)
            current = row[1]
        chain.reverse()
        return chain

    def _compose_address(self, chain):
        return "/".join(self._index_component(row[2]) for row in chain)


    def _descendants(self, object_id):
        result = []
        queue = [object_id]
        while queue:
            current = queue.pop(0)
            result.append(current)
            queue.extend(row[0] for row in self.connection.execute(
                "SELECT object_id FROM spectral_objects WHERE parent_object_id = ? "
                "ORDER BY hierarchy_order, object_id", (current,)
            ).fetchall())
        return result

    def _replace_active_addresses(self, object_ids):
        db = self.connection
        if not object_ids:
            return
        placeholders = ",".join("?" for _ in object_ids)
        db.execute(
            f"UPDATE spectral_object_addresses SET status = 'retired' "
            f"WHERE status = 'active' AND object_id IN ({placeholders})", object_ids
        )
        for current in object_ids:
            chain = self._parent_chain(current)
            address_value = self._compose_address(chain)
            version = db.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM spectral_object_addresses WHERE object_id = ?",
                (current,)
            ).fetchone()[0]
            cursor = db.execute(
                """INSERT INTO spectral_object_addresses
                   (object_id, version, address_value, status)
                   VALUES (?, ?, ?, 'active')""",
                (current, version, address_value)
            )
            db.executemany(
                """INSERT INTO spectral_object_address_segments
                   (address_id, segment_order, object_id, index_node_id)
                   VALUES (?, ?, ?, ?)""",
                [(cursor.lastrowid, i, row[0], row[2]) for i, row in enumerate(chain)]
            )

    def create_object(self, object_id, object_type, name, index_node_id,
                      parent_object_id=None, hierarchy_order=0):
        object_id = self._required(object_id, "object_id")
        object_type = self._required(object_type, "object_type")
        name = self._required(name, "name")
        if isinstance(hierarchy_order, bool) or not isinstance(hierarchy_order, int):
            raise ValueError("hierarchy_order must be an integer")
        self._index_component(index_node_id)
        db = self.connection
        if parent_object_id is not None:
            parent_object_id = self._required(parent_object_id, "parent_object_id")
            if db.execute("SELECT 1 FROM spectral_objects WHERE object_id = ?",
                          (parent_object_id,)).fetchone() is None:
                raise KeyError("parent object does not exist")
        owns = not db.in_transaction
        db.execute("SAVEPOINT create_spectral_object")
        try:
            db.execute(
                """INSERT INTO spectral_objects
                   (object_id, object_type, name, parent_object_id, hierarchy_order, index_node_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (object_id, object_type, name, parent_object_id, hierarchy_order, index_node_id)
            )
            chain = self._parent_chain(object_id)
            address_value = self._compose_address(chain)
            version = db.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM spectral_object_addresses WHERE object_id = ?",
                (object_id,)
            ).fetchone()[0]
            cursor = db.execute(
                """INSERT INTO spectral_object_addresses
                   (object_id, version, address_value, status) VALUES (?, ?, ?, 'active')""",
                (object_id, version, address_value)
            )
            address_id = cursor.lastrowid
            db.executemany(
                """INSERT INTO spectral_object_address_segments
                   (address_id, segment_order, object_id, index_node_id) VALUES (?, ?, ?, ?)""",
                [(address_id, i, row[0], row[2]) for i, row in enumerate(chain)]
            )
            db.execute("RELEASE SAVEPOINT create_spectral_object")
            if owns:
                db.commit()
            return self.get_object(object_id)
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT create_spectral_object")
            db.execute("RELEASE SAVEPOINT create_spectral_object")
            if owns:
                db.rollback()
            raise

    def update_index_node(self, object_id, index_node_id):
        """Change one object's spectral component and version all affected descendant addresses."""
        self._required(object_id, "object_id")
        self._index_component(index_node_id)
        db = self.connection
        if db.execute("SELECT index_node_id FROM spectral_objects WHERE object_id = ?",
                      (object_id,)).fetchone() is None:
            raise KeyError("object does not exist")
        if db.execute("SELECT index_node_id FROM spectral_objects WHERE object_id = ?",
                      (object_id,)).fetchone()[0] == index_node_id:
            return self.get_object(object_id)

        owns = not db.in_transaction
        db.execute("SAVEPOINT update_object_index")
        try:
            db.execute(
                "UPDATE spectral_objects SET index_node_id = ?, updated_at = CURRENT_TIMESTAMP WHERE object_id = ?",
                (index_node_id, object_id)
            )
            affected = self._descendants(object_id)
            self._replace_active_addresses(affected)
            db.execute("RELEASE SAVEPOINT update_object_index")
            if owns:
                db.commit()
            return self.get_object(object_id)
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT update_object_index")
            db.execute("RELEASE SAVEPOINT update_object_index")
            if owns:
                db.rollback()
            raise


    def rename_object(self, object_id, name):
        """Rename an object without changing its stable identity or address."""
        object_id = self._required(object_id, "object_id")
        name = self._required(name, "name")
        cursor = self.connection.execute(
            "UPDATE spectral_objects SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE object_id = ?",
            (name, object_id)
        )
        if cursor.rowcount != 1:
            raise KeyError("object does not exist")
        return self.get_object(object_id)

    def reorder_object(self, object_id, hierarchy_order):
        """Change sibling display order without changing the address."""
        object_id = self._required(object_id, "object_id")
        if isinstance(hierarchy_order, bool) or not isinstance(hierarchy_order, int):
            raise ValueError("hierarchy_order must be an integer")
        cursor = self.connection.execute(
            "UPDATE spectral_objects SET hierarchy_order = ?, updated_at = CURRENT_TIMESTAMP WHERE object_id = ?",
            (hierarchy_order, object_id)
        )
        if cursor.rowcount != 1:
            raise KeyError("object does not exist")
        return self.get_object(object_id)

    def reparent_object(self, object_id, new_parent_object_id=None, hierarchy_order=None):
        """Move an object subtree and version all affected addresses atomically."""
        object_id = self._required(object_id, "object_id")
        if new_parent_object_id is not None:
            new_parent_object_id = self._required(new_parent_object_id, "new_parent_object_id")
        if hierarchy_order is not None and (
            isinstance(hierarchy_order, bool) or not isinstance(hierarchy_order, int)
        ):
            raise ValueError("hierarchy_order must be an integer")
        db = self.connection
        if db.execute("SELECT 1 FROM spectral_objects WHERE object_id = ?", (object_id,)).fetchone() is None:
            raise KeyError("object does not exist")
        if new_parent_object_id is not None and db.execute(
            "SELECT 1 FROM spectral_objects WHERE object_id = ?", (new_parent_object_id,)
        ).fetchone() is None:
            raise KeyError("new parent object does not exist")
        subtree = self._descendants(object_id)
        if new_parent_object_id in subtree:
            raise ValueError("reparenting would create an object hierarchy cycle")
        current = db.execute(
            "SELECT parent_object_id, hierarchy_order FROM spectral_objects WHERE object_id = ?",
            (object_id,)
        ).fetchone()
        new_order = current[1] if hierarchy_order is None else hierarchy_order
        if current[0] == new_parent_object_id:
            if current[1] != new_order:
                db.execute(
                    "UPDATE spectral_objects SET hierarchy_order = ?, updated_at = CURRENT_TIMESTAMP WHERE object_id = ?",
                    (new_order, object_id)
                )
            return self.get_object(object_id)
        owns = not db.in_transaction
        db.execute("SAVEPOINT reparent_spectral_object")
        try:
            db.execute(
                """UPDATE spectral_objects SET parent_object_id = ?, hierarchy_order = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE object_id = ?""",
                (new_parent_object_id, new_order, object_id)
            )
            self._replace_active_addresses(subtree)
            db.execute("RELEASE SAVEPOINT reparent_spectral_object")
            if owns:
                db.commit()
            return self.get_object(object_id)
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT reparent_spectral_object")
            db.execute("RELEASE SAVEPOINT reparent_spectral_object")
            if owns:
                db.rollback()
            raise

    def get_object(self, object_id):
        row = self.connection.execute(
            """SELECT o.object_id, o.object_type, o.name, o.parent_object_id,
                      o.hierarchy_order, a.address_value, a.version
               FROM spectral_objects o
               LEFT JOIN spectral_object_addresses a
                 ON a.object_id = o.object_id AND a.status = 'active'
               WHERE o.object_id = ?""", (object_id,)
        ).fetchone()
        if row is None:
            raise KeyError("object does not exist")
        return dict(zip(("object_id", "object_type", "name", "parent_object_id",
                         "hierarchy_order", "address", "address_version"), row))

    def children(self, parent_object_id):
        return [self.get_object(row[0]) for row in self.connection.execute(
            """SELECT object_id FROM spectral_objects WHERE parent_object_id = ?
               ORDER BY hierarchy_order, object_id""", (parent_object_id,)
        ).fetchall()]

    def resolve_address(self, address_value):
        if not isinstance(address_value, str) or not address_value:
            raise ValueError("address_value must be a non-empty string")
        row = self.connection.execute(
            """SELECT address_id, object_id, version FROM spectral_object_addresses
               WHERE address_value = ? AND status = 'active'""", (address_value,)
        ).fetchone()
        if row is None:
            raise KeyError("active spectral object address does not exist")
        segments = self.connection.execute(
            """SELECT s.segment_order, s.object_id, o.object_type, o.name,
                      s.index_node_id, o.index_node_id, o.parent_object_id
               FROM spectral_object_address_segments s
               JOIN spectral_objects o ON o.object_id = s.object_id
               WHERE s.address_id = ? ORDER BY s.segment_order""", (row[0],)
        ).fetchall()
        if not segments:
            raise RuntimeError("address has no hierarchy segments")
        expected = list(range(len(segments)))
        if [segment[0] for segment in segments] != expected:
            raise RuntimeError("address hierarchy segments are incomplete")
        if segments[-1][1] != row[1]:
            raise RuntimeError("address terminal segment does not match its object")
        if segments[0][6] is not None:
            raise RuntimeError("address hierarchy does not begin at a root object")
        for segment in segments:
            if segment[4] != segment[5]:
                raise RuntimeError("active address snapshot index does not match current object index")
        for previous, current in zip(segments, segments[1:]):
            if current[6] != previous[1]:
                raise RuntimeError("address segments do not match object parent hierarchy")
        return {
            "address": address_value, "object_id": row[1], "version": row[2],
            "hierarchy": [
                {"level": s[0], "object_id": s[1], "object_type": s[2],
                 "name": s[3], "index_node_id": s[4],
                 "component": self._index_component(s[4])}
                for s in segments
            ]
        }

    def set_coordinates(self, object_id, coordinate_system_id, values):
        system = self.geometry.coordinate_system(coordinate_system_id)
        if self.connection.execute("SELECT 1 FROM spectral_objects WHERE object_id = ?",
                                   (object_id,)).fetchone() is None:
            raise KeyError("object does not exist")
        if not isinstance(values, (list, tuple)) or len(values) != system["dimension_count"]:
            raise ValueError("coordinate count must match coordinate-system dimensions")
        fractions = [self.geometry._fraction(value) for value in values]
        db = self.connection
        owns = not db.in_transaction
        db.execute("SAVEPOINT set_object_coordinates")
        try:
            for order, value in enumerate(fractions):
                db.execute(
                    """INSERT INTO spectral_object_position_coordinates
                       (object_id, coordinate_system_id, axis_order, numerator, denominator)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(object_id, coordinate_system_id, axis_order) DO UPDATE SET
                         numerator = excluded.numerator, denominator = excluded.denominator""",
                    (object_id, coordinate_system_id, order,
                     str(value.numerator), str(value.denominator))
                )
            db.execute("RELEASE SAVEPOINT set_object_coordinates")
            if owns:
                db.commit()
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT set_object_coordinates")
            db.execute("RELEASE SAVEPOINT set_object_coordinates")
            if owns:
                db.rollback()
            raise

    def get_coordinates(self, object_id, coordinate_system_id):
        system = self.geometry.coordinate_system(coordinate_system_id)
        rows = self.connection.execute(
            """SELECT axis_order, numerator, denominator
               FROM spectral_object_position_coordinates
               WHERE object_id = ? AND coordinate_system_id = ? ORDER BY axis_order""",
            (object_id, coordinate_system_id)
        ).fetchall()
        if len(rows) != system["dimension_count"] or [r[0] for r in rows] != list(range(system["dimension_count"])):
            raise KeyError("object has no complete position in this coordinate system")
        return [{"axis": system["axes"][i], "numerator": int(n), "denominator": int(d)}
                for i, n, d in rows]
