import unittest
from fractions import Fraction

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
        self.field.set_mix_component("SC03-G00:", 3, 2, 6)
        self.field.set_mix_component("SC03-G00:", 4, 5, 7)
        self.assertEqual(
            self.field.mix_components("SC03-G00:"),
            [
                {"component_id": 3, "component_key": "cluster-03", "numerator": 1, "denominator": 3},
                {"component_id": 4, "component_key": "cluster-04", "numerator": 5, "denominator": 7},
            ],
        )

    def test_recursive_child_is_a_distinct_mixable_index_value(self):
        child = self.field.split_index("SC03-G00")[0]
        self.field.set_mix_component(child["node_id"], 3, 1, 2)
        self.assertEqual(
            self.field.mix_components(child["node_id"])[0]["numerator"], 1
        )

    def test_service_shade_cannot_be_used_in_mixing(self):
        with self.assertRaises(PermissionError):
            self.field.set_mix_component("SC01-G00:", 3, 1, 2)

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


if __name__ == "__main__":
    unittest.main()
