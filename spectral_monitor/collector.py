"""Independent, allowlisted diagnostic receiver; reports are data, never commands."""
import json
import os
import threading
from pathlib import Path

SCHEMA = "spectral-core.diagnostic.v1"
AGENT = "spectral-core-internal-monitor"
ALLOWED_EVENTS = {
    "monitor_started", "self_diagnostic", "router_added", "link_connected",
    "endpoint_registered", "route_started", "route_hop", "packet_delivered",
    "packet_rejected", "database_read", "database_write", "database_delete",
    "runtime_error", "health_check", "responsibility_assigned", "route_correction",
    "router_availability", "router_load", "neighbour_assistance",
}
FORBIDDEN_KEYS = {"payload", "content", "token", "secret", "password",
                  "private_key", "authorization", "api_key"}


class ReportCollector:
    """Separate process/service can accept JSON reports and persist an audit spool."""
    def __init__(self, report_path):
        self.report_path = Path(report_path).expanduser()
        self._lock = threading.RLock()
        self._seen = set()
        self._accepted = 0
        self._rejected = 0
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        if self.report_path.exists():
            with self.report_path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        self._seen.add(row["report_id"])
                        self._accepted += 1
                    except (ValueError, KeyError, TypeError):
                        continue

    @classmethod
    def _validate(cls, value, key=""):
        if key.lower() in FORBIDDEN_KEYS:
            raise ValueError("Sensitive diagnostic field rejected")
        if value is None or isinstance(value, (str, int, float, bool)):
            if isinstance(value, str) and len(value) > 512:
                raise ValueError("Diagnostic string too long")
            return value
        if isinstance(value, list) and len(value) <= 100:
            return [cls._validate(item, key) for item in value]
        if isinstance(value, dict) and len(value) <= 50:
            return {str(k): cls._validate(v, str(k)) for k, v in value.items()}
        raise ValueError("Unsupported or oversized diagnostic value")

    def accept(self, report_json):
        try:
            return self._accept(report_json)
        except Exception:
            with self._lock:
                self._rejected += 1
            raise

    def _accept(self, report_json):
        report = json.loads(report_json) if isinstance(report_json, str) else report_json
        if not isinstance(report, dict) or report.get("schema") != SCHEMA:
            raise ValueError("Unsupported diagnostic schema")
        if report.get("agent") != AGENT or report.get("event") not in ALLOWED_EVENTS:
            raise ValueError("Untrusted diagnostic agent or event")
        if report.get("level") not in {"debug", "info", "warning", "error", "critical"}:
            raise ValueError("Invalid diagnostic level")
        report_id = report.get("report_id")
        if not isinstance(report_id, str) or not report_id or len(report_id) > 64:
            raise ValueError("Invalid report ID")
        safe = {
            "schema": SCHEMA, "agent": AGENT, "event": report["event"],
            "level": report["level"], "timestamp_ms": int(report["timestamp_ms"]),
            "report_id": report_id, "data": self._validate(report.get("data", {})),
        }
        encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 16384:
            raise ValueError("Diagnostic report exceeds 16 KiB")
        with self._lock:
            if report_id in self._seen:
                return {"ok": True, "duplicate": True, "report_id": report_id}
            with self.report_path.open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._seen.add(report_id)
            self._accepted += 1
        return {"ok": True, "duplicate": False, "report_id": report_id}

    def status(self):
        with self._lock:
            return {"agent": "spectral-core-external-monitor",
                    "status": "running", "accepted": self._accepted,
                    "rejected": self._rejected, "report_path": str(self.report_path)}
