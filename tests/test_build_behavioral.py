"""The behavioral runner's own logic (SUBMIT parsing, trio expectations), no VMs (round-1 review: the enforcement of the trio contract had zero unit coverage and two vacuous-pass shapes hid in it)."""

import asyncio
import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest
from inspect_ranges._build.behavioral import _SUBMIT, _execute_and_score
from inspect_ranges._channel.channel import (  # pyright: ignore[reportPrivateUsage]
    _StoredReply,
)
from inspect_ranges._channel.protocol import ExecRequest

from tests.test_challenges_oracle import RecordingEndpoint


@dataclass
class FakeOutcome:
    rc: int = 0
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_truncated: bool = False


@dataclass
class FakeOracle:
    outcome: FakeOutcome
    execs: list[list[str]] = field(default_factory=list[list[str]])

    async def exec(self, guest: str, argv: list[str], **_: Any) -> FakeOutcome:
        self.execs.append(argv)
        return self.outcome


def run_check(
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    outcome: FakeOutcome,
    value: float = 0.0,
    validity: str = "valid",
    goals: "list[Any] | None" = None,
    goals_meta: "dict[str, dict[str, Any]] | None" = None,
    challenge: Any = None,
    scored_goal_ids: "list[str] | None" = None,
) -> Any:
    import inspect_ranges._challenges.scorer as scorer_module
    from inspect_ai.util._store import Store

    async def fake_score(*args: Any, **kwargs: Any) -> tuple[float, dict[str, Any]]:
        if scored_goal_ids is not None:
            scored_goal_ids.extend(goal.id for goal in args[2].goals)
        return value, {"validity": validity, "goals": goals_meta or {}}

    monkeypatch.setattr(scorer_module, "score_challenge", fake_score)
    monkeypatch.setattr(
        "inspect_ranges._build.behavioral.asyncio",
        SimpleNamespace(sleep=fake_sleep, run=asyncio.run),
    )
    if challenge is None:
        challenge = SimpleNamespace(id="demo", goals=goals or [])
    return asyncio.run(
        _execute_and_score(
            FakeOracle(outcome),  # type: ignore[arg-type]
            challenge,
            name,
            "echo chain",
            "attacker",
            "10.0.0.9",
            Store(),
        )
    )


async def fake_sleep(_: float) -> None:
    return None


def test_submit_regex_tolerates_whitespace_runs() -> None:
    """Round-1: tabs and double spaces silently dropped submissions."""
    for line in ("SUBMIT g v", "SUBMIT  g  v", "SUBMIT\tg\tv"):
        match = _SUBMIT.match(line)
        assert match is not None and match.group(1) == "g" and match.group(2) == "v"


def test_reference_requires_full_valid_score(monkeypatch: pytest.MonkeyPatch) -> None:
    good = FakeOutcome(stdout=b"SUBMIT g tok\n")
    assert (
        run_check(monkeypatch, name="reference", outcome=good, value=1.0).status
        == "pass"
    )
    assert (
        run_check(
            monkeypatch,
            name="reference",
            outcome=good,
            value=1.0,
            validity="indeterminate",
        ).status
        == "fail"
    )
    assert (
        run_check(monkeypatch, name="reference", outcome=good, value=0.5).status
        == "fail"
    )


