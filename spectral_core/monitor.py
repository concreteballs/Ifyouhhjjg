"""Embedded diagnostics for the Spectral Core software emulator.

Reports contain operational metadata only: packet payloads and application data
are deliberately never accepted by the monitor API.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

SCHEMA = "spectral-core.diagnostic.v1"
ALLOWED_EVENTS = {
    "monitor_started",
    "self_diagnostic",
    "router_added",
    "link_connected",
    "endpoint_registered",
    "route_started",
    "route_hop",
    "packet_delivered",
    "packet_rejected",
    "database_read",
    "database_write",
    "database_delete",
    "runtime_error",
    "health_check",
    "responsibility_assigned",
    "route_correction",
    "router_availability",
    "router_load",
    "neighbour_assistance",
}
FORBIDDEN_KEYS = {
    "payload", "content", "token", "secret", "password", "private_key",
    "authorization", "api_key",
}


class DiagnosticMonitor:
    """Thread-safe event monitor with optional durable JSONL report storage."""

    def __init__(self, report_path: Optional[str | Path] = None):
        self.report_path = Path(report_path).expanduser() if report_path else None
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._last_error: Optional[dict[str, Any]] = None
        self._started_at_ms = int(time.time() * 1000)
        self.emit("monitor_started", mode="persistent" if self.report_path else "memory")

    @staticmethod
    def _validate_data(data: dict[str, Any]) -> dict[str, Any]:
        def check(value: Any, key: str = "") -> Any:
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"Diagnostic field is not allowed: {key}")
            if value is None or isinstance(value, (str, int, float, bool)):
                if isinstance(value, str) and len(value) > 512:
                    raise ValueError(f"Diagnostic string is too long: {key}")
                return value
            if isinstance(value, (list, tuple)):
                if len(value) > 100:
                    raise ValueError(f"Diagnostic list is too large: {key}")
                return [check(item, key) for item in value]
            if isinstance(value, dict):
                if len(value) > 50:
                    raise ValueError(f"Diagnostic object is too large: {key}")
                return {str(k): check(v, str(k)) for k, v in value.items()}
            raise TypeError(f"Unsupported diagnostic value for {key}: {type(value).__name__}")
        if not isinstance(data, dict):
            raise TypeError("Diagnostic data must be an object")
        return {str(key): check(value, str(key)) for key, value in data.items()}

    def emit(self, event: str, level: str = "info", **data: Any) -> dict[str, Any]:
        if event not in ALLOWED_EVENTS:
            raise ValueError(f"Unknown diagnostic event: {event}")
        if level not in {"debug", "info", "warning", "error", "critical"}:
            raise ValueError(f"Unknown diagnostic level: {level}")
        safe_data = self._validate_data(data)
        report = {
            "schema": SCHEMA,
            "agent": "spectral-core-internal-monitor",
            "event": event,
            "level": level,
            "timestamp_ms": int(time.time() * 1000),
            "report_id": uuid.uuid4().hex,
            "data": safe_data,
        }
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 16384:
            raise ValueError("Diagnostic report exceeds 16 KiB")
        with self._lock:
            self._events.append(report)
            if level in {"error", "critical"}:
                self._last_error = report
            if self.report_path:
                self.report_path.parent.mkdir(parents=True, exist_ok=True)
                with self.report_path.open("a", encoding="utf-8") as handle:
                    handle.write(encoded + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        return report

    def record_exception(self, operation: str, error: Exception, **context: Any) -> None:
        self.emit(
            "runtime_error",
            level="error",
            operation=operation,
            error_type=type(error).__name__,
            error_message=str(error)[:512],
            **context,
        )

    def self_check(self, network: Any = None, database: Any = None) -> dict[str, Any]:
        checks: dict[str, Any] = {"monitor": "ok"}
        if network is not None:
            try:
                routers = network.routers
                endpoints = network.endpoints
                checks["routers"] = len(routers)
                checks["endpoints"] = len(endpoints)
                broken_links = []
                for router_id, router in routers.items():
                    for neighbour_id in router.neighbours:
                        neighbour = routers.get(neighbour_id)
                        if neighbour is None or router_id not in neighbour.neighbours:
                            broken_links.append(f"{router_id}->{neighbour_id}")
                checks["topology"] = "ok" if not broken_links else "invalid"
                checks["broken_links"] = broken_links[:20]
                checks["endpoint_owners"] = (
                    "ok" if all(owner in routers for owner in endpoints.values()) else "invalid"
                )
            except Exception as exc:
                checks["network"] = f"check_error:{type(exc).__name__}"
        if database is not None:
            try:
                database.connection.execute("SELECT 1").fetchone()
                checks["database"] = "ok"
            except Exception as exc:
                checks["database"] = f"check_error:{type(exc).__name__}"
        healthy = all(
            value in {"ok", "valid"} or isinstance(value, (int, list))
            for key, value in checks.items()
            if key not in {"broken_links", "routers", "endpoints"}
        )
        report = self.emit(
            "self_diagnostic",
            level="info" if healthy else "error",
            healthy=healthy,
            checks=checks,
        )
        return report

    def status(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for report in self._events:
                counts[report["level"]] = counts.get(report["level"], 0) + 1
            return {
                "agent": "spectral-core-internal-monitor",
                "schema": SCHEMA,
                "status": "error" if self._last_error else "running",
                "started_at_ms": self._started_at_ms,
                "event_count": len(self._events),
                "level_counts": counts,
                "last_event": self._events[-1] if self._events else None,
                "last_error": self._last_error,
                "report_path": str(self.report_path) if self.report_path else None,
            }

    def events(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._events)
        return rows[-limit:] if limit is not None else rows

    def export_jsonl(self) -> str:
        with self._lock:
            return "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in self._events
            )

    def write_status(self, path: str | Path) -> None:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.status(), ensure_ascii=False, indent=2, sort_keys=True)
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
