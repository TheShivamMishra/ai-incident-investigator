# Development baseline: benchmark v1

The unchanged rule baseline completed all 10 development cases and matched the
expected status and suspected service in **9/10**. All citations passed reference
provenance validation. This is not an LLM accuracy result, a mechanism score, or a
measure of how well claims follow from evidence. Human semantic review is pending.
The [machine-readable run summary](results/baseline-v1-dev.json) records input,
manifest, and source hashes. Its artifact paths refer to locally generated reports;
run the command below to recreate those report bundles.

Reproduce from the repository root:

```sh
python3 -m incident_assistant benchmark datasets/v1/manifest.json --output artifacts/dev-baseline
```

| Category | Status + service matches | Observation |
| --- | --- | --- |
| Healthy | 2/2 | No incident reported for successful checkout traffic |
| Dependency timeouts | 2/2 | Correlated payment durations exceed the checkout timeout |
| Upstream HTTP errors | 2/2 | Explicit dependency failures are identified |
| Missing evidence | 2/2 | Baseline abstains when dependency correlation is absent |
| Distractor/conflict | 1/2 | Ignores an unrelated error but misses contradictory checkout records |

## Three cases to inspect

**case-018: contradictory evidence.** Both failed and successful checkout records
exist for the same span IDs. The baseline identifies a timeout from a log and
payment span but does not acknowledge the contradictory checkout records. The
conservative rubric expects uncertainty. This is the first known failure to
compare with the LLM; the baseline has intentionally not been tuned to fix it.

**case-014: missing correlation.** Slow payment spans exist, but their trace IDs
do not match checkout errors. The baseline abstains. The LLM should similarly
avoid using unrelated slowness as causal evidence.

**case-017: distracting failure.** An unrelated search-service HTTP error appears
alongside the checkout/payment timeout. The baseline uses the shared trace and
identifies payment. The LLM should not select a service solely because it has an
error record.

## Next comparison

Run a configured Claude model in prompt-only and tool-using modes against these
same inputs, with three repetitions and a bounded batch. Review every claim and
record both successful and failed attempts. The held-out split has not been
evaluated during this implementation. Live LLM measurements, dollar costs, and
independent label review remain pending.
