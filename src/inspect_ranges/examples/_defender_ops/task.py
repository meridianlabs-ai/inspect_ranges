from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.agent import react

from inspect_ranges import (
    challenge_dataset,
    challenge_scorer,
    challenge_setup,
    load_collectors,
    register_exploit,
    terminal,
    verify_goal,
)

# importing the module registers the custom `lotl` goal type with the engine
# (and with challenges.yaml parsing) before anything reads the challenges file.
# The absolute package import deliberately: the build's conformance loader
# executes this file standalone (no parent package, so a relative import
# refuses), and a bare `import goals` would execute the module a second time
# and trip the registry's shadow guard; the package form resolves to the one
# already-registered module in both contexts.
from inspect_ranges.examples._defender_ops import goals as goals  # noqa: PLC0414

_DIR = Path(__file__).parent

# the patch goal's reference exploit chain, registered at import so planting
# and scoring resolve it in every process (idempotent for identical text)
register_exploit(
    "orderboard-remote-admin",
    (_DIR / "exploits" / "orderboard-remote-admin.sh").read_text(),
)


@task
def defender_ops() -> Task:
    """The defender-ops example range: king-of-the-hill sabotage of a small ops environment, then a quiet patch-and-cleanup scored from the exec witness and the exported ops log."""
    return Task(
        dataset=challenge_dataset(
            _DIR / "challenges.yaml", range_spec=_DIR / "range.yaml"
        ),
        setup=challenge_setup(
            telemetry_collectors=load_collectors(_DIR / "collectors.yaml")
        ),
        solver=react(tools=[terminal(), verify_goal()]),
        scorer=challenge_scorer(),
        sandbox=("range", str(_DIR / "range.yaml")),
    )
