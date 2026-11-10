import sqlite3
import tempfile
import unittest
from pathlib import Path
from fractions import Fraction

from spectral_core import SpectralDatabase


class SpectralFieldDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = SpectralDatabase()
        self.field = self.db.spectral_field
        self.geometry = self.field.geometry

    def tearDown(self):
        self.db.close()

    def test_initial_field_has_ten_clusters_seven_primary_and_three_service(self):
        self.assertEqual(
            self.field.validate_initial_field(),
            {"clusters": 10, "primary_clusters": 7, "service_clusters": 3,
             "mixing_components": 7, "shades": 100, "index_roots": 100},
        )
        clusters = self.field.clusters()
        self.assertEqual(clusters[0]["lower_hz"], 300)
        self.assertEqual(clusters[0]["upper_hz"], 3_000)
        self.assertEqual(clusters[1]["designation"], "VLF")
        self.assertEqual(clusters[2]["designation"], "LF")
        self.assertEqual(clusters[2]["visual_order"], 1)
        self.assertEqual(clusters[8]["designation"], "EHF")
        self.assertEqual(clusters[8]["visual_order"], 7)
        self.assertIsNone(clusters[0]["visual_order"])
        self.assertEqual(clusters[9]["lower_hz"], 300_000_000_000)
        self.assertEqual(clusters[9]["upper_hz"], 3_000_000_000_000)

    def test_primary_index_splits_into_exact_halves_and_can_split_again(self):
        children = self.field.split_index("SC03-G00")
        self.assertEqual(children[0]["lower"], (0, 1))
        self.assertEqual(children[0]["upper"], (1, 20))
        self.assertEqual(children[1]["lower"], (1, 20))
        self.assertEqual(children[1]["upper"], (1, 10))
        grandchildren = self.field.split_index("SC03-G00", "0")
        self.assertEqual(grandchildren[0]["lower"], (0, 1))
        self.assertEqual(grandchildren[0]["upper"], (1, 40))
        self.assertEqual(grandchildren[1]["lower"], (1, 40))
        self.assertEqual(grandchildren[1]["upper"], (1, 20))

    def test_recursive_index_exceeds_sqlite_integer_limit_without_precision_loss(self):
        path = ""
        for _ in range(70):
            self.field.split_index("SC03-G00", path)
            path += "0"
        leaf = self.db.connection.execute(
            "SELECT lower_numerator, lower_denominator, upper_numerator, upper_denominator "
            "FROM spectral_index_nodes WHERE shade_id = ? AND path = ?",
            ("SC03-G00", path),
        ).fetchone()
        self.assertTrue(all(isinstance(value, str) for value in leaf))
        self.assertGreater(len(leaf[3]), 19)
        lower = Fraction(int(leaf[0]), int(leaf[1]))
        upper = Fraction(int(leaf[2]), int(leaf[3]))
        self.assertEqual(upper - lower, Fraction(1, 10 * (2 ** 70)))
        component_id = self.db.connection.execute(
            "SELECT component_id FROM spectral_components WHERE cluster_id = 3"
        ).fetchone()[0]
        self.field.set_mix_component(f"SC03-G00:{path}", component_id, 1, 2 ** 80)
        self.assertEqual(self.field.mix_components(f"SC03-G00:{path}")[0]["denominator"], 2 ** 80)
        self.assertEqual(self.db.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_service_zone_index_cannot_be_subdivided_for_mixing(self):
        for shade_id in ("SC01-G00", "SC02-G00", "SC10-G00"):
            with self.assertRaises(PermissionError):
                self.field.split_index(shade_id)

    def test_index_node_cannot_be_split_twice(self):
        self.field.split_index("SC03-G00")
        with self.assertRaises(ValueError):
            self.field.split_index("SC03-G00")

    def test_mixing_uses_only_seven_primary_components_and_exact_coefficients(self):
        component3 = self.db.connection.execute(
            "SELECT component_id FROM spectral_components WHERE cluster_id = 3"
        ).fetchone()[0]
        component4 = self.db.connection.execute(
            "SELECT component_id FROM spectral_components WHERE cluster_id = 4"
        ).fetchone()[0]
        self.field.set_mix_component("SC03-G00:", component3, 2, 6)
        self.field.set_mix_component("SC03-G00:", component4, 5, 7)
        self.assertEqual(
            self.field.mix_components("SC03-G00:"),
            [
                {"component_id": component3, "component_key": "cluster-03", "numerator": 1, "denominator": 3},
                {"component_id": component4, "component_key": "cluster-04", "numerator": 5, "denominator": 7},
            ],
        )

    def test_recursive_child_is_a_distinct_mixable_index_value(self):
        component3 = self.db.connection.execute(
            "SELECT component_id FROM spectral_components WHERE cluster_id = 3"
        ).fetchone()[0]
        child = self.field.split_index("SC03-G00")[0]
        self.field.set_mix_component(child["node_id"], component3, 1, 2)
        self.assertEqual(self.field.mix_components(child["node_id"])[0]["numerator"], 1)

    def test_service_shade_cannot_be_used_in_mixing(self):
        component3 = self.db.connection.execute(
            "SELECT component_id FROM spectral_components WHERE cluster_id = 3"
        ).fetchone()[0]
        with self.assertRaises(PermissionError):
            self.field.set_mix_component("SC01-G00:", component3, 1, 2)

    def test_service_cluster_cannot_be_a_mixing_component(self):
        with self.assertRaises(KeyError):
            self.field.set_mix_component("SC03-G00:", 10, 1, 2)

    def test_existing_endpoint_store_remains_available_after_migration(self):
        from spectral_core import SpectralAddress
        address = SpectralAddress("123")
        self.db.put(address, b"preserved")
        self.assertEqual(self.db.get(address), b"preserved")

    def test_set_mix_component_respects_outer_transaction_rollback(self):
        component_id = self.db.connection.execute(
            "SELECT component_id FROM spectral_components WHERE cluster_id = 3"
        ).fetchone()[0]
        self.db.connection.execute("BEGIN")
        self.field.set_mix_component("SC03-G00:", component_id, 3, 5)
        self.assertEqual(len(self.field.mix_components("SC03-G00:")), 1)
        self.db.connection.rollback()
        self.assertEqual(self.field.mix_components("SC03-G00:"), [])

    def test_gradient_rows_increase_from_top_to_bottom(self):
        top = self.geometry.get_coordinates("SC03-G00")
        bottom = self.geometry.get_coordinates("SC03-G09")
        self.assertEqual(top[1], {
            "axis": "gradient-row", "numerator": 0, "denominator": 1
        })
        self.assertEqual(bottom[1], {
            "axis": "gradient-row", "numerator": 9, "denominator": 1
        })
        self.assertLess(top[1]["numerator"], bottom[1]["numerator"])

    def test_spectral_data_and_transforms_survive_database_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spectral-persistence.sqlite"
            first = SpectralDatabase(path)
            component_id = first.connection.execute(
                "SELECT component_id FROM spectral_components WHERE cluster_id = 3"
            ).fetchone()[0]
            first.spectral_field.set_mix_component("SC03-G00:", component_id, 7, 11)
            first.spectral_field.geometry.create_coordinate_system(
                "persisted-3d", "Persistent 3D", ["x", "y", "z"], "unit"
            )
            first.spectral_field.geometry.set_coordinates(
                "SC03-G00", "persisted-3d", [1, (2, 3), 4]
            )
            first.spectral_field.geometry.create_scale_transform(
                "persisted-scale", "persisted-3d", [2, 3, 4]
            )
            first.close()

            reopened = SpectralDatabase(path)
            try:
                self.assertEqual(
                    reopened.spectral_field.mix_components("SC03-G00:")[0]["numerator"],
                    7,
                )
                self.assertEqual(
                    reopened.spectral_field.mix_components("SC03-G00:")[0]["denominator"],
                    11,
                )
                self.assertEqual(
                    reopened.spectral_field.geometry.get_coordinates(
                        "SC03-G00", "persisted-3d"
                    ),
                    [
                        {"axis": "x", "numerator": 1, "denominator": 1},
                        {"axis": "y", "numerator": 2, "denominator": 3},
                        {"axis": "z", "numerator": 4, "denominator": 1},
                    ],
                )
                transformed = reopened.spectral_field.geometry.apply_transform(
                    "SC03-G00", "persisted-scale"
                )
                self.assertEqual(
                    [(v["numerator"], v["denominator"])
                     for v in transformed["coordinates"]],
                    [(2, 1), (2, 1), (16, 1)],
                )
                self.assertEqual(
                    reopened.connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    reopened.connection.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )
            finally:
                reopened.close()

    def test_visual_codes_are_not_guessed_or_auto_assigned(self):
        row = self.db.connection.execute(
            """SELECT rgb_hex, visual_code_system FROM spectral_shade_versions
               WHERE shade_id = 'SC03-G00'"""
        ).fetchone()
        self.assertEqual(row, (None, None))

    def test_upgrade_preserves_earlier_mix_rows_as_root_index_values(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("""CREATE TABLE spectral_clusters (
            cluster_id INTEGER PRIMARY KEY, cluster_order INTEGER NOT NULL UNIQUE,
            designation TEXT NOT NULL UNIQUE, lower_hz INTEGER NOT NULL,
            upper_hz INTEGER NOT NULL, standard_band_number INTEGER,
            role TEXT NOT NULL, mixing_enabled INTEGER NOT NULL, source_note TEXT NOT NULL)""")
        connection.execute("""CREATE TABLE spectral_components (
            component_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id INTEGER NOT NULL UNIQUE REFERENCES spectral_clusters(cluster_id),
            component_key TEXT NOT NULL UNIQUE)""")
        connection.execute("""CREATE TABLE spectral_shades (
            shade_id TEXT PRIMARY KEY, cluster_id INTEGER NOT NULL REFERENCES spectral_clusters(cluster_id),
            grid_column INTEGER NOT NULL, grid_row INTEGER NOT NULL,
            UNIQUE(cluster_id, grid_row), UNIQUE(grid_column, grid_row))""")
        connection.execute("""CREATE TABLE spectral_index_nodes (
            node_id TEXT PRIMARY KEY, shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
            parent_node_id TEXT REFERENCES spectral_index_nodes(node_id), branch TEXT NOT NULL,
            path TEXT NOT NULL, depth INTEGER NOT NULL, lower_numerator INTEGER NOT NULL,
            lower_denominator INTEGER NOT NULL, upper_numerator INTEGER NOT NULL,
            upper_denominator INTEGER NOT NULL, UNIQUE(shade_id, path))""")
        connection.execute("""CREATE TABLE spectral_mix_components (
            shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
            component_id INTEGER NOT NULL REFERENCES spectral_components(component_id),
            coefficient_numerator INTEGER NOT NULL, coefficient_denominator INTEGER NOT NULL,
            PRIMARY KEY(shade_id, component_id))""")
        connection.execute("""INSERT INTO spectral_clusters
            VALUES (3, 3, 'LF', 30000, 300000, 5, 'primary', 1, 'legacy')""")
        connection.execute("INSERT INTO spectral_components(cluster_id, component_key) VALUES (3, 'cluster-03')")
        connection.execute("INSERT INTO spectral_shades VALUES ('SC03-G00', 3, 3, 0)")
        connection.execute("""INSERT INTO spectral_index_nodes VALUES
            ('SC03-G00:', 'SC03-G00', NULL, 'root', '', 0, 0, 1, 1, 10)""")
        connection.execute("""CREATE TABLE spectral_positions (
            shade_id TEXT NOT NULL, coordinate_system_id TEXT NOT NULL,
            x_numerator INTEGER NOT NULL, x_denominator INTEGER NOT NULL,
            y_numerator INTEGER NOT NULL, y_denominator INTEGER NOT NULL,
            PRIMARY KEY(shade_id, coordinate_system_id))""")
        connection.execute("""INSERT INTO spectral_positions VALUES
            ('SC03-G00', 'spectral-grid-2d-v1', 2, 1, 0, 1)""")
        connection.execute("INSERT INTO spectral_mix_components VALUES ('SC03-G00', 1, 2, 6)")
        connection.commit()
        from spectral_core.spectral_field import SpectralFieldStore
        field = SpectralFieldStore(connection)
        migrated = field.mix_components("SC03-G00:")
        self.assertEqual(migrated[0]["numerator"], 2)
        self.assertEqual(migrated[0]["denominator"], 6)
        interval = connection.execute(
            "SELECT lower_numerator, lower_denominator, upper_numerator, upper_denominator "
            "FROM spectral_index_nodes WHERE node_id = 'SC03-G00:'"
        ).fetchone()
        self.assertEqual(interval, ("0", "1", "1", "10"))
        from spectral_core.geometry import SpectralGeometryStore
        geometry = SpectralGeometryStore(connection)
        self.assertEqual(geometry.get_coordinates("SC03-G00"), [
            {"axis": "cluster-column", "numerator": 2, "denominator": 1},
            {"axis": "gradient-row", "numerator": 0, "denominator": 1},
        ])
        self.assertEqual(connection.execute("PRAGMA table_info(spectral_positions)").fetchall()[2][2].upper(), "TEXT")
        self.assertEqual(connection.execute("PRAGMA table_info(spectral_position_coordinates)").fetchall()[3][2].upper(), "TEXT")
        self.assertEqual(connection.execute("PRAGMA table_info(spectral_mix_components)").fetchall()[2][2].upper(), "TEXT")
        self.assertEqual(connection.execute("PRAGMA table_info(spectral_mix_components)").fetchall()[0][1],
                         "index_node_id")
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='spectral_mix_components_legacy_v1'"
        ).fetchone()[0], 0)
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(connection.execute("PRAGMA table_info(spectral_index_nodes)").fetchall()[6][2].upper(), "TEXT")
        connection.close()

    def test_existing_two_dimensional_positions_are_migrated_to_generic_axes(self):
        rows = self.geometry.get_coordinates("SC03-G04")
        self.assertEqual(rows, [
            {"axis": "cluster-column", "numerator": 2, "denominator": 1},
            {"axis": "gradient-row", "numerator": 4, "denominator": 1},
        ])
        self.assertEqual(self.db.connection.execute(
            "SELECT COUNT(*) FROM spectral_position_coordinates"
        ).fetchone()[0], 200)

    def test_exact_scale_and_translation_do_not_change_shade_identity(self):
        before = self.geometry.get_coordinates("SC03-G04")
        self.geometry.create_affine_transform(
            "scale-and-shift", "spectral-grid-2d-v1",
            [[2, 0], [0, 3]], [1, -1])
        result = self.geometry.apply_transform("SC03-G04", "scale-and-shift")
        self.assertEqual(result["coordinates"], [
            {"axis": "cluster-column", "numerator": 5, "denominator": 1},
            {"axis": "gradient-row", "numerator": 11, "denominator": 1},
        ])
        self.assertEqual(self.geometry.get_coordinates("SC03-G04"), before)
        self.assertEqual(result["shade_id"], "SC03-G04")
        self.assertEqual(self.geometry.apply_transform_to_field("scale-and-shift")[0]["shade_id"],
                         "SC01-G00")

    def test_fractional_scale_remains_exact(self):
        self.geometry.create_scale_transform("half-scale", "spectral-grid-2d-v1",
                                             [Fraction(1, 2), Fraction(1, 3)])
        result = self.geometry.apply_transform("SC03-G03", "half-scale")
        self.assertEqual([(v["numerator"], v["denominator"]) for v in result["coordinates"]],
                         [(1, 1), (1, 1)])

    def test_coordinate_system_supports_more_than_two_dimensions(self):
        self.geometry.create_coordinate_system(
            "spectral-space-3d-v1", "Three dimensional extension",
            ["cluster", "gradient", "depth"], "grid-unit")
        self.geometry.set_coordinates("SC03-G04", "spectral-space-3d-v1", [2, 4, (3, 2)])
        self.assertEqual(self.geometry.get_coordinates("SC03-G04", "spectral-space-3d-v1"), [
            {"axis": "cluster", "numerator": 2, "denominator": 1},
            {"axis": "gradient", "numerator": 4, "denominator": 1},
            {"axis": "depth", "numerator": 3, "denominator": 2},
        ])
        self.geometry.create_affine_transform(
            "3d-affine", "spectral-space-3d-v1",
            [[1, 0, 0], [0, 2, 0], [0, 0, 1]], [0, 1, (1, 2)])
        transformed = self.geometry.apply_transform("SC03-G04", "3d-affine")
        self.assertEqual([(v["numerator"], v["denominator"]) for v in transformed["coordinates"]],
                         [(2, 1), (9, 1), (2, 1)])

    def test_geometry_coordinates_support_values_beyond_sqlite_integer_limit(self):
        self.geometry.create_coordinate_system(
            "huge-rational-space", "Huge rational coordinates", ["x", "y"], "unit"
        )
        huge = Fraction(1, 2 ** 100)
        self.geometry.set_coordinates("SC03-G00", "huge-rational-space", [huge, -huge])
        values = self.geometry.get_coordinates("SC03-G00", "huge-rational-space")
        self.assertEqual(values[0]["numerator"], 1)
        self.assertEqual(values[0]["denominator"], 2 ** 100)
        self.assertEqual(values[1]["numerator"], -1)
        self.assertEqual(values[1]["denominator"], 2 ** 100)

    def test_v5_migrates_existing_integer_coordinate_storage(self):
        connection = self.db.connection
        connection.execute(
            "ALTER TABLE spectral_position_coordinates "
            "RENAME TO spectral_position_coordinates_before_v5"
        )
        connection.execute("""CREATE TABLE spectral_position_coordinates (
            shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
            coordinate_system_id TEXT NOT NULL, axis_order INTEGER NOT NULL,
            numerator INTEGER NOT NULL, denominator INTEGER NOT NULL CHECK(denominator > 0),
            PRIMARY KEY(shade_id, coordinate_system_id, axis_order),
            FOREIGN KEY(coordinate_system_id, axis_order)
                REFERENCES coordinate_axes(coordinate_system_id, axis_order))""")
        connection.execute("""INSERT INTO spectral_position_coordinates
            SELECT shade_id, coordinate_system_id, axis_order,
                   CAST(numerator AS INTEGER), CAST(denominator AS INTEGER)
            FROM spectral_position_coordinates_before_v5""")
        connection.execute("DROP TABLE spectral_position_coordinates_before_v5")
        connection.commit()
        from spectral_core.geometry import SpectralGeometryStore
        migrated = SpectralGeometryStore(connection)
        self.assertEqual(migrated.get_coordinates("SC03-G04"), [
            {"axis": "cluster-column", "numerator": 2, "denominator": 1},
            {"axis": "gradient-row", "numerator": 4, "denominator": 1},
        ])
        info = {row[1]: row[2].upper()
                for row in connection.execute("PRAGMA table_info(spectral_position_coordinates)")}
        self.assertEqual(info["numerator"], "TEXT")
        self.assertEqual(info["denominator"], "TEXT")
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_coordinate_dimension_and_transform_shapes_are_validated(self):
        with self.assertRaises(ValueError):
            self.geometry.set_coordinates("SC03-G00", "spectral-grid-2d-v1", [1, 2, 3])
        with self.assertRaises(ValueError):
            self.geometry.create_affine_transform(
                "bad-matrix", "spectral-grid-2d-v1", [[1, 0]], [0, 0])


if __name__ == "__main__":
    unittest.main()
