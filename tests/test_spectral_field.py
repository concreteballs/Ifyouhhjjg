import sqlite3
import unittest

from spectral_core import SpectralDatabase


class SpectralFieldDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = SpectralDatabase()
        self.field = self.db.spectral_field

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
        self.assertEqual(
            self.field.mix_components(child["node_id"])[0]["numerator"], 1
        )

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
            cluster_id INTEGER PRIMARY KEY,
            cluster_order INTEGER NOT NULL UNIQUE,
            designation TEXT NOT NULL UNIQUE,
            lower_hz INTEGER NOT NULL,
            upper_hz INTEGER NOT NULL,
            standard_band_number INTEGER,
            role TEXT NOT NULL,
            mixing_enabled INTEGER NOT NULL,
            source_note TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE spectral_components (
            component_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id INTEGER NOT NULL UNIQUE REFERENCES spectral_clusters(cluster_id),
            component_key TEXT NOT NULL UNIQUE
        )""")
        connection.execute("""CREATE TABLE spectral_shades (
            shade_id TEXT PRIMARY KEY,
            cluster_id INTEGER NOT NULL REFERENCES spectral_clusters(cluster_id),
            grid_column INTEGER NOT NULL,
            grid_row INTEGER NOT NULL,
            UNIQUE(cluster_id, grid_row),
            UNIQUE(grid_column, grid_row)
        )""")
        connection.execute("""CREATE TABLE spectral_index_nodes (
            node_id TEXT PRIMARY KEY,
            shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
            parent_node_id TEXT REFERENCES spectral_index_nodes(node_id),
            branch TEXT NOT NULL,
            path TEXT NOT NULL,
            depth INTEGER NOT NULL,
            lower_numerator INTEGER NOT NULL,
            lower_denominator INTEGER NOT NULL,
            upper_numerator INTEGER NOT NULL,
            upper_denominator INTEGER NOT NULL,
            UNIQUE(shade_id, path)
        )""")
        connection.execute("""CREATE TABLE spectral_mix_components (
            shade_id TEXT NOT NULL REFERENCES spectral_shades(shade_id),
            component_id INTEGER NOT NULL REFERENCES spectral_components(component_id),
            coefficient_numerator INTEGER NOT NULL,
            coefficient_denominator INTEGER NOT NULL,
            PRIMARY KEY(shade_id, component_id)
        )""")
        connection.execute(
            """INSERT INTO spectral_clusters
               VALUES (3, 3, 'LF', 30000, 300000, 5, 'primary', 1, 'legacy')"""
        )
        connection.execute(
            "INSERT INTO spectral_components(cluster_id, component_key) VALUES (3, 'cluster-03')"
        )
        connection.execute(
            "INSERT INTO spectral_shades VALUES ('SC03-G00', 3, 3, 0)"
        )
        connection.execute(
            "INSERT INTO spectral_mix_components VALUES ('SC03-G00', 1, 2, 6)"
        )
        from spectral_core.spectral_field import SpectralFieldStore
        field = SpectralFieldStore(connection)
        migrated = field.mix_components("SC03-G00:")
        self.assertEqual(migrated[0]["numerator"], 2)
        self.assertEqual(migrated[0]["denominator"], 6)
        self.assertEqual(
            connection.execute("PRAGMA table_info(spectral_mix_components)").fetchall()[0][1],
            "index_node_id",
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='spectral_mix_components_legacy_v1'"
            ).fetchone()[0],
            0,
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
