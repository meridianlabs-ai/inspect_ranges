"""The conformance prove surface: context assertions over real check/compare and script execution semantics — all against fakes (no VMs)."""

import asyncio
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from inspect_ranges import GoalBase, GoalResult, GoalType, Observations, range_goal
from inspect_ranges._challenges.prove import (
    ConformanceError,
    ProveContext,
    execute_prove,
)
from inspect_ranges._challenges.schema import Challenge


def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
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


class EchoGoal(GoalBase):
    type: Literal["prove-echo"] = "prove-echo"


class FakeStore:
    def get(self, key: str) -> bytes:
        return b"expected"


class _FakeOracle:
    store = FakeStore()

    async def flush_capture(self) -> int:
        return 0

    def evidence_memo(self):  # noqa: ANN201 - test double for the memo contextmanager
        from contextlib import nullcontext

        return nullcontext()


def _challenge(goals: "list[dict[str, Any]] | None" = None) -> Challenge:
    return Challenge.model_validate(
        {
            "id": "prove-check",
            "prompt": "p",
            "goals": goals or [{"id": "echo", "type": "prove-echo"}],
        }
    )


def _context(
    monkeypatch: pytest.MonkeyPatch, challenge: "Challenge | None" = None
) -> ProveContext:
    _isolate(monkeypatch)

    @range_goal
    class EchoType(GoalType):
        name = "prove-echo"
        spec = EchoGoal
        assurance = "guest-corroborated"

        async def check(self, goal: Any, oracle: Any, submissions: Any) -> Observations:
            latest = submissions.value(goal.id)
            return Observations(
                source="submission", reads={"v": (latest or "").encode()}
            )

        def compare(self, goal: Any, obs: Observations, store: Any) -> GoalResult:
            achieved = obs.reads["v"] == b"expected"
            return GoalResult(achieved=achieved, reason="echo compare")

    from inspect_ranges._challenges.oracle import RangeOracle

    return ProveContext(
        oracle=cast(RangeOracle, _FakeOracle()), challenge=challenge or _challenge()
    )


def test_assert_goal_passes_and_records_on_a_matching_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A submission that genuinely achieves the goal satisfies assert_goal(achieved=True) and the assertion is recorded for the manifest marker."""
    context = _context(monkeypatch)
    context.submit("echo", "expected")
    asyncio.run(context.assert_goal("echo", achieved=True))
    assert [a.goal_id for a in context.assertions] == ["echo"]


def test_assert_goal_refuses_a_contradicting_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verdict that contradicts the expectation raises with the goal and both verdicts; expecting not-achieved on silence passes (the negative-path proof)."""
    context = _context(monkeypatch)
    asyncio.run(context.assert_goal("echo", achieved=False))
    context.submit("echo", "wrong")
    with pytest.raises(ConformanceError, match="expected achieved=True"):
        asyncio.run(context.assert_goal("echo", achieved=True))
    with pytest.raises(ConformanceError, match="no goal 'missing'"):
        asyncio.run(context.assert_goal("missing", achieved=True))


def test_assert_goal_refuses_a_model_graded_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build-time proofs have no model (judge-at-build.md): asserting a judge goal refuses instead of grading vacuously."""
    from inspect_ranges._challenges.registration import ensure_goal_type_registrations

    ensure_goal_type_registrations()
    _isolate(monkeypatch)
    challenge = _challenge(
        [{"id": "report", "type": "judge", "rubric": "grade the report"}]
    )
    from inspect_ranges._challenges.oracle import RangeOracle

    context = ProveContext(oracle=cast(RangeOracle, _FakeOracle()), challenge=challenge)
    with pytest.raises(ConformanceError, match="model-graded"):
        asyncio.run(context.assert_goal("report", achieved=True))
    assert context.assertions == []


def test_assert_goal_takes_the_pre_assert_read_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner's prober flush runs before every verdict read, so a proof's own probe records are visible to the goals that score them."""
    flushed: list[str] = []

    async def barrier() -> None:
        flushed.append("flush")

    _isolate(monkeypatch)
    context = _context(monkeypatch)
    context._pre_assert = barrier  # pyright: ignore[reportPrivateUsage]
    context.submit("echo", "expected")
    asyncio.run(context.assert_goal("echo", achieved=True))
    assert flushed == ["flush"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("value = 1\n", "defines no prove"),
        (
            "async def prove(ctx):\n    raise RuntimeError('exploit hung')\n",
            "raised RuntimeError: exploit hung",
        ),
        ("async def prove(ctx):\n    pass\n", "asserted no goal verdicts"),
    ],
)
def test_execute_prove_refuses_misshapen_scripts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str, message: str
) -> None:
    """A script without prove, a raising script, and a script that asserts nothing all fail as verdicts: a proof that demonstrates nothing is indistinguishable from no proof."""
    context = _context(monkeypatch)
    script = tmp_path / "prove_demo.py"
    script.write_text(body)
    with pytest.raises(ConformanceError, match=message):
        asyncio.run(execute_prove(script, context))


def test_execute_prove_runs_an_async_prove_and_refuses_a_sync_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An `async def prove` runs against the context and its assertions count; a sync prove refuses (assert_goal is async, so a sync prove could never assert)."""
    context = _context(monkeypatch)
    async_script = tmp_path / "b_async.py"
    async_script.write_text(
        "async def prove(ctx):\n"
        "    ctx.submit('echo', 'expected')\n"
        "    await ctx.assert_goal('echo', achieved=True)\n"
    )
    asyncio.run(execute_prove(async_script, context))
    assert len(context.assertions) == 1
    sync_script = tmp_path / "a_sync.py"
    sync_script.write_text("def prove(ctx):\n    pass\n")
    with pytest.raises(ConformanceError, match="must be `async def`"):
        asyncio.run(execute_prove(sync_script, context))


def test_load_prove_module_caches_by_path(tmp_path: Path) -> None:
    """Repeated loads of one script in a process return the cached module: registrations in a task.py must not re-execute."""
    from inspect_ranges._challenges.prove import load_prove_module

    script = tmp_path / "counted.py"
    script.write_text("import itertools\nticks = []\nticks.append(1)\n")
    first = load_prove_module(script, "script")
    second = load_prove_module(script, "script")
    assert first is second
    assert cast(Any, first).ticks == [1]
