"""Embedded diagnostics for the Spectral Core software emulator.

Reports contain operational metadata only: packet payloads and application data
are deliberately never accepted by the monitor API.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from collections import deque
import threading
import time
import uuid
import urllib.request
import urllib.parse
import urllib.error
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
    "authorization", "api_key", "access_token",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DiagnosticMonitor:
    """Thread-safe event monitor with optional durable JSONL report storage."""

    def __init__(self, report_path: Optional[str | Path] = None,
                 external_endpoint: Optional[str] = None,
                 external_token: Optional[str] = None,
                 max_report_bytes: int = 5 * 1024 * 1024,
                 report_backups: int = 3,
                 max_spool_bytes: int = 10 * 1024 * 1024):
        for name, value, minimum in (
            ("max_report_bytes", max_report_bytes, 16384),
            ("report_backups", report_backups, 0),
            ("max_spool_bytes", max_spool_bytes, 16384),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} is outside its allowed range")
        self.max_report_bytes = max_report_bytes
        self.report_backups = report_backups
        self.max_spool_bytes = max_spool_bytes
        self._spool_dropped = 0
        self.report_path = Path(report_path).expanduser() if report_path else None
        self.external_endpoint = external_endpoint
        self.external_token = external_token
        self.external_spool_path = (
            self.report_path.with_name("external-pending.jsonl") if self.report_path else None
        )
        if external_endpoint and self.report_path is None:
            raise ValueError("Persistent report_path is required for external forwarding")
        if external_endpoint:
            parsed = urllib.parse.urlparse(external_endpoint)
            if not parsed.hostname or parsed.query:
                raise ValueError("External monitor URL must include a host and must not contain a query")
            if parsed.username or parsed.password or parsed.fragment:
                raise ValueError("External monitor URL must not contain credentials or fragments")
            if parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            ):
                raise ValueError("External monitor endpoint must use HTTPS or loopback HTTP")
            if not external_token:
                raise ValueError("External monitor token is required when forwarding is enabled")
        self._lock = threading.RLock()
        self._events = deque(maxlen=5000)
        self._event_count = 0
        self._last_error: Optional[dict[str, Any]] = None
        self._started_at_ms = int(time.time() * 1000)
        self.emit("monitor_started", mode="persistent" if self.report_path else "memory")

    @staticmethod
    def _validate_data(data: dict[str, Any]) -> dict[str, Any]:
        def check(value: Any, key: str = "", depth: int = 0) -> Any:
            if depth > 8:
                raise ValueError("Diagnostic nesting limit exceeded")
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"Diagnostic field is not allowed: {key}")
            if value is None or isinstance(value, (str, int, float, bool)):
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"Non-finite diagnostic number is not allowed: {key}")
                if isinstance(value, str) and len(value) > 512:
                    raise ValueError(f"Diagnostic string is too long: {key}")
                return value
            if isinstance(value, (list, tuple)):
                if len(value) > 100:
                    raise ValueError(f"Diagnostic list is too large: {key}")
                return [check(item, key, depth + 1) for item in value]
            if isinstance(value, dict):
                if len(value) > 50:
                    raise ValueError(f"Diagnostic object is too large: {key}")
                return {str(k): check(v, str(k), depth + 1) for k, v in value.items()}
            raise TypeError(f"Unsupported diagnostic value for {key}: {type(value).__name__}")
        if not isinstance(data, dict):
            raise TypeError("Diagnostic data must be an object")
        return {str(key): check(value, str(key)) for key, value in data.items()}

    @staticmethod
    def _rotate_jsonl(path: Path, backups: int) -> None:
        if backups <= 0:
            path.unlink(missing_ok=True)
            return
        for index in range(backups, 1, -1):
            source = path.with_name(path.name + f".{index - 1}")
            target = path.with_name(path.name + f".{index}")
            if source.exists():
                os.replace(source, target)
        if path.exists():
            os.replace(path, path.with_name(path.name + ".1"))

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
            self._event_count += 1
            if level in {"error", "critical"}:
                self._last_error = report
            if self.report_path:
                self.report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                line = encoded + "\n"
                if self.report_path.exists() and self.report_path.stat().st_size + len(line.encode("utf-8")) > self.max_report_bytes:
                    self._rotate_jsonl(self.report_path, self.report_backups)
                fd = os.open(self.report_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "a", encoding="utf-8", closefd=False) as handle:
                        handle.write(line)
                        handle.flush()
                        os.fsync(fd)
                finally:
                    os.close(fd)
        if self.external_endpoint:
            pending = self.external_spool_path.exists() and self.external_spool_path.stat().st_size > 0
            if pending:
                self._spool_external(report)
                self.flush_external_spool()
            elif not self._forward_report(report):
                self._spool_external(report)
        return report

    def _forward_report(self, report: dict[str, Any]) -> bool:
        body = json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            self.external_endpoint, data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + str(self.external_token)},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=2.0) as response:
                ack = json.loads(response.read(4096).decode("utf-8"))
                return 200 <= response.status < 300 and ack.get("report_id") == report["report_id"] and ack.get("ok") is True
        except (OSError, urllib.error.URLError, ValueError, TypeError):
            return False

    def _spool_external(self, report: dict[str, Any]) -> None:
        if self.external_spool_path is None:
            return
        with self._lock:
            self.external_spool_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            line = json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n"
            if self.external_spool_path.exists() and self.external_spool_path.stat().st_size + len(line.encode("utf-8")) > self.max_spool_bytes:
                self._spool_dropped += 1
                return
            if len(line.encode("utf-8")) > self.max_spool_bytes:
                self._spool_dropped += 1
                return
            fd = os.open(self.external_spool_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8", closefd=False) as handle:
                    handle.write(line)
                    handle.flush()
                    os.fsync(fd)
            finally:
                os.close(fd)

    def flush_external_spool(self) -> int:
        """Retry pending reports in order; keep the first unacknowledged record and tail."""
        if not self.external_endpoint or self.external_spool_path is None or not self.external_spool_path.is_file():
            return 0
        with self._lock:
            lines = self.external_spool_path.read_text(encoding="utf-8").splitlines()
            sent = 0
            remaining = []
            blocked = False
            for line in lines:
                if blocked:
                    remaining.append(line)
                    continue
                try:
                    report = json.loads(line)
                except ValueError:
                    blocked = True
                    remaining.append(line)
                    continue
                if self._forward_report(report):
                    sent += 1
                else:
                    blocked = True
                    remaining.append(line)
            temporary = self.external_spool_path.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as handle:
                    handle.write("".join(line + "\n" for line in remaining))
                    handle.flush()
                    os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temporary, self.external_spool_path)
            return sent

    def record_exception(self, operation: str, error: Exception, **context: Any) -> None:
        self.emit(
            "runtime_error",
            level="error",
            operation=operation,
            error_type=type(error).__name__,
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
                "event_count": self._event_count,
                "level_counts": counts,
                "last_event": self._events[-1] if self._events else None,
                "last_error": self._last_error,
                "report_path": str(self.report_path) if self.report_path else None,
                "external_spool_dropped": self._spool_dropped,
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
