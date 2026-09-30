from dataclasses import dataclass
from typing import Literal

CheckStatus = Literal["ok", "warn", "fail", "skip"]
"""Outcome of a check: `warn` doesn't fail `doctor`, `skip` means a prerequisite check failed."""


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one `doctor` check."""

    group: str
    """Heading the check is reported under (e.g. "Docker")."""

    name: str
    """Short name of what was checked (e.g. "/dev/kvm")."""

    status: CheckStatus
    """Whether the check passed."""

    detail: str
    """One line describing what was found."""

    fix: str | None = None
    """How to fix a `warn` or `fail`, as exact commands where possible."""
