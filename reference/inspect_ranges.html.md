# inspect_ranges – Inspect Ranges

The package’s top-level surface. The eval wiring is covered in [Challenges](../challenges.html.md), the custom goal-type contract in [Custom Goals](../goals.html.md), and range definition loading in [Ranges](../ranges.html.md). Range definition types have their own page: [inspect_ranges.types](../reference/types.html.md).

## Challenge Tasks

### challenge_dataset

Build an Inspect dataset from a challenges file.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/dataset.py#L63)

``` python
def challenge_dataset(
    challenges: str | Path | Challenges,
    range_spec: RangeSpec | str | Path | None = None,
) -> Dataset
```

`challenges` str \| Path \| [Challenges](../reference/inspect_ranges.html.md#challenges)  
Path to a `challenges.yaml`, or an already validated [Challenges](../reference/inspect_ranges.html.md#challenges).

`range_spec` [RangeSpec](../reference/types.html.md#rangespec) \| str \| Path \| None  
The range the challenges run against, for early cross-reference validation: a validated [RangeSpec](../reference/types.html.md#rangespec) or a `range.yaml` path. Omitted means structural validation only; sample-time setup still refuses unavailable observers, unsupplied collector specs, and `answer` variables the range does not declare, while other cross-references (goal hosts, segments) surface only when their plant or probe fails against the live range.

### challenge_setup

Plant every goal’s per-sample material before the agent acts, and start the sample’s observers.

Pass as the task’s `setup` (equivalently, prepend to the solver chain; `setup=` is the same thing and is what the packaged examples do). Refuses (raises) when the sample carries no challenge metadata, a required observer is unavailable in this deployment, or any plant fails; plants written before a failure are unwound, so the agent never starts against a half-planted range.

Prober-based goals (`availability`, `degrade`, `tamper`) start the active prober after a successful setup, probing from the rendered probe endpoint on a cadence; `detection` and `evade` goals start the telemetry export poller for their collector, which must have a matching entry in `telemetry_collectors` (poll mechanics are deployment knowledge the schema deliberately does not carry: the collector name binds the two). Both producers write evidence mid-run and are stopped by the evidence session at finalize; the scorer reads recorded results only.

This solver never touches the agent’s tools: [verify_goal()](../reference/inspect_ranges.html.md#verify_goal) is the only submission channel, and the task author always passes it to their agent (`react(tools=[bash(), verify_goal()])`, or inspect_swe’s `bridged_tools=[verify_goal()]`). The dataset’s appended prompt paragraph names the tool and the goal ids for every challenge; this solver registers the sample’s verification context so the tool can verify cheap-tier goals at call time.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/setup.py#L267)

``` python
@solver
def challenge_setup(
    telemetry_collectors: "list[CollectorSpec] | None" = None,
) -> Solver
```

`telemetry_collectors` list\[CollectorSpec\] \| None  

### challenge_scorer

Score samples built by [challenge_dataset()](../reference/inspect_ranges.html.md#challenge_dataset) against their typed goals.

The scorer is a single end-of-run authority; its machinery (probers, corroboration windows, `patch` exploit re-runs) assumes the run is over and must execute at most once per sample. A mid-run invocation (react’s `attempts > 1` scores each submission with the task scorer; detected via `state.completed`, which the task runner sets only before the end-of-sample invocation) is supported and returns an intermediate verdict: the fraction of verifiable (submission-taking) goals already achieved among the latched records, exactly `1.0` once every verifiable goal is achieved (which ends react’s attempt loop), `0.0` for a challenge whose goals are all end-of-run types (react then burns its remaining attempts and ends), with the pending deferred goal ids in the metadata. A repeat invocation returns the recorded end-of-run score. Neither runs any scoring machinery, an intermediate verdict is never recorded as the final score, and a legitimate single end-of-run invocation is unaffected.

Raises (at scoring time): `RuntimeError` when the sample carries no challenge metadata.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/scorer.py#L357)

``` python
@scorer(metrics=[accuracy()])
def challenge_scorer() -> Scorer
```

### verify_goal

A tool verifying submitted proof values against challenge goals.

Pass it to the agent (`react(tools=[bash(), verify_goal()])`, or inspect_swe’s `bridged_tools=[verify_goal()]`); it is the only submission channel, and `challenge_dataset` names it with the goal ids in every sample’s instructions.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/verify.py#L67)

``` python
@tool
def verify_goal(feedback: bool = True) -> Tool
```

`feedback` bool  
Report the per-call verification outcome and the running goal checklist in tool results. With `feedback=False` results confirm recording only; values are still recorded, verified, and latched identically.

## Challenges

### Challenge

One agent-facing prompt paired with the typed goals that verify it.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L720)

``` python
class Challenge(_StrictModel)
```

#### Attributes

`id` str  
Challenge name, unique within the file; becomes the Inspect sample id.

`prompt` str  
The agent-facing task statement.

`goals` list\[SerializeAsAny\[[Goal](../reference/inspect_ranges.html.md#goal)\]\]  
Typed goals; each drives per-sample setup and supplies the scorer’s verification. `SerializeAsAny` serializes each goal by its runtime class, so a registry-dispatched custom goal round-trips through sample metadata with all its fields.

`scoring` [Scoring](../reference/inspect_ranges.html.md#scoring)  
Aggregation of goal results (weights by default).

### Challenges

A complete `challenges.yaml`: the list of challenges a range serves.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L797)

``` python
class Challenges(_StrictModel)
```

#### Attributes

`challenges` list\[[Challenge](../reference/inspect_ranges.html.md#challenge)\]  
The challenges; each becomes one Inspect sample.

### Goal

One typed goal; the YAML shape is flat and dispatches on `type` (built-ins through the union, registered custom types through `_dispatch_goal`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L658)

``` python
Goal = Annotated[
    FlagGoal
    | AnswerGoal
    | ExfiltrateGoal
    | ExecuteGoal
    | HijackGoal
    | ControlGoal
    | DegradeGoal
    | TamperGoal
    | AvailabilityGoal
    | DetectionGoal
    | EvadeGoal
    | JudgeGoal
    | PatchGoal,
    Field(discriminator="type"),
    WrapValidator(_dispatch_goal),
]
```

### Scoring

How a challenge’s goal results aggregate.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L696)

``` python
class Scoring(_StrictModel)
```

#### Attributes

`mode` Literal\['weights', 'milestones', 'coverage'\]  
`weights` (default), `milestones` (ordered steps), or `coverage` (fraction achieved).

`later_implies_earlier` bool  
Under `milestones`, a later step passing implies the earlier steps.

### Primitive

Capability labels for cross-benchmark aggregation: descriptive only, never a scoring input.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L92)

``` python
Primitive = Literal[
    "crash", "leak", "hijack", "write", "execute", "escalate", "control"
]
```

## Goal Types

### GoalBase

Base class for goal `Spec` models: the fields every goal shares, independent of its proof contract.

A goal type’s `spec` (see [GoalType](../reference/inspect_ranges.html.md#goaltype)) subclasses this to declare the fields its goals carry in `challenges.yaml`. A subclass must declare a `type` field whose `Literal` value(s) match the name(s) the type registers under (`register_goal_type`), e.g. `type: Literal["marker"] = "marker"`; the parser dispatches a goal mapping to the spec through that name. Validation is strict exactly like the built-ins: unknown keys are errors, the shared fields below apply, and the goal id must satisfy the evidence stream-name grammar (lowercase key-safe, since ids name `probe/<goal id>` streams).

Override `observers()` to declare the trusted observers goals of the type require; declaring them is what makes a deployment that cannot supply one refuse the challenge at planning time instead of scoring indeterminate at the end.

A custom spec parses from YAML only in processes where the type’s registration has already run: under inspect the `inspect_ai` entry-point mechanism imports registering modules before any parsing, while a plain `load_challenges`/`validate_challenges` caller must import the registering module first, or the goal’s `type` name refuses as unknown.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L119)

``` python
class GoalBase(_StrictModel)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`default_primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Per-type default label. The mapping across types is a v1 proposal pending external-review feedback (`challenges-v1.md`): the design names the vocabulary but not the table.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

#### Methods

observers  
The trusted observers this goal requires; every goal’s plant record needs the sink.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L174)

``` python
def observers(self) -> frozenset[ObserverKind]
```

### FlagGoal

Submit a per-sample secret planted at a path; no guest is consulted at scoring.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L179)

``` python
class FlagGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`host` str  
Guest the flag is planted on.

`path` str  
Absolute in-guest path of the planted flag.

`owner` str  
Account the planted file is readable by (mode 0600, owned by `owner`).

#### Methods

observers  
The trusted observers this goal requires; every goal’s plant record needs the sink.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L174)

``` python
def observers(self) -> frozenset[ObserverKind]
```

### AnswerGoal

Submit a fact about the environment, compared against exactly one declared source.

Sources: `variable` (the declared default, read from the spec; nothing draws in v1), `value` (a literal fact that is scenario content, visible in the spec by design), or `host` plus `path` (read by the oracle from the live instance). Exactly one source must be declared.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L193)

``` python
class AnswerGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`variable` str \| None  
Name of a declared range variable whose per-instance value is the expected answer.

`value` str \| None  
Literal expected fact (scenario content; never per-sample proof material).

`host` str \| None  
Guest to read the expected fact from, with `path`.

`path` str \| None  
In-guest path the oracle reads the expected fact from, with `host`.

#### Methods

observers  
The trusted observers this goal requires; every goal’s plant record needs the sink.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L174)

``` python
def observers(self) -> frozenset[ObserverKind]
```

### ExfiltrateGoal

Obtain target content: the submitted content or its per-sample canary matches the plant.

A file’s presence on the attack box never passes. When `segment` is declared, source-bound pcap corroborates the flow.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L241)

``` python
class ExfiltrateGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`host` str  
Guest holding the target content.

`path` str  
In-guest path of the content the canary is planted in.

`segment` str \| None  
Network whose pcap corroborates the exfiltration flow, when declared.

### ExecuteGoal

Run code on a host: produce a per-sample token readable only by the targeted execution context.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L262)

``` python
class ExecuteGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`host` str  
Guest the execution happens on.

`service_user` str  
Account the exploited context runs as; the token is readable only by it.

`token_path` str  
In-guest path the token is planted at (mode 0600, owned by `service_user`).

`beacon_segment` str \| None  
Network whose pcap carries the source-bound beacon corroboration, when declared.

### HijackGoal

Redirect control flow short of code execution: the crash record shows the per-sample disclosed value.

The proof is `guest-corroborated` with a declared floor: forging the crash record costs code execution on the target (an unprivileged process renamed to the service can jump to the disclosed address and the kernel emits a genuinely matching segfault line), so the type is sound when the claimed capability is cheaper than execution on that host.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L282)

``` python
class HijackGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`host` str  
Guest the crashable target runs on.

`service` str  
Name of the target process whose crash record is checked.

### ControlGoal

Gain a host or principal: produce a secret planted where the claim lives.

Registered under both `control` and `privilege`; `privilege` defaults the capability label to `escalate`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L300)

``` python
class ControlGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`host` str  
Guest the secret is planted on.

`principal` str  
Account the secret is readable by; producing it requires the claimed access.

`secret_path` str  
In-guest path of the planted secret (mode 0600, owned by `principal`).

#### Methods

observers  
The trusted observers this goal requires; every goal’s plant record needs the sink.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L174)

``` python
def observers(self) -> frozenset[ObserverKind]
```

### DegradeGoal

Deny or degrade a service: the declared external probe fails its nonce-bound check within the window.

DOWN is full credit; a declared degradation `measure` with its `threshold` earns partial credit between MUMBLE and DOWN.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L323)

``` python
class DegradeGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`host` str  
Guest running the probed service.

`port` int  
Service port the active prober checks.

`segment` str \| None  
Network the probe reaches the service through; omitted means the host’s first interface on a probed segment. A declared segment must carry a probe endpoint in the plan, or setup refuses.

`window_s` float  
Observation window the probe verdict is scored over, in seconds.

`measure` Literal\['latency', 'error-fraction'\] \| None  
Degradation measure for partial credit, when declared.

`threshold` float \| None  
Threshold the measure is scored against; required with `measure`.

### TamperGoal

Modify target data or behavior: the written per-sample value is observed from outside.

The write target must require the claimed access (the placement rule). `observer: guest-snapshot` (write-what-where) is designed, pending the introspected channel, and refuses at validation.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L363)

``` python
class TamperGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`host` str  
Guest holding the designated protected location.

`location` str  
The protected location the value must appear in (a database record, a served response), interpreted by the goal engine (v1: `PORT/PATH` observed over HTTP).

`segment` str \| None  
Network the probe reaches the location through; omitted means the host’s first interface on a probed segment. A declared segment must carry a probe endpoint in the plan, or setup refuses.

`observer` Literal\['active-prober', 'guest-snapshot'\]  
How the written value is observed from outside.

### AvailabilityGoal

Keep a service up (defender direction): the external probe answers its per-probe nonce within the window.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L403)

``` python
class AvailabilityGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`host` str  
Guest running the probed service.

`port` int  
Service port the active prober checks.

`segment` str \| None  
Network the probe reaches the service through; omitted means the host’s first interface on a probed segment. A declared segment must carry a probe endpoint in the plan, or setup refuses.

`window_s` float  
Observation window, in seconds; DOWN and MUMBLE inside it are penalized.

### DetectionGoal

Surface an alert (defender direction): the collector contains, or for stealth lacks, the expected signal.

Scored inside the observation window with a completeness precondition: no alert over an incomplete window is indeterminate, never a stealth pass.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L422)

``` python
class DetectionGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`collector` str  
Declared telemetry collector or sink the signal is expected in.

`signal` str  
The expected signal: a regex searched against the collector’s exported records in the bytes domain with multiline semantics, so author it to match the export’s record text, not as a prose description.

`window_s` float \| None  
Observation window in seconds; omitted means the whole run.

`stealth` bool  
When true, the goal passes if the expected signal is absent over a complete window.

### SeverityFilter

How to read an alert’s severity from one export record, and the floor that counts.

Severity vocabularies are collector-specific, so the goal declares the extraction: `pattern` is a regex with exactly one capture group, applied per newline-delimited export record. Numeric mode (no `levels`): the capture parses as an integer, `floor` is an integer, and `lower_is_more_severe` flips the comparison for vocabularies like journald’s `PRIORITY` (0 is emergency, 7 is debug, so a floor of 4 counts captures of 4 or lower). Ordered mode (`levels` given, least to most severe): the capture and `floor` are both level names. Records the pattern does not match, or whose capture does not parse in the declared vocabulary, are not alerts and never count toward the threshold.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L463)

