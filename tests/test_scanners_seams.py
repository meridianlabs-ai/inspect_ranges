"""`range_apparatus` through its two real consumption seams, with no machine-local fixtures.

The online seam puts the scanner directly in a task's scorer list; the after-the-fact seam feeds a finished eval log through scout's own loader (`transcripts_from` + `scan`). Both run against a log generated in-test with mockllm, so they run everywhere. The detector-level red and green cases live in `test_scanners_engine.py`; this file pins only the seams. (An earlier version additionally pinned zero-findings and a real uncorroborated-segments fire against machine-local 2026-10-21 eval logs; those logs are gone and their timestamped filenames are unreproducible, so the pins went with them.)
"""

from pathlib import Path

from inspect_ai import Task
from inspect_ai import (
    eval as inspect_eval,  # pyright: ignore[reportUnknownVariableType]
)
from inspect_ai.dataset import Sample
from inspect_ranges.scanners import range_apparatus
from inspect_scout import scan, scan_results_df, transcripts_from


def _healthy_log(log_dir: Path) -> str:
    """One healthy mockllm sample, evaluated to a finished log; returns the log location."""
    task = Task(
        dataset=[Sample(input="say hi", target="hi")],
        scorer=[range_apparatus()],
    )
    log = inspect_eval(
        task, model="mockllm/model", display="none", log_dir=str(log_dir)
    )[0]
    assert log.status == "success"
    return log.location


def test_scanner_rides_the_scorer_list_directly(tmp_path: Path) -> None:
    """The online seam: the scanner sits directly in the scorer list (no adapter) and lands a 0/no-findings score on a healthy sample."""
    task = Task(
        dataset=[Sample(input="say hi", target="hi")],
        scorer=[range_apparatus()],
    )
    log = inspect_eval(
        task, model="mockllm/model", display="none", log_dir=str(tmp_path)
    )[0]
    assert log.status == "success"
    sample = (log.samples or [])[0]
    assert sample.scores is not None
    score = sample.scores["range_apparatus"]
    assert score.value == 0
    assert score.explanation == "no findings"


def test_scout_scan_over_a_finished_log_reads_zero(tmp_path: Path) -> None:
    """The after-the-fact seam: scout's eval-log loader feeds the same engine and reads zero findings on a healthy log."""
    location = _healthy_log(tmp_path / "logs")
    status = scan(
        [range_apparatus()],
        transcripts_from(location),
        scans=str(tmp_path / "scans"),
        display="none",
        max_processes=1,
    )
    assert status.complete
    results = scan_results_df(status.location)
    frame = results.scanners["range_apparatus"]
    # pandas is untyped here; the ignores are scoped to the frame reads
    assert list(frame["value"]) == [0]  # pyright: ignore[reportUnknownArgumentType]
    assert list(frame["explanation"]) == ["no findings"]  # pyright: ignore[reportUnknownArgumentType]
