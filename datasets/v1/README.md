# Incident benchmark v1

Twenty independent captures from the local HTTP lab, with five categories and
four cases per category. Each category has two development and two test cases.
Use the committed bytes for replay; fresh captures have different timings and
belong in a new version directory.

| Category | Dev cases | Test cases | Expected behavior |
| --- | --- | --- | --- |
| Healthy | 001, 002 | 003, 004 | Report no failures in the sample |
| Dependency timeout | 005, 006 | 007, 008 | Identify correlated payment latency above checkout timeout |
| Upstream HTTP error | 009, 010 | 011, 012 | Distinguish explicit HTTP failure from timeout |
| Missing evidence | 013, 014 | 015, 016 | Abstain from assigning a dependency cause without correlated evidence |
| Distractor/conflict | 017, 018 | 019, 020 | Ignore unrelated errors; acknowledge contradictory records for the same span |

## Provenance

Generated with `python3 -m scripts.generate_benchmark --output datasets/v1`.
Each case starts with a separate real loopback HTTP capture involving fake
payments. Durations and initial statuses are measured. Dates are shifted to a
fixed anchor and random trace IDs are normalized; those are not real incident
timestamps. Original span IDs are assigned from evidence IDs.

The missing-evidence cases remove payment telemetry or replace its trace IDs.
The last category adds an unrelated synthetic search error, or contradictory
synthetic success records for existing checkout span IDs. Transformations are
recorded in the manifest and label rubric. These are deliberately modified lab
snapshots, not production observations or a realistic distribution of incidents.

`inputs/` contains only evidence. `labels/` contains expected status, service,
mechanism, evidence references, uncertainty guidance, and prohibited claims.
The loader verifies SHA-256 hashes, path containment, input shape, unique IDs,
and capture-group/input isolation across splits before any API call.

Labels are author-defined and await independent human review. In conflicting
cases the rubric conservatively requires `insufficient_evidence` and a null
suspected service. An investigator may describe observed timeout symptoms, but
must acknowledge the contradictory records rather than assert a firm diagnosis.

## Limits

- Ten test cases are too few for reliable estimates of real-world accuracy.
- Fault templates and service topology are shared across development and test
  splits. Independent captures prevent exact-run leakage, not template overlap.
- The baseline was written before this dataset. Do not tune on test outcomes.
- The current scores cover status and service only. Review mechanism and claim
  support separately; valid reference IDs do not establish semantic support.
- This benchmark does not test runbook prompt injection or production-scale
  telemetry; those need later datasets.

## Commands

```sh
python3 -m incident_assistant validate-dataset datasets/v1/manifest.json
python3 -m incident_assistant benchmark datasets/v1/manifest.json --output artifacts/dev-baseline
```

The default split is `dev`. Choose `--split test` explicitly after freezing the
prompt. The generator refuses to replace an existing directory.