``` python
class SeverityFilter(_StrictModel)
```

#### Attributes

`pattern` str  
Regex with exactly one capture group extracting the severity token from a record.

`floor` int \| str  
Severity at or beyond which a record counts: an integer in numeric mode, a level name in ordered mode.

`levels` list\[str\] \| None  
Ordered severity vocabulary, least to most severe; omitted means numeric mode.

`lower_is_more_severe` bool  
Numeric mode only: lower captured numbers are more severe (journald `PRIORITY` semantics).

### EvadeGoal

Achieve objectives while staying quiet (attacker direction): the dual of `detection`.

Alerts matching the declared filter stay at or below `threshold` within the window, scored from the exported telemetry under the same completeness precondition as `detection`: a silenced collector reads per `on_sensor_tamper`, never as a free stealth pass. Export records are newline-delimited (the v1 convention); window edges resolve at chunk-span granularity like `detection`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L542)

``` python
class EvadeGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`collector` str  
Declared telemetry collector or sink whose export is counted.

`severity` [SeverityFilter](../reference/inspect_ranges.html.md#severityfilter)  
How severity is read from a record and the floor at which it counts.

`match` str \| None  
Optional regex a record must also match to count (a tag or alert marker); omitted means every record is a candidate.

`threshold` int  
Maximum qualifying alerts for full credit.

`zero_at` int \| None  
Count at which partial credit reaches zero (linear decay above `threshold`); omitted means binary at the threshold.

`window_s` float \| None  
Observation window in seconds; omitted means the whole run.

`on_sensor_tamper` Literal\['indeterminate', 'fail', 'succeed'\]  
What a completeness violation means: `indeterminate` (default; never a free stealth pass), `fail` (tampering is out of bounds; accepts that an infrastructure gap also fails this goal), or `succeed` (sensor destruction is legitimate evasion; waives completeness but never erases alerts already recorded).

`default_primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
No default label: evade is a constraint on how objectives are reached, not a capability (the primitive mapping is a v1 proposal; see `challenges-v1.md`).

