import json
from dataclasses import asdict
from itertools import groupby

import click

from ._result import CheckResult, CheckStatus

_SYMBOLS: dict[CheckStatus, tuple[str, str]] = {
    "ok": ("✓", "green"),
    "warn": ("!", "yellow"),
    "fail": ("✗", "red"),
    "skip": ("-", "bright_black"),
}


def passed(results: list[CheckResult]) -> bool:
    """Whether no check failed (warnings and skips don't count)."""
    return not any(result.status == "fail" for result in results)


def render_text(results: list[CheckResult]) -> str:
    """Render results grouped under headings, with a fix line for each warning or failure."""
    width = max((len(result.name) for result in results), default=0)
    lines: list[str] = []
    for group, group_results in groupby(results, key=lambda result: result.group):
        lines.append(click.style(group, bold=True))
        for result in group_results:
            symbol, color = _SYMBOLS[result.status]
            lines.append(
                f"  {click.style(symbol, fg=color)} {result.name.ljust(width)}  {result.detail}"
            )
            if result.fix and result.status in ("warn", "fail"):
                lines.append(f"  {' ' * (width + 4)}fix: {result.fix}")
    counts = {
        status: sum(result.status == status for result in results)
        for status in _SYMBOLS
    }
    lines.append("")
    lines.append(
        f"{counts['ok']} ok, {counts['warn']} warning(s), {counts['fail']} failed, {counts['skip']} skipped"
    )
    return "\n".join(lines)


def render_json(results: list[CheckResult]) -> str:
    """Render results as JSON: `{"passed": bool, "checks": [...]}`."""
    return json.dumps(
        {"passed": passed(results), "checks": [asdict(result) for result in results]},
        indent=2,
    )
