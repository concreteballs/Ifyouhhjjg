import tempfile
import unittest
from pathlib import Path

from spectral_core.monitor import DiagnosticMonitor
from spectral_monitor.collector import ReportCollector, SCHEMA, AGENT


def report(report_id, text):
    return {
        "schema": SCHEMA,
        "agent": AGENT,
        "event": "health_check",
        "level": "info",
        "timestamp_ms": 1,
        "report_id": report_id,
        "data": {"detail": text},
    }


class DiagnosticRetentionTests(unittest.TestCase):
    def test_internal_jsonl_rotates_and_stays_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "internal.jsonl"
            monitor = DiagnosticMonitor(path, max_report_bytes=16385, report_backups=2)
            for index in range(40):
                monitor.emit("health_check", detail="x" * 400, sequence=index)
            self.assertTrue(path.exists())
            self.assertTrue(path.with_name("internal.jsonl.1").exists())
            self.assertLessEqual(path.stat().st_size, 16385)
            self.assertLessEqual(path.with_name("internal.jsonl.1").stat().st_size, 16384)

    def test_external_spool_has_hard_size_limit_and_drop_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "internal.jsonl"
            monitor = DiagnosticMonitor(path, max_spool_bytes=16384)
            monitor.external_endpoint = "https://collector.invalid/reports"
            monitor.external_token = "t" * 32
            for index in range(40):
                monitor._spool_external(report(f"spool-{index}", "x" * 400))
            spool = path.with_name("external-pending.jsonl")
            self.assertLessEqual(spool.stat().st_size, 16384)
            self.assertGreater(monitor.status()["external_spool_dropped"], 0)

    def test_collector_rotates_and_keeps_recent_dedup_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "external.jsonl"
            collector = ReportCollector(path, max_file_bytes=16385, backups=2)
            first = report("first-report", "x" * 400)
            self.assertFalse(collector.accept(first)["duplicate"])
            for index in range(30):
                collector.accept(report(f"report-{index}", "y" * 400))
            self.assertTrue(path.with_name("external.jsonl.1").exists())
            reopened = ReportCollector(path, max_file_bytes=16385, backups=2)
            self.assertTrue(reopened.accept(first)["duplicate"])


if __name__ == "__main__":
    unittest.main()
