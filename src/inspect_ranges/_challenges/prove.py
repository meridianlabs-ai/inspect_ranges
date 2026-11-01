"""The python conformance-proof surface: `prove(ctx)` scripts asserting goal verdicts through the scorer's own evaluation.

Scripts live at `conformance/<challenge-id>/*.py`, each defining `prove(ctx)` (sync or async). The build's proof phase executes them inside the proof boot — after the challenge's own setup, under the same oracle, evidence, draws, and prober vantage a sample sees — and `inspect-ranges prove` re-runs them post hoc against a built artifact. The context exposes the scoring oracle, a submission channel, and `assert_goal`, whose verdict comes from the same `evaluate_goal` the scorer runs, so a proof can never pass under semantics scoring would not apply.

This module lives in `_challenges`, not `_build`: the context is scoring-surface code, and `_build` imports `_challenges` lazily (the provider imports `_build`, so the reverse edge must stay runtime-only); the manifest's `GoalAssertion` is imported inside the method for the same reason.

Proof artifacts are working exploits. They run from the operator side through the oracle and must never ride a recipe payload or any other guest-ward path.
"""

import hashlib
import importlib.util
import inspect as pyinspect
import math
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .engine import goal_type
from .schema import Challenge
from .scorer import evaluate_goal
from .submission import Submission, Submissions

if TYPE_CHECKING:
    from .._build.manifest import GoalAssertion
    from .oracle import RangeOracle


class ConformanceError(Exception):
    """A proof failed or the proof surface was misused; the message names the script or goal and what contradicted what."""


class ProveContext:
    """The surface a proof script drives: the real oracle, a submission channel, and verdict assertions through the scorer's own evaluation."""

    def __init__(
        self,
        oracle: "RangeOracle",
        challenge: Challenge,
        *,
        pre_assert: "Callable[[], Awaitable[None]] | None" = None,
    ) -> None:
        self.oracle = oracle
        self.challenge = challenge
        self._pre_assert = pre_assert
        self._submissions: list[Submission] = []
        self.assertions: "list[GoalAssertion]" = []

    def submit(self, goal_id: str, value: str) -> None:
        """Record a submission exactly as an agent's `verify_goal` would, so submission-consuming goals can be proven."""
        self._submissions.append(
            Submission(goal_id=goal_id, value=value, wall=time.time())
        )

    async def assert_goal(
        self, goal_id: str, *, achieved: bool, partial: float | None = None
    ) -> None:
        """Evaluate `goal_id` now, through the scorer's own candidate semantics, and refuse unless the verdict matches the expectation (and `partial`, when given).

        Raises:
            ConformanceError: The goal is unknown or model-graded (build-time proofs have no model to grade with), or the verdict contradicts the expectation; the message carries the verdict's reason so a failing proof reads like a scoring diagnosis.
        """
        from .._build.manifest import GoalAssertion

        goal = next((g for g in self.challenge.goals if g.id == goal_id), None)
        if goal is None:
            known = ", ".join(g.id for g in self.challenge.goals)
            raise ConformanceError(
                f"assert_goal: no goal {goal_id!r} in challenge "
                f"{self.challenge.id!r} (goals: {known})"
            )
        try:
            engine = goal_type(goal.type)
        except KeyError as error:
            raise ConformanceError(
                f"assert_goal: goal {goal_id!r} has unresolvable type "
                f"{goal.type!r}: {error}"
            ) from error
        if engine.assurance_for(goal) == "model-graded":
            raise ConformanceError(
                f"assert_goal: goal {goal_id!r} is model-graded; build-time "
                "proofs have no model to grade with (judge-at-build.md), so a "
                "proof cannot assert it"
            )
        # the scorer snapshots active capture before any goal reads pcap; the
        # proof must observe through the same lens
        await self.oracle.flush_capture()
        if self._pre_assert is not None:
            # the runner's read barrier (a live prober force-flushes its
            # batched records so the verdict reads this proof's own probes)
            await self._pre_assert()
        result, _ = await evaluate_goal(
            engine, goal, self.oracle, Submissions(list(self._submissions))
        )
        if result.achieved != achieved:
            raise ConformanceError(
                f"goal {goal_id!r}: expected achieved={achieved}, got "
                f"achieved={result.achieved} ({result.reason or 'no reason recorded'})"
            )
        if partial is not None and not math.isclose(
            result.partial or 0.0, partial, rel_tol=0.0, abs_tol=1e-9
        ):
            # tolerant equality: a goal type computing partial as 1/3 must be
            # assertable with a literal
            raise ConformanceError(
                f"goal {goal_id!r}: expected partial={partial}, got {result.partial}"
            )
        self.assertions.append(
            GoalAssertion(
                goal_id=goal_id, expected_achieved=achieved, reason=result.reason
            )
        )


