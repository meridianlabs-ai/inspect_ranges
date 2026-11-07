"""Tests for the terminal tool's capture leg against fake evidence and recorder processes."""

import asyncio
import json
from collections.abc import Iterator
from itertools import count
from pathlib import Path
from typing import Any

import inspect_ranges._terminal.capture as capture_module
import pytest
from inspect_ai.util import ExecResult, Store
from inspect_ai.util._sandbox.exec_remote import ExecStdout
from inspect_ranges._terminal.capture import (
    captures_for_tests,
    discard_sample_captures,
    start_capture,
    stop_all_captures,
    stop_capture,
)
from inspect_ranges._terminal.session import SessionState


class FakeEvidence:
    """The evidence surface capture touches: location, append_driver, register_producer."""

    def __init__(self, location: str) -> None:
        self.location = location
        self.appended: list[tuple[str, bytes]] = []
        self.producers: list[Any] = []

    async def append_driver(self, stream: str, data: bytes) -> None:
        self.appended.append((stream, data))

    def register_producer(self, stop: Any) -> None:
        self.producers.append(stop)


class FakeProcess:
    """An exec_remote handle yielding scripted output events."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.killed = False

    def __aiter__(self) -> "FakeProcess":
        return self

    async def __anext__(self) -> ExecStdout:
        if not self._outputs:
            raise StopAsyncIteration
        return ExecStdout(data=self._outputs.pop(0))

    async def kill(self) -> None:
        self.killed = True


class FakeSandbox:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process

    async def exec(self, cmd: list[str], timeout: int | None = None) -> ExecResult[str]:
        return ExecResult(success=True, returncode=0, stdout="", stderr="")

    async def exec_remote(self, cmd: list[str], stream: bool = True) -> FakeProcess:
        return self.process


class PaneFakeSandbox(FakeSandbox):
    """A sandbox serving a sink directory: `panes` are tailed by their own scripted processes (the poller path), `contents` answer one-shot reads (the stop-time collect path); the primary tailer keeps the base process."""

    def __init__(
        self,
        process: FakeProcess,
        panes: dict[str, FakeProcess] | None = None,
        contents: dict[str, str] | None = None,
    ) -> None:
        super().__init__(process)
        self.panes = panes or {}
        self.contents = contents or {}

    async def exec(self, cmd: list[str], timeout: int | None = None) -> ExecResult[str]:
        if cmd[-1].startswith("cat "):
            body = self.contents.get(cmd[-1][len("cat ") :], "")
            return ExecResult(success=True, returncode=0, stdout=body, stderr="")
        listing = "\n".join([*self.panes, *self.contents])
        return ExecResult(success=True, returncode=0, stdout=listing, stderr="")

    async def exec_remote(self, cmd: list[str], stream: bool = True) -> FakeProcess:
        for path, process in self.panes.items():
            if path in cmd[-1]:
                return process
        return self.process


_STORE_IDS = count(4242)


current_store: Store | None = None
"""The current test's sample store, served through the patched `_current_store` (module-level so the fixture closure sees reassignment)."""


@pytest.fixture()
def arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[FakeEvidence, FakeProcess, SessionState, int]]:
    """A per-test store id (the module registry is shared state, so a reused id would leak one test's sample entry into the next) with the registry entry discarded afterward."""
    global current_store
    evidence = FakeEvidence(str(tmp_path / "evidence"))
    process = FakeProcess(["chunk-one\n", "chunk-two\n"])
    current_store = Store()
    monkeypatch.setattr(
        capture_module, "_capture_target", lambda: (True, evidence, "ir-cap-test")
    )
    monkeypatch.setattr(capture_module, "_current_store", lambda: current_store)
    monkeypatch.setattr(capture_module, "sandbox", lambda: FakeSandbox(process))

    tasks: list[asyncio.Task[None]] = []

    def run_background(fn: Any, *args: Any) -> None:
        tasks.append(asyncio.get_event_loop().create_task(fn(*args)))

    monkeypatch.setattr(capture_module, "background", run_background)
    state = SessionState(opened_wall=1_700_000_000.0, opened_monotonic=0.0)
    store_id = next(_STORE_IDS)
    try:
        yield evidence, process, state, store_id
    finally:
        discard_sample_captures(store_id)


