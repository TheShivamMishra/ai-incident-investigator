# Milestone 2: measure the AI investigator

Status: offline evaluation infrastructure implemented. The repository now has
20 hash-checked snapshots with separate labels, dev/test splits, schema checks,
a replay runner, prompt-only comparison mode, budget accounting, human-review
templates, and offline CI configuration. There are 23 passing local tests.
The unchanged baseline matches status/service on 9/10 development cases.
See [the results and known failure](BENCHMARK_RESULTS.md).

Pending: independent label review, live Claude configuration and execution,
human claim-support review, model pricing/cost estimates, held-out LLM evaluation,
and a recorded demo. API credentials and a model are not configured locally.

## Goal

Compare the rule baseline, a prompt-only LLM, and a tool-using LLM on exactly the
same captured incidents. Produce a reproducible results table and a reviewed
failure analysis. Improving the score is an experiment, not a promised outcome.

## Work in order

### 1. Freeze the benchmark inputs and labels

- Create 20 sanitized local snapshots: 4 healthy, 4 dependency timeouts,
  4 explicit dependency HTTP failures, 4 partial/missing-evidence cases, and
  4 cases with unrelated or conflicting telemetry.
- Split each category into 2 development and 2 held-out test cases before tuning.
  Keep all variants from one captured run on the same side of the split.
- Store ground truth outside model inputs: expected status, suspected service,
  failure mechanism, evidence IDs, acceptable uncertainty, and prohibited claims.
- Add a dataset manifest with schema version, generation instructions, hashes,
  split membership, and a description of hand-edited variants.
- Validate snapshots before investigation and fail clearly on malformed records.

Acceptance: replay inputs are immutable, labels never reach the model, and every
case has a reviewed rubric. Twenty cases are an initial benchmark, not a robust
estimate of production accuracy.

### 2. Run one live model investigation

- Configure the existing Claude adapter with a model available to the account.
  Keep credentials in the local environment, outside source control.
- Replay the existing payment-latency snapshot and inspect every tool result and
  final claim. Verify the actual API protocol and model behavior end to end.
- Save model ID, prompt version/hash, input hash, token usage, latency, and errors.
- Add a total token/spend budget before batch runs. Price estimates must use the
  selected model's current pricing, recorded with a source and retrieval date.

Acceptance: one real report has valid citations and manually reviewed support;
failed or truncated responses remain failures rather than disappearing from results.

### 3. Implement a fair comparison runner

- Extend evaluation to replay saved cases rather than recapturing traffic for
  each investigator. Current `evaluate` is only a three-case smoke check.
- Add prompt-only mode: provide the same available evidence directly, without
  iterative retrieval; retain the same report schema and citation validator.
- Use the same model and output limits for prompt-only and tool-using modes.
- Run each LLM variant three times per case to expose variability. Report
  per-case outcomes and aggregate counts; do not cherry-pick successful runs.
- Capture exceptions as explicit case failures and continue within the budget.

Acceptance: one command produces JSON and Markdown results for all modes, using
the same case IDs and input hashes, with no API access required for baseline runs.

### 4. Grade reasoning and evidence separately

| Dimension | Scoring approach |
| --- | --- |
| Incident detection | Correct status against labels |
| Service identification | Correct service, including null when evidence is insufficient |
| Failure mechanism | Timeout vs upstream HTTP failure vs unknown; reviewed rubric |
| Citation provenance | Every cited ID exists and was available to the investigator |
| Claim support | Human review: supported, unsupported, or contradicted by cited records |
| Abstention | Correctly acknowledges cases that cannot be diagnosed |
| Runtime reliability | Valid completion rate, tool errors, budget exhaustion, API failures |
| Efficiency | Latency, tokens, tool calls, and estimated cost per attempted/completed case |

Acceptance: every held-out report has a claim-support review. A correct service
name alone does not count as a correct diagnosis. A model grader may assist later,
but cannot replace the initial human rubric.

### 5. Publish the evidence and learning

- Add offline CI for tests, schema checks, and baseline replay; never require
  paid API calls or secrets in ordinary pull-request checks.
- Publish a benchmark summary with model/prompt versions, counts, costs, known
  limitations, and at least three representative failures or difficult cases.
- Record a short demo following one incident from telemetry to a cited finding.
- Update resume wording only after results exist; distinguish simulated lab
  measurements from real production impact.

## Suggested learning sessions

1. Dataset design and leakage prevention (2–3 hours).
2. First live LLM run and tool-loop inspection (1–2 hours).
3. Replay runner and comparison modes (3–4 hours).
4. Evaluation, failure analysis, and documentation (3–4 hours).

These are planning estimates. Dataset quality and model failures may require
additional iterations. Next execution task: configure the Claude API locally,
run one saved development incident, and inspect its evidence and output before
starting a budgeted comparison batch.

## After this milestone

Connect OpenTelemetry and a real trace/log backend, expand runbook retrieval,
then build an investigation UI. Keep those changes separate so that improvements
can be measured against the frozen benchmark.
