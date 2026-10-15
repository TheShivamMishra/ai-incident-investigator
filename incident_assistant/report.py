import json
from pathlib import Path


def save_bundle(directory, snapshot, report, store, execution):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in (("snapshot", snapshot), ("report", report), ("tool_calls", store.audit), ("execution", execution)):
        (directory / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")
    lines = ["# Incident investigation", "", "Mode: **%s** · Status: **%s**" % (execution["mode"], report["status"]), "",
             report["summary"], "", "## Findings", ""]
    for finding in report["findings"]:
        lines.append("- %s [%s]" % (finding["claim"], ", ".join(finding["evidence_ids"])))
    for title, field in (("Suggested next steps", "next_steps"), ("Limitations", "limitations")):
        lines += ["", "## " + title, ""] + ["- " + x for x in report[field]]
    lines += ["", "## Cited evidence", "", "Citation validation checks provenance, not whether every claim is supported.", ""]
    for reference in sorted({i for f in report["findings"] for i in f["evidence_ids"]}):
        lines += ["### " + reference, "", "```json", json.dumps(store.by_id[reference], indent=2), "```", ""]
    path = directory / "report.md"
    path.write_text("\n".join(lines))
    return path