def test_negative_checks_cannot_pass_vacuously(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round-1: 0.0 via an indeterminate scorer, or via zero submissions, proved nothing about the forgery."""
    submitted = FakeOutcome(stdout=b"SUBMIT g forged-tok\n")
    assert run_check(monkeypatch, name="forged", outcome=submitted).status == "pass"
    assert (
        run_check(
            monkeypatch, name="forged", outcome=submitted, validity="indeterminate"
        ).status
        == "fail"
    )
    empty = FakeOutcome(stdout=b"the chain ran but emitted nothing\n")
    assert run_check(monkeypatch, name="insufficient", outcome=empty).status == "fail"
    truncated = FakeOutcome(stdout=b"SUBMIT g tok\n", stdout_truncated=True)
    assert run_check(monkeypatch, name="forged", outcome=truncated).status == "fail"
    nonzero = FakeOutcome(rc=1, stderr=b"boom")
    assert run_check(monkeypatch, name="forged", outcome=nonzero).status == "fail"


_JUDGE_GOAL: dict[str, Any] = {
    "id": "telemetry-report",
    "type": "judge",
    "rubric": "grade the report",
    "weight": 0.25,
}
_FLAG_GOAL: dict[str, Any] = {
    "id": "token",
    "type": "flag",
    "host": "web",
    "path": "/root/flag",
}
_DETECTION_GOAL: dict[str, Any] = {
    "id": "detected",
    "type": "detection",
    "collector": "splunk",
    "signal": "needle",
}


def _schema_challenge(goals: "list[dict[str, Any]]") -> Any:
    """A real schema `Challenge`: the exemption classifies goals through the type registry, so these tests parse real goal specs."""
    from inspect_ranges._challenges.registration import (
        ensure_goal_type_registrations,
    )
    from inspect_ranges._challenges.schema import Challenge

    ensure_goal_type_registrations()
    return Challenge.model_validate({"id": "demo", "prompt": "p", "goals": goals})


@pytest.mark.parametrize(
    ("name", "goals", "stdout", "value", "expected"),
    [
        # reference passes at 1.0 over the non-judge share
        ("reference", [_FLAG_GOAL, _JUDGE_GOAL], b"SUBMIT token tok\n", 1.0, "pass"),
        # a partially achieved non-judge share still fails reference
        ("reference", [_FLAG_GOAL, _JUDGE_GOAL], b"SUBMIT token tok\n", 0.5, "fail"),
        # the one-submission floor reads the scored share: an observation-only
        # trio stays floor-free when its judge goal is exempted
        ("insufficient", [_DETECTION_GOAL, _JUDGE_GOAL], b"quiet\n", 0.0, "pass"),
        # a submission-consuming provable share keeps the strict floor
        ("forged", [_FLAG_GOAL, _JUDGE_GOAL], b"nothing submitted\n", 0.0, "fail"),
    ],
)
def test_trio_exempts_model_graded_goals(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    goals: "list[dict[str, Any]]",
    stdout: bytes,
    value: float,
    expected: str,
) -> None:
    """judge-at-build.md: the trio scores the challenge over its non-model-graded goals and records the exemption in the check detail."""
    scored_goal_ids: list[str] = []
    record = run_check(
        monkeypatch,
        name=name,
        outcome=FakeOutcome(stdout=stdout),
        value=value,
        challenge=_schema_challenge(goals),
        scored_goal_ids=scored_goal_ids,
    )
    assert record.status == expected
    assert "telemetry-report" not in scored_goal_ids
    assert len(scored_goal_ids) == 1
    assert "judge-exempt=telemetry-report" in record.detail


def test_judge_only_challenge_refuses_challenge_not_provable(
    tmp_path: pathlib.Path,
) -> None:
    """judge-at-build.md: a challenge whose goals are all model-graded has no provable share, so a complete conformance tree still refuses before any chain runs; a mixed challenge validates."""
    from inspect_ranges._build.behavioral import validate_conformance
    from inspect_ranges._build.errors import BuildError
    from inspect_ranges._challenges.registration import (
        ensure_goal_type_registrations,
    )
    from inspect_ranges._challenges.schema import Challenges

    ensure_goal_type_registrations()
    check_dir = tmp_path / "conformance" / "demo"
    check_dir.mkdir(parents=True)
    for script in ("reference", "insufficient", "forged"):
        (check_dir / f"{script}.sh").write_text("true\n")
    judge_only = Challenges.model_validate(
        {"challenges": [{"id": "demo", "prompt": "p", "goals": [_JUDGE_GOAL]}]}
    )
    with pytest.raises(BuildError, match="challenge-not-provable"):
        validate_conformance(judge_only, tmp_path)
    mixed = Challenges.model_validate(
        {
            "challenges": [
                {"id": "demo", "prompt": "p", "goals": [_FLAG_GOAL, _JUDGE_GOAL]}
            ]
        }
    )
    validate_conformance(mixed, tmp_path)


def test_retired_checks_layout_refuses(tmp_path: pathlib.Path) -> None:
    """A directory still using the retired `checks/` layout refuses with the rename hint, even when challenges.yaml is missing: a layout this code no longer reads must never build silently unproven."""
    from inspect_ranges._build.behavioral import conformance_root, proofs_declared
    from inspect_ranges._build.errors import BuildError

    (tmp_path / "checks" / "demo").mkdir(parents=True)
    with pytest.raises(BuildError, match="git mv checks conformance"):
        conformance_root(tmp_path)
    with pytest.raises(BuildError, match="retired checks/ layout"):
        proofs_declared(tmp_path)


def test_digest_is_root_name_invariant(tmp_path: pathlib.Path) -> None:
    """The digest hashes paths relative to the tree root, so a `checks_sha256` recorded over `checks/` matches the identical tree under `conformance/`: the rename invalidates no build caches."""
    from inspect_ranges._build.behavioral import (
        _tree_digest,  # pyright: ignore[reportPrivateUsage]
    )

    (tmp_path / "challenges.yaml").write_text("challenges: []\n")
    digests: list[str] = []
    for root_name in ("checks", "conformance"):
        root = tmp_path / root_name
        (root / "demo").mkdir(parents=True)
        (root / "demo" / "reference.sh").write_text("true\n")
        digests.append(_tree_digest(tmp_path, root))
    assert digests[0] == digests[1]


def test_digest_covers_prove_scripts(tmp_path: pathlib.Path) -> None:
    """An authored or edited prove script must invalidate the build's cached fast path exactly like an edited trio chain."""
    from inspect_ranges._build.behavioral import checks_digest

    (tmp_path / "challenges.yaml").write_text("challenges: []\n")
    demo = tmp_path / "conformance" / "demo"
    demo.mkdir(parents=True)
    script = demo / "prove_flow.py"
    script.write_text("async def prove(ctx): ...\n")
    before = checks_digest(tmp_path)
    script.write_text("async def prove(ctx):\n    pass\n")
    assert checks_digest(tmp_path) != before


def test_validate_conformance_trio_or_prove_scripts(tmp_path: pathlib.Path) -> None:
    """The unified completeness rule: a challenge directory needs the full trio, at least one prove script, or both; a partial trio refuses, a `.py` without a top-level `prove` refuses by AST, and an unparseable `.py` refuses."""
    from inspect_ranges._build.behavioral import validate_conformance
    from inspect_ranges._build.errors import BuildError
    from inspect_ranges._challenges.registration import (
        ensure_goal_type_registrations,
    )
    from inspect_ranges._challenges.schema import Challenges

    ensure_goal_type_registrations()
    challenges = Challenges.model_validate(
        {"challenges": [{"id": "demo", "prompt": "p", "goals": [_FLAG_GOAL]}]}
    )
    demo = tmp_path / "conformance" / "demo"
    demo.mkdir(parents=True)
    with pytest.raises(BuildError, match="neither the behavioral trio nor"):
        validate_conformance(challenges, tmp_path)
    (demo / "prove_flow.py").write_text("def prove(ctx):\n    pass\n")
    with pytest.raises(BuildError, match="no top-level `async def prove`"):
        validate_conformance(challenges, tmp_path)
    (demo / "prove_flow.py").write_text("async def prove(ctx):\n    pass\n")
    validate_conformance(challenges, tmp_path)  # a prove script alone is complete
    (demo / "reference.sh").write_text("true\n")
    with pytest.raises(BuildError, match="all-or-nothing"):
        validate_conformance(challenges, tmp_path)
    for script in ("insufficient", "forged"):
        (demo / f"{script}.sh").write_text("true\n")
    validate_conformance(challenges, tmp_path)  # trio and scripts coexist
    (demo / "broken.py").write_text("def prove(:\n")
    with pytest.raises(BuildError, match="does not parse"):
        validate_conformance(challenges, tmp_path)
    # a stray file at the root would digest without ever running: refuse
    (tmp_path / "conformance" / "exfil_prove.py").write_text(
        "async def prove(ctx):\n    pass\n"
    )
    with pytest.raises(BuildError, match="not a challenge directory"):
        validate_conformance(challenges, tmp_path)


def test_reference_requires_corroborated_beacon_goals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parked-decisions item 6: a goal that declares a beacon must land it in capture; a 1.0/valid score with an uncorroborated beacon fails the reference check."""
    beacon_goal = SimpleNamespace(id="execute-web", beacon_segment="lab")
    plain_goal = SimpleNamespace(id="answer-q", beacon_segment=None)
    good = FakeOutcome(stdout=b"SUBMIT execute-web tok\n")
    passing = run_check(
        monkeypatch,
        name="reference",
        outcome=good,
        value=1.0,
        goals=[beacon_goal, plain_goal],
        goals_meta={"execute-web": {"corroborated": True}, "answer-q": {}},
    )
    assert passing.status == "pass"
    failing = run_check(
        monkeypatch,
        name="reference",
        outcome=good,
        value=1.0,
        goals=[beacon_goal, plain_goal],
        goals_meta={"execute-web": {"corroborated": False}, "answer-q": {}},
    )
    assert failing.status == "fail"
    assert "uncorroborated=execute-web" in failing.detail


def _section6_spec() -> Any:
    """A dedicated attacker multi-homed on `lab` (shared with `web`, range-served DNS) and `mgmt` (attacker-only, no reservation)."""
    from inspect_ranges.types import (
        Attacker,
        DnsConfig,
        DnsRecord,
        Host,
        Interface,
        Network,
        Os,
        RangeMeta,
        RangeSpec,
    )

    return RangeSpec(
        meta=RangeMeta(name="conf", description="conformance targets"),
        networks=[
            Network(
                name="lab",
                cidr="10.44.0.0/24",
                mode="isolated",
                dns=DnsConfig(records=[DnsRecord(name="web")]),
            ),
            Network(name="mgmt", cidr="10.45.0.0/24", mode="isolated"),
        ],
        hosts=[
            Host(
                name="web",
                os=Os(type="linux"),
                image="tiny-golden",
                interfaces=[Interface(network="lab", ip="10.44.0.10")],
            )
        ],
        attacker=Attacker(
            image="tiny-golden",
            interfaces=[
                Interface(network="lab"),
                Interface(network="mgmt", ip="10.45.0.9"),
            ],
            entry="external",
        ),
    )


def test_conformance_plan_resolves_the_section6_targets() -> None:
    """Issue #6: the pure resolution picks a shared-segment defender, the attacker's SHARED-SEGMENT addresses only (round-3 B2: a non-shared address would only measure the segment's drop policy), the reserved hypervisor endpoints with their allowed ports, and the silent candidates."""
    from inspect_ranges._build.behavioral import conformance_plan
    from inspect_ranges._compiler import resolve_plan

    spec = _section6_spec()
    plan = resolve_plan(spec)
    defender, attacker_ips, hypervisor, silent = conformance_plan(spec, plan)
    assert defender == "web"
    # only the lab address: web does not share mgmt, so 10.45.0.9 is excluded
    assert len(attacker_ips) == 1 and attacker_ips[0].startswith("10.44.0.")
    # range-served DNS reserves the bridge address, allowed to answer port 53
    address, allowed = hypervisor["lab"]
    assert allowed == {53}
    assert address.startswith("10.44.0.")
    # mgmt has no reservation: its conventional gateway candidates must be silent
    assert any(candidate.startswith("10.45.0.") for candidate in silent)
    assigned = set(attacker_ips) | {"10.44.0.10", "10.45.0.9"}
    assert all(candidate not in assigned for candidate in silent)


def test_conformance_plan_is_empty_for_foothold_ranges() -> None:
    """N1 (round-3): a foothold range has no dedicated attack box; the plan must be empty rather than StopIteration, and the executor must skip cleanly."""
    from inspect_ranges._build.behavioral import (
        conformance_plan,
        run_conformance_checks,
    )
    from inspect_ranges._compiler import resolve_plan
    from inspect_ranges.types import (
        Attacker,
        Host,
        Interface,
        Network,
        Os,
        RangeMeta,
        RangeSpec,
    )

    spec = RangeSpec(
        meta=RangeMeta(name="foothold", description="assumed breach"),
        networks=[Network(name="lab", cidr="10.44.0.0/24", mode="isolated")],
        hosts=[
            Host(
                name="web",
                os=Os(type="linux"),
                image="tiny-golden",
                interfaces=[Interface(network="lab", ip="10.44.0.10")],
            )
        ],
        attacker=Attacker(host="web", entry="assumed-breach"),
    )
    plan = resolve_plan(spec)
    assert conformance_plan(spec, plan) == (None, [], {}, [])
    recorder = StageRecorder()
    # no channel is ever constructed: the skip happens before any exec
    asyncio.run(run_conformance_checks(spec, plan, {"web": 100}, stage_log=recorder))
    assert recorder.entries == [
        (
            "conformance",
            "ok",
            {
                "check": "attacker-surface",
                "detail": "foothold range: no dedicated attack box",
            },
        )
    ]


class StageRecorder:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, Any]]] = []

    def log(self, stage: str, status: str, **fields: Any) -> None:
        self.entries.append((stage, status, fields))


