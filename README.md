# Incident Investigation Assistant

A learning project for building and evaluating an AI assistant that investigates
service failures using evidence. The first milestone is a reproducible local
checkout/payment incident, a transparent rule baseline, and an optional Claude
agent that queries telemetry and submits a cited report.

## Run the first incident

Python 3.9+ is sufficient. No dependencies, Docker, account, or API key needed:

```sh
python3 -m incident_assistant demo --output artifacts/first-incident
```

Two temporary HTTP servers bind to loopback on automatically chosen ports.
Checkout waits up to 150 ms for payment. The default fault makes payment take
400 ms; checkout returns 504 while payment eventually completes. The servers
shut down after the workload. All payments are fake.

Open `artifacts/first-incident/report.md` to inspect the result. The directory also
contains captured telemetry (`snapshot.json`), structured findings (`report.json`),
tool queries (`tool_calls.json`), and runtime/usage metrics (`execution.json`).
Choose a new output directory to preserve previous results; reusing it replaces
the files. Default output directories are timestamped.

```sh
python3 -m incident_assistant demo --scenario healthy
python3 -m incident_assistant demo --scenario payment-errors
python3 -m incident_assistant investigate artifacts/first-incident/snapshot.json
python3 -m incident_assistant evaluate --output artifacts/baseline-evaluation
python3 -m unittest discover -s tests -v
```

## Enable the AI investigator

Baseline mode is deterministic Python logic, **not AI**. LLM mode sends the local
sample telemetry and runbook tool results to Anthropic and incurs API usage.
Set `ANTHROPIC_API_KEY` securely in your shell and set `ANTHROPIC_MODEL` to a Claude
model ID available to your account. The application does not automatically load
`.env` files. Never commit credentials.

```sh
python3 -m incident_assistant investigate artifacts/first-incident/snapshot.json \
  --mode llm --output artifacts/llm-investigation
python3 -m incident_assistant evaluate --mode llm --output artifacts/llm-evaluation
```

This allows a direct comparison on the same captured incident. The agent chooses
between telemetry queries and keyword runbook search, then submits structured
findings. It has no shell, file modification, or remediation tools. Each run has
an eight-request limit and a 2,048-output-token limit per request. Tool errors are
returned to the model; invalid reports cannot become final artifacts. API errors
fail explicitly; there is no silent fallback to the baseline.

## Architecture

```text
Local HTTP workload → checkout → payment (injected delay/error)
                          ↓          ↓
                      JSON telemetry snapshot
                               ↓
                  Read-only evidence tool boundary
                         ↙              ↘
                Rule baseline       Claude tool loop
                         ↘              ↙
                   Report schema + citation validation
                               ↓
                  Markdown report + JSON audit artifacts
```

- `lab.py`: local services and trace-correlated telemetry capture.
- `evidence.py`: queries, retrieval tracking, citation validation, sample metrics.
- `investigate.py`: deliberately narrow rules for comparison.
- `agent.py`: provider adapter and bounded tool loop.
- `report.py`: saved report and evidence bundle.
- `__main__.py`: demo, replay, and smoke evaluation commands.

## What the evaluation establishes

The three-case smoke evaluation checks incident status and suspected service.
Tests additionally exercise trace correlation, timeout versus HTTP-error
diagnoses, abstention, invalid citations, model tool-result handling, and budget
exhaustion. Provider tests use scripted responses; they do not measure LLM quality.

Citation validation verifies that an ID was retrieved. It does **not** verify
that a claim follows from its cited evidence. Human review and a larger, separately
held-out evaluation set are required before reporting agent accuracy. Tiny-sample
p95 and error rate are lab observations, not production performance results.
Token counts are recorded; dollar costs are not estimated without model pricing.

## Learning milestones

The next implementation plan is in [Milestone 2: measure the AI investigator](docs/NEXT_MILESTONE.md).
For a guided walkthrough of this version, start with [the learning guide](docs/LEARNING_GUIDE.md).

1. **Local evidence loop (implemented):** run an incident, follow its trace, inspect
   the baseline, and review citations. Run the LLM adapter with your credentials.
2. **Evaluate the AI:** build a held-out set with missing/conflicting evidence,
   distractor logs, and multiple fault causes. Compare prompt-only, tool-using,
   and rule approaches on identical snapshots. Grade cause, evidence support,
   abstention, latency, and cost separately.
3. **Real telemetry integration:** connect the OpenTelemetry demo and a trace/log
   backend. Current telemetry is custom JSON; there is no OTel integration yet.
4. **Retrieval experiments:** expand runbooks, establish a keyword baseline, then
   test semantic retrieval and reranking against labeled queries.
5. **Portfolio release:** add a small investigation UI, deployment, CI, a recorded
   demo, reproducible benchmarks, and a write-up of failures and tradeoffs.

Keep resume claims tied to measured results. This initial milestone does not
establish production readiness, reduced incident resolution time, or AI accuracy.

## References

- [OpenTelemetry demo and fault scenarios](https://opentelemetry.io/docs/demo/)
- [Anthropic agent evaluation guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Claude tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [Messages API reference](https://platform.claude.com/docs/en/api/messages/create)
