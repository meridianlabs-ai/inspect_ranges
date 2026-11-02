"""`inspect-ranges prove`: re-run a range's conformance proofs against its built artifacts."""

from pathlib import Path

import click

from .._build.errors import BuildError
from .._build.prove import run_prove
from .._challenges.prove import ConformanceError
from .._diagnostics import IssueError
from .._runtime.up import UpError
from .buildcmd import _echo_stage  # pyright: ignore[reportPrivateUsage]
from .specpath import resolve_spec_path


@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
@click.option(
    "--image-cache",
    type=click.Path(path_type=Path),
    default=None,
    show_default="~/.cache/inspect-ranges/images (or INSPECT_RANGES_IMAGE_CACHE)",
    help="Image cache the built artifacts resolve from.",
)
@click.option(
    "--build-cache",
    type=click.Path(path_type=Path),
    default=None,
    show_default="~/.cache/inspect-ranges/builds (or INSPECT_RANGES_BUILD_CACHE)",
    help="Build cache holding the manifest the proof runs against (and receives the proven record).",
)
@click.option(
    "--uplink-network",
    default=None,
    help="Deployment-supplied uplink network, for ranges that request egress.",
)
@click.option(
    "--keep",
    is_flag=True,
    help="Keep a FAILED proof boot running for diagnosis (named in the error); successful proofs always tear down.",
)
def prove(
    path: Path | None,
    image_cache: Path | None,
    build_cache: Path | None,
    uplink_network: str | None,
    keep: bool,
) -> None:
    """Prove PATH's scoring post hoc (default `.`): boot the recorded build once and run every declared conformance proof against it, exactly as the build's own proof phase does.

    The build already refuses unproven ranges; `prove` is the consumer-side re-demonstration. All proofs under `conformance/<challenge-id>/` run (behavioral trios and `prove(ctx)` scripts) against the exact realized images the manifest names. A passing run stamps the manifest `proven` (additive; `verification` is untouched); a failing one exits nonzero and changes nothing on disk. A REFUSED manifest refuses proving: rebuild first.
    """
    spec_path = resolve_spec_path(path)
    try:
        record = run_prove(
            spec_path.parent,
            image_cache=image_cache,
            build_cache=build_cache,
            uplink_network=uplink_network,
            keep=keep,
            on_stage=_echo_stage,
        )
    except (ConformanceError, BuildError, UpError, IssueError, RuntimeError) as error:
        raise click.ClickException(str(error)) from error
    # one entry per assertion, in order: a proof may assert BOTH directions on
    # one goal (the falsifiability pattern), and the summary must show both
    asserted = ", ".join(
        f"{entry.goal_id}={'achieved' if entry.expected_achieved else 'not-achieved'}"
        for entry in record.assertions
    )
    click.echo(
        f"proven: {len(record.scripts)} check(s)"
        + (f", assertions [{asserted}]" if asserted else "")
        + f" at {record.proven_at}"
    )