def _run_conformance(
    monkeypatch: pytest.MonkeyPatch,
    replies: "Callable[[str, str], str]",
) -> "tuple[StageRecorder, Exception | None]":
    """Run the section-6 executor against `_section6_spec` with a fake channel answering `(guest, script) -> stdout`."""
    from inspect_ranges._build.behavioral import run_conformance_checks
    from inspect_ranges._build.errors import BuildError
    from inspect_ranges._compiler import resolve_plan

    spec = _section6_spec()
    plan = resolve_plan(spec)

    class FakeChannel:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def exec(self, guest: str, request: Any, stdin: bytes) -> FakeOutcome:
            return FakeOutcome(stdout=replies(guest, request.cmd[2]).encode())

    monkeypatch.setattr("inspect_ranges._channel.channel.MessageChannel", FakeChannel)
    recorder = StageRecorder()
    cids = {guest.name: 100 + index for index, guest in enumerate(plan.guests)}
    error: Exception | None = None
    try:
        asyncio.run(run_conformance_checks(spec, plan, cids, stage_log=recorder))
    except BuildError as raised:
        error = raised
    return recorder, error


def test_conformance_executor_passes_on_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder, error = _run_conformance(monkeypatch, lambda guest, script: "")
    assert error is None
    assert [entry[1] for entry in recorder.entries] == ["ok"] * len(recorder.entries)
    assert {entry[2].get("check") for entry in recorder.entries} == {
        "attacker-surface",
        "hypervisor-endpoint",
        "segment-silence",
    }


