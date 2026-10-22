# inspect_ranges.scanners – Inspect Ranges

Scanners checking that the range apparatus itself behaved, built on [inspect_scout](https://meridianlabs-ai.github.io/inspect_scout/). The scanner form covers both consumption paths: scan finished logs with `scout scan inspect_ranges/range_apparatus -T ./logs` (or `inspect_scout.scan` from Python), or put it directly in a task’s scorer list to run online beside `challenge_scorer`, as the packaged example tasks do. See [Running the Range](../building.html.md#scan) for the development usage and what a finding looks like.

## Scanners

### range_apparatus

Scan a sample’s transcript for range-apparatus anomalies.

The result value is the finding count (0 is healthy; the [mean()](https://inspect.aisi.org.uk/reference/inspect_ai.scorer.html#mean) metric reads as mean findings per sample, with no accuracy semantics). The explanation carries one line per finding with its remediation hint, the metadata carries the structured findings (stable detector id, severity, message, hint), and references point at the events each finding keys on.

Detector families: PLUMBING (post-readiness channel/transport failures, repeated retries against one guest, evidence finalize/teardown errors, the in-guest tool’s rc 124/125 contract), CONFIG-AWARE REACHABILITY (reading the range definition from the sample metadata `challenge_dataset(range_spec=...)` writes: connectivity failures toward addresses the spec declares reachable from the foothold under its ACLs, and attempts toward private addresses no declared network holds), VERIFY_GOAL BEHAVIOR (zero recorded submissions, submissions binding to no goal, dropped candidates, completion claims over unattempted goals), and SCORING/EVIDENCE INTEGRITY (recorded validity other than `valid`, corroboration flags, the all-segment-goals-uncorroborated hint).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/28890ce6d7f86f353f8638103ddb5de4f3db2fca/src/inspect_ranges/scanners.py#L36)

``` python
@scanner(messages="all", events="all", metadata=True, metrics=[mean()])
def range_apparatus() -> Scanner[Transcript]
```
