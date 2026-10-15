"""An intentionally narrow, transparent rule-based comparison baseline."""
from .evidence import validate_report


def baseline(store):
    spans = store.call("query_telemetry", {"kind": "span"})
    logs = store.call("query_telemetry", {"kind": "log"})
    configs = store.call("query_telemetry", {"kind": "config", "service": "checkout"})
    store.call("search_runbooks", {"query": "checkout payment"})
    checkout = [r for r in spans if r["service"] == "checkout"]
    payment = {r["trace_id"]: r for r in spans if r["service"] == "payment"}
    timeouts = [r for r in logs if r["service"] == "checkout" and r["message"] == "upstream_timeout"]
    slow = [(log, payment[log["trace_id"]]) for log in timeouts
            if log["trace_id"] in payment and payment[log["trace_id"]]["duration_ms"] > log["timeout_ms"]]
    upstream_errors = [r for r in spans if r["service"] == "payment" and r["status"] >= 500
                       and any(c["trace_id"] == r["trace_id"] and c["status"] >= 500 for c in checkout)]
    report = {
        "status": "insufficient_evidence", "suspected_service": None,
        "summary": "Available evidence does not match a supported diagnosis.",
        "findings": [], "next_steps": ["Collect correlated checkout and payment spans and error logs."],
        "limitations": ["Rule-based baseline, not an LLM diagnosis; supports only this two-service lab.",
                        "A small local sample does not establish production reliability or a deeper root cause."],
    }
    if slow:
        log, span = slow[0]
        report.update(status="incident", suspected_service="payment",
                      summary="Payment latency exceeds checkout's timeout, causing checkout failures.",
                      findings=[{"claim": "A timed-out checkout request shares a trace with a payment taking %.2f ms, above its %.0f ms timeout." %
                                            (span["duration_ms"], log["timeout_ms"]), "evidence_ids": [log["id"], span["id"]]}],
                      next_steps=["Inspect payment/provider latency and recent changes to explain the slowdown.",
                                  "Verify payment idempotency before retrying; a timed-out request may still complete.",
                                  "Validate a proposed fix against the same workload before changing timeout settings."])
    elif upstream_errors:
        report.update(status="incident", suspected_service="payment",
                      summary="Payment returns HTTP errors on traces with failed checkout requests.",
                      findings=[{"claim": "Payment and checkout both return errors on the same trace.",
                                 "evidence_ids": [upstream_errors[0]["id"], next(c["id"] for c in checkout if c["trace_id"] == upstream_errors[0]["trace_id"])]}],
                      next_steps=["Inspect payment's provider health and error logs before retrying or rolling back."])
    elif checkout and all(r["status"] < 400 and r["trace_id"] in payment and payment[r["trace_id"]]["status"] < 400 for r in checkout):
        report.update(status="healthy", summary="No checkout failures observed in this sample.",
                      findings=[{"claim": "All captured checkout requests succeeded.", "evidence_ids": [r["id"] for r in checkout]}],
                      next_steps=["Continue observing a larger workload before concluding the service is healthy."])
    else:
        visible = checkout or spans or configs or [r for r in store.runbooks if r["id"] in store.seen]
        if visible:
            report["findings"] = [{"claim": "The available sample is insufficient for a supported diagnosis.", "evidence_ids": [visible[0]["id"]]}]
    return validate_report(report, store)