### JudgeGoal

Produce an open-ended artifact graded by an LLM or human (`model-graded`, weight-capped by the engine).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L597)

``` python
class JudgeGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`rubric` str  
Grading instructions for the hardened judge template.

#### Methods

observers  
The trusted observers this goal requires; every goal’s plant record needs the sink.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L174)

``` python
def observers(self) -> frozenset[ObserverKind]
```

### PatchGoal

Fix a vulnerability (defender direction): the reference exploit re-run fails while the functional check passes.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L607)

``` python
class PatchGoal(GoalBase)
```

#### Attributes

`id` str  
Goal name, unique within its challenge; `verify_goal(goal_id, value)` binds to it.

`weight` float  
Relative contribution under the challenge’s scoring mode.

`primitive` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
Capability label override; `None` means the type’s default applies.

`primitive_label` [Primitive](../reference/inspect_ranges.html.md#primitive) \| None  
The effective capability label: the authored override, else the type default.

`host` str  
Guest the vulnerability lives on.

`exploit` str  
Identifier of the reference exploit chain re-run at scoring time.

`port` int  
Service port of the functional check that must still pass.

`segment` str \| None  
Network the probe reaches the service through; omitted means the host’s first interface on a probed segment. A declared segment must carry a probe endpoint in the plan, or setup refuses.

## Custom Goal Types

### GoalType

One goal type’s proof mechanics; stateless, registered once, shared across samples.

`spec` is the schema class the YAML dispatched to; `assurance` is the type’s default label (override `assurance_for` when a goal’s declared source moves the trust, as `answer`’s oracle-read source does).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/engine.py#L124)

``` python
class GoalType(ABC)
```

#### Attributes

`uses_submissions` bool  
Whether `check` consumes the submissions view. When False, the scorer runs ONE check per goal instead of one per submitted candidate: an agent must not be able to multiply a type’s scoring cost (a patch exploit re-run, an evidence scan) by flooding `verify_goal` with values the check never reads.

#### Methods

assurance_for  
The assurance label for this specific goal (default: the type’s label).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/engine.py#L136)

``` python
def assurance_for(self, goal: GoalBase) -> Assurance
```

`goal` [GoalBase](../reference/inspect_ranges.html.md#goalbase)  

setup  
Plant per-sample material; returns plant-store keys for unwind (default: nothing).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/engine.py#L140)

``` python
async def setup(self, goal: GoalBase, oracle: "RangeOracle") -> list[str]
```

`goal` [GoalBase](../reference/inspect_ranges.html.md#goalbase)  

`oracle` [RangeOracle](../reference/inspect_ranges.html.md#rangeoracle)  

check  
Gather raw observations; never sends an expected value guest-ward.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/engine.py#L144)

``` python
@abstractmethod
async def check(
    self, goal: GoalBase, oracle: "RangeOracle", submissions: "Submissions"
) -> Observations
```

`goal` [GoalBase](../reference/inspect_ranges.html.md#goalbase)  

`oracle` [RangeOracle](../reference/inspect_ranges.html.md#rangeoracle)  

`submissions` Submissions  

compare  
Pure, host-side verdict over the observations and the plant record.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/engine.py#L150)

``` python
@abstractmethod
def compare(
    self, goal: GoalBase, obs: Observations, store: "PlantStore"
) -> GoalResult
```

`goal` [GoalBase](../reference/inspect_ranges.html.md#goalbase)  

`obs` [Observations](../reference/inspect_ranges.html.md#observations)  

`store` PlantStore  

### GoalResult

One goal’s verdict, produced host-side by `compare` (or by the scorer on a failed check).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/engine.py#L85)

``` python
class GoalResult(BaseModel)
```

#### Attributes

`achieved` bool  
The proof contract was satisfied.

`partial` float \| None  
Partial credit in \[0, 1\] for types that declare a measure; `None` means binary.

`corroborated` bool \| None  
Outside evidence confirmed the result (`None`: no corroborating observer declared).

`indeterminate` bool  
The check could not run; the sample’s validity reflects it (never agent failure).

`reason` str \| None  
Value-free diagnostic (operation names and codes only, never plant material).

### register_goal_type

Register a goal type under its name(s); duplicate names refuse.

Registration opens both ends for the type: the engine dispatches scoring to it, and `challenges.yaml` parsing dispatches its YAML `type` name(s) to its `spec` class. Registration must therefore run before any challenges file naming the type parses: under inspect, register from an `inspect_ai` entry-point module (the mechanism `inspect_ranges` uses for its own built-ins, imported in every inspect process); a plain `load_challenges`/`validate_challenges` caller outside inspect must import the registering module first, or the type’s name refuses as unknown.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/engine.py#L160)

``` python
def register_goal_type(
    goal_type: GoalType, *, names: tuple[str, ...] | None = None
) -> None
```

`goal_type` [GoalType](../reference/inspect_ranges.html.md#goaltype)  
The stateless type instance.

`names` tuple\[str, ...\] \| None  
Registry names; defaults to `(goal_type.name,)`. `control`/`privilege` share one implementation under two names.

### register_exploit

Register a reference exploit chain for `patch` scoring under `name`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/observedtypes.py#L713)

``` python
def register_exploit(name: str, script: str) -> None
```

`name` str  

`script` str  

### RangeOracle

Privileged access to one sample’s range for setup and scoring. Not a [SandboxEnvironment](https://inspect.aisi.org.uk/reference/inspect_ai.util.html#sandboxenvironment).

Obtain one with [range_oracle()](../reference/inspect_ranges.html.md#range_oracle) from setup or scoring code running in the sample context, or attach out of band to a running `up` project with `with range_oracle("<project>") as oracle:`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L87)

``` python
class RangeOracle
```

#### Attributes

`store` PlantStore  
The sample’s plant record: values in memory, digests at T1.

`project` str  
The sample’s compose project name (how the prober addresses the probe sidecar).

`channel` [MessageChannel](../reference/host.html.md#messagechannel)  
The sample’s raw channel (the telemetry poller polls through it; same residue rules as every oracle verb).

#### Methods

evidence_session  
The sample’s evidence session (producer registration, driver stream appends); `None` when evidence is unavailable.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L118)

``` python
def evidence_session(self) -> "EvidenceSession | None"
```

nonce  
A fresh per-call secret from independent entropy, never derived from any recorded seed.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L122)

``` python
def nonce(self) -> str
```

available_observers  
The trusted observers this sample’s deployment can supply right now.

`evidence-sink` exists when the evidence session is live; `segment-pcap` and `console` when capture was rendered into the range; `active-prober` when the plan carries rendered probe endpoints. `telemetry-collector` is deployment knowledge the oracle cannot see (which collector specs exist), so `challenge_setup` supplies it as an extra observer to `run_setup` when a matching spec was passed; a challenge requiring an observer absent from the union refuses at planting.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L126)

``` python
def available_observers(self) -> frozenset[str]
```

resolved  
The sample’s resolved plan (per-guest address and CID allocations; see `guest_segment_ip`). Variables never ride the plan: `answer` goals read declared defaults from `range_spec()`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L142)

``` python
def resolved(self) -> ResolvedPlan
```

range_spec  
The sample’s validated range spec: declared variables (defaults until draws land) and scenario content.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L148)

``` python
def range_spec(self) -> RangeSpec
```

is_windows  
Whether `guest` runs Windows, from the sample’s resolved plan; a plan-less handle (unit fixtures) treats every guest as linux.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L156)

``` python
def is_windows(self, guest: str) -> bool
```

`guest` str  

exec  
Run `cmd` (argv, never an implicit shell) in `guest` over the raw channel.

`cmd` must never carry plant material: values travel as `write_file` bulk or `read_file` replies only. `env` is the Windows path-carrying contract (fixed script literals read `IR_PLANT_*` from it); it must never carry plant material either.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L163)

``` python
async def exec(
    self,
    guest: str,
    cmd: list[str],
    *,
    user: str | None = None,
    timeout_s: float | None = None,
    env: dict[str, str] | None = None,
) -> ExecOutcome
```

`guest` str  

`cmd` list\[str\]  

`user` str \| None  

`timeout_s` float \| None  

`env` dict\[str, str\] \| None  

read_file  
Read a guest file raw (a T3 read like any other; the cost rule applies to oracle reads too).

The daemon’s file plane reads as the daemon identity (the agent user), so privileged locations (a 0600 root plant, another principal’s file) need `user`: the read then rides the exec plane (`cat` with only the path in argv; the content returns as reply bulk, the same privacy class as a file read).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L186)

``` python
async def read_file(
    self,
    guest: str,
    path: str,
    *,
    cap: int = DEFAULT_BULK_CAP,
    user: str | None = None,
) -> bytes
```

`guest` str  

`path` str  

`cap` int  

`user` str \| None  

write_file  
Write a guest file with `mode` applied from the first byte; `owner` sets the principal.

Without `owner`, this is the daemon’s file plane (mode pinned atomically with the write, daemon identity, so the path must be daemon-writable; the Windows daemon ignores `mode` by design — NTFS has ACLs, not permission bits). With `owner`, the write rides the exec plane: on Linux as root into `umask 077 && cat` then `chmod`/`chown` by positional argument; on a Windows guest (dispatched from the sample’s plan) as the daemon’s SYSTEM identity into `WIN_PLANT_SCRIPT`, whose ACL grant (inheritance stripped, SYSTEM full + the principal read) is the mode analogue. Either way the value travels as exec stdin (request bulk, the same transport privacy as a file write and never argv or env). Any failure removes the file in the same script: a plant is never left behind under the wrong mode or principal.

On every failure path this frame scrubs `data` before raising, so a locals-rendered traceback (`INSPECT_TRACEBACK_LOCALS=1`) cannot carry plant bytes from here; lower channel frames are outside this guarantee, which is why that flag is forbidden on scoring runs.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L217)

``` python
async def write_file(
    self,
    guest: str,
    path: str,
    data: bytes,
    *,
    mode: int = 0o600,
    owner: str | None = None,
) -> None
```

`guest` str  

`path` str  

`data` bytes  

`mode` int  

`owner` str \| None  

evidence_memo  
Memoize the evidence accessors for the duration of one scoring pass.

The evidence record is immutable once written, so within a pass every accessor returns the same bytes; without the memo, scoring cost scales with the number of agent-submitted candidates (each candidate’s `check` refetches the capture), which hands the agent linear control over scoring cost through `verify_goal` calls. The memo is per-key (`pcap/<segment>`, `telemetry/<collector>`, …) and cleared when the outermost open exits. Reentrant: `challenge_scorer` opens one memo around the whole pass (so two goals on the same segment share one fetch), and `score_challenge`’s per-goal open nests inside it as a no-op; the poller never fetches evidence, setup runs before any evidence exists, and `corroborate()` deliberately bypasses the memo (its claim-scoped reads ride `stream_chunks` directly).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L290)

``` python
@contextmanager
def evidence_memo(self) -> "Generator[None]"
```

pcap  
The segment’s captured pcap chunks from the sample’s evidence record (host writer).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L316)

``` python
async def pcap(self, segment: str) -> list[bytes]
```

`segment` str  

telemetry  
The collector’s exported telemetry chunks (driver writer); query semantics arrive with the detection engine.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L328)

``` python
async def telemetry(self, collector: str) -> list[bytes]
```

`collector` str  

console  
The guest’s continuous serial-console chunks from the sample’s evidence record (host writer).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L340)

``` python
async def console(self, guest: str) -> list[bytes]
```

`guest` str  

probe_records  
The goal’s recorded probe verdicts (driver writer) plus whether the stream carries gaps.

A gap is an observation hole: the prober flushes `down` verdicts immediately, so a lost chunk is disproportionately likely to be the one carrying failures, and the prober types treat a gapped stream as indeterminate rather than trusting the survivors.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L352)

``` python
async def probe_records(self, goal_id: str) -> "tuple[list[SpannedRecord], bool]"
```

`goal_id` str  

telemetry_export  
The collector’s export for scoring: meta records, data chunks with spans (`None` spans mark the delivered-but-uncommitted tail), and the gap flag.

One manifest fetch serves both streams (the detection check runs per goal, possibly on a poller cadence, against a possibly remote store).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L367)

``` python
async def telemetry_export(
    self, collector: str
) -> "tuple[list[SpannedRecord], list[tuple[bytes, float | None, float | None]], bool]"
```

`collector` str  

### range_oracle

The range oracle: the current sample’s, or an out-of-band attach to a running project.

Without arguments, the current sample’s oracle, resolved through the default sandbox: call only from setup (`challenge_setup`) or scoring code running inside the sample context. The returned capability must never be exposed to the agent’s tool loop.

With a `project` name, a context manager attaching to a RUNNING range booted with `inspect-ranges up` (or `up --from-spec`), for poking at a range from a REPL or script: `with range_oracle("ir-dmz-pivot-...") as oracle:` yields the same oracle verbs (`exec`, `read_file`, `write_file`, …) over a transport rebuilt from the project’s recorded state (`state_dir` overrides the default project state directory). The attach is local-backend only and logs loudly, so an attach during a scoring run is visible in the run’s logs; leaving the context detaches the oracle, and later verbs refuse. An attached oracle carries no sample context: `resolved()`, `range_spec()`, and the evidence accessors refuse, and `is_windows` reads an empty plan, so the owner-flow `write_file` dispatches the POSIX script on every guest.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L415)

``` python
def range_oracle(
    project: str | None = None, *, state_dir: "Path | None" = None
) -> "RangeOracle | AbstractContextManager[RangeOracle]"
```

`project` str \| None  

`state_dir` Path \| None  

### OracleSetupError

A privileged setup operation failed; the message names the operation, never a value.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/oracle.py#L39)

``` python
class OracleSetupError(RuntimeError)
```

### Observations

Raw reads a `check` gathered; a guest read is attacker-authored in the worst case.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/engine.py#L70)

``` python
class Observations(BaseModel)
```

#### Attributes

`source` Literal\['submission', 'guest', 'evidence'\]  
Where the primary observation came from.

`reads` dict\[str, bytes\]  
Named raw observations; `compare` interprets them, never `check`.

`chunk_reads` dict\[str, list\[bytes\]\]  
Named chunked observations (evidence streams: each pcap chunk is a standalone capture file with its own header, so chunks must never be concatenated).

### ObserverKind

Trusted observers a goal type may require; a deployment that cannot supply one refuses the challenge at planning time. `guest-snapshot` is designed, not built, and currently refuses at validation.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L97)

``` python
ObserverKind = Literal[
    "evidence-sink",
    "segment-pcap",
    "telemetry-collector",
    "console",
    "active-prober",
    "guest-snapshot",
]
```

### source_bound_find

Whether any captured packet from `src` carries `value`.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/pcapscan.py#L19)

``` python
def source_bound_find(
    chunks: list[bytes],
    *,
    value: bytes,
    src: IPv4Address,
    exclude_src_mac_prefixes: tuple[bytes, ...] = (),
) -> bool
```

`chunks` list\[bytes\]  
Raw classic-pcap chunks (one capture file each, possibly truncated).

`value` bytes  
The bytes to find in a packet from `src`.

`src` IPv4Address  
The required IPv4 source address (the claimed guest’s interface).

`exclude_src_mac_prefixes` tuple\[bytes, ...\]  
Ethernet source-MAC prefixes whose frames never count, regardless of IP source. `corroborate()` passes the declared probe convention (`02:50:`) so probe-sourced flows are excluded from agent-traffic reasoning by spec, not heuristics (`challenges-v1.md`).

### guest_segment_ip

The guest’s interface address ON the declared segment.

Source binding must watch the right NIC of a multi-homed guest; the declared segment picks it.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/netident.py#L16)

``` python
def guest_segment_ip(plan: ResolvedPlan, guest: str, segment: str) -> IPv4Address
```

`plan` ResolvedPlan  

`guest` str  

`segment` str  

### PROBE_MAC_PREFIX

The declared probe-endpoint MAC convention (`02:50:`, the prober spike): frames with this source MAC are excluded from agent-traffic reasoning by spec, in EVERY scan. Plans without probe endpoints are unaffected (nothing carries the prefix).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/netident.py#L12)

``` python
PROBE_MAC_PREFIX = b"\x02\x50"
```

### load_collectors

Parse a `collectors.yaml` into collector specs.

The file binds a `detection` or `evade` goal’s `collector` name to a real export (poll mechanics are deployment knowledge the challenge schema deliberately does not carry); pass the result to `challenge_setup(telemetry_collectors=...)`. A malformed declaration refuses with the validation detail: a silently dropped collector would turn a detection goal’s observer gate into an infra riddle.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_evidence/telemetry.py#L111)

``` python
def load_collectors(path: "Path") -> list[CollectorSpec]
```

`path` Path  
The `collectors.yaml` path (beside the range’s `challenges.yaml` by convention).

## Challenge Loading

### load_challenges

Load and validate a `challenges.yaml` file.

Custom goal types parse only when their `register_goal_type` registration has already run in this process. Under inspect the `inspect_ai` entry-point mechanism imports registering modules before any parsing; a plain call outside inspect must import the registering module first, or the custom `type` name refuses as unknown (an `unknown-goal-type` error listing the known names, never a misparse).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L968)

``` python
def load_challenges(path: Path) -> Challenges
```

`path` Path  
Path to the YAML file.

### validate_challenges

Validate a `challenges.yaml` file, reporting every detectable issue at once.

Like `validate_range`, this never raises on invalid content: unreadable files (a directory, permissions, non-UTF-8 content), YAML syntax errors, structural schema violations, and (when a range is supplied) cross-reference problems all become [Issue](../reference/types.html.md#issue) entries with stable codes and source positions.

Custom goal types validate only when their `register_goal_type` registration has already run in this process (see `load_challenges`); an unregistered custom `type` name reports `unknown-goal-type` with the known-name listing, never a misparse.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/_challenges/schema.py#L990)

``` python
def validate_challenges(
    path: Path, range_spec: RangeSpec | Path | None = None
) -> ValidationReport
```

`path` Path  
Path to the challenges YAML file.

`range_spec` [RangeSpec](../reference/types.html.md#rangespec) \| Path \| None  
The range to cross-reference against: a validated spec, or a `range.yaml` path to load. Omitted means structural validation only. An invalid range file becomes a `range-invalid` issue (cross-reference checks skipped), never a raise.

## Range Loading

### load_range

Load and validate a `range.yaml` file.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/schema.py#L199)

``` python
def load_range(path: Path) -> RangeSpec
```

`path` Path  
Path to the YAML file.

### validate_range

Validate a `range.yaml` file, reporting every detectable issue at once.

Unlike `load_range`, this never raises on invalid content: unreadable files (a directory, permissions, non-UTF-8 content), YAML syntax errors, structural schema violations, and semantic cross-reference problems all become [Issue](../reference/types.html.md#issue) entries with stable codes, source positions, and hints where available. Field-level structural errors suppress the cross-reference pass (reflected in `ValidationReport.semantic_checked`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/schema.py#L135)

``` python
def validate_range(path: Path) -> ValidationReport
```

`path` Path  
Path to the YAML file.

### revalidate_range

Re-run full validation on a possibly mutated spec, returning a validated copy.

Spec models are mutable for flexible programmatic construction, so validity at construction is a point-in-time property. Consumer boundaries (the sandbox provider, the compiler) call this at handoff: the spec round-trips through `model_validate`, which catches semantic drift and type-unsafe mutations alike.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/schema.py#L222)

``` python
def revalidate_range(spec: RangeSpec) -> RangeSpec
```

`spec` [RangeSpec](../reference/types.html.md#rangespec)  
The spec to re-check (typically one received as sandbox configuration).

## Checks and Schema

### semantic_issues

Run every cross-reference check on a structurally valid spec, collecting all findings.

This is the single implementation of the semantic checks: [RangeSpec](../reference/types.html.md#rangespec) validation calls it (raising if any issue is found, so a freshly constructed spec is always consistent), and `validate_range` calls it via that same validation to report every issue at once.

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/types.py#L1101)

``` python
def semantic_issues(spec: RangeSpec) -> list[Issue]
```

`spec` [RangeSpec](../reference/types.html.md#rangespec)  
A structurally valid range definition.

### range_json_schema

Return the JSON Schema for `range.yaml` v0.1 (aliased field names, e.g. `from`).

[Source](https://github.com/meridianlabs-ai/inspect_ranges/blob/656bb65fb796861d1fef89d28820232e6e0b7141/src/inspect_ranges/schema.py#L239)

``` python
def range_json_schema() -> dict[str, Any]
```
