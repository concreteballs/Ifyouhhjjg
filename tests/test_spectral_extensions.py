import unittest

from spectral_core import SpectralDatabase


class SpectralExtensionDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = SpectralDatabase()
        self.ext = self.db.spectral_extensions
        self.objects = self.db.spectral_objects
        self.geometry = self.db.spectral_field.geometry
        self.objects.create_object("root", "domain", "Root", "SC03-G00:")
        self.objects.create_object("child", "page", "Child", "SC04-G00:", "root")

    def tearDown(self):
        self.db.close()

    def test_reserved_regions_and_extension_points_are_metadata_only(self):
        region = self.ext.create_reserved_region(
            "guard-zone-a", "guard_placeholder", "Guard zone",
            metadata={"purpose": "future-protection"}
        )
        self.assertEqual(region["status"], "reserved")
        point = self.ext.create_extension_point(
            "future-connector", "connection", "Future connector",
            region_id="guard-zone-a", object_id="child"
        )
        self.assertEqual(point["status"], "planned")
        self.assertEqual(point["region_id"], "guard-zone-a")
        self.assertEqual(
            self.ext.set_extension_point_status("future-connector", "available")["status"],
            "available"
        )
        self.assertEqual(
            self.ext.set_reserved_region_status("guard-zone-a", "planned")["status"],
            "planned"
        )

    def test_semantic_and_interspace_links_are_persisted_and_searchable(self):
        semantic = self.ext.create_semantic_link(
            "meaning-1", "root", "child", "contains-concept",
            description="Conceptual relation", metadata={"weight": 3}
        )
        self.assertEqual(semantic["relation_type"], "contains-concept")
        self.assertEqual(len(self.ext.semantic_links_for("child")), 1)

        self.geometry.create_coordinate_system(
            "abstract-space-v1", "Abstract space", ["u", "v", "w"]
        )
        interspace = self.ext.create_interspace_link(
            "space-link-1", "root", "child",
            self.geometry.DEFAULT_SYSTEM, "abstract-space-v1",
            "correspondence", metadata={"mapping": "future-defined"}
        )
        self.assertEqual(interspace["target_coordinate_system_id"], "abstract-space-v1")
        self.assertEqual(self.ext.get_interspace_link("space-link-1")["link_id"], "space-link-1")

    def test_snapshot_detects_changes_and_recovery_restores_captured_state(self):
        self.ext.create_hierarchy_snapshot("baseline-1")
        self.objects.rename_object("child", "Changed child")
        self.objects.create_object("later", "page", "Later addition", "SC05-G00:", "root")

        report = self.ext.compare_hierarchy_snapshot("baseline-1")
        self.assertEqual(report["added"], ["later"])
        self.assertEqual(report["changed"][0]["object_id"], "child")
        self.assertIn("name", report["changed"][0]["fields"])

        recovered = self.ext.restore_hierarchy_snapshot("baseline-1")
        self.assertFalse(any(item["object_id"] == "child" for item in recovered["changed"]))
        self.assertEqual(self.objects.get_object("child")["name"], "Child")
        self.assertEqual(recovered["added"], ["later"])
        self.assertEqual(self.objects.get_object("later")["name"], "Later addition")
        events = self.ext.integrity_events("baseline-1")
        self.assertIn("recovery_completed", [event["event_type"] for event in events])

    def test_snapshot_recovery_refuses_to_silently_recreate_missing_identity(self):
        self.ext.create_hierarchy_snapshot("baseline-2")
        self.db.connection.execute("DELETE FROM spectral_object_addresses WHERE object_id = 'child'")
        self.db.connection.execute("DELETE FROM spectral_objects WHERE object_id = 'child'")
        self.db.connection.commit()
        with self.assertRaises(ValueError):
            self.ext.restore_hierarchy_snapshot("baseline-2")
        self.assertIn(
            "recovery_rejected",
            [event["event_type"] for event in self.ext.integrity_events("baseline-2")]
        )

    def test_foreign_key_and_integrity_checks_after_extension_operations(self):
        self.ext.create_reserved_region("reserve-1", "reserved", "Reserved")
        self.ext.create_semantic_link("semantic-2", "root", "child", "related")
        self.ext.create_hierarchy_snapshot("integrity-1")
        self.assertEqual(self.db.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.db.connection.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