def load_prove_module(path: Path, label: str, *, content_keyed: bool = False) -> object:
    """Import a loose module by path, cached in `sys.modules` so repeated proofs in one process never re-execute registrations.

    The cache key is the resolved location; with `content_keyed` it also hashes the file's bytes, so an edited proof script re-imports (the digest invalidated the cached build, and the re-proof must run the edited code, not a stale module). `task.py` stays path-keyed on purpose: re-executing it would re-register its goal types under the same names.

    Sibling imports a script makes during its own import are scoped to it: modules newly landed in `sys.modules` whose file lives beside the script are evicted afterward, so two challenges each shipping a `helpers.py` never read each other's.

    Raises:
        ConformanceError: The module cannot be read or imported.
    """
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ConformanceError(f"{path} cannot be read: {error}") from error
    hasher = hashlib.sha256(str(path.resolve()).encode())
    if content_keyed:
        hasher.update(b"\0" + content)
    key = f"ir_prove_{label}_{hasher.hexdigest()[:12]}"
    cached = sys.modules.get(key)
    if cached is not None:
        return cached
    module_spec = importlib.util.spec_from_file_location(key, path)
    if module_spec is None or module_spec.loader is None:
        raise ConformanceError(f"{path} cannot be imported")
    module = importlib.util.module_from_spec(module_spec)
    parent = str(path.parent)
    before = set(sys.modules)
    sys.path.insert(0, parent)
    try:
        try:
            # the exact bytes the cache key (and the build digest) saw run,
            # never the loader's __pycache__ view: an edit within one mtime
            # second at equal size would otherwise execute stale bytecode
            exec(compile(content, str(path), "exec"), module.__dict__)  # noqa: S102
        except Exception as error:
            raise ConformanceError(
                f"{path.name} failed to import: {type(error).__name__}: {error}"
            ) from error
    finally:
        sys.path.remove(parent)
        for name in set(sys.modules) - before:
            file = getattr(sys.modules[name], "__file__", None)
            if file is not None and Path(file).parent == path.parent:
                del sys.modules[name]
    sys.modules[key] = module
    return module


def register_range_goal_types(range_dir: Path) -> None:
    """Import the range's loose `task.py`, when one exists, so its `@range_goal` types register before challenges parse — the same rule inspect itself applies (task import registers); package-referenced tasks register through entry points instead.

    The module cache keeps a second build or proof in one process from re-executing the module and re-registering a fresh instance under the same name.

    Raises:
        ConformanceError: The task module cannot be imported.
    """
    task_module = range_dir / "task.py"
    if task_module.is_file():
        load_prove_module(task_module, "task")


async def execute_prove(script: Path, context: ProveContext) -> None:
    """Load one proof script and drive its `prove(ctx)` (sync or async) against `context`.

    A script that asserts nothing fails: a proof that demonstrates no verdict is indistinguishable from no proof. `prove` must be async (`assert_goal` is), which validation already enforced by AST at build time.

    Raises:
        ConformanceError: The script defines no async `prove`, raises (any exception becomes the proof's failure, named), or finishes without asserting a goal verdict.
    """
    # content-keyed: an edited script re-imports (the digest already
    # invalidated the cached build; the re-proof must run the edited code)
    module = load_prove_module(script, "script", content_keyed=True)
    prove_fn = getattr(module, "prove", None)
    if not callable(prove_fn):
        raise ConformanceError(f"{script.name} defines no prove(ctx)")
    before = len(context.assertions)
    try:
        outcome = prove_fn(context)
        if not pyinspect.iscoroutine(outcome):
            raise ConformanceError(
                f"{script.name}: prove(ctx) must be `async def` (assert_goal "
                "is async; a sync prove could never assert)"
            )
        await outcome
    except ConformanceError:
        raise
    except Exception as error:
        raise ConformanceError(
            f"{script.name} raised {type(error).__name__}: {error}"
        ) from error
    if len(context.assertions) == before:
        raise ConformanceError(
            f"{script.name} asserted no goal verdicts; a proof that asserts "
            "nothing is vacuous"
        )
