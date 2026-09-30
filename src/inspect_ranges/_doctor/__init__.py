"""Host checks for `inspect-ranges doctor`: can this machine run and develop ranges?"""

from ._checks import run_checks
from ._report import passed, render_json, render_text
from ._result import CheckResult, CheckStatus

__all__ = [
    "CheckResult",
    "CheckStatus",
    "passed",
    "render_json",
    "render_text",
    "run_checks",
]
