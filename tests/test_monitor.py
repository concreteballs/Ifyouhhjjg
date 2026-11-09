import json
import tempfile
import unittest
from pathlib import Path

from spectral_core import DiagnosticMonitor, Router, SpectralNetwork, SpectralAddress


class DiagnosticMonitorTests(unittest.TestCase):
    def test_persistent_jsonl_spool_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reports" / "diagnostics.jsonl"
            monitor = DiagnosticMonitor(path)
            monitor.emit("router_added", router_id="r1", position=[0, 0])
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[-1]["schema"], "spectral-core.diagnostic.v1")
            self.assertEqual(rows[-1]["event"], "router_added")
            self.assertEqual(monitor.status()["event_count"], 2)

    def test_unknown_events_are_rejected(self):
        monitor = DiagnosticMonitor()
        with self.assertRaises(ValueError):
            monitor.emit("arbitrary_command", command="run")

    def test_sensitive_payload_fields_are_rejected(self):
        monitor = DiagnosticMonitor()
        with self.assertRaises(ValueError):
            monitor.emit("packet_delivered", payload="do not log this")

    def test_exception_text_is_not_written_to_diagnostics(self):
        monitor = DiagnosticMonitor()
        try:
            raise RuntimeError("database password=do-not-log")
        except RuntimeError as error:
            monitor.record_exception("test", error)
        report = monitor.events()[-1]
        self.assertNotIn("error_message", report["data"])
        self.assertNotIn("do-not-log", monitor.export_jsonl())

    def test_monitor_rejects_non_finite_metrics(self):
        monitor = DiagnosticMonitor()
        with self.assertRaises(ValueError):
            monitor.emit("router_load", load=float("nan"))

    def test_self_check_detects_broken_topology(self):
        monitor = DiagnosticMonitor()
        network = SpectralNetwork()
        network.add_router(Router("r1", (0, 0)))
        network.add_router(Router("r2", (1, 0)))
        network.routers["r1"].neighbours.append("missing")
        result = monitor.self_check(network=network)
        self.assertFalse(result["data"]["healthy"])
        self.assertEqual(result["data"]["checks"]["topology"], "invalid")


if __name__ == "__main__":
    unittest.main()
