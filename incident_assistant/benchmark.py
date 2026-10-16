"""Hash-checked replay with labels isolated from investigator inputs."""
import hashlib
import json
import re
import time
from pathlib import Path

from .agent import SYSTEM, TOOLS, anthropic_request, investigate, prompt_only
from .budget import BudgetExceeded, MeteredProvider
from .evidence import EvidenceStore, validate_report
from .investigate import baseline
from .report import save_bundle


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_json(root, relative, expected_hash):
    if not isinstance(relative, str) or not isinstance(expected_hash, str):
        raise ValueError("Dataset paths and hashes must be strings")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("Dataset path escapes its directory")
    data = path.read_bytes()
    if digest(data) != expected_hash:
        raise ValueError("Dataset hash mismatch: " + relative)
    return json.loads(data)


def load_dataset(path):
    path = Path(path)
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("cases"), list) or not manifest["cases"] or not isinstance(manifest.get("dataset_version"), str):
        raise ValueError("Invalid dataset manifest")
    ids, groups, hashes, loaded = set(), {}, {}, []
    for case in manifest["cases"]:
        if not isinstance(case, dict) or not {"id", "split", "capture_group", "input", "input_sha256", "label", "label_sha256"} <= set(case):
            raise ValueError("Manifest case is missing required fields")
        case_id = case["id"]
        if not isinstance(case_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", case_id) or case_id in ids:
            raise ValueError("Case IDs must be unique safe path components")
        ids.add(case_id)
        if case["split"] not in ("dev", "test"):
            raise ValueError("Unknown dataset split")
        group = case["capture_group"]
        if not isinstance(group, str) or not group:
            raise ValueError("Capture group must be a nonempty string")
        if group in groups and groups[group] != case["split"]:
            raise ValueError("Capture group leaked across splits")
        groups[group] = case["split"]
        snapshot = checked_json(path.parent, case["input"], case["input_sha256"])
        input_hash = case["input_sha256"]
        if input_hash in hashes and hashes[input_hash] != case["split"]:
            raise ValueError("Identical input leaked across splits")
        hashes[input_hash] = case["split"]
        store = EvidenceStore(snapshot)
        label = checked_json(path.parent, case["label"], case["label_sha256"])
        if not isinstance(label, dict):
            raise ValueError("Ground truth must be an object")
        if label.get("status") not in ("incident", "healthy", "insufficient_evidence"):
            raise ValueError("Invalid ground-truth status")
        if "suspected_service" not in label or (label["suspected_service"] is not None and (not isinstance(label["suspected_service"], str) or label["suspected_service"] not in {r["service"] for r in store.records})):
            raise ValueError("Invalid ground-truth service")
        if label.get("mechanism") not in ("none", "unknown", "dependency_timeout", "upstream_http_error"):
            raise ValueError("Invalid ground-truth mechanism")
        if not isinstance(label.get("evidence_ids"), list) or any(not isinstance(i, str) or i not in store.by_id for i in label["evidence_ids"]):
            raise ValueError("Ground-truth evidence is missing")
        loaded.append((case, snapshot, label))
    return manifest, loaded


def summarize(results):
    rows = []
    for mode in sorted({r["mode"] for r in results}):
        subset = [r for r in results if r["mode"] == mode]
        completed = [r for r in subset if r["outcome"] == "completed"]
        attempted = [r for r in subset if r["outcome"] != "budget_skipped"]
        rows.append({"mode": mode, "scheduled": len(subset), "attempted": len(attempted), "completed": len(completed),
                     "failed": sum(r["outcome"] == "failed" for r in subset),
                     "budget_skipped": sum(r["outcome"] == "budget_skipped" for r in subset),
                     "correct_status_and_service": sum(r.get("status_correct", False) and r.get("service_correct", False) for r in subset),
                     "human_reviews_pending": len(completed)})
    return rows


def replay(manifest_path, output, modes=("baseline",), split="dev", repeats=3, model=None,
           max_api_calls=100, max_total_tokens=100000, request_fn=anthropic_request):
    if not modes or len(set(modes)) != len(modes) or any(m not in ("baseline", "llm", "prompt-only") for m in modes):
        raise ValueError("Choose distinct modes: baseline, llm, prompt-only")
    if split not in ("dev", "test", "all") or type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("Invalid split or repeats (1–10)")
    if any(m != "baseline" for m in modes) and not model:
        raise ValueError("LLM comparison requires a model ID")
    manifest, cases = load_dataset(manifest_path)  # Verify all inputs before any API call.
    manifest_hash = digest(Path(manifest_path).read_bytes())
    selected = [(c, s, l) for c, s, l in cases if split == "all" or c["split"] == split]
    if not selected:
        raise ValueError("Selected split has no cases")
    provider = MeteredProvider(request_fn, max_api_calls, max_total_tokens)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite experiment results.
    prompt_hash = digest(json.dumps({"system": SYSTEM, "tools": TOOLS}, sort_keys=True).encode())
    source_hash = digest(b"".join(p.name.encode() + p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py"))))
    results = []

    def persist():
        summary = {"schema_version": 1, "dataset_version": manifest["dataset_version"],
            "manifest_sha256": manifest_hash, "split": split,
            "model": model, "prompt_schema_sha256": prompt_hash, "source_sha256": source_hash,
            "budget": {"max_api_calls": max_api_calls, "max_total_tokens": max_total_tokens,
                       "token_limit_semantics": "Stop between requests after observed usage reaches limit; the final request can overshoot."},
            "usage": provider.snapshot(), "summary": summarize(results), "results": results,
            "estimated_cost_usd": None, "cost_note": "No price table supplied; use recorded token usage and verified model pricing.",
            "scope": "Automated scores cover status/service and citation provenance only. Mechanism and claim support require human review."}
        (output / "evaluation.json").write_text(json.dumps(summary, indent=2) + "\n")
        lines = ["# Replay evaluation", "", "Split: **%s**. Fixed inputs; no traffic recaptured." % split,
            "", summary["scope"], "", "| Mode | Scheduled | Completed | Failed | Budget skipped | Correct status + service |",
            "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for row in summary["summary"]:
            lines.append("| {mode} | {scheduled} | {completed} | {failed} | {budget_skipped} | {correct_status_and_service} |".format(**row))
        lines += ["", "## Cases", "", "| Case | Mode | Repeat | Outcome | Status + service | Report |", "| --- | --- | ---: | --- | --- | --- |"]
        for row in results:
            score = "pass" if row.get("status_correct") and row.get("service_correct") else "fail"
            link = "[report](%s/report.md)" % row["artifact_dir"] if row["outcome"] == "completed" else "—"
            lines.append("| %s | %s | %s | %s | %s | %s |" % (row["case_id"], row["mode"], row["repeat"], row["outcome"], score, link))
        lines += ["", "Each completed run has review.json with ungraded mechanism/claim checks. Scores are not AI accuracy.",
                  "Failed and budget-skipped cases remain in the scheduled denominator. Token totals include failed runs when usage is available."]
        (output / "evaluation.md").write_text("\n".join(lines) + "\n")
        return summary

    for case, snapshot, label in selected:
        for repeat in range(1, repeats + 1):
            for mode in modes:  # Interleave LLM modes instead of spending all budget on one.
                if mode == "baseline" and repeat > 1:
                    continue
                directory = Path(case["id"]) / mode / str(repeat)
                row = {"case_id": case["id"], "split": case["split"], "mode": mode, "repeat": repeat,
                       "input_sha256": case["input_sha256"], "artifact_dir": str(directory)}
                store = EvidenceStore(snapshot)
                before = provider.snapshot()
                start = time.perf_counter()
                report = None
                try:
                    if mode == "baseline":
                        report = baseline(store)
                    else:
                        function = investigate if mode == "llm" else prompt_only
                        report, _ = function(store, model, request_fn=provider)
                    validate_report(report, store)
                    row.update(outcome="completed", status_correct=report["status"] == label["status"],
                               service_correct=report["suspected_service"] == label["suspected_service"], citation_provenance_valid=True)
                except BudgetExceeded as error:
                    row.update(outcome="failed" if provider.calls > before["api_calls"] else "budget_skipped", error=str(error))
                except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
                    row.update(outcome="failed", error=str(error), error_type=type(error).__name__)
                attempts = provider.attempts[before["api_calls"]:]
                row.update(duration_seconds=round(time.perf_counter() - start, 6),
                           api_calls=provider.calls - before["api_calls"],
                           usage={k: provider.usage[k] - before["usage"][k] for k in provider.usage},
                           usage_complete=all(a["response"] is not None and all(type(a["response"].get("usage", {}).get(k)) is int for k in provider.usage) for a in attempts),
                           tool_calls=len(store.audit))
                target = output / directory
                target.mkdir(parents=True)
                execution = dict(row, model=model if mode != "baseline" else None, source_sha256=source_hash, prompt_schema_sha256=prompt_hash)
                if report is not None and row["outcome"] == "completed":
                    save_bundle(target, snapshot, report, store, execution)
                    review = {"status": "pending_human_review", "expected": label,
                              "mechanism_correct": None, "summary_supported": None,
                              "findings": [{"claim": f["claim"], "evidence_ids": f["evidence_ids"], "support": None, "notes": ""} for f in report["findings"]],
                              "prohibited_claims_present": None, "reviewer": None}
                    (target / "review.json").write_text(json.dumps(review, indent=2) + "\n")
                else:
                    (target / "execution.json").write_text(json.dumps(execution, indent=2) + "\n")
                    (target / "tool_calls.json").write_text(json.dumps(store.audit, indent=2) + "\n")
                # Headers/credentials are never in payloads. Contains only benchmark evidence and model responses.
                (target / "provider_calls.json").write_text(json.dumps(attempts, indent=2) + "\n")
                results.append(row)
                persist()  # Preserve finished cases if a later investigation is interrupted.
    return persist()