def test_capture_records_mirrors_and_writes_cast(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    evidence, process, state, store_id = arm

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        assert len(evidence.producers) == 1
        await asyncio.sleep(0.05)  # the consumer drains the scripted events
        assert [data for _, data in evidence.appended] == [
            b"chunk-one\n",
            b"chunk-two\n",
        ]
        assert all(stream == "terminal/s" for stream, _ in evidence.appended)
        assert len(state.chunks) == 2
        state.markers.append((0.5, "send s: 'ls'"))
        await stop_capture(store_id, "s")
        assert process.killed
        cast_file = Path(evidence.location) / "terminal-s.cast"
        lines = cast_file.read_text().strip().split("\n")
        header = json.loads(lines[0])
        assert header["title"] == "terminal session s"
        kinds = [json.loads(line)[1] for line in lines[1:]]
        assert kinds.count("o") == 2 and kinds.count("m") == 1

    asyncio.run(scenario())


def test_finalize_stops_everything_and_runs_cleanup(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    _, process, state, store_id = arm
    cleaned: list[bool] = []

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: cleaned.append(True))
        await asyncio.sleep(0.05)
        assert "s" in captures_for_tests(store_id)
        await stop_all_captures(store_id)
        assert process.killed
        assert cleaned == [True]
        assert captures_for_tests(store_id) == {}
        # idempotent: a second finalize finds nothing
        await stop_all_captures(store_id)
        assert cleaned == [True]

    asyncio.run(scenario())


def test_stop_drains_pending_output_before_the_cast(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    """An immediate stop must still land every pending output event in the cast: kill enqueues output buffered since the last poll, and the cast waits for the consumer to drain it."""
    evidence, _, state, store_id = arm

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await stop_capture(store_id, "s")  # no sleep: the consumer has not run yet
        cast_file = Path(evidence.location) / "terminal-s.cast"
        lines = cast_file.read_text().strip().split("\n")
        kinds = [json.loads(line)[1] for line in lines[1:]]
        assert kinds.count("o") == 2

    asyncio.run(scenario())


def test_second_life_cast_does_not_overwrite_the_first(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    """A session name can record more than one life (close then reopen): the later life's cast must land beside the first, not clobber it."""
    evidence, _, state, store_id = arm

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)
        await stop_capture(store_id, "s")
        await start_capture(store_id, "s", SessionState(), lambda: None)
        await stop_capture(store_id, "s")
        directory = Path(evidence.location)
        first = directory / "terminal-s.cast"
        second = directory / "terminal-s-2.cast"
        assert first.exists() and second.exists()
        # the first life's output is still in the first file
        kinds = [
            json.loads(line)[1] for line in first.read_text().strip().split("\n")[1:]
        ]
        assert kinds.count("o") == 2

    asyncio.run(scenario())


class CancellingProcess(FakeProcess):
    """A recorder handle whose stream is cancelled mid-iteration (a dying sample cancels background tasks)."""

    async def __anext__(self) -> ExecStdout:
        raise asyncio.CancelledError()


def test_stop_tolerates_cancelled_consumer(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dying sample cancels background tasks: finalize must still stop the recorder and write the cast when the consume task was cancelled mid-stream."""
    evidence, _, state, store_id = arm
    process = CancellingProcess([])
    monkeypatch.setattr(capture_module, "sandbox", lambda: FakeSandbox(process))

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)  # the consumer runs and is cancelled
        await stop_all_captures(store_id)
        assert process.killed
        assert (Path(evidence.location) / "terminal-s.cast").exists()

    asyncio.run(scenario())


def test_discard_sample_captures_drops_the_registry_entry(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    """GC-time cleanup: a collected store's capture entry disappears so a reused id never inherits it."""
    _, _, state, store_id = arm

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        assert "s" in captures_for_tests(store_id)
        discard_sample_captures(store_id)
        assert captures_for_tests(store_id) == {}

    asyncio.run(scenario())


def test_remote_location_skips_cast_but_mirrors(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    evidence, _, state, store_id = arm
    evidence.location = "s3://bucket/evidence"

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)
        await stop_all_captures(store_id)
        assert len(evidence.appended) == 2  # the mirror is unaffected

    asyncio.run(scenario())


def test_exec_remote_surface_pin() -> None:
    """Capture leans on inspect_ai's exec_remote surface (a private module for the event classes): every runtime use is wrapped in broad excepts, so a shape change on an inspect_ai bump would silently turn capture off in live runs; this pin fails loudly here instead."""
    import inspect

    from inspect_ai.util._sandbox.environment import SandboxEnvironment
    from inspect_ai.util._sandbox.exec_remote import ExecRemoteProcess

    assert ExecStdout(data="x").data == "x"
    assert callable(getattr(ExecRemoteProcess, "kill", None))
    assert hasattr(ExecRemoteProcess, "__aiter__")
    parameters = inspect.signature(SandboxEnvironment.exec_remote).parameters
    assert "stream" in parameters


def test_store_cast_written_with_life_suffixes(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    """Every cast also lands in the sample store under the asciinema convention, with later lives suffixed like the files."""
    _, _, state, store_id = arm

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)
        await stop_capture(store_id, "s")
        assert current_store is not None
        first = current_store.get("asciinema:terminal-s")
        assert isinstance(first, str)
        assert json.loads(first.split("\n")[0])["title"] == "terminal session s"
        second_life = SessionState(opened_wall=1_700_000_100.0, opened_monotonic=0.0)
        await start_capture(store_id, "s", second_life, lambda: None)
        await stop_capture(store_id, "s")
        assert current_store.get("asciinema:terminal-s-2") is not None

    asyncio.run(scenario())


def test_opener_identity_rides_the_cast_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opener captured at session open lands as `ir_*` fields on the stored cast's header, so playback can group sessions by agent (absent fields present flat)."""
    from inspect_ranges._terminal.capture import finalize_terminal_captures
    from inspect_ranges._terminal.cast import SessionOpener

    process = FakeProcess(["chunk\n"])
    sample_store = Store()
    monkeypatch.setattr(
        capture_module, "_capture_target", lambda: (True, None, "ir-opener")
    )
    monkeypatch.setattr(capture_module, "_current_store", lambda: sample_store)
    monkeypatch.setattr(capture_module, "sandbox", lambda: FakeSandbox(process))
    tasks: list[asyncio.Task[None]] = []

    def run_background(fn: Any, *args: Any) -> None:
        tasks.append(asyncio.get_event_loop().create_task(fn(*args)))

    monkeypatch.setattr(capture_module, "background", run_background)
    state = SessionState(opened_wall=1_700_000_000.0, opened_monotonic=0.0)
    store_id = next(_STORE_IDS)

    async def scenario() -> None:
        await start_capture(
            store_id,
            "s",
            state,
            lambda: None,
            SessionOpener(
                agent_span_id="sp-1", agent_name="researcher", tool_span_id="sp-2"
            ),
        )
        await asyncio.sleep(0.05)
        await finalize_terminal_captures("ir-opener")
        cast = sample_store.get("asciinema:terminal-s")
        assert isinstance(cast, str)
        header = json.loads(cast.split("\n", 1)[0])
        assert header["ir_agent_span_id"] == "sp-1"
        assert header["ir_agent"] == "researcher"
        assert header["ir_tool_span_id"] == "sp-2"
        assert header["ir_session"] == "s"

    try:
        asyncio.run(scenario())
    finally:
        discard_sample_captures(store_id)


def test_current_opener_reads_the_enclosing_agent_span() -> None:
    """Inside an agent span, `_current_opener` captures the agent span id, the denormalized agent name, and the tool call's own span id; outside any span everything is None."""
    from inspect_ai.util import span
    from inspect_ai.util._store import init_subtask_store
    from inspect_ranges._terminal.tool import _current_opener

    async def scenario() -> None:
        init_subtask_store(Store())
        bare = _current_opener()
        assert bare.agent_span_id is None and bare.agent_name is None

        async with span("researcher", type="agent"):
            async with span("terminal", type="tool"):
                opener = _current_opener()
        assert opener.agent_name == "researcher"
        assert opener.agent_span_id is not None
        assert opener.tool_span_id is not None
        assert opener.tool_span_id != opener.agent_span_id

    asyncio.run(scenario())


def test_records_without_evidence_and_finalizes_by_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sample with no evidence session still records: chunks accumulate, the store cast writes, no mirroring and no cast file; the provider's project-keyed finalize stops it."""
    from inspect_ranges._terminal.capture import finalize_terminal_captures

    process = FakeProcess(["only-chunk\n"])
    sample_store = Store()
    monkeypatch.setattr(
        capture_module, "_capture_target", lambda: (True, None, "ir-no-evidence")
    )
    monkeypatch.setattr(capture_module, "_current_store", lambda: sample_store)
    monkeypatch.setattr(capture_module, "sandbox", lambda: FakeSandbox(process))
    tasks: list[asyncio.Task[None]] = []

    def run_background(fn: Any, *args: Any) -> None:
        tasks.append(asyncio.get_event_loop().create_task(fn(*args)))

    monkeypatch.setattr(capture_module, "background", run_background)
    state = SessionState(opened_wall=1_700_000_000.0, opened_monotonic=0.0)
    store_id = next(_STORE_IDS)

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)
        assert len(state.chunks) == 1
        await finalize_terminal_captures("ir-no-evidence")
        assert process.killed
        cast = sample_store.get("asciinema:terminal-s")
        assert isinstance(cast, str) and "only-chunk" in cast
        assert captures_for_tests(store_id) == {}
        await finalize_terminal_captures("ir-no-evidence")  # idempotent

    try:
        asyncio.run(scenario())
    finally:
        discard_sample_captures(store_id)


def test_dead_store_ref_skips_the_store_cast(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    """The deferred-teardown case: the sample store is gone, so the store write is skipped (by decision) while the evidence cast still lands."""
    global current_store
    evidence, _, state, store_id = arm

    async def scenario() -> None:
        global current_store
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)
        current_store = None  # drop the only strong reference; the weakref dies
        import gc

        gc.collect()
        await stop_capture(store_id, "s")
        assert (Path(evidence.location) / "terminal-s.cast").exists()

    asyncio.run(scenario())


def test_capture_off_outside_range_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capture_module, "_capture_target", lambda: (False, None, None))
    state = SessionState()

    async def scenario() -> None:
        await start_capture(1, "s", state, lambda: None)
        assert captures_for_tests(1) == {}
        await stop_all_captures(1)  # no-op, never raises

    asyncio.run(scenario())


def test_discovered_pane_gets_a_sibling_cast(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-pane sink the session's hooks created is discovered, tailed, mirrored to its own evidence stream, and assembled into a sibling cast beside the primary (file and store key alike), grouped under the session by its header and carrying the session's tool-call markers."""
    from inspect_ranges._terminal.session import pane_sink_path

    evidence, _, state, store_id = arm
    pane_path = pane_sink_path("s", state.token, "%7")
    pane_process = FakeProcess(["pane-output\n"])
    stub = PaneFakeSandbox(FakeProcess(["primary\n"]), {pane_path: pane_process})
    monkeypatch.setattr(capture_module, "sandbox", lambda: stub)
    monkeypatch.setattr(capture_module, "_PANE_POLL_S", 0.02)

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.1)  # the poller discovers and the tailers drain
        state.markers.append((0.5, "send s: 'ls'"))
        await stop_capture(store_id, "s")
        assert pane_process.killed
        directory = Path(evidence.location)
        assert (directory / "terminal-s.cast").exists()
        lines = (directory / "terminal-s.p7.cast").read_text().strip().split("\n")
        header = json.loads(lines[0])
        assert header["ir_session"] == "s"
        assert header["title"] == "terminal session s pane %7"
        events = [json.loads(line) for line in lines[1:]]
        assert any(kind == "o" and data == "pane-output\n" for _, kind, data in events)
        # the session's tool-call markers are session-level context, so the
        # pane's playback carries them too
        assert any(kind == "m" and "send s" in data for _, kind, data in events)
        assert ("terminal/s.p7", b"pane-output\n") in evidence.appended
        assert current_store is not None
        assert current_store.get("asciinema:terminal-s.p7") is not None

    asyncio.run(scenario())


def test_stop_collects_a_pane_the_poller_never_saw(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pane created just before close still gets its sibling cast: stop lists the sinks once more and reads an undiscovered one whole in a bounded one-shot (no tailer spawned just to be killed), mirroring the read to the pane's evidence stream."""
    from inspect_ranges._terminal.session import pane_sink_path

    evidence, _, state, store_id = arm
    pane_path = pane_sink_path("s", state.token, "%3")
    stub = PaneFakeSandbox(
        FakeProcess(["primary\n"]), contents={pane_path: "late-pane\n"}
    )
    monkeypatch.setattr(capture_module, "sandbox", lambda: stub)

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await stop_capture(store_id, "s")  # no sleep: the poller never swept
        sibling = Path(evidence.location) / "terminal-s.p3.cast"
        assert "late-pane" in sibling.read_text()
        assert ("terminal/s.p3", b"late-pane\n") in evidence.appended

    asyncio.run(scenario())


def test_another_life_pane_sink_is_never_picked_up(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The discovery parse is token-exact: a dead life's pane sink still on disk (its close never ran) is invisible to the new life's recorder, so no sibling cast records across lives."""
    from inspect_ranges._terminal.session import pane_sink_path

    evidence, _, state, store_id = arm
    stale_path = pane_sink_path("s", "ffffffff", "%2")
    stub = PaneFakeSandbox(
        FakeProcess(["primary\n"]),
        {stale_path: FakeProcess(["stale\n"])},
        contents={stale_path: "stale\n"},
    )
    monkeypatch.setattr(capture_module, "sandbox", lambda: stub)

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)
        await stop_capture(store_id, "s")
        directory = Path(evidence.location)
        assert sorted(path.name for path in directory.glob("terminal-*.cast")) == [
            "terminal-s.cast"
        ]

    asyncio.run(scenario())


def test_without_hooks_no_pane_discovery_runs(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the tool could not install the hooks (`pane_hooks=False`), no per-pane sink can exist, so the recorder runs no poller and spends no stop-time exec: even a sink-shaped file on disk produces no sibling cast."""
    from inspect_ranges._terminal.session import pane_sink_path

    evidence, _, state, store_id = arm
    pane_path = pane_sink_path("s", state.token, "%9")
    stub = PaneFakeSandbox(
        FakeProcess(["primary\n"]),
        {pane_path: FakeProcess(["orphan\n"])},
        contents={pane_path: "orphan\n"},
    )
    monkeypatch.setattr(capture_module, "sandbox", lambda: stub)
    monkeypatch.setattr(capture_module, "_PANE_POLL_S", 0.02)

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None, pane_hooks=False)
        await asyncio.sleep(0.1)
        await stop_capture(store_id, "s")
        directory = Path(evidence.location)
        assert sorted(path.name for path in directory.glob("terminal-*.cast")) == [
            "terminal-s.cast"
        ]

    asyncio.run(scenario())


def test_sibling_casts_share_the_session_store_cap(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The store cap is a per-session budget: the primary clips to the full cap exactly as before, and each sibling takes only what remains, so a many-pane session cannot blow the store; a starved multi-event sibling degrades to the header-and-marker stub with none of its output leaking past the cap."""
    from inspect_ranges._terminal.session import pane_sink_path

    _, _, state, store_id = arm
    pane_path = pane_sink_path("s", state.token, "%5")
    stub = PaneFakeSandbox(
        FakeProcess(["x" * 600]),
        {pane_path: FakeProcess(["y" * 200, "y" * 200, "y" * 200])},
    )
    monkeypatch.setattr(capture_module, "sandbox", lambda: stub)
    monkeypatch.setattr(capture_module, "cast_store_cap_bytes", lambda: 900)

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)
        await stop_capture(store_id, "s")
        assert current_store is not None
        primary = current_store.get("asciinema:terminal-s")
        sibling = current_store.get("asciinema:terminal-s.p5")
        assert isinstance(primary, str) and isinstance(sibling, str)
        # the primary fits the cap whole, exactly as it would alone; the
        # sibling is cut to the leftovers (a header-and-marker stub here),
        # not given a fresh cap of its own, and none of its events survive
        assert "clipped" not in primary and "x" * 600 in primary
        assert "clipped" in sibling and "y" not in sibling
        kinds = [json.loads(line)[1] for line in sibling.strip().split("\n")[1:]]
        assert kinds == ["m"]

    asyncio.run(scenario())


def test_no_pane_session_store_cast_is_byte_identical(
    arm: tuple[FakeEvidence, FakeProcess, SessionState, int],
) -> None:
    """The headline regression pin: a session that never spawned panes stores exactly the cast `assemble_cast` produces from its chunks and markers, one cast file, one store key, nothing pane-shaped anywhere."""
    from inspect_ranges._terminal.cast import assemble_cast
    from inspect_ranges._terminal.session import wait_channel_prefix

    evidence, _, state, store_id = arm

    async def scenario() -> None:
        await start_capture(store_id, "s", state, lambda: None)
        await asyncio.sleep(0.05)
        state.markers.append((0.5, "send s: 'ls'"))
        await stop_capture(store_id, "s")
        expected = assemble_cast(
            chunks=state.chunks,
            markers=state.markers,
            start_monotonic=state.opened_monotonic,
            start_wall=state.opened_wall,
            title="terminal session s",
            session="s",
            opener=None,
            channel_prefix=wait_channel_prefix("s", state.token),
        )
        assert current_store is not None
        assert current_store.get("asciinema:terminal-s") == expected
        directory = Path(evidence.location)
        assert sorted(path.name for path in directory.glob("terminal-*")) == [
            "terminal-s.cast"
        ]
        assert (directory / "terminal-s.cast").read_text() == expected

    asyncio.run(scenario())
