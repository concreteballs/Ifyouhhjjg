"""Dimension-independent exact coordinates and non-destructive affine geometry."""
from fractions import Fraction
import json
import sqlite3
from typing import Iterable, Sequence


class SpectralGeometryStore:
    """Store exact N-dimensional positions and reusable affine transforms."""

    DEFAULT_SYSTEM = "spectral-grid-2d-v1"

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._migrate()

    def _migrate(self):
        db = self.connection
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 30000")
        owns = not db.in_transaction
        if owns:
            db.execute("BEGIN IMMEDIATE")
        db.execute("SAVEPOINT spectral_geometry_v1")
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS spectral_position_coordinates (
                shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
                coordinate_system_id TEXT NOT NULL,
                axis_order INTEGER NOT NULL,
                numerator INTEGER NOT NULL,
                denominator INTEGER NOT NULL CHECK(denominator > 0),
                PRIMARY KEY(shade_id, coordinate_system_id, axis_order),
                FOREIGN KEY(coordinate_system_id, axis_order)
                    REFERENCES coordinate_axes(coordinate_system_id, axis_order)
            )""")
            db.execute("""INSERT OR IGNORE INTO spectral_position_coordinates
                (shade_id, coordinate_system_id, axis_order, numerator, denominator)
                SELECT shade_id, coordinate_system_id, 0, x_numerator, x_denominator
                FROM spectral_positions""")
            db.execute("""INSERT OR IGNORE INTO spectral_position_coordinates
                (shade_id, coordinate_system_id, axis_order, numerator, denominator)
                SELECT shade_id, coordinate_system_id, 1, y_numerator, y_denominator
                FROM spectral_positions""")
            db.execute("""INSERT OR IGNORE INTO spectral_schema_migrations(version)
                VALUES (3)""")
            db.execute("RELEASE SAVEPOINT spectral_geometry_v1")
            if owns:
                db.commit()
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT spectral_geometry_v1")
            db.execute("RELEASE SAVEPOINT spectral_geometry_v1")
            if owns:
                db.rollback()
            raise

    @staticmethod
    def _fraction(value):
        if isinstance(value, bool):
            raise ValueError("boolean is not a coordinate value")
        if isinstance(value, Fraction):
            return value
        if isinstance(value, int):
            return Fraction(value, 1)
        if (isinstance(value, (tuple, list)) and len(value) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
                and value[1] != 0):
            return Fraction(value[0], value[1])
        raise ValueError("coordinate values must be integers, Fractions, or (numerator, denominator) pairs")

    def create_coordinate_system(self, coordinate_system_id: str, name: str,
                                 axes: Sequence[str], unit_name: str = "unit"):
        if not isinstance(coordinate_system_id, str) or not coordinate_system_id:
            raise ValueError("coordinate_system_id must be non-empty")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be non-empty")
        if not isinstance(unit_name, str) or not unit_name:
            raise ValueError("unit_name must be non-empty")
        if (not isinstance(axes, (list, tuple)) or len(axes) < 2
                or any(not isinstance(axis, str) or not axis for axis in axes)
                or len(set(axes)) != len(axes)):
            raise ValueError("axes must contain at least two unique non-empty names")
        db = self.connection
        db.execute("SAVEPOINT create_coordinate_system")
        try:
            db.execute("""INSERT INTO coordinate_systems
                (coordinate_system_id, name, dimension_count, unit_name)
                VALUES (?, ?, ?, ?)""",
                (coordinate_system_id, name, len(axes), unit_name))
            db.executemany("""INSERT INTO coordinate_axes
                (coordinate_system_id, axis_order, axis_name) VALUES (?, ?, ?)""",
                [(coordinate_system_id, i, axis) for i, axis in enumerate(axes)])
            db.execute("RELEASE SAVEPOINT create_coordinate_system")
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT create_coordinate_system")
            db.execute("RELEASE SAVEPOINT create_coordinate_system")
            raise

    def coordinate_system(self, coordinate_system_id: str):
        row = self.connection.execute("""SELECT name, dimension_count, unit_name
            FROM coordinate_systems WHERE coordinate_system_id = ?""",
            (coordinate_system_id,)).fetchone()
        if row is None:
            raise KeyError("coordinate system does not exist")
        axes = self.connection.execute("""SELECT axis_order, axis_name
            FROM coordinate_axes WHERE coordinate_system_id = ? ORDER BY axis_order""",
            (coordinate_system_id,)).fetchall()
        if len(axes) != row[1] or [a[0] for a in axes] != list(range(row[1])):
            raise RuntimeError("coordinate system axis definition is incomplete")
        return {"coordinate_system_id": coordinate_system_id, "name": row[0],
                "dimension_count": row[1], "unit_name": row[2],
                "axes": [a[1] for a in axes]}

    def set_coordinates(self, shade_id: str, coordinate_system_id: str,
                        values: Sequence):
        system = self.coordinate_system(coordinate_system_id)
        if self.connection.execute("SELECT 1 FROM spectral_shades WHERE shade_id = ?",
                                    (shade_id,)).fetchone() is None:
            raise KeyError("shade does not exist")
        if not isinstance(values, (list, tuple)) or len(values) != system["dimension_count"]:
            raise ValueError("coordinate count must match coordinate-system dimensions")
        fractions = [self._fraction(value) for value in values]
        db = self.connection
        db.execute("SAVEPOINT set_spectral_coordinates")
        try:
            for order, value in enumerate(fractions):
                db.execute("""INSERT INTO spectral_position_coordinates
                    (shade_id, coordinate_system_id, axis_order, numerator, denominator)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(shade_id, coordinate_system_id, axis_order) DO UPDATE SET
                    numerator = excluded.numerator, denominator = excluded.denominator""",
                    (shade_id, coordinate_system_id, order,
                     value.numerator, value.denominator))
            if coordinate_system_id == self.DEFAULT_SYSTEM and len(fractions) == 2:
                db.execute("""UPDATE spectral_positions SET
                    x_numerator = ?, x_denominator = ?, y_numerator = ?, y_denominator = ?
                    WHERE shade_id = ? AND coordinate_system_id = ?""",
                    (fractions[0].numerator, fractions[0].denominator,
                     fractions[1].numerator, fractions[1].denominator,
                     shade_id, coordinate_system_id))
            db.execute("RELEASE SAVEPOINT set_spectral_coordinates")
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT set_spectral_coordinates")
            db.execute("RELEASE SAVEPOINT set_spectral_coordinates")
            raise

    def get_coordinates(self, shade_id: str, coordinate_system_id: str = DEFAULT_SYSTEM):
        system = self.coordinate_system(coordinate_system_id)
        rows = self.connection.execute("""SELECT axis_order, numerator, denominator
            FROM spectral_position_coordinates
            WHERE shade_id = ? AND coordinate_system_id = ? ORDER BY axis_order""",
            (shade_id, coordinate_system_id)).fetchall()
        if len(rows) != system["dimension_count"] or [r[0] for r in rows] != list(range(system["dimension_count"])):
            raise KeyError("shade has no complete position in this coordinate system")
        return [{"axis": system["axes"][i], "numerator": n, "denominator": d}
                for i, n, d in rows]

    def create_affine_transform(self, transform_id: str, coordinate_system_id: str,
                                matrix: Sequence[Sequence], offset: Sequence):
        """Persist x' = matrix*x + offset using exact rational coefficients."""
        system = self.coordinate_system(coordinate_system_id)
        size = system["dimension_count"]
        if not isinstance(transform_id, str) or not transform_id:
            raise ValueError("transform_id must be non-empty")
        if not isinstance(matrix, (list, tuple)) or len(matrix) != size:
            raise ValueError("transform matrix must be square and match the dimension count")
        if any(not isinstance(row, (list, tuple)) or len(row) != size for row in matrix):
            raise ValueError("every transform matrix row must match the dimension count")
        if not isinstance(offset, (list, tuple)) or len(offset) != size:
            raise ValueError("transform offset must match the dimension count")
        m = [[self._fraction(v) for v in row] for row in matrix]
        b = [self._fraction(v) for v in offset]
        payload = {"matrix": [[[v.numerator, v.denominator] for v in row] for row in m],
                   "offset": [[v.numerator, v.denominator] for v in b]}
        self.connection.execute("""INSERT INTO geometry_transforms
            (transform_id, coordinate_system_id, transform_type, parameters_json)
            VALUES (?, ?, 'affine-rational', ?)""",
            (transform_id, coordinate_system_id,
             json.dumps(payload, separators=(",", ":"), sort_keys=True)))

    def create_scale_transform(self, transform_id: str, coordinate_system_id: str,
                               factors: Sequence, offset: Sequence = None):
        system = self.coordinate_system(coordinate_system_id)
        size = system["dimension_count"]
        if not isinstance(factors, (list, tuple)) or len(factors) != size:
            raise ValueError("one scale factor is required for each axis")
        if offset is None:
            offset = [0] * size
        matrix = [[self._fraction(factors[i]) if i == j else Fraction(0, 1)
                   for j in range(size)] for i in range(size)]
        self.create_affine_transform(transform_id, coordinate_system_id, matrix, offset)

    def apply_transform(self, shade_id: str, transform_id: str):
        row = self.connection.execute("""SELECT coordinate_system_id, parameters_json
            FROM geometry_transforms WHERE transform_id = ?""", (transform_id,)).fetchone()
        if row is None:
            raise KeyError("geometry transform does not exist")
        coordinate_system_id, raw = row
        coords = self.get_coordinates(shade_id, coordinate_system_id)
        payload = json.loads(raw)
        vector = [Fraction(item["numerator"], item["denominator"]) for item in coords]
        matrix = [[Fraction(*pair) for pair in line] for line in payload["matrix"]]
        offset = [Fraction(*pair) for pair in payload["offset"]]
        result = [sum((matrix[i][j] * vector[j] for j in range(len(vector))), Fraction(0, 1))
                  + offset[i] for i in range(len(vector))]
        return {"shade_id": shade_id, "coordinate_system_id": coordinate_system_id,
                "transform_id": transform_id,
                "coordinates": [{"axis": coords[i]["axis"], "numerator": v.numerator,
                                 "denominator": v.denominator}
                                for i, v in enumerate(result)]}

    def apply_transform_to_field(self, transform_id: str):
        row = self.connection.execute("""SELECT coordinate_system_id
            FROM geometry_transforms WHERE transform_id = ?""", (transform_id,)).fetchone()
        if row is None:
            raise KeyError("geometry transform does not exist")
        shades = self.connection.execute("SELECT shade_id FROM spectral_shades ORDER BY shade_id").fetchall()
        return [self.apply_transform(item[0], transform_id) for item in shades]
