from pathlib import Path

import click
import yaml
from pydantic import ValidationError

from ..schema import load_range


@click.command()
@click.argument(
    "paths", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path)
)
@click.pass_context
def validate(ctx: click.Context, paths: tuple[Path, ...]) -> None:
    """Validate `range.yaml` files against schema v0.1.

    Exits with status 1 if any file is invalid.
    """
    failed = False
    for path in paths:
        try:
            spec = load_range(path)
        except ValidationError as error:
            failed = True
            click.echo(f"{click.style('✗', fg='red')} {path}")
            for issue in error.errors():
                location = ".".join(str(part) for part in issue["loc"]) or "(root)"
                click.echo(f"    {location}: {issue['msg']}")
        except (yaml.YAMLError, ValueError) as error:
            failed = True
            click.echo(f"{click.style('✗', fg='red')} {path}")
            click.echo(f"    {error}")
        else:
            click.echo(f"{click.style('✓', fg='green')} {path}  ({spec.meta.name})")
    ctx.exit(1 if failed else 0)
