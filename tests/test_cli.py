from click.testing import CliRunner
from inspect_ranges import __version__
from inspect_ranges._cli.main import ranges


def test_version() -> None:
    result = CliRunner().invoke(ranges, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
