"""Capture a NEW dataset version. Existing output directories are never replaced.

Run from the repository root: python3 -m scripts.generate_benchmark --output datasets/v1
Timing measurements vary across captures; committed snapshots, not regeneration,
are the reproducible evaluation input.
"""
import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from incident_assistant.lab import capture
from incident_assistant.schema import validate_snapshot


def write_json(path, value):
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def sanitize(snapshot):
    traces = {}
    origin = min(datetime.fromisoformat(r["timestamp"]) for r in snapshot["records"])
    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for record in snapshot["records"]:
        record["timestamp"] = (anchor + (datetime.fromisoformat(record["timestamp"]) - origin)).isoformat()
        if "trace_id" in record:
            traces.setdefault(record["trace_id"], "trace-%03d" % (len(traces) + 1))
            record["trace_id"] = traces[record["trace_id"]]
        if record["kind"] == "span":
            record["span_id"] = record["id"]
    snapshot["captured_at"] = anchor.isoformat()
    snapshot["source"] = "Local fake-payment HTTP lab; timestamps and trace IDs normalized. Benchmark variants may alter evidence; no production data."
    return snapshot


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "inputs").mkdir()
    (output / "labels").mkdir()
    manifest = {"schema_version": 1, "dataset_version": output.name,
                "generation": "python3 -m scripts.generate_benchmark --output <new-directory>",
                "limitations": "Independent local captures; repeated fault families across splits. Small benchmark, not production or unseen-family generalization.",
                "cases": []}
    groups = ("healthy", "timeout", "http-error", "missing-evidence", "distractor-or-conflict")
    for category in groups:
        for variant in range(4):
            case_id = "case-%03d" % (len(manifest["cases"]) + 1)
            split = "dev" if variant < 2 else "test"
            scenario = "healthy" if category == "healthy" else "payment-errors" if category == "http-error" else "payment-latency"
            snapshot = sanitize(capture(scenario, requests=2 + variant))
            status = "healthy" if category == "healthy" else "incident"
            service = None if category == "healthy" else "payment"
            mechanism = "none" if category == "healthy" else "upstream_http_error" if category == "http-error" else "dependency_timeout"
            transformation = "Normalize timestamps and trace IDs only; retain measured durations and statuses."
            if category == "missing-evidence":
                if variant % 2 == 0:
                    snapshot["records"] = [r for r in snapshot["records"] if r["service"] != "payment"]
                    transformation += " Remove payment telemetry; checkout timeout symptoms alone cannot establish payment execution time."
                else:
                    for record in snapshot["records"]:
                        if record["service"] == "payment":
                            record["trace_id"] = "unrelated-" + record["trace_id"]
                    transformation += " Replace payment trace IDs, leaving no correlated dependency observations."
                status, service, mechanism = "insufficient_evidence", None, "unknown"
            if category == "distractor-or-conflict":
                if variant % 2 == 0:
                    distractor = copy.deepcopy(next(r for r in snapshot["records"] if r["kind"] == "span"))
                    distractor.update(id="distractor-1", span_id="distractor-span", service="search", trace_id="unrelated-search", status=503)
                    snapshot["records"].append(distractor)
                    transformation += " Append an unrelated synthetic search-service error span."
                else:
                    originals = [r for r in snapshot["records"] if r["kind"] == "span" and r["service"] == "checkout"]
                    for original in originals:
                        conflict = dict(original, id="conflict-" + original["id"], status=200, duration_ms=5.0)
                        snapshot["records"].append(conflict)
                    transformation += " Append contradictory success records for the SAME checkout span IDs. Do not resolve exporter conflicts by guessing."
                    status, service, mechanism = "insufficient_evidence", None, "unknown"
            validate_snapshot(snapshot)
            label = {"status": status, "suspected_service": service, "mechanism": mechanism,
                     "review_status": "author-defined; independent human review pending",
                     "evidence_ids": [r["id"] for r in snapshot["records"]],
                     "acceptable_uncertainty": "Describe observed symptoms, but do not assert a deeper provider cause or resolve contradictory span records without evidence.",
                     "prohibited_claims": ["A deployment caused the incident", "Production customers or revenue were affected", "A remediation was executed"],
                     "rubric": transformation}
            input_path, label_path = "inputs/" + case_id + ".json", "labels/" + case_id + ".json"
            manifest["cases"].append({"id": case_id, "split": split, "capture_group": case_id,
                "category": category, "input": input_path, "input_sha256": write_json(output / input_path, snapshot),
                "label": label_path, "label_sha256": write_json(output / label_path, label), "transformation": transformation})
    write_json(output / "manifest.json", manifest)
    print("Captured %s cases in %s" % (len(manifest["cases"]), output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    generate(parser.parse_args().output)