def test_conformance_executor_refuses_and_logs_per_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hypervisor-endpoint finding refuses the build, and its stage line carries ONLY its own findings, not the earlier arms' (round-3 N2)."""

    def replies(guest: str, script: str) -> str:
        if guest == "web":
            return "OPEN 10.44.0.20 22\n"  # defender sees the attacker answer
        if "ALIVE" in script:
            return ""  # silence probe: quiet
        return "OPEN 10.44.0.1 80\n"  # hypervisor address answers beyond :53

    recorder, error = _run_conformance(monkeypatch, replies)
    assert error is not None and "conformance" in str(error)
    assert "10.44.0.20 22" in str(error) and "10.44.0.1 80" in str(error)
    by_check = {entry[2].get("check"): entry for entry in recorder.entries}
    hypervisor_entry = by_check["hypervisor-endpoint"]
    assert hypervisor_entry[1] == "fail"
    assert "10.44.0.1 80" in hypervisor_entry[2]["error"]
    assert "10.44.0.20" not in hypervisor_entry[2]["error"]
    assert by_check["segment-silence"][1] == "ok"


def test_sweep_and_silence_scripts_are_falsifiable() -> None:
    from inspect_ranges._build.behavioral import (
        CONFORMANCE_EXTRA_PORTS,
        silence_script,
        sweep_script,
    )

    script = sweep_script(["10.44.0.9"], allowed={53})
    assert "/dev/tcp/$ip/$p" in script
    # round-3 B2: every connect is bounded, or a drop-policy address costs the
    # kernel's ~130 s connect timeout per port and exhausts the exec budget
    assert "timeout 1" in script
    assert " 53 " not in f" {script.split('do for p in ', 1)[1].split(';')[0]} "
    assert str(CONFORMANCE_EXTRA_PORTS[0]) in script
    assert script.rstrip().endswith("exit 0")
    probe = silence_script(["10.44.0.1", "10.44.0.254"])
    assert 'echo "ALIVE $ip"' in probe
    assert "TCP53" in probe and "timeout 1" in probe


