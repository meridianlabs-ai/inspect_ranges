# inspect_ranges.scanners – Inspect Ranges

Scanners checking that the range apparatus itself behaved, built on [inspect_scout](https://meridianlabs-ai.github.io/inspect_scout/). `range_apparatus` matches machine signatures and costs no model call, so it also runs online in a task’s scorer list beside `challenge_scorer`, as the packaged example tasks do. `range_friction` reads the same transcripts with a model, for the defects that exist only as prose.

See [Running the Range](../building.html.md#scan) for the scanjob that runs both over finished logs, and what a finding looks like.

## Scanners

### range_apparatus

Scan a sample’s transcript for range-apparatus anomalies.

The result value is the finding count (0 is healthy; the [mean()](https://inspect.aisi.org.uk/reference/inspect_ai.scorer.html#mean) metric reads as mean findings per sample, with no accuracy semantics). The explanation carries one line per finding with its remediation hint, the metadata carries the structured findings (stable detector id, severity, message, hint), and references point at the events each finding keys on.

Detector families: PLUMBING (post-readiness channel/transport failures, repeated retries against one guest, evidence finalize/teardown errors, the in-guest tool’s rc 124/125 contract), CONFIG-AWARE REACHABILITY (reading the range definition from the sample metadata `challenge_dataset(range_spec=...)` writes: connectivity failures toward addresses the spec declares reachable from the foothold under its ACLs, and attempts toward private addresses no declared network holds), VERIFY_GOAL BEHAVIOR (zero recorded submissions, submissions binding to no goal, dropped candidates, completion claims over unattempted goals), and SCORING/EVIDENCE INTEGRITY (recorded validity other than `valid`, corroboration flags, the all-segment-goals-uncorroborated hint).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/91489b4f544a510e92b7d1c89cf825c1ee654458/src/inspect_ranges/scanners.py#L46)

``` python
@scanner(messages="all", events="all", metadata=True, metrics=[mean()])
def range_apparatus() -> Scanner[Transcript]
```

### range_friction

Read a sample’s transcript for evidence that the range contradicted its own brief.

The companion to `range_apparatus`, and the half that needs a model. `range_apparatus` matches exact machine signatures and is blind to a defect that exists only as prose: a file the brief promised and the agent could not find, a credential that did not authenticate, a terminal that swallowed output, scoring scaffolding the agent tripped over. Those appear in the transcript as the agent saying so.

The result value carries the findings (`{"findings": [...]}`), each with a category, a confidence, a verbatim quote and the `[M12]` marker it came from. An empty list is the healthy answer and the expected one for most transcripts, including most that scored zero: the prompt separates “the environment broke its promises” from “the task was hard and the agent failed”, and only the former is a finding.

Costs a model call per transcript, so this is an after-the-fact audit over eval logs (`inspect_scout.scan` or `scout scan`) rather than something to put in a scorer list.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/91489b4f544a510e92b7d1c89cf825c1ee654458/src/inspect_ranges/scanners.py#L98)

``` python
@scanner(messages="all", metadata=True)
def range_friction(model: str | Model | None = None) -> Scanner[Transcript]
```

`model` str \| [Model](https://inspect.aisi.org.uk/reference/inspect_ai.model.html#model) \| None  
Model to read with. Defaults to the scan’s model.
