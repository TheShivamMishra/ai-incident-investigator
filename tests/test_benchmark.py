import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from incident_assistant.agent import prompt_only
from incident_assistant.benchmark import load_dataset, replay
from incident_assistant.budget import BudgetExceeded, MeteredProvider
from incident_assistant.evidence import EvidenceStore
from incident_assistant.investigate import baseline
from incident_assistant.schema import validate_snapshot


def sample():
    return {"schema_version": 1, "records": [
        {"id": "p1", "timestamp": "2026-01-01T00:00:00+00:00", "kind": "span", "service": "payment", "trace_id": "t1", "operation": "charge", "status": 200, "duration_ms": 10.0},
        {"id": "c1", "timestamp": "2026-01-01T00:00:00+00:00", "kind": "span", "service": "checkout", "trace_id": "t1", "operation": "checkout", "status": 200, "duration_ms": 12.0}], "runbooks": []}


def write(path, value):
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.label = {"status": "healthy", "suspected_service": None, "mechanism": "none", "evidence_ids": ["c1"], "rubric": "SECRET_LABEL_SENTINEL"}
        case = {"id": "case-1", "split": "dev", "capture_group": "capture-1", "input": "input.json", "label": "label.json",
                "input_sha256": write(self.root / "input.json", sample()), "label_sha256": write(self.root / "label.json", self.label)}
        self.manifest = {"schema_version": 1, "dataset_version": "test", "cases": [case]}
        self.path = self.root / "manifest.json"
        self.save_manifest()

    def save_manifest(self):
        write(self.path, self.manifest)

    def response(self, report=None):
        return {"stop_reason": "tool_use", "usage": {"input_tokens": 20, "output_tokens": 10},
                "content": [{"type": "tool_use", "id": "submit-1", "name": "submit_report", "input": report or baseline(EvidenceStore(sample()))}]}

    def test_dataset_integrity_tamper_detected_before_provider(self):
        snapshot = sample()
        snapshot["records"][0]["duration_ms"] = 999
        write(self.root / "input.json", snapshot)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            replay(self.path, self.root / "out", request_fn=lambda _: self.fail("Provider should not be called"))

    def test_capture_groups_and_identical_inputs_cannot_cross_splits(self):
        new = dict(self.manifest["cases"][0], id="case-2", split="test")
        self.manifest["cases"].append(new)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Capture group"):
            load_dataset(self.path)
        new["capture_group"] = "different-capture"
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Identical input"):
            load_dataset(self.path)

    def test_path_escape_is_rejected(self):
        self.manifest["cases"][0]["input"] = "../escape.json"
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "escapes"):
            load_dataset(self.path)

    def test_prompt_only_sees_evidence_but_no_labels_or_retrieval_tools(self):
        requests = []

        def provider(payload):
            requests.append(copy.deepcopy(payload))
            self.assertNotIn("SECRET_LABEL_SENTINEL", json.dumps(payload))
            self.assertEqual([t["name"] for t in payload["tools"]], ["submit_report"])
            self.assertIn('"id": "c1"', payload["messages"][0]["content"])
            return self.response()

        result = replay(self.path, self.root / "out", modes=("baseline", "prompt-only"), repeats=3,
                        model="test-model", request_fn=provider)
        self.assertEqual(len(requests), 3)
        self.assertEqual(len(result["results"]), 4)
        self.assertTrue(all(r["status_correct"] for r in result["results"]))
        review = json.loads((self.root / "out/case-1/prompt-only/1/review.json").read_text())
        self.assertIsNone(review["mechanism_correct"])
        self.assertEqual(review["status"], "pending_human_review")
        self.assertEqual(len({r["input_sha256"] for r in result["results"]}), 1)

    def test_tool_mode_never_receives_labels(self):
        count = 0

        def provider(payload):
            nonlocal count
            count += 1
            self.assertNotIn("SECRET_LABEL_SENTINEL", json.dumps(payload))
            if count == 1:
                return {"usage": {"input_tokens": 5, "output_tokens": 5}, "content": [{"type": "tool_use", "id": "read", "name": "query_telemetry", "input": {}}]}
            return self.response()

        result = replay(self.path, self.root / "out", modes=("llm",), repeats=1, model="test", request_fn=provider)
        self.assertEqual(result["results"][0]["api_calls"], 2)
        self.assertEqual(result["results"][0]["usage"], {"input_tokens": 25, "output_tokens": 15})

    def test_invalid_report_counts_as_failure_and_keeps_usage(self):
        count = 0

        def provider(payload):
            nonlocal count
            count += 1
            response = self.response()
            if count == 1:
                response["content"][0]["input"]["findings"][0]["evidence_ids"] = ["invented"]
            return response

        result = replay(self.path, self.root / "out", modes=("prompt-only",), repeats=2, model="test", request_fn=provider)
        self.assertEqual([r["outcome"] for r in result["results"]], ["failed", "completed"])
        self.assertEqual(result["usage"]["usage"]["input_tokens"], 40)
        self.assertEqual(result["summary"][0]["scheduled"], 2)
        self.assertEqual(result["summary"][0]["correct_status_and_service"], 1)

    def test_budget_retains_skipped_cases_and_baseline_runs_once(self):
        result = replay(self.path, self.root / "out", modes=("baseline", "prompt-only"), repeats=3,
                        model="test", max_api_calls=1, request_fn=lambda _: self.response())
        self.assertEqual(result["usage"]["api_calls"], 1)
        self.assertEqual([r["outcome"] for r in result["results"]], ["completed", "completed", "budget_skipped", "budget_skipped"])

    def test_usage_limit_stops_between_requests(self):
        meter = MeteredProvider(lambda _: self.response(), max_tokens=25)
        meter({})
        self.assertEqual(sum(meter.usage.values()), 30)
        with self.assertRaises(BudgetExceeded):
            meter({})

    def test_missing_usage_halts_batch_instead_of_counting_zero(self):
        meter = MeteredProvider(lambda _: {"content": []})
        with self.assertRaisesRegex(RuntimeError, "usage"):
            meter({})
        with self.assertRaises(BudgetExceeded):
            meter({})

    def test_existing_experiment_is_not_overwritten(self):
        replay(self.path, self.root / "out")
        with self.assertRaises(FileExistsError):
            replay(self.path, self.root / "out")

    def test_malformed_snapshot_values_fail_at_boundary(self):
        for field, bad in (("duration_ms", float("nan")), ("duration_ms", -1), ("status", True), ("trace_id", ""), ("timestamp", "yesterday")):
            snapshot = sample()
            snapshot["records"][0][field] = bad
            with self.subTest(field=field, value=bad), self.assertRaises(ValueError):
                validate_snapshot(snapshot)
        snapshot = sample()
        snapshot["expected_status"] = "healthy"
        with self.assertRaisesRegex(ValueError, "labels"):
            validate_snapshot(snapshot)

    def test_prompt_only_rejects_unseen_citation(self):
        report = baseline(EvidenceStore(sample()))
        report["findings"][0]["evidence_ids"] = ["made-up"]
        with self.assertRaisesRegex(ValueError, "returned by tools"):
            prompt_only(EvidenceStore(sample()), "test", request_fn=lambda _: self.response(report))


if __name__ == "__main__":
    unittest.main()
