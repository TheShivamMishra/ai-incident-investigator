"""Read-only tool boundary shared by the rule baseline and LLM agent."""
import math
from .schema import validate_snapshot


class EvidenceStore:
    def __init__(self, snapshot):
        validate_snapshot(snapshot)
        self.records = snapshot["records"]
        self.runbooks = snapshot["runbooks"]
        self.by_id = {item["id"]: item for item in self.records + self.runbooks}
        if len(self.by_id) != len(self.records) + len(self.runbooks):
            raise ValueError("Evidence IDs must be unique")
        self.seen = set()
        self.audit = []

    def call(self, name, arguments):
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        if name == "query_telemetry":
            if set(arguments) - {"service", "kind", "trace_id"}:
                raise ValueError("Unknown telemetry filter")
            if any(not isinstance(value, str) for value in arguments.values()):
                raise ValueError("Filters must be strings")
            if "kind" in arguments and arguments["kind"] not in ("span", "log", "config"):
                raise ValueError("Unknown telemetry kind")
            result = [r for r in self.records if all(r.get(k) == v for k, v in arguments.items())]
        elif name == "search_runbooks":
            if set(arguments) != {"query"} or not isinstance(arguments["query"], str):
                raise ValueError("A string query is required")
            terms = arguments["query"].lower().split()
            result = [r for r in self.runbooks if any(t in (r["title"] + " " + r["text"]).lower() for t in terms)]
        else:
            raise ValueError("Unknown tool: %s" % name)
        self.seen.update(r["id"] for r in result)
        self.audit.append({"tool": name, "arguments": arguments, "result_ids": [r["id"] for r in result]})
        return result


def validate_report(report, store):
    required = {"status", "suspected_service", "summary", "findings", "next_steps", "limitations"}
    if not isinstance(report, dict) or set(report) != required:
        raise ValueError("Report fields must be exactly: " + ", ".join(sorted(required)))
    if report["status"] not in ("incident", "healthy", "insufficient_evidence"):
        raise ValueError("Invalid report status")
    if report["suspected_service"] is not None and report["suspected_service"] not in {r["service"] for r in store.records}:
        raise ValueError("Suspected service is absent from telemetry")
    if not isinstance(report["summary"], str) or not report["summary"].strip():
        raise ValueError("A summary is required")
    for field in ("next_steps", "limitations"):
        if not isinstance(report[field], list) or not report[field] or any(not isinstance(x, str) or not x.strip() for x in report[field]):
            raise ValueError(field + " must contain nonempty strings")
    if not isinstance(report["findings"], list) or (not report["findings"] and report["status"] != "insufficient_evidence"):
        raise ValueError("A diagnosis needs at least one cited finding")
    for finding in report["findings"]:
        if not isinstance(finding, dict) or set(finding) != {"claim", "evidence_ids"}:
            raise ValueError("Each finding needs claim and evidence_ids")
        if not isinstance(finding["claim"], str) or not finding["claim"].strip():
            raise ValueError("A finding needs a nonempty claim")
        ids = finding["evidence_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in store.seen for i in ids):
            raise ValueError("Citations must refer to evidence returned by tools")
    # Existence/provenance checks do not prove that prose is entailed by evidence.
    return report


def metrics(snapshot):
    result = {}
    for service in sorted({r["service"] for r in snapshot["records"]}):
        spans = [r for r in snapshot["records"] if r["service"] == service and r["kind"] == "span"]
        if spans:
            durations = sorted(r["duration_ms"] for r in spans)
            result[service] = {"requests": len(spans), "error_rate": sum(r["status"] >= 500 for r in spans) / len(spans),
                               "p95_ms": durations[math.ceil(0.95 * len(durations)) - 1]}
    return result