def test_attacker_guest_resolution_prefers_the_attack_box_then_the_foothold() -> None:
    """Chains exec on the dedicated attack box when one exists, else the foothold host (linux-examples-v1: foothold ranges have no attacker-kind guest)."""
    from types import SimpleNamespace

    from inspect_ranges._build.behavioral import _attacker_guest

    def guest(name: str, kind: str, ip: str) -> SimpleNamespace:
        return SimpleNamespace(
            name=name, kind=kind, interfaces=[SimpleNamespace(ip=ip)]
        )

    dedicated = SimpleNamespace(
        guests=[
            guest("web", "host", "10.0.0.5"),
            guest("attacker", "attacker", "10.0.0.9"),
        ]
    )
    spec = SimpleNamespace(attacker=SimpleNamespace(host=None))
    assert _attacker_guest(spec, dedicated) == ("attacker", "10.0.0.9")  # type: ignore[arg-type]

    foothold_plan = SimpleNamespace(
        guests=[
            guest("client", "host", "192.168.30.5"),
            guest("server", "host", "192.168.20.5"),
        ]
    )
    foothold_spec = SimpleNamespace(attacker=SimpleNamespace(host="client"))
    assert _attacker_guest(foothold_spec, foothold_plan) == (  # type: ignore[arg-type]
        "client",
        "192.168.30.5",
    )


def test_collectors_file_loads_and_feeds_the_checks_digest(
    tmp_path: pathlib.Path,
) -> None:
    """Windows-ad-v1 slice 5: collectors.yaml parses into CollectorSpecs (command and file sources, name grammar enforced) and participates in checks_digest — an edited export command must re-run the trio. The loader imports from `inspect_ranges` (its public export: the `challenge_setup(telemetry_collectors=...)` wiring needs it)."""
    from inspect_ranges import load_collectors
    from inspect_ranges._build.behavioral import checks_digest

    collectors_yaml = tmp_path / "collectors.yaml"
    collectors_yaml.write_text(
        """
collectors:
  - name: splunk
    guest: splunk
    poll_s: 2.0
    source:
      kind: command
      command: ["/opt/range/telemetry-export.sh", "{cursor}"]
      bootstrap: ["/opt/range/telemetry-export.sh"]
      cursor_pattern: '-- cursor: (\\d+)'
      user: root
  - name: endpoint-file
    guest: win
    source:
      kind: file
      path: C:/telemetry/export.log
"""
    )
    loaded = load_collectors(collectors_yaml)
    assert [spec.name for spec in loaded] == ["splunk", "endpoint-file"]
    assert loaded[0].source.kind == "command" and loaded[1].source.kind == "file"
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "collectors: [{name: 'Not Legal', guest: g, source: {kind: file, path: /x}}]"
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        load_collectors(bad)
    # digest coverage
    (tmp_path / "challenges.yaml").write_text("challenges: []\n")
    (tmp_path / "conformance").mkdir()
    before = checks_digest(tmp_path)
    collectors_yaml.write_text(collectors_yaml.read_text() + "# edited\n")
    assert checks_digest(tmp_path) != before


def test_probe_segments_for_checks_derives_the_dataset_segments() -> None:
    """The proof boot's bundle must render the same probe segments the provider derives per sample: the union over every challenge's prober-backed goals, empty when none exist."""
    from inspect_ranges._build.behavioral import probe_segments_for_checks
    from inspect_ranges._challenges.schema import Challenges

    spec = _section6_spec()
    cases: list[tuple[str, list[dict[str, Any]], tuple[str, ...]]] = [
        (
            "degrade-goal-first-interface",
            [
                {
                    "id": "svc",
                    "type": "degrade",
                    "host": "web",
                    "port": 80,
                    "window_s": 30,
                }
            ],
            ("lab",),
        ),
        (
            "no-prober-goals",
            [{"id": "f", "type": "flag", "host": "web", "path": "/tmp/f"}],
            (),
        ),
    ]
    for label, goals, expected in cases:
        challenges = Challenges.model_validate(
            {"challenges": [{"id": "c", "prompt": "p", "goals": goals}]}
        )
        assert probe_segments_for_checks(challenges, spec) == expected, label


class RootBashEndpoint(RecordingEndpoint):
    """Runs the behavioral chains' root bash execs as the current user: the CI endpoint cannot switch users, and the contract under test is the trio verdict, not the exec identity."""

    async def _run_command(self, request: ExecRequest, stdin: bytes) -> "_StoredReply":
        if request.user == "root" and request.cmd[:2] == ["bash", "-c"]:
            request = request.model_copy(update={"user": None})
        return await super()._run_command(request, stdin)


