import json

from click.testing import CliRunner
from inspect_ranges import __version__
from inspect_ranges._cli.main import ranges


def test_version() -> None:
    result = CliRunner().invoke(ranges, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_json_exit_code_reflects_result() -> None:
    # runs the real checks, so assert only the output contract, not this machine's state
    result = CliRunner().invoke(ranges, ["doctor", "--json"])
    report = json.loads(result.output)
    assert result.exit_code == (0 if report["passed"] else 1)
    assert report["checks"]
    assert {check["status"] for check in report["checks"]} <= {
        "ok",
        "warn",
        "fail",
        "skip",
    }
