import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .agent import investigate
from .evidence import EvidenceStore, metrics
from .investigate import baseline
from .lab import capture
from .report import save_bundle


def run(snapshot, mode, model, output):
    store = EvidenceStore(snapshot)
    started = time.perf_counter()
    if mode == "llm":
        report, usage = investigate(store, model)
    else:
        report, usage = baseline(store), {"input_tokens": 0, "output_tokens": 0}
    execution = {"mode": mode, "model": model if mode == "llm" else None,
                 "duration_seconds": round(time.perf_counter() - started, 3), "usage": usage,
                 "citation_check": "retrieved IDs only; semantic support not automatically verified",
                 "service_metrics": metrics(snapshot)}
    path = save_bundle(output, snapshot, report, store, execution)
    return report, path


def main():
    parser = argparse.ArgumentParser(description="Evidence-first incident investigation lab")
    sub = parser.add_subparsers(dest="command", required=True)
    default_output = "artifacts/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for command in ("demo", "investigate", "evaluate"):
        child = sub.add_parser(command)
        child.add_argument("--mode", choices=["baseline", "llm"], default="baseline")
        child.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL"))
        child.add_argument("--output", default=default_output)
        if command == "demo":
            child.add_argument("--scenario", choices=["payment-latency", "payment-errors", "healthy"], default="payment-latency")
            child.add_argument("--requests", type=int, default=6)
        elif command == "investigate":
            child.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "llm" and (not args.model or not os.environ.get("ANTHROPIC_API_KEY")):
            raise ValueError("LLM mode needs ANTHROPIC_API_KEY and --model (or ANTHROPIC_MODEL).")
        if args.command == "evaluate":
            results = []
            for scenario, expected_status, expected_service in (("payment-latency", "incident", "payment"),
                                                               ("payment-errors", "incident", "payment"),
                                                               ("healthy", "healthy", None)):
                report, path = run(capture(scenario), args.mode, args.model, Path(args.output) / scenario)
                # Ground truth stays in this harness; never passed to the agent.
                passed = report["status"] == expected_status and report["suspected_service"] == expected_service
                results.append({"scenario": scenario, "passed": passed, "status": report["status"],
                                "suspected_service": report["suspected_service"]})
                print(("PASS" if passed else "FAIL") + " " + scenario)
            evaluation = {"mode": args.mode, "cases": results,
                          "scope": "Smoke evaluation of status and service only; not root-cause or prose correctness."}
            (Path(args.output) / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n")
            print("Evaluation: " + str(Path(args.output).resolve() / "evaluation.json"))
            return 0 if all(r["passed"] for r in results) else 1
        snapshot = capture(args.scenario, args.requests) if args.command == "demo" else json.loads(args.snapshot.read_text())
        report, path = run(snapshot, args.mode, args.model, args.output)
        print("[%s] %s" % (args.mode, report["summary"]))
        print("Report: " + str(path.resolve()))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        print("Error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
