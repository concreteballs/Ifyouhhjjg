"""Independent, strict diagnostic receiver. Reports are data, never commands."""
import json
import math
import os
import re
import threading
from collections import deque
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
                  "private_key", "authorization", "api_key", "access_token"}
REPORT_KEYS = {"schema", "agent", "event", "level", "timestamp_ms", "report_id", "data"}
MAX_REPORT_BYTES = 16384
MAX_DEPTH = 8
MAX_DEDUP_IDS = 50000


class ReportCollector:
    """Allowlisted JSONL receiver with bounded input and durable acknowledgements."""
    def __init__(self, report_path):
        self.report_path = Path(report_path).expanduser()
        self._lock = threading.RLock()
        self._seen = set()
        self._seen_order = deque()
        self._accepted = 0
        self._rejected = 0
        self.report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.report_path.exists():
            with self.report_path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        report_id = row.get("report_id")
                        if isinstance(report_id, str):
                            self._remember(report_id)
                            self._accepted += 1
                    except (ValueError, AttributeError, TypeError):
                        continue

    def _remember(self, report_id):
        if report_id in self._seen:
            return
        if len(self._seen_order) >= MAX_DEDUP_IDS:
            expired = self._seen_order.popleft()
            self._seen.discard(expired)
        self._seen_order.append(report_id)
        self._seen.add(report_id)

    @classmethod
    def _validate(cls, value, key="", depth=0):
        if depth > MAX_DEPTH:
            raise ValueError("Diagnostic nesting limit exceeded")
        if key.lower() in FORBIDDEN_KEYS:
            raise ValueError("Sensitive diagnostic field rejected")
        if value is None or isinstance(value, (str, int, float, bool)):
            if isinstance(value, str) and len(value) > 512:
                raise ValueError("Diagnostic string too long")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Non-finite diagnostic number rejected")
            return value
        if isinstance(value, list) and len(value) <= 100:
            return [cls._validate(item, key, depth + 1) for item in value]
        if isinstance(value, dict) and len(value) <= 50:
            safe = {}
            for raw_key, item in value.items():
                if not isinstance(raw_key, str) or len(raw_key) > 128:
                    raise ValueError("Invalid diagnostic field name")
                safe[raw_key] = cls._validate(item, raw_key, depth + 1)
            return safe
        raise ValueError("Unsupported or oversized diagnostic value")

    def accept(self, report_json):
        try:
            return self._accept(report_json)
        except Exception:
            with self._lock:
                self._rejected += 1
            raise

    def _accept(self, report_json):
        if isinstance(report_json, str):
            if len(report_json.encode("utf-8")) > MAX_REPORT_BYTES:
                raise ValueError("Diagnostic report exceeds 16 KiB")
            report = json.loads(report_json)
        else:
            report = report_json
        if not isinstance(report, dict) or set(report) != REPORT_KEYS:
            raise ValueError("Invalid diagnostic report structure")
        if report.get("schema") != SCHEMA:
            raise ValueError("Unsupported diagnostic schema")
        if report.get("agent") != AGENT or report.get("event") not in ALLOWED_EVENTS:
            raise ValueError("Untrusted diagnostic agent or event")
        if report.get("level") not in {"debug", "info", "warning", "error", "critical"}:
            raise ValueError("Invalid diagnostic level")
        report_id = report.get("report_id")
        if not isinstance(report_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", report_id):
            raise ValueError("Invalid report ID")
        timestamp = report.get("timestamp_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ValueError("Invalid diagnostic timestamp")
        data = report.get("data")
        if not isinstance(data, dict):
            raise ValueError("Diagnostic data must be an object")
        safe = {
            "schema": SCHEMA, "agent": AGENT, "event": report["event"],
            "level": report["level"], "timestamp_ms": timestamp,
            "report_id": report_id, "data": self._validate(data),
        }
        encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("Diagnostic report exceeds 16 KiB")
        with self._lock:
            if report_id in self._seen:
                return {"ok": True, "duplicate": True, "report_id": report_id}
            fd = os.open(self.report_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8", closefd=False) as stream:
                    stream.write(encoded + "\n")
                    stream.flush()
                    os.fsync(fd)
            finally:
                os.close(fd)
            self._remember(report_id)
            self._accepted += 1
        return {"ok": True, "duplicate": False, "report_id": report_id}

    def status(self):
        with self._lock:
            return {"agent": "spectral-core-external-monitor",
                    "status": "running", "accepted": self._accepted,
                    "rejected": self._rejected, "report_path": str(self.report_path)}