def test_prober_backed_trio_reads_valid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The per-check prober makes a prober-backed goal scoreable in the trio (the fix for the proof boot starting no prober): each check starts a prober over ITS challenge's derived targets, stops and flushes it before scoring, and scores only its own records. Running the three checks sequentially against the shared evidence stream is the contamination regression: without the per-check floor, the reference chain's genuine outage records would score the insufficient and forged chains' degrade goal as achieved too (degrade scans every fully-observed window), failing them (measured: dropping the floor fails `insufficient` at value=1.00)."""
    import inspect_ranges._challenges.prober as prober_module
    from inspect_ranges._build.behavioral import _run_one, _scoped_oracle_class
    from inspect_ranges._challenges.oracle import RangeOracle
    from inspect_ranges._challenges.schema import Challenge
    from inspect_ranges._channel.channel import LoopbackTransport, MessageChannel
    from inspect_ranges._compiler.plan import ResolvedPlan, Totals
    from inspect_ranges._provider.state import SampleHandle

    from tests.test_challenges_oracle import FakePlantSession

    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(
        "inspect_ranges._build.behavioral.time",
        SimpleNamespace(time=lambda: clock["now"]),
    )
    monkeypatch.setattr(
        "inspect_ranges._build.behavioral.asyncio",
        SimpleNamespace(sleep=fake_sleep, run=asyncio.run),
    )
    streams: dict[str, list[dict[str, object]]] = {}
    scripted_statuses: list[str] = []
    created: list[Any] = []

    class FakeProber:
        """Writes the scripted verdicts into the shared stream on stop, like the real prober's force-flush; walls land inside the running check's span."""

        def __init__(self, session: Any, project: str, targets: list[Any]) -> None:
            self.targets = targets
            self.stopped = False
            created.append(self)

        def start(self) -> None:
            pass

        async def stop(self, **_: Any) -> None:
            if self.stopped:
                return
            self.stopped = True
            for index, status in enumerate(scripted_statuses):
                for target in self.targets:
                    streams.setdefault(target.goal_id, []).append(
                        {
                            "goal": target.goal_id,
                            "status": status,
                            "wall": clock["now"] + 0.02 * (index + 1),
                        }
                    )

    monkeypatch.setattr(prober_module, "Prober", FakeProber)

    async def fake_probe_records(self: Any, goal_id: str) -> tuple[list[Any], bool]:
        def spanned(record: dict[str, object]) -> Any:
            wall = float(cast(float, record["wall"]))
            return SimpleNamespace(record=dict(record), wall=lambda wall=wall: wall)

        return [spanned(r) for r in streams.get(goal_id, [])], False

    monkeypatch.setattr(RangeOracle, "probe_records", fake_probe_records)

    challenge = Challenge.model_validate(
        {
            "id": "svc-outage",
            "prompt": "down the service",
            "goals": [
                {
                    "id": "svc",
                    "type": "degrade",
                    "host": "box",
                    "port": 8080,
                    "window_s": 0.05,
                }
            ],
        }
    )
    endpoint = RootBashEndpoint("box", tmp_path / "guest")
    transport = LoopbackTransport(guests=())
    transport.guests["box"] = endpoint
    plan = cast(
        ResolvedPlan,
        SimpleNamespace(
            requirements=SimpleNamespace(
                evidence_capture=False, probe_segments=("lab",)
            ),
            guests=[
                SimpleNamespace(
                    name="box",
                    os="linux",
                    interfaces=[SimpleNamespace(network="lab", ip="10.0.0.5")],
                )
            ],
        ),
    )
    handle = SampleHandle(
        project="ir-build-prober-test",
        task_name="build-prober",
        staging=tmp_path / "staging",
        totals=Totals(guests=1, cpus=1, memory_mb=1024),
        cid_base=10_000,
        guest_cids={"box": 10_000},
        channel=MessageChannel(transport, label="build-prober-test"),
        evidence=cast(Any, FakePlantSession()),
        plan=plan,
    )
    trio: list[tuple[str, list[str]]] = [
        ("reference", ["down", "down", "down", "down"]),
        ("insufficient", ["ok", "ok", "ok", "ok"]),
        ("forged", ["ok", "ok", "ok", "ok"]),
    ]
    for name, statuses in trio:
        clock["now"] += 100.0
        scripted_statuses[:] = statuses
        handle.plants = None
        oracle = _scoped_oracle_class()(handle)
        record = asyncio.run(
            _run_one(oracle, challenge, name, "true", "box", "10.0.0.5")
        )
        assert record.status == "pass", (name, record.detail)
        assert "validity=valid" in record.detail, (name, record.detail)
    assert len(created) == 3 and all(prober.stopped for prober in created)
    target = created[0].targets[0]
    assert (target.goal_id, target.ip, target.port, target.path) == (
        "svc",
        "10.0.0.5",
        8080,
        "/probe",
    )


@pytest.fixture()
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the test against a copy of the goal-type registry, like tests/test_challenges_custom_types.py."""
    import inspect_ai._util.registry as registry_module
    import inspect_ranges._challenges.engine as engine_module

    monkeypatch.setattr(
        registry_module,
        "_registry",
        dict(registry_module._registry),  # pyright: ignore[reportPrivateUsage]
    )
    monkeypatch.setattr(
        engine_module,
        "_REGISTERED",
        dict(engine_module._REGISTERED),  # pyright: ignore[reportPrivateUsage]
    )
    monkeypatch.setattr(
        engine_module,
        "_ALIASES",
        dict(engine_module._ALIASES),  # pyright: ignore[reportPrivateUsage]
    )
    import inspect_ai._util.entrypoints as entrypoints_module

    for flag in ("_inspect_ai_eps_loaded", "_inspect_ai_eps_loaded_all"):
        monkeypatch.setattr(entrypoints_module, flag, getattr(entrypoints_module, flag))


def _write_challenges(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    (tmp_path / "challenges.yaml").write_text(text)
    return tmp_path


def test_build_parse_accepts_registered_custom_type(
    isolated_registry: None, tmp_path: pathlib.Path
) -> None:
    """The build's parse entry point dispatches a registered custom `type:` name exactly like the eval path."""
    from inspect_ranges import register_goal_type
    from inspect_ranges._build.behavioral import load_challenges

    from tests.test_challenges_custom_types import MARKER_YAML, MarkerGoal, MarkerType

    register_goal_type(MarkerType())
    challenges = load_challenges(_write_challenges(tmp_path, MARKER_YAML))
    assert isinstance(challenges.challenges[0].goals[0], MarkerGoal)


