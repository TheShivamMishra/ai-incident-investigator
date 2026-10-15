import copy
import json
import tempfile
import unittest
from pathlib import Path

from incident_assistant.agent import investigate
from incident_assistant.evidence import EvidenceStore, metrics, validate_report
from incident_assistant.investigate import baseline
from incident_assistant.lab import capture
from incident_assistant.report import save_bundle


class InvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slow = capture("payment-latency", requests=3)
        cls.healthy = capture("healthy", requests=3)
        cls.errors = capture("payment-errors", requests=3)

    def test_real_http_fault_propagates_and_has_correlated_evidence(self):
        store = EvidenceStore(self.slow)
        report = baseline(store)
        self.assertEqual(report["status"], "incident")
        self.assertEqual(report["suspected_service"], "payment")
        self.assertIn("latency", report["summary"])
        cited = [store.by_id[i] for i in report["findings"][0]["evidence_ids"]]
        self.assertEqual(cited[0]["trace_id"], cited[1]["trace_id"])
        self.assertGreater(cited[1]["duration_ms"], cited[0]["timeout_ms"])
        self.assertEqual(metrics(self.slow)["checkout"]["error_rate"], 1.0)

    def test_healthy_workload_does_not_raise_incident(self):
        self.assertEqual(baseline(EvidenceStore(self.healthy))["status"], "healthy")

    def test_explicit_upstream_errors_are_not_diagnosed_as_latency(self):
        report = baseline(EvidenceStore(self.errors))
        self.assertEqual(report["status"], "incident")
        self.assertIn("HTTP errors", report["summary"])
        self.assertNotIn("latency", report["summary"])

    def test_missing_trace_correlation_does_not_invent_diagnosis(self):
        snapshot = copy.deepcopy(self.slow)
        for record in snapshot["records"]:
            if record["service"] == "payment":
                record["trace_id"] = "unrelated"
        self.assertEqual(baseline(EvidenceStore(snapshot))["status"], "insufficient_evidence")

    def test_empty_evidence_abstains(self):
        self.assertEqual(baseline(EvidenceStore({"schema_version": 1, "records": [], "runbooks": []}))["status"], "insufficient_evidence")

    def test_unseen_and_invented_citations_are_rejected(self):
        report = baseline(EvidenceStore(self.slow))
        with self.assertRaisesRegex(ValueError, "returned by tools"):
            validate_report(report, EvidenceStore(self.slow))
        store = EvidenceStore(self.slow)
        report = baseline(store)
        report["findings"][0]["evidence_ids"] = ["made-up-id"]
        with self.assertRaises(ValueError):
            validate_report(report, store)

    def test_read_only_tool_boundary_and_filters(self):
        store = EvidenceStore(self.slow)
        with self.assertRaises(ValueError):
            store.call("run_shell", {"command": "echo no"})
        with self.assertRaises(ValueError):
            store.call("query_telemetry", {"service": ["payment"]})
        self.assertEqual(store.call("query_telemetry", {"service": "missing"}), [])

    def test_agent_consumes_tool_results_then_submits_report(self):
        expected = baseline(EvidenceStore(self.slow))
        requests = []

        def provider(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                block = {"type": "tool_use", "id": "call1", "name": "query_telemetry", "input": {}}
            else:
                self.assertEqual(payload["messages"][-1]["content"][0]["tool_use_id"], "call1")
                block = {"type": "tool_use", "id": "call2", "name": "submit_report", "input": expected}
            return {"stop_reason": "tool_use", "content": [block], "usage": {"input_tokens": 10, "output_tokens": 5}}

        report, usage = investigate(EvidenceStore(self.slow), "test-model", request_fn=provider)
        self.assertEqual(report, expected)
        self.assertEqual(usage, {"input_tokens": 20, "output_tokens": 10})
        self.assertEqual(len(requests), 2)

    def test_agent_receives_error_for_invalid_report_and_stops_at_budget(self):
        expected = baseline(EvidenceStore(self.slow))
        received = []

        def provider(payload):
            received.append(copy.deepcopy(payload))
            return {"content": [{"type": "tool_use", "id": "bad", "name": "submit_report", "input": expected}]}

        with self.assertRaisesRegex(RuntimeError, "round limit"):
            investigate(EvidenceStore(self.slow), "test-model", request_fn=provider, max_rounds=2)
        self.assertTrue(received[1]["messages"][-1]["content"][0]["is_error"])

    def test_truncated_model_output_is_not_accepted(self):
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            investigate(EvidenceStore(self.slow), "test-model", request_fn=lambda _: {"stop_reason": "max_tokens"})

    def test_artifact_bundle_can_be_replayed(self):
        store = EvidenceStore(self.slow)
        report = baseline(store)
        with tempfile.TemporaryDirectory() as tmp:
            path = save_bundle(tmp, self.slow, report, store, {"mode": "baseline"})
            self.assertIn("Cited evidence", path.read_text())
            replay = json.loads((Path(tmp) / "snapshot.json").read_text())
            self.assertEqual(baseline(EvidenceStore(replay)), report)


if __name__ == "__main__":
    unittest.main()
