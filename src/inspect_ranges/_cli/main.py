import click

from .. import __version__


@click.group()
@click.version_option(version=__version__, prog_name="inspect-ranges")
def ranges() -> None:
    """Inspect Ranges CLI."""


def main() -> None:
    ranges()
