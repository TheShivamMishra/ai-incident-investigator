"""Validate the portable telemetry boundary before tools or models see it."""
import math
from datetime import datetime


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1:
        raise ValueError("Unsupported snapshot schema")
    if set(snapshot) - {"schema_version", "captured_at", "source", "records", "runbooks"}:
        raise ValueError("Snapshot contains unsupported fields (labels must remain separate)")
    if not isinstance(snapshot.get("records"), list) or not isinstance(snapshot.get("runbooks"), list):
        raise ValueError("Snapshot records and runbooks must be arrays")
    ids = set()
    for item in snapshot["records"] + snapshot["runbooks"]:
        if not isinstance(item, dict) or not nonempty(item.get("id")):
            raise ValueError("Each evidence item needs a nonempty string ID")
        if item["id"] in ids:
            raise ValueError("Evidence IDs must be unique")
        ids.add(item["id"])
    for record in snapshot["records"]:
        if not nonempty(record.get("service")) or record.get("kind") not in ("span", "log", "config"):
            raise ValueError("Each telemetry record needs a service and supported kind")
        try:
            timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError()
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ValueError("Telemetry timestamps must be timezone-aware ISO timestamps") from None
        if record["kind"] == "span":
            if not nonempty(record.get("trace_id")) or not nonempty(record.get("operation")):
                raise ValueError("Spans require trace_id and operation")
            if not number(record.get("duration_ms")) or type(record.get("status")) is not int or not 100 <= record["status"] <= 599:
                raise ValueError("Spans require finite nonnegative duration_ms and HTTP status")
        if record["kind"] == "log":
            if not nonempty(record.get("message")) or not nonempty(record.get("trace_id")):
                raise ValueError("Logs require message and trace_id")
            if record["message"] == "upstream_timeout" and not number(record.get("timeout_ms")):
                raise ValueError("Timeout logs require finite nonnegative timeout_ms")
        if "timeout_ms" in record and not number(record["timeout_ms"]):
            raise ValueError("Invalid timeout_ms")
    for runbook in snapshot["runbooks"]:
        if not nonempty(runbook.get("title")) or not nonempty(runbook.get("text")):
            raise ValueError("Runbooks require title and text")
    return snapshot
