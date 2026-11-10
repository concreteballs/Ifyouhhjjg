import hashlib
import json
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

    def test_extension_writes_respect_caller_owned_transactions(self):
        connection = self.db.connection
        connection.execute("BEGIN")
        self.ext.create_reserved_region("rolled-back-region", "reserved", "Temporary")
        self.ext.create_semantic_link("rolled-back-link", "root", "child", "related")
        connection.rollback()

        self.assertIsNone(connection.execute(
            "SELECT 1 FROM spectral_reserved_regions WHERE region_id = ?",
            ("rolled-back-region",)
        ).fetchone())
        self.assertIsNone(connection.execute(
            "SELECT 1 FROM spectral_semantic_links WHERE link_id = ?",
            ("rolled-back-link",)
        ).fetchone())

        self.ext.create_reserved_region("committed-region", "reserved", "Committed")
        self.assertFalse(connection.in_transaction)
        self.ext.create_hierarchy_snapshot("transaction-snapshot")
        self.ext.compare_hierarchy_snapshot("transaction-snapshot")
        self.assertFalse(connection.in_transaction)

        self.objects.rename_object("child", "Changed")
        self.ext.restore_hierarchy_snapshot("transaction-snapshot")
        self.assertEqual(self.objects.get_object("child")["name"], "Child")
        self.assertFalse(connection.in_transaction)

    def test_scoped_recovery_rejects_changed_external_ancestor_context(self):
        self.ext.create_hierarchy_snapshot("child-scope-1", root_object_id="child")
        self.objects.update_index_node("root", "SC05-G00:")

        with self.assertRaisesRegex(ValueError, "external ancestor context changed"):
            self.ext.restore_hierarchy_snapshot("child-scope-1")

        rejected = [
            event for event in self.ext.integrity_events("child-scope-1")
            if event["event_type"] == "recovery_rejected"
        ]
        self.assertTrue(rejected)
        self.assertEqual(
            rejected[-1]["details"]["reason"],
            "external_ancestor_context_changed"
        )

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

    def test_scoped_snapshot_ignores_objects_outside_its_subtree(self):
        self.objects.create_object("other-root", "domain", "Other root", "SC06-G00:")
        self.ext.create_hierarchy_snapshot("scoped-1", root_object_id="root")
        self.objects.rename_object("other-root", "Changed outside")
        self.objects.create_object("unrelated", "domain", "Unrelated", "SC07-G00:")

        report = self.ext.compare_hierarchy_snapshot("scoped-1")
        self.assertTrue(report["is_consistent"])
        self.assertEqual(report["added"], [])
        self.assertEqual(report["changed"], [])

        self.objects.create_object("nested", "page", "Nested", "SC08-G00:", "child")
        report = self.ext.compare_hierarchy_snapshot("scoped-1")
        self.assertEqual(report["added"], ["nested"])
        self.assertFalse(report["is_consistent"])

    def test_snapshot_detects_objects_without_active_addresses(self):
        self.ext.create_hierarchy_snapshot("address-integrity-1")
        self.db.connection.execute(
            "DELETE FROM spectral_object_addresses WHERE object_id = ? AND status = 'active'",
            ("child",)
        )
        self.db.connection.commit()

        report = self.ext.compare_hierarchy_snapshot("address-integrity-1")
        changed = next(item for item in report["changed"] if item["object_id"] == "child")
        self.assertIn("address_value", changed["fields"])
        with self.assertRaisesRegex(RuntimeError, "no active spectral address"):
            self.ext.create_hierarchy_snapshot("invalid-address-snapshot")

    def test_snapshot_checksum_covers_scope_metadata_and_supports_legacy_rows(self):
        self.ext.create_hierarchy_snapshot("scope-digest-1", root_object_id="root")
        current = self.ext.verify_hierarchy_snapshot("scope-digest-1")
        self.assertTrue(current["is_valid"])
        self.assertEqual(current["digest_version"], 2)

        self.db.connection.execute(
            "UPDATE spectral_hierarchy_snapshots SET root_object_id = ? WHERE snapshot_id = ?",
            ("child", "scope-digest-1")
        )
        self.db.connection.commit()
        self.assertFalse(self.ext.verify_hierarchy_snapshot("scope-digest-1")["is_valid"])
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.ext.restore_hierarchy_snapshot("scope-digest-1")

        self.ext.create_hierarchy_snapshot("legacy-digest-1")
        rows = self.db.connection.execute(
            """SELECT object_id, object_type, name, parent_object_id, hierarchy_order,
                      index_node_id, address_value
               FROM spectral_hierarchy_snapshot_objects
               WHERE snapshot_id = ? ORDER BY object_id""",
            ("legacy-digest-1",)
        ).fetchall()
        serial = [list(row) for row in rows]
        legacy_digest = hashlib.sha256(json.dumps(
            serial, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        self.db.connection.execute(
            "UPDATE spectral_hierarchy_snapshots SET digest_version = 1, digest_sha256 = ? "
            "WHERE snapshot_id = ?",
            (legacy_digest, "legacy-digest-1")
        )
        self.db.connection.commit()
        legacy = self.ext.verify_hierarchy_snapshot("legacy-digest-1")
        self.assertTrue(legacy["is_valid"])
        self.assertEqual(legacy["digest_version"], 1)

    def test_snapshot_checksum_is_verified_and_corruption_blocks_recovery(self):
        self.ext.create_hierarchy_snapshot("checksum-1")
        valid = self.ext.verify_hierarchy_snapshot("checksum-1")
        self.assertTrue(valid["is_valid"])
        self.assertEqual(valid["expected_count"], valid["actual_count"])

        self.db.connection.execute(
            "UPDATE spectral_hierarchy_snapshot_objects SET name = ? "
            "WHERE snapshot_id = ? AND object_id = ?",
            ("Tampered snapshot", "checksum-1", "child"))
        self.db.connection.commit()

        invalid = self.ext.verify_hierarchy_snapshot("checksum-1")
        self.assertFalse(invalid["is_valid"])
        report = self.ext.compare_hierarchy_snapshot("checksum-1")
        self.assertFalse(report["snapshot_valid"])
        self.assertFalse(report["is_consistent"])
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.ext.restore_hierarchy_snapshot("checksum-1")
        self.assertIn(
            "recovery_rejected",
            [event["event_type"] for event in self.ext.integrity_events("checksum-1")]
        )

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
