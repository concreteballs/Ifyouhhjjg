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

    def test_recursive_index_tree_metadata_and_partition_are_consistent(self):
        root_id = "SC03-G00:"
        children = self.field.split_index("SC03-G00")
        rows = self.db.connection.execute(
            """SELECT node_id, parent_node_id, branch, path, depth,
                      lower_numerator, lower_denominator, upper_numerator, upper_denominator
               FROM spectral_index_nodes WHERE parent_node_id = ? ORDER BY path""",
            (root_id,),
        ).fetchall()
        self.assertEqual([row[0] for row in rows],
                         ["SC03-G00:0", "SC03-G00:1"])
        self.assertEqual([row[1] for row in rows], [root_id, root_id])
        self.assertEqual([(row[2], row[3], row[4]) for row in rows],
                         [("left", "0", 1), ("right", "1", 1)])
        left_upper = Fraction(int(rows[0][7]), int(rows[0][8]))
        right_lower = Fraction(int(rows[1][5]), int(rows[1][6]))
        self.assertEqual(left_upper, right_lower)
        self.assertEqual(Fraction(*children[0]["lower"]), Fraction(0, 1))
        self.assertEqual(Fraction(*children[1]["upper"]), Fraction(1, 10))
        grandchildren = self.field.split_index("SC03-G00", "1")
        self.assertEqual([item["path"] for item in grandchildren], ["10", "11"])
        self.assertTrue(all(item["depth"] == 2 for item in grandchildren))
        self.assertEqual(grandchildren[0]["upper"], grandchildren[1]["lower"])

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

    def test_mix_coefficients_allow_zero_and_reject_negative_or_zero_denominator(self):
        component_id = self.db.connection.execute(
            "SELECT component_id FROM spectral_components WHERE cluster_id = 3"
        ).fetchone()[0]
        self.field.set_mix_component("SC03-G00:", component_id, 0, 17)
        self.assertEqual(
            self.field.mix_components("SC03-G00:")[0]["numerator"], 0
        )
        self.assertEqual(
            self.field.mix_components("SC03-G00:")[0]["denominator"], 1
        )
        with self.assertRaises(ValueError):
            self.field.set_mix_component("SC03-G00:", component_id, -1, 2)
        with self.assertRaises(ValueError):
            self.field.set_mix_component("SC03-G00:", component_id, 1, 0)
        with self.assertRaises(ValueError):
            self.field.set_mix_component("SC03-G00:", component_id, True, 1)

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

    def test_spectral_migration_preserves_endpoint_receipt_and_correction_tables(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("""CREATE TABLE endpoint_data (
            spectral_id TEXT PRIMARY KEY, payload BLOB NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        connection.execute("""CREATE TABLE packet_receipts (
            packet_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, expires_at INTEGER NOT NULL)""")
        connection.execute("""CREATE TABLE route_correction_nonces (
            nonce TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)""")
        connection.execute("""CREATE TABLE applied_route_corrections (
            previous_router TEXT NOT NULL, destination_id TEXT NOT NULL,
            rejected_next_hop TEXT NOT NULL, corrected_next_hop TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            PRIMARY KEY(previous_router, destination_id))""")
        connection.execute("INSERT INTO endpoint_data VALUES ('endpoint-1', X'616263', 'before')")
        connection.execute("INSERT INTO packet_receipts VALUES ('packet-1', 'source-1', 500)")
        connection.execute("INSERT INTO route_correction_nonces VALUES ('nonce-1', 600)")
        connection.execute(
            "INSERT INTO applied_route_corrections VALUES "
            "('router-a', 'destination-a', 'router-b', 'router-c', 700)"
        )
        connection.commit()
        from spectral_core.spectral_field import SpectralFieldStore
        from spectral_core.geometry import SpectralGeometryStore
        SpectralFieldStore(connection)
        SpectralGeometryStore(connection)
        self.assertEqual(connection.execute(
            "SELECT spectral_id, payload, updated_at FROM endpoint_data"
        ).fetchall(), [("endpoint-1", b"abc", "before")])
        self.assertEqual(connection.execute(
            "SELECT * FROM packet_receipts"
        ).fetchall(), [("packet-1", "source-1", 500)])
        self.assertEqual(connection.execute(
            "SELECT * FROM route_correction_nonces"
        ).fetchall(), [("nonce-1", 600)])
        self.assertEqual(connection.execute(
            "SELECT * FROM applied_route_corrections"
        ).fetchall(), [("router-a", "destination-a", "router-b", "router-c", 700)])
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        connection.close()

    def test_spectral_migration_rolls_back_when_foreign_key_check_fails(self):
        connection = self.db.connection
        component_id = self.db.connection.execute(
            "SELECT component_id FROM spectral_components WHERE cluster_id = 3"
        ).fetchone()[0]
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """INSERT INTO spectral_mix_components
               (index_node_id, component_id, coefficient_numerator, coefficient_denominator)
               VALUES ('SC03-G00:', ?, '1', '2')""",
            (component_id + 10000,),
        )
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON")
        from spectral_core.spectral_field import SpectralFieldStore
        with self.assertRaises(RuntimeError):
            SpectralFieldStore(connection)
        self.assertEqual(connection.in_transaction, False)
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM spectral_mix_components WHERE component_id = ?",
            (component_id + 10000,),
        ).fetchone()[0], 1)
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "DELETE FROM spectral_mix_components WHERE component_id = ?",
            (component_id + 10000,),
        )
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON")

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

    def test_all_initial_shades_map_to_their_zero_based_grid_coordinates(self):
        rows = self.db.connection.execute(
            """SELECT s.shade_id, s.grid_column, s.grid_row,
                      p.numerator, p.denominator, p.axis_order
               FROM spectral_shades s
               JOIN spectral_position_coordinates p ON p.shade_id = s.shade_id
               WHERE p.coordinate_system_id = 'spectral-grid-2d-v1'
               ORDER BY s.grid_column, s.grid_row, p.axis_order"""
        ).fetchall()
        self.assertEqual(len(rows), 200)
        for shade_id, column, row, numerator, denominator, axis in rows:
            self.assertEqual(int(numerator), column - 1 if axis == 0 else row)
            self.assertEqual(int(denominator), 1)
            self.assertEqual(shade_id, f"SC{column:02d}-G{row:02d}")

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

    def test_v5_repairs_mixed_rational_column_affinities(self):
        connection = self.db.connection
        connection.execute(
            "ALTER TABLE spectral_position_coordinates "
            "RENAME TO spectral_position_coordinates_before_mixed_v5"
        )
        connection.execute("""CREATE TABLE spectral_position_coordinates (
            shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
            coordinate_system_id TEXT NOT NULL, axis_order INTEGER NOT NULL,
            numerator TEXT NOT NULL, denominator INTEGER NOT NULL,
            PRIMARY KEY(shade_id, coordinate_system_id, axis_order),
            FOREIGN KEY(coordinate_system_id, axis_order)
                REFERENCES coordinate_axes(coordinate_system_id, axis_order))""")
        connection.execute("""INSERT INTO spectral_position_coordinates
            SELECT shade_id, coordinate_system_id, axis_order, numerator,
                   CAST(denominator AS INTEGER)
            FROM spectral_position_coordinates_before_mixed_v5""")
        connection.execute("DROP TABLE spectral_position_coordinates_before_mixed_v5")
        connection.commit()
        from spectral_core.geometry import SpectralGeometryStore
        SpectralGeometryStore(connection)
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


    def test_objects_build_itu_spectral_addresses_and_resolve_ancestry(self):
        objects = self.db.spectral_objects
        root = objects.create_object("obj-root", "domain", "Example",
                                     "SC03-G00:")
        child = objects.create_object("obj-child", "section", "Products",
                                       "SC04-G02:", "obj-root", 0)
        self.field.split_index("SC05-G03")
        self.field.split_index("SC05-G03", "0")
        leaf = objects.create_object("obj-leaf", "page", "Item",
                                      "SC05-G03:01", "obj-child", 0)
        self.assertEqual(root["address"], "B05-G00")
        self.assertEqual(child["address"], "B05-G00/B06-G02")
        self.assertEqual(leaf["address"], "B05-G00/B06-G02/B07-G03~01")
        resolved = objects.resolve_address(leaf["address"])
        self.assertEqual([x["object_id"] for x in resolved["hierarchy"]],
                         ["obj-root", "obj-child", "obj-leaf"])
        self.assertEqual([x["component"] for x in resolved["hierarchy"]],
                         ["B05-G00", "B06-G02", "B07-G03~01"])

    def test_object_address_rejects_reserved_bands_and_duplicate_addresses(self):
        objects = self.db.spectral_objects
        with self.assertRaises(PermissionError):
            objects.create_object("reserved", "domain", "Reserved", "SC01-G00:")
        objects.create_object("first", "domain", "First", "SC03-G00:")
        with self.assertRaises(sqlite3.IntegrityError):
            objects.create_object("second", "domain", "Second", "SC03-G00:")

    def test_object_coordinates_reuse_exact_ndimensional_geometry(self):
        objects = self.db.spectral_objects
        objects.create_object("spatial-object", "site", "Site", "SC03-G01:")
        self.geometry.create_coordinate_system(
            "object-space-3d", "Object 3D", ["x", "y", "z"], "unit")
        objects.set_coordinates("spatial-object", "object-space-3d",
                                [Fraction(1, 3), 2, Fraction(1, 2 ** 90)])
        self.assertEqual(objects.get_coordinates("spatial-object", "object-space-3d"), [
            {"axis": "x", "numerator": 1, "denominator": 3},
            {"axis": "y", "numerator": 2, "denominator": 1},
            {"axis": "z", "numerator": 1, "denominator": 2 ** 90},
        ])

    def test_object_address_tables_migrate_additively_and_preserve_existing_data(self):
        self.db.put(__import__("spectral_core").SpectralAddress("123"), b"old")
        objects = self.db.spectral_objects
        objects.create_object("persist", "domain", "Persist", "SC03-G04:")
        self.assertEqual(self.db.get(__import__("spectral_core").SpectralAddress("123")), b"old")
        self.assertEqual(self.db.connection.execute(
            "SELECT version FROM spectral_schema_migrations WHERE version = 6"
        ).fetchone(), (6,))
        self.assertEqual(self.db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])


    def test_readdressing_parent_versions_all_descendant_addresses(self):
        objects = self.db.spectral_objects
        objects.create_object("address-root", "domain", "Root", "SC03-G00:")
        objects.create_object("address-child", "section", "Child", "SC04-G01:",
                              "address-root", 0)
        old_child_address = objects.get_object("address-child")["address"]
        updated = objects.update_index_node("address-root", "SC05-G02:")
        self.assertEqual(updated["address"], "B07-G02")
        new_child_address = objects.get_object("address-child")["address"]
        self.assertEqual(new_child_address, "B07-G02/B06-G01")
        with self.assertRaises(KeyError):
            objects.resolve_address(old_child_address)
        self.assertEqual(objects.resolve_address(new_child_address)["hierarchy"][-1]["object_id"],
                         "address-child")
        history = self.db.connection.execute(
            """SELECT version, status, address_value FROM spectral_object_addresses
               WHERE object_id = 'address-child' ORDER BY version"""
        ).fetchall()
        self.assertEqual(history, [
            (1, "retired", old_child_address),
            (2, "active", new_child_address),
        ])




    def test_independent_branches_and_shared_leaf_component_resolve_separately(self):
        objects = self.db.spectral_objects
        objects.create_object("branch-a", "domain", "A", "SC03-G00:")
        objects.create_object("branch-b", "domain", "B", "SC04-G00:")
        objects.create_object("branch-a-leaf", "page", "Leaf A", "SC05-G01:", "branch-a")
        objects.create_object("branch-b-leaf", "page", "Leaf B", "SC05-G01:", "branch-b")
        a = objects.get_object("branch-a-leaf")["address"]
        b = objects.get_object("branch-b-leaf")["address"]
        self.assertNotEqual(a, b)
        self.assertEqual(objects.resolve_address(a)["hierarchy"][-1]["object_id"], "branch-a-leaf")
        self.assertEqual(objects.resolve_address(b)["hierarchy"][-1]["object_id"], "branch-b-leaf")

    def test_deep_hierarchy_and_recursive_index_paths_resolve(self):
        objects = self.db.spectral_objects
        self.field.split_index("SC03-G00")
        self.field.split_index("SC03-G00", "0")
        self.field.split_index("SC03-G00", "00")
        parent = None
        for level in range(18):
            object_id = f"deep-{level}"
            objects.create_object(object_id, "level", f"Level {level}", "SC03-G00:000",
                                  parent, level)
            parent = object_id
        address = objects.get_object("deep-17")["address"]
        resolved = objects.resolve_address(address)
        self.assertEqual(len(resolved["hierarchy"]), 18)
        self.assertEqual(resolved["hierarchy"][0]["object_id"], "deep-0")
        self.assertEqual(resolved["hierarchy"][-1]["object_id"], "deep-17")
        self.assertTrue(address.endswith("B05-G00~000"))

    def test_reusing_retired_address_is_allowed_but_active_collision_is_not(self):
        objects = self.db.spectral_objects
        objects.create_object("reusable", "domain", "Reusable", "SC03-G00:")
        old = objects.get_object("reusable")["address"]
        objects.update_index_node("reusable", "SC04-G00:")
        objects.update_index_node("reusable", "SC03-G00:")
        self.assertEqual(objects.get_object("reusable")["address"], old)
        self.assertEqual(objects.resolve_address(old)["object_id"], "reusable")
        with self.assertRaises(sqlite3.IntegrityError):
            objects.create_object("collision", "domain", "Collision", "SC03-G00:")

    def test_reparent_versions_subtree_and_rejects_cycles(self):
        objects = self.db.spectral_objects
        objects.create_object("move-root-a", "domain", "A", "SC03-G00:")
        objects.create_object("move-root-b", "domain", "B", "SC04-G00:")
        objects.create_object("move-child", "section", "Child", "SC05-G00:", "move-root-a")
        objects.create_object("move-leaf", "page", "Leaf", "SC06-G00:", "move-child")
        old_leaf = objects.get_object("move-leaf")["address"]
        moved = objects.reparent_object("move-child", "move-root-b", 4)
        self.assertEqual(moved["parent_object_id"], "move-root-b")
        new_leaf = objects.get_object("move-leaf")["address"]
        self.assertNotEqual(old_leaf, new_leaf)
        with self.assertRaises(KeyError):
            objects.resolve_address(old_leaf)
        self.assertEqual(objects.resolve_address(new_leaf)["hierarchy"][-1]["object_id"], "move-leaf")
        with self.assertRaises(ValueError):
            objects.reparent_object("move-root-b", "move-leaf")
        self.assertEqual(objects.get_object("move-child")["parent_object_id"], "move-root-b")

    def test_rename_and_sibling_reorder_do_not_change_addresses(self):
        objects = self.db.spectral_objects
        objects.create_object("order-parent", "domain", "Parent", "SC03-G00:")
        objects.create_object("order-one", "section", "One", "SC04-G00:", "order-parent", 1)
        objects.create_object("order-two", "section", "Two", "SC05-G00:", "order-parent", 2)
        before = objects.get_object("order-one")["address"]
        objects.rename_object("order-one", "Renamed")
        objects.reorder_object("order-one", 3)
        self.assertEqual(objects.get_object("order-one")["name"], "Renamed")
        self.assertEqual(objects.get_object("order-one")["hierarchy_order"], 3)
        self.assertEqual(objects.get_object("order-one")["address"], before)
        self.assertEqual([x["object_id"] for x in objects.children("order-parent")],
                         ["order-two", "order-one"])

    def test_active_address_resolution_detects_stale_snapshot_index(self):
        objects = self.db.spectral_objects
        objects.create_object("integrity-root", "domain", "Root", "SC03-G00:")
        objects.update_index_node("integrity-root", "SC04-G00:")
        active_id = self.db.connection.execute(
            "SELECT address_id FROM spectral_object_addresses WHERE object_id = ? AND status = 'active'",
            ("integrity-root",)
        ).fetchone()[0]
        self.db.connection.execute(
            "UPDATE spectral_object_address_segments SET index_node_id = ? WHERE address_id = ?",
            ("SC03-G00:", active_id)
        )
        with self.assertRaises(RuntimeError):
            objects.resolve_address(objects.get_object("integrity-root")["address"])

    def test_migration_v7_preserves_foreign_keys_and_active_address_index(self):
        self.assertEqual(self.db.connection.execute(
            "SELECT version FROM spectral_schema_migrations WHERE version = 7"
        ).fetchone(), (7,))
        indexes = {row[1] for row in self.db.connection.execute(
            "PRAGMA index_list(spectral_object_addresses)"
        )}
        self.assertIn("spectral_object_active_address_value", indexes)
        self.assertEqual(self.db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_reparent_order_only_change_does_not_create_address_version(self):
        objects = self.db.spectral_objects
        objects.create_object("reorder-parent", "domain", "Parent", "SC03-G00:")
        objects.create_object("reorder-child", "section", "Child", "SC04-G00:", "reorder-parent", 1)
        before = objects.get_object("reorder-child")
        after = objects.reparent_object("reorder-child", "reorder-parent", 9)
        self.assertEqual(after["address"], before["address"])
        self.assertEqual(after["address_version"], before["address_version"])
        self.assertEqual(after["hierarchy_order"], 9)


    def test_object_metadata_updates_commit_when_called_without_outer_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "object-transactions.sqlite"
            db = SpectralDatabase(path)
            objects = db.spectral_objects
            objects.create_object("transaction-root", "domain", "Before", "SC03-G00:")
            objects.create_object("transaction-child", "section", "Child", "SC04-G00:",
                                  "transaction-root", 1)

            objects.rename_object("transaction-root", "After")
            objects.reorder_object("transaction-child", 7)
            objects.reparent_object("transaction-child", "transaction-root", 9)
            db.close()

            reopened = SpectralDatabase(path)
            try:
                self.assertEqual(reopened.spectral_objects.get_object("transaction-root")["name"], "After")
                child = reopened.spectral_objects.get_object("transaction-child")
                self.assertEqual(child["hierarchy_order"], 9)
                self.assertEqual(child["parent_object_id"], "transaction-root")
            finally:
                reopened.close()

    def test_object_metadata_updates_respect_caller_owned_transaction(self):
        objects = self.db.spectral_objects
        objects.create_object("caller-transaction-root", "domain", "Before", "SC03-G00:")
        self.db.connection.execute("BEGIN")
        objects.rename_object("caller-transaction-root", "Uncommitted")
        self.assertTrue(self.db.connection.in_transaction)
        self.db.connection.rollback()
        self.assertEqual(objects.get_object("caller-transaction-root")["name"], "Before")

        objects.create_object("caller-transaction-child", "section", "Child", "SC04-G00:",
                              "caller-transaction-root", 1)
        self.db.connection.execute("BEGIN")
        objects.reorder_object("caller-transaction-child", 8)
        self.assertTrue(self.db.connection.in_transaction)
        self.db.connection.rollback()
        self.assertEqual(objects.get_object("caller-transaction-child")["hierarchy_order"], 1)

        self.db.connection.execute("BEGIN")
        objects.reparent_object("caller-transaction-child", "caller-transaction-root", 9)
        self.assertTrue(self.db.connection.in_transaction)
        self.db.connection.rollback()
        self.assertEqual(objects.get_object("caller-transaction-child")["hierarchy_order"], 1)


if __name__ == "__main__":
    unittest.main()
