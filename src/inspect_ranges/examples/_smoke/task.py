"""One task over the Linux example ranges, for proving a deployment end to end.

Each sample names its own range (inspect resolves `Sample.sandbox` when the task declares none), so one eval boots every example's range in turn, pulling each published build at init: the first challenge of each example by default, every challenge with `per_example="all"`. Sample ids are prefixed with the example name, since two examples may share a challenge id. The Windows examples (goad_light, splunk_detection) stay out because their goldens derive locally from licensed media and are never published; defender_ops stays out because its range requires an egress uplink the deployment must supply.

    inspect eval inspect_ranges/examples_smoke --model anthropic/claude-opus-5
    inspect eval inspect_ranges/examples_smoke -T per_example=all --model anthropic/claude-opus-5
"""

from pathlib import Path
from typing import Literal

from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import MemoryDataset, Sample

from inspect_ranges import (
    challenge_dataset,
    challenge_scorer,
    challenge_setup,
    terminal,
    verify_goal,
)

EXAMPLES = Path(__file__).parent.parent

LINUX_EXAMPLES = ("dmz_pivot", "vulhub_zabbix", "kypo_demo", "cyris_basic", "equifax")
"""The examples the smoke task spans: published builds, Linux guests, no egress."""


@task
def examples_smoke(per_example: int | Literal["all"] = 1) -> Task:
    """The Linux example ranges in one eval: `per_example` challenges of each (the first by default, every one with `"all"`), each sample booting its own example's range."""
    samples: list[Sample] = []
    for name in LINUX_EXAMPLES:
        # one multi-range entry per example so `per_example` truncates per
        # example, not across the combined dataset
        dataset = challenge_dataset([(name, EXAMPLES / f"_{name}")], prefix_ids=True)
        samples.extend(list(dataset)[: None if per_example == "all" else per_example])
    return Task(
        dataset=MemoryDataset(samples, name="examples_smoke"),
        setup=challenge_setup(),
        solver=react(tools=[terminal(), verify_goal()]),
        scorer=challenge_scorer(),
    )