def test_build_parse_refuses_unknown_type_with_known_names(
    isolated_registry: None, tmp_path: pathlib.Path
) -> None:
    """An unregistered name still refuses honestly at the build parse: `unknown-goal-type` with the known-name listing, never a misparse."""
    from inspect_ranges._build.behavioral import load_challenges
    from pydantic import ValidationError

    from tests.test_challenges_custom_types import MARKER_YAML

    range_dir = _write_challenges(
        tmp_path, MARKER_YAML.replace("type: marker", "type: zzz")
    )
    with pytest.raises(ValidationError) as excinfo:
        load_challenges(range_dir)
    assert "known types:" in str(excinfo.value) and "flag" in str(excinfo.value)


@dataclass
class FakeEntryPoint:
    name: str
    value: str
    loader: "Callable[[], None]"

    def load(self) -> None:
        self.loader()


def test_build_parse_loads_entry_point_registrations(
    isolated_registry: None,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The build loads the `inspect_ai` entry-point group before parsing, so a package registering a custom type works with zero in-process imports; one entry point's load failure is a warning naming it and its cause, never a build failure (inspect's own loader posture)."""
    import logging

    from inspect_ranges import register_goal_type
    from inspect_ranges._build.behavioral import load_challenges

    from tests.test_challenges_custom_types import MARKER_YAML, MarkerGoal, MarkerType

    def register_marker() -> None:
        register_goal_type(MarkerType())

    def explode() -> None:
        raise ImportError("missing transitive dependency")

    fakes = [
        FakeEntryPoint("broken", "broken_pkg._registry", explode),
        FakeEntryPoint("markers", "marker_pkg._registry", register_marker),
    ]

    def fake_entry_points(*, group: str) -> list[FakeEntryPoint]:
        return fakes if group == "inspect_ai" else []

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)
    with caplog.at_level(
        logging.WARNING, logger="inspect_ranges._challenges.registration"
    ):
        challenges = load_challenges(_write_challenges(tmp_path, MARKER_YAML))
    assert isinstance(challenges.challenges[0].goals[0], MarkerGoal)
    warning = next(
        record.getMessage()
        for record in caplog.records
        if "entry point" in record.getMessage()
    )
    assert "broken" in warning and "missing transitive dependency" in warning


def test_detection_only_negatives_pass_without_submissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slice-5 rule: detection goals score by observation, so a negative check over detection-only goals passes at 0.0/valid with zero submissions; any submission-consuming or unknown goal in the mix keeps the strict floor."""
    detection = SimpleNamespace(id="d", type="detection")
    flag = SimpleNamespace(id="f", type="flag")
    unknown = SimpleNamespace(id="u", type="not-a-goal-type")
    quiet = FakeOutcome(stdout=b"no submissions, by design\n")
    assert (
        run_check(
            monkeypatch, name="insufficient", outcome=quiet, goals=[detection]
        ).status
        == "pass"
    )
    assert (
        run_check(
            monkeypatch, name="forged", outcome=quiet, goals=[detection, flag]
        ).status
        == "fail"
    )
    assert (
        run_check(
            monkeypatch, name="insufficient", outcome=quiet, goals=[unknown]
        ).status
        == "fail"
    )


