import json
import tempfile
import unittest
from pathlib import Path
from spectral_monitor import ReportCollector


class ExternalMonitorTests(unittest.TestCase):
    def report(self, **changes):
        row = {"schema": "spectral-core.diagnostic.v1",
               "agent": "spectral-core-internal-monitor",
               "event": "packet_delivered", "level": "info",
               "timestamp_ms": 123456, "report_id": "r-001",
               "data": {"packet_id": "p-1", "route": ["a", "b"]}}
        row.update(changes)
        return row

    def test_accepts_and_durably_spools_allowlisted_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "external" / "reports.jsonl"
            collector = ReportCollector(path)
            ack = collector.accept(self.report())
            self.assertTrue(ack["ok"])
            saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(saved["report_id"], "r-001")
            self.assertEqual(collector.status()["accepted"], 1)

    def test_duplicate_report_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            collector = ReportCollector(Path(folder) / "reports.jsonl")
            collector.accept(self.report())
            ack = collector.accept(self.report())
            self.assertTrue(ack["duplicate"])
            self.assertEqual(collector.status()["accepted"], 1)

    def test_rejects_unknown_commands_and_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            collector = ReportCollector(Path(folder) / "reports.jsonl")
            with self.assertRaises(ValueError):
                collector.accept(self.report(event="execute_command"))
            with self.assertRaises(ValueError):
                collector.accept(self.report(data={"payload": "private"}))
            self.assertEqual(collector.status()["rejected"], 2)

    def test_rejects_wrong_schema_or_agent(self):
        with tempfile.TemporaryDirectory() as folder:
            collector = ReportCollector(Path(folder) / "reports.jsonl")
            with self.assertRaises(ValueError):
                collector.accept(self.report(schema="yj64.diagnostic.v1"))


if __name__ == "__main__":
    unittest.main()
