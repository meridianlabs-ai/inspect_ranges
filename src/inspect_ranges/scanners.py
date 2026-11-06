"""Scanners checking that the range apparatus itself behaved, built on `inspect_scout`.

`range_apparatus` is a deterministic "is my range working" checker for range developers: it reads a sample's transcript (events, messages, metadata) and reports concrete anomaly signatures mined from the real provider, channel, and challenges code: post-readiness plumbing failures, spec-contradicting reachability, `verify_goal` wiring trouble, and scoring/evidence integrity flags. Zero findings is the healthy state; every detector fires only on a concrete signature, deduped per sample.

Use it after the fact over eval logs (`inspect_scout.scan` or `scout scan`), or online by putting it directly in a task's scorer list, where it runs as samples land and shows beside `challenge_scorer` in the normal log view. Samples produced by `challenge_dataset(range_spec=...)` carry the range definition in their metadata, which is where the config-aware detectors read it; samples without it leave those detectors quiet. Cross-scorer ordering is not a contract: when it scores before `challenge_scorer`, the scoring-integrity detectors stay quiet for that sample and the after-the-fact scan still sees everything.
"""

from typing import Any, cast

import yaml
from inspect_ai.model import Model
from inspect_ai.scorer import mean
from inspect_scout import (
    AnswerStructured,
    Reference,
    Result,
    Scanner,
    Transcript,
    llm_scanner,
    scanner,
)

from ._metadata import RANGE_SPEC_METADATA_KEY
from ._scanners.engine import apparatus_findings
from ._scanners.friction import QUESTION, FrictionReport
from .schema import substitute_variables
from .types import RangeSpec

__all__ = ["range_apparatus", "range_friction"]


def _spec_from_yaml_text(text: str) -> RangeSpec | None:
    """A validated spec from metadata-carried YAML text, or `None` when the text does not parse (a finding about the apparatus must never come from the scanner failing, so unparseable metadata disarms the config-aware detectors instead of raising)."""
    try:
        data: Any = yaml.safe_load(text)
        if not isinstance(data, dict):
            return None
        data, reference_issues = substitute_variables(data)
        if reference_issues:
            return None
        return RangeSpec.model_validate(data)
    except Exception:
        return None


@scanner(messages="all", events="all", metadata=True, metrics=[mean()])
def range_apparatus() -> Scanner[Transcript]:
    """Scan a sample's transcript for range-apparatus anomalies.

    The result value is the finding count (0 is healthy; the `mean()` metric reads as mean findings per sample, with no accuracy semantics). The explanation carries one line per finding with its remediation hint, the metadata carries the structured findings (stable detector id, severity, message, hint), and references point at the events each finding keys on.

    Detector families: PLUMBING (post-readiness channel/transport failures, repeated retries against one guest, evidence finalize/teardown errors, the in-guest tool's rc 124/125 contract), CONFIG-AWARE REACHABILITY (reading the range definition from the sample metadata `challenge_dataset(range_spec=...)` writes: connectivity failures toward addresses the spec declares reachable from the foothold under its ACLs, and attempts toward private addresses no declared network holds), VERIFY_GOAL BEHAVIOR (zero recorded submissions, submissions binding to no goal, dropped candidates, completion claims over unattempted goals), and SCORING/EVIDENCE INTEGRITY (recorded validity other than `valid`, corroboration flags, the all-segment-goals-uncorroborated hint).


    Returns:
        The scanner; pass it to `inspect_scout.scan` over eval logs, or put it directly in a task's scorer list.
    """

    async def scan(transcript: Transcript) -> Result:
        raw_metadata = transcript.metadata.get("sample_metadata")
        sample_metadata = (
            cast("dict[str, Any]", raw_metadata)
            if isinstance(raw_metadata, dict)
            else None
        )
        sample_spec = None
        if sample_metadata is not None:
            spec_text = sample_metadata.get(RANGE_SPEC_METADATA_KEY)
            if isinstance(spec_text, str):
                sample_spec = _spec_from_yaml_text(spec_text)
        findings = apparatus_findings(
            transcript.events, transcript.messages, sample_metadata, sample_spec
        )
        if not findings:
            return Result(value=0, explanation="no findings")
        explanation = "\n".join(
            f"[{finding.severity}] {finding.detector}: {finding.message} "
            f"(hint: {finding.hint})"
            for finding in findings
        )
        references = [
            Reference(type="event", id=uuid)
            for finding in findings
            for uuid in finding.references
        ]
        return Result(
            value=len(findings),
            explanation=explanation,
            metadata={
                "findings": [finding.model_dump(mode="json") for finding in findings]
            },
            references=references,
        )

    return scan


@scanner(messages="all", metadata=True)
def range_friction(model: str | Model | None = None) -> Scanner[Transcript]:
    """Read a sample's transcript for evidence that the range contradicted its own brief.

    The companion to `range_apparatus`, and the half that needs a model. `range_apparatus` matches exact machine signatures and is blind to a defect that exists only as prose: a file the brief promised and the agent could not find, a credential that did not authenticate, a terminal that swallowed output, scoring scaffolding the agent tripped over. Those appear in the transcript as the agent saying so.

    The result value carries the findings (`{"findings": [...]}`), each with a category, a confidence, a verbatim quote and the `[M12]` marker it came from. An empty list is the healthy answer and the expected one for most transcripts, including most that scored zero: the prompt separates "the environment broke its promises" from "the task was hard and the agent failed", and only the former is a finding.

    Costs a model call per transcript, so this is an after-the-fact audit over eval logs (`inspect_scout.scan` or `scout scan`) rather than something to put in a scorer list.

    Args:
        model: Model to read with. Defaults to the scan's model.

    Returns:
        The scanner.
    """
    return llm_scanner(
        question=QUESTION,
        answer=AnswerStructured(FrictionReport),
        model=model,
    )
