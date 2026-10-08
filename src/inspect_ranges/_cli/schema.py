import json

import click

from ..schema import range_json_schema


@click.command()
def schema() -> None:
    """Print the JSON Schema for `range.yaml` v0.1 to stdout."""
    click.echo(json.dumps(range_json_schema(), indent=2))
