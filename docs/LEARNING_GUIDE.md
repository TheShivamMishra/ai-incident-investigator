# Your first investigation

The goal is to understand why the diagnosis is justified, then measure whether an
LLM can reach that diagnosis through tools.

1. Run the default demo. Read the report before reading the baseline code.
2. Find the cited checkout log and payment span in `snapshot.json`. Follow their
   shared `trace_id`. Explain why payment can succeed while checkout fails.
3. Run the healthy and payment-errors scenarios. Compare HTTP status, latency,
   and the report. Why would increasing a timeout not fix an explicit HTTP 503?
4. Replay a saved snapshot. The input is now fixed, so you can compare investigators
   without changes in workload or timing confounding the result.
5. Remove payment spans from a copy of a snapshot. Run the investigator again.
   Explain why it should acknowledge missing evidence instead of guessing.
6. Read `agent.py`. The model chooses tools; Python executes only the allowed
   reads. The report validator checks citations against records actually returned.
7. After configuring an API key and model, replay the same snapshot with the LLM.
   Compare `tool_calls.json`, report quality, token counts, and execution time.

## Questions to answer in your project write-up

- What evidence distinguishes a slow dependency from an unavailable dependency?
- What can the evidence establish, and what remains unknown about the deeper cause?
- Why is a valid citation ID insufficient to prove a claim?
- When should the investigator abstain?
- What is the simplest baseline the agent must improve on?
- How will you avoid evaluating only scenarios used to develop the prompt?

## Next experiment

Create 10–20 additional labeled snapshots with varied timing, partial telemetry,
and distractors. Keep labels separate from inputs. Define the rubric before
changing the prompt. Reserve a subset for final evaluation, and manually inspect
each claim's support rather than scoring only the suspected service name.
