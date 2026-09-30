import click

from .. import __version__
from .doctor import doctor


@click.group()
@click.version_option(version=__version__, prog_name="inspect-ranges")
def ranges() -> None:
    """Inspect Ranges CLI."""


ranges.add_command(doctor)


def main() -> None:
    ranges()