def test_prove_script_outcomes_map_to_check_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A failed assertion returns a fail record (the build's refusal verdict), a passing script a pass record with its assertions in the sink, and plants unwind either way (the per-check lifecycle)."""
    import inspect_ranges._challenges.prove as prove_module
    import inspect_ranges._challenges.setup as setup_module
    from inspect_ranges._build.behavioral import (
        _run_prove_script,  # pyright: ignore[reportPrivateUsage]
    )
    from inspect_ranges._challenges.engine import GoalResult

    unwound: list[list[str]] = []

    async def fake_run_setup(
        oracle: Any,
        challenge: Any,
        store: Any = None,
        *,
        extra_observers: Any = frozenset(),
    ) -> list[str]:
        return ["planted-key"]

    async def fake_unwind(oracle: Any, planted: list[str]) -> None:
        unwound.append(planted)

    monkeypatch.setattr(setup_module, "run_setup", fake_run_setup)
    monkeypatch.setattr(setup_module, "_unwind", fake_unwind)

    def fake_targets(oracle: Any, challenge: Any) -> list[Any]:
        return []

    monkeypatch.setattr(setup_module, "_probe_targets", fake_targets)

    class FakeEngine:
        uses_submissions = True

        def assurance_for(self, goal: Any) -> str:
            return "guest-corroborated"

    async def fake_eval(
        engine: Any, goal: Any, oracle: Any, submissions: Any
    ) -> tuple[GoalResult, int]:
        achieved = submissions.value(goal.id) == "expected"
        return GoalResult(achieved=achieved, reason="fake verdict"), 0

    def fake_goal_type(name: str) -> Any:
        return FakeEngine()

    monkeypatch.setattr(prove_module, "goal_type", fake_goal_type)
    monkeypatch.setattr(prove_module, "evaluate_goal", fake_eval)

    class ProveOracle:
        async def flush_capture(self) -> int:
            return 0

    challenge = _schema_challenge([_FLAG_GOAL])
    script = tmp_path / "prove_flow.py"
    script.write_text(
        "async def prove(ctx):\n"
        "    ctx.submit('token', 'expected')\n"
        "    await ctx.assert_goal('token', achieved=True)\n"
    )
    sink: list[Any] = []
    record = asyncio.run(
        _run_prove_script(
            cast(Any, ProveOracle()), challenge, script, assertion_sink=sink
        )
    )
    assert record.status == "pass" and record.check == "prove_flow.py"
    assert "goals=token" in record.detail
    assert [a.goal_id for a in sink] == ["token"]

    failing = tmp_path / "prove_fail.py"
    failing.write_text(
        "async def prove(ctx):\n"
        "    ctx.submit('token', 'wrong')\n"
        "    await ctx.assert_goal('token', achieved=True)\n"
    )
    record = asyncio.run(
        _run_prove_script(cast(Any, ProveOracle()), challenge, failing)
    )
    assert record.status == "fail"
    assert "expected achieved=True" in record.detail
    assert len(unwound) == 2


def test_runner_orders_trio_then_scripts_and_early_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """run_behavioral_checks executes a challenge's trio before its prove scripts, scripts in name order, challenges in declaration order; the first failing record ends the run (the caller records the refusal)."""
    import inspect_ranges._build.behavioral as behavioral_module
    import inspect_ranges._channel.channel as channel_module
    import inspect_ranges._channel.vsock as vsock_module
    import inspect_ranges._provider.evidence as evidence_module
    import inspect_ranges._provider.state as state_module
    from inspect_ranges._build.behavioral import run_behavioral_checks
    from inspect_ranges._build.manifest import BehavioralCheckRecord

    monkeypatch.setenv("INSPECT_RANGES_EXEC_WITNESS", "0")
    (tmp_path / "challenges.yaml").write_text(
        "challenges:\n"
        "  - id: c1\n"
        "    prompt: p\n"
        "    goals: [{id: g1, type: flag, host: atk, path: /f}]\n"
        "  - id: c2\n"
        "    prompt: p\n"
        "    goals: [{id: g2, type: flag, host: atk, path: /f}]\n"
    )
    chain_dir = tmp_path / "conformance" / "c1"
    chain_dir.mkdir(parents=True)
    for name in ("reference", "insufficient", "forged"):
        (chain_dir / f"{name}.sh").write_text("true\n")
    script_dir = tmp_path / "conformance" / "c2"
    script_dir.mkdir()
    for script in ("a_first.py", "b_second.py"):
        (script_dir / script).write_text("async def prove(ctx):\n    pass\n")

    class FakeSession:
        driver_writer = None
        enabled = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def open(self, **kwargs: Any) -> None:
            pass

        async def finalize(self) -> None:
            pass

        def register_producer(self, stop: Any) -> None:
            pass

    def fake_handle(**kwargs: Any) -> Any:
        return SimpleNamespace(**kwargs)

    def fake_channel(*args: Any, **kwargs: Any) -> Any:
        return object()

    def fake_transport(*args: Any, **kwargs: Any) -> Any:
        return object()

    def fake_attacker(spec: Any, plan: Any) -> tuple[str, str]:
        return ("atk", "10.0.0.2")

    def fake_oracle_class() -> Any:
        def construct(handle: Any) -> Any:
            return object()

        return construct

    monkeypatch.setattr(evidence_module, "EvidenceSession", FakeSession)
    monkeypatch.setattr(state_module, "SampleHandle", fake_handle)
    monkeypatch.setattr(channel_module, "MessageChannel", fake_channel)
    monkeypatch.setattr(vsock_module, "VsockTransport", fake_transport)
    monkeypatch.setattr(behavioral_module, "_attacker_guest", fake_attacker)
    monkeypatch.setattr(behavioral_module, "_scoped_oracle_class", fake_oracle_class)

    ran: list[str] = []
    outcomes: dict[str, str] = {}

    async def fake_run_one(
        oracle: Any, challenge: Any, name: str, script: str, *args: Any, **kwargs: Any
    ) -> BehavioralCheckRecord:
        ran.append(f"{challenge.id}:{name}")
        return BehavioralCheckRecord(
            challenge=challenge.id, check=name, status="pass", detail=""
        )

    async def fake_prove(
        oracle: Any, challenge: Any, script: pathlib.Path, **kwargs: Any
    ) -> BehavioralCheckRecord:
        ran.append(f"{challenge.id}:{script.name}")
        return BehavioralCheckRecord(
            challenge=challenge.id,
            check=script.name,
            status=outcomes.get(script.name, "pass"),
            detail="",
        )

    monkeypatch.setattr(behavioral_module, "_run_one", fake_run_one)
    monkeypatch.setattr(behavioral_module, "_run_prove_script", fake_prove)

    def run() -> tuple[BehavioralCheckRecord, ...]:
        spec = SimpleNamespace(meta=SimpleNamespace(name="r"))
        plan = SimpleNamespace(totals=None, guests=[])
        return asyncio.run(
            run_behavioral_checks(
                cast(Any, spec),
                cast(Any, plan),
                tmp_path,
                project="p",
                bundle=tmp_path,
                cids={"atk": 3},
                evidence_dir=tmp_path / "ev",
            )
        )

    records = run()
    assert ran == [
        "c1:reference",
        "c1:insufficient",
        "c1:forged",
        "c2:a_first.py",
        "c2:b_second.py",
    ]
    assert all(record.status == "pass" for record in records)

    ran.clear()
    outcomes["a_first.py"] = "fail"
    records = run()
    assert ran[-1] == "c2:a_first.py" and "c2:b_second.py" not in ran
    assert records[-1].status == "fail" and records[-1].check == "a_first.py"
