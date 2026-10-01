import click

from .. import __version__
from .doctor import doctor
from .schema import schema
from .validate import validate


@click.group()
@click.version_option(version=__version__, prog_name="inspect-ranges")
def ranges() -> None:
    """Inspect Ranges CLI."""


ranges.add_command(doctor)
ranges.add_command(schema)
ranges.add_command(validate)


def main() -> None:
    ranges()
