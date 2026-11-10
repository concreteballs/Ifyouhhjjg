"""Database-only extension points, semantic links, and hierarchy integrity snapshots."""
import hashlib
import json
import sqlite3


class SpectralExtensionStore:
    """Persist extension metadata and reconcile immutable hierarchy snapshots.

    This module deliberately contains no routing, forwarding, guard-network runtime,
    or spectral-adder behavior.
    """

    def __init__(self, connection, objects):
        self.connection = connection
        self.objects = objects
        self._migrate()

    def _migrate(self):
        db = self.connection
        owns = not db.in_transaction
        if owns:
            db.execute("BEGIN IMMEDIATE")
        db.execute("SAVEPOINT spectral_extensions_v8")
        try:
            statements = (
                """CREATE TABLE IF NOT EXISTS spectral_reserved_regions (
                    region_id TEXT PRIMARY KEY,
                    region_type TEXT NOT NULL CHECK(region_type IN
                        ('reserved', 'guard_placeholder', 'future_space')),
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'reserved'
                        CHECK(status IN ('reserved', 'planned', 'released')),
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_extension_points (
                    point_id TEXT PRIMARY KEY,
                    region_id TEXT REFERENCES spectral_reserved_regions(region_id),
                    point_type TEXT NOT NULL CHECK(point_type IN
                        ('connection', 'guard_placeholder', 'dimension', 'integration')),
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned'
                        CHECK(status IN ('planned', 'available', 'occupied', 'disabled')),
                    object_id TEXT REFERENCES spectral_objects(object_id),
                    coordinate_system_id TEXT REFERENCES coordinate_systems(coordinate_system_id),
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_semantic_links (
                    link_id TEXT PRIMARY KEY,
                    source_object_id TEXT NOT NULL REFERENCES spectral_objects(object_id),
                    target_object_id TEXT NOT NULL REFERENCES spectral_objects(object_id),
                    relation_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK(source_object_id <> target_object_id)
                )""",
                """CREATE INDEX IF NOT EXISTS spectral_semantic_links_source
                    ON spectral_semantic_links(source_object_id, relation_type)""",
                """CREATE INDEX IF NOT EXISTS spectral_semantic_links_target
                    ON spectral_semantic_links(target_object_id, relation_type)""",
                """CREATE TABLE IF NOT EXISTS spectral_interspace_links (
                    link_id TEXT PRIMARY KEY,
                    source_object_id TEXT NOT NULL REFERENCES spectral_objects(object_id),
                    target_object_id TEXT NOT NULL REFERENCES spectral_objects(object_id),
                    source_coordinate_system_id TEXT NOT NULL REFERENCES coordinate_systems(coordinate_system_id),
                    target_coordinate_system_id TEXT NOT NULL REFERENCES coordinate_systems(coordinate_system_id),
                    relation_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK(source_coordinate_system_id <> target_coordinate_system_id
                          OR source_object_id <> target_object_id)
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_hierarchy_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    root_object_id TEXT,
                    object_count INTEGER NOT NULL CHECK(object_count >= 0),
                    digest_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS spectral_hierarchy_snapshot_objects (
                    snapshot_id TEXT NOT NULL REFERENCES spectral_hierarchy_snapshots(snapshot_id) ON DELETE CASCADE,
                    object_id TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    parent_object_id TEXT,
                    hierarchy_order INTEGER NOT NULL,
                    index_node_id TEXT NOT NULL,
                    address_value TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, object_id)
                )""",
                """CREATE INDEX IF NOT EXISTS spectral_snapshot_objects_parent
                    ON spectral_hierarchy_snapshot_objects(snapshot_id, parent_object_id)""",
                """CREATE TABLE IF NOT EXISTS spectral_integrity_events (
                    event_id INTEGER PRIMARY KEY,
                    snapshot_id TEXT NOT NULL REFERENCES spectral_hierarchy_snapshots(snapshot_id),
                    event_type TEXT NOT NULL CHECK(event_type IN
                        ('comparison', 'recovery_started', 'recovery_completed', 'recovery_rejected')),
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""",
            )
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT OR IGNORE INTO spectral_schema_migrations(version) VALUES (8)")
            violations = db.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"foreign-key violations after extension migration: {violations[:5]}")
            db.execute("RELEASE SAVEPOINT spectral_extensions_v8")
            if owns:
                db.commit()
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT spectral_extensions_v8")
            db.execute("RELEASE SAVEPOINT spectral_extensions_v8")
            if owns:
                db.rollback()
            raise

    @staticmethod
    def _required(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _json(value):
        if value is None:
            value = {}
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-serializable") from exc

    def create_reserved_region(self, region_id, region_type, name, description="", metadata=None):
        region_id = self._required(region_id, "region_id")
        name = self._required(name, "name")
        if region_type not in ("reserved", "guard_placeholder", "future_space"):
            raise ValueError("unsupported reserved region type")
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        self.connection.execute(
            """INSERT INTO spectral_reserved_regions
               (region_id, region_type, name, description, metadata_json)
               VALUES (?, ?, ?, ?, ?)""",
            (region_id, region_type, name, description, self._json(metadata)))
        self.connection.commit()
        return self.get_reserved_region(region_id)

    def get_reserved_region(self, region_id):
        row = self.connection.execute(
            """SELECT region_id, region_type, name, description, status, metadata_json
               FROM spectral_reserved_regions WHERE region_id = ?""", (region_id,)).fetchone()
        if row is None:
            raise KeyError("reserved region does not exist")
        return dict(zip(("region_id", "region_type", "name", "description", "status", "metadata"), 
                        (*row[:5], json.loads(row[5]))))

    def set_reserved_region_status(self, region_id, status):
        if status not in ("reserved", "planned", "released"):
            raise ValueError("unsupported reserved region status")
        cur = self.connection.execute(
            """UPDATE spectral_reserved_regions SET status = ?, updated_at = CURRENT_TIMESTAMP
               WHERE region_id = ?""", (status, region_id))
        if cur.rowcount != 1:
            raise KeyError("reserved region does not exist")
        self.connection.commit()
        return self.get_reserved_region(region_id)

    def create_extension_point(self, point_id, point_type, name, region_id=None,
                               object_id=None, coordinate_system_id=None, metadata=None):
        point_id = self._required(point_id, "point_id")
        name = self._required(name, "name")
        if point_type not in ("connection", "guard_placeholder", "dimension", "integration"):
            raise ValueError("unsupported extension point type")
        if region_id is not None and self.connection.execute(
                "SELECT 1 FROM spectral_reserved_regions WHERE region_id = ?", (region_id,)).fetchone() is None:
            raise KeyError("reserved region does not exist")
        self.connection.execute(
            """INSERT INTO spectral_extension_points
               (point_id, region_id, point_type, name, object_id, coordinate_system_id, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (point_id, region_id, point_type, name, object_id, coordinate_system_id, self._json(metadata)))
        self.connection.commit()
        return self.get_extension_point(point_id)

    def get_extension_point(self, point_id):
        row = self.connection.execute(
            """SELECT point_id, region_id, point_type, name, status, object_id,
                      coordinate_system_id, metadata_json
               FROM spectral_extension_points WHERE point_id = ?""", (point_id,)).fetchone()
        if row is None:
            raise KeyError("extension point does not exist")
        keys = ("point_id", "region_id", "point_type", "name", "status", "object_id",
                "coordinate_system_id", "metadata")
        return dict(zip(keys, (*row[:7], json.loads(row[7]))))

    def set_extension_point_status(self, point_id, status):
        if status not in ("planned", "available", "occupied", "disabled"):
            raise ValueError("unsupported extension point status")
        cur = self.connection.execute(
            """UPDATE spectral_extension_points SET status = ?, updated_at = CURRENT_TIMESTAMP
               WHERE point_id = ?""", (status, point_id))
        if cur.rowcount != 1:
            raise KeyError("extension point does not exist")
        self.connection.commit()
        return self.get_extension_point(point_id)

    def create_semantic_link(self, link_id, source_object_id, target_object_id,
                             relation_type, description="", metadata=None):
        link_id = self._required(link_id, "link_id")
        relation_type = self._required(relation_type, "relation_type")
        if source_object_id == target_object_id:
            raise ValueError("semantic self-links are not allowed")
        self.connection.execute(
            """INSERT INTO spectral_semantic_links
               (link_id, source_object_id, target_object_id, relation_type, description, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (link_id, source_object_id, target_object_id, relation_type, description, self._json(metadata)))
        self.connection.commit()
        return self.get_semantic_link(link_id)

    def get_semantic_link(self, link_id):
        row = self.connection.execute(
            """SELECT link_id, source_object_id, target_object_id, relation_type,
                      description, metadata_json FROM spectral_semantic_links WHERE link_id = ?""",
            (link_id,)).fetchone()
        if row is None:
            raise KeyError("semantic link does not exist")
        return dict(zip(("link_id", "source_object_id", "target_object_id", "relation_type",
                         "description", "metadata"), (*row[:5], json.loads(row[5]))))

    def semantic_links_for(self, object_id):
        rows = self.connection.execute(
            """SELECT link_id, source_object_id, target_object_id, relation_type,
                      description, metadata_json FROM spectral_semantic_links
               WHERE source_object_id = ? OR target_object_id = ? ORDER BY link_id""",
            (object_id, object_id)).fetchall()
        return [dict(zip(("link_id", "source_object_id", "target_object_id", "relation_type",
                          "description", "metadata"), (*row[:5], json.loads(row[5])))) for row in rows]

    def create_interspace_link(self, link_id, source_object_id, target_object_id,
                               source_coordinate_system_id, target_coordinate_system_id,
                               relation_type, metadata=None):
        link_id = self._required(link_id, "link_id")
        relation_type = self._required(relation_type, "relation_type")
        if (source_coordinate_system_id == target_coordinate_system_id
                and source_object_id == target_object_id):
            raise ValueError("interspace link must connect distinct object-space endpoints")
        self.connection.execute(
            """INSERT INTO spectral_interspace_links
               (link_id, source_object_id, target_object_id, source_coordinate_system_id,
                target_coordinate_system_id, relation_type, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (link_id, source_object_id, target_object_id, source_coordinate_system_id,
             target_coordinate_system_id, relation_type, self._json(metadata)))
        self.connection.commit()
        return self.get_interspace_link(link_id)

    def get_interspace_link(self, link_id):
        row = self.connection.execute(
            """SELECT link_id, source_object_id, target_object_id,
                      source_coordinate_system_id, target_coordinate_system_id,
                      relation_type, metadata_json FROM spectral_interspace_links WHERE link_id = ?""",
            (link_id,)).fetchone()
        if row is None:
            raise KeyError("interspace link does not exist")
        keys = ("link_id", "source_object_id", "target_object_id",
                "source_coordinate_system_id", "target_coordinate_system_id",
                "relation_type", "metadata")
        return dict(zip(keys, (*row[:6], json.loads(row[6]))))

    def _snapshot_rows(self, root_object_id=None):
        if root_object_id is None:
            rows = self.connection.execute(
                """SELECT o.object_id, o.object_type, o.name, o.parent_object_id,
                          o.hierarchy_order, o.index_node_id, a.address_value
                   FROM spectral_objects o JOIN spectral_object_addresses a
                     ON a.object_id = o.object_id AND a.status = 'active'
                   ORDER BY o.object_id""").fetchall()
        else:
            if self.connection.execute("SELECT 1 FROM spectral_objects WHERE object_id = ?",
                                       (root_object_id,)).fetchone() is None:
                raise KeyError("snapshot root object does not exist")
            ids = self.objects._descendants(root_object_id)
            marks = ",".join("?" for _ in ids)
            rows = self.connection.execute(
                f"""SELECT o.object_id, o.object_type, o.name, o.parent_object_id,
                           o.hierarchy_order, o.index_node_id, a.address_value
                    FROM spectral_objects o JOIN spectral_object_addresses a
                      ON a.object_id = o.object_id AND a.status = 'active'
                    WHERE o.object_id IN ({marks}) ORDER BY o.object_id""", ids).fetchall()
        return rows

    def create_hierarchy_snapshot(self, snapshot_id, root_object_id=None):
        snapshot_id = self._required(snapshot_id, "snapshot_id")
        rows = self._snapshot_rows(root_object_id)
        serial = [list(row) for row in rows]
        digest = hashlib.sha256(json.dumps(serial, ensure_ascii=False,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
        db = self.connection
        owns = not db.in_transaction
        db.execute("SAVEPOINT create_hierarchy_snapshot")
        try:
            db.execute(
                """INSERT INTO spectral_hierarchy_snapshots
                   (snapshot_id, root_object_id, object_count, digest_sha256)
                   VALUES (?, ?, ?, ?)""",
                (snapshot_id, root_object_id, len(rows), digest))
            db.executemany(
                """INSERT INTO spectral_hierarchy_snapshot_objects
                   (snapshot_id, object_id, object_type, name, parent_object_id,
                    hierarchy_order, index_node_id, address_value)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(snapshot_id, *row) for row in rows])
            db.execute("RELEASE SAVEPOINT create_hierarchy_snapshot")
            if owns:
                db.commit()
            return self.get_hierarchy_snapshot(snapshot_id)
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT create_hierarchy_snapshot")
            db.execute("RELEASE SAVEPOINT create_hierarchy_snapshot")
            if owns:
                db.rollback()
            raise

    def get_hierarchy_snapshot(self, snapshot_id):
        row = self.connection.execute(
            """SELECT snapshot_id, root_object_id, object_count, digest_sha256, created_at
               FROM spectral_hierarchy_snapshots WHERE snapshot_id = ?""", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError("hierarchy snapshot does not exist")
        return dict(zip(("snapshot_id", "root_object_id", "object_count", "digest_sha256", "created_at"), row))

    def compare_hierarchy_snapshot(self, snapshot_id):
        self.get_hierarchy_snapshot(snapshot_id)
        expected = {row[0]: row[1:] for row in self.connection.execute(
            """SELECT object_id, object_type, name, parent_object_id, hierarchy_order,
                      index_node_id, address_value
               FROM spectral_hierarchy_snapshot_objects WHERE snapshot_id = ?""", (snapshot_id,))}
        actual = {row[0]: row[1:] for row in self._snapshot_rows()}
        added = sorted(set(actual) - set(expected))
        missing = sorted(set(expected) - set(actual))
        changed = []
        fields = ("object_type", "name", "parent_object_id", "hierarchy_order",
                  "index_node_id", "address_value")
        for object_id in sorted(set(expected) & set(actual)):
            if expected[object_id] != actual[object_id]:
                changed.append({"object_id": object_id,
                                "fields": [fields[i] for i, pair in enumerate(zip(expected[object_id], actual[object_id]))
                                           if pair[0] != pair[1]]})
        report = {"snapshot_id": snapshot_id, "added": added, "missing": missing,
                  "changed": changed, "is_consistent": not (added or missing or changed)}
        self._record_event(snapshot_id, "comparison", report)
        return report

    def _record_event(self, snapshot_id, event_type, details):
        self.connection.execute(
            """INSERT INTO spectral_integrity_events(snapshot_id, event_type, details_json)
               VALUES (?, ?, ?)""", (snapshot_id, event_type, self._json(details)))

    def integrity_events(self, snapshot_id):
        rows = self.connection.execute(
            """SELECT event_id, event_type, details_json, created_at
               FROM spectral_integrity_events WHERE snapshot_id = ? ORDER BY event_id""",
            (snapshot_id,)).fetchall()
        return [{"event_id": r[0], "event_type": r[1], "details": json.loads(r[2]),
                 "created_at": r[3]} for r in rows]

    def restore_hierarchy_snapshot(self, snapshot_id):
        """Restore captured attributes for extant objects; never delete later additions."""
        self.get_hierarchy_snapshot(snapshot_id)
        rows = self.connection.execute(
            """SELECT object_id, object_type, name, parent_object_id, hierarchy_order,
                      index_node_id, address_value
               FROM spectral_hierarchy_snapshot_objects WHERE snapshot_id = ?
               ORDER BY length(COALESCE(parent_object_id, '')), object_id""",
            (snapshot_id,)).fetchall()
        db = self.connection
        missing = [r[0] for r in rows if db.execute(
            "SELECT 1 FROM spectral_objects WHERE object_id = ?", (r[0],)).fetchone() is None]
        if missing:
            report = {"missing_objects": missing, "restored": [], "preserved_new_objects": True}
            self._record_event(snapshot_id, "recovery_rejected", report)
            db.commit()
            raise ValueError("snapshot recovery cannot recreate deleted object identities without an explicit identity policy")
        before = self.compare_hierarchy_snapshot(snapshot_id)
        owns = not db.in_transaction
        db.execute("SAVEPOINT restore_hierarchy_snapshot")
        try:
            self._record_event(snapshot_id, "recovery_started", before)
            # Parent references are checked by the existing FK; cycles are checked before writes.
            parents = {r[0]: r[3] for r in rows}
            for object_id in parents:
                seen = set()
                current = object_id
                while current in parents and parents[current] is not None:
                    if current in seen:
                        raise ValueError("snapshot contains a hierarchy cycle")
                    seen.add(current)
                    current = parents[current]
            for r in rows:
                db.execute(
                    """UPDATE spectral_objects SET object_type = ?, name = ?, parent_object_id = ?,
                              hierarchy_order = ?, index_node_id = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE object_id = ?""", (r[1], r[2], r[3], r[4], r[5], r[0]))
            affected = [r[0] for r in rows]
            self.objects._replace_active_addresses(affected)
            after = self.compare_hierarchy_snapshot(snapshot_id)
            self._record_event(snapshot_id, "recovery_completed", after)
            db.execute("RELEASE SAVEPOINT restore_hierarchy_snapshot")
            if owns:
                db.commit()
            return after
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT restore_hierarchy_snapshot")
            db.execute("RELEASE SAVEPOINT restore_hierarchy_snapshot")
            if owns:
                db.rollback()
            raise
