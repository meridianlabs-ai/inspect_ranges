"""The terminal tool's capture leg: per-session recording, evidence mirroring, cast assembly, and the store cast.

Each open session gets one streaming `exec_remote` tailing its pipe-pane sink; every output event is timestamped host-side on arrival, appended to the session's chunk list (for playback assembly), and mirrored to the `terminal/<session>` evidence stream when the sample has an evidence session. At session close, and for still-open sessions at sample finalize (the provider's `finalize_terminal_captures`, plus the evidence producer where one exists), the chunks and per-call markers assemble into an asciicast v2 document, written into the sample store under `asciinema:<name>` (clipped to `INSPECT_RANGES_CAST_STORE_CAP_MB`; the viewer-side binding) and, when a local evidence location exists, as a file beside the sample's evidence.

Capture is observability, never load-bearing: it requires a range sandbox (evidence optional), degrades to off everywhere else, and no failure in this module ever reaches the agent. The sample handle is used inside this module only and never surfaces to the agent (`terminal-tool-v1.md`, recorded exceptions).
"""

import logging
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
from inspect_ai.util import SandboxEnvironment, background, sandbox
from inspect_ai.util._sandbox.exec_remote import ExecRemoteProcess, ExecStdout

from .cast import SessionOpener, assemble_cast, cast_store_cap_bytes, clip_cast
from .session import (
    SessionState,
    pane_id_from_sink,
    pane_label,
    pane_sink_glob,
    sink_path,
    wait_channel_prefix,
)

if TYPE_CHECKING:
    from .._provider.evidence import EvidenceSession

logger = logging.getLogger("inspect_ranges.terminal")

__all__ = [
    "discard_sample_captures",
    "finalize_terminal_captures",
    "start_capture",
    "stop_all_captures",
    "stop_capture",
]


@dataclass
class _PaneCapture:
    """One agent-created pane's live tailer inside a session's recorder, with its own chunk buffer for the sibling cast."""

    pane_id: str
    sink: str
    chunks: list[tuple[float, bytes]] = field(default_factory=list[tuple[float, bytes]])
    process: ExecRemoteProcess | None = None
    drained: anyio.Event = field(default_factory=anyio.Event)


@dataclass
class _Capture:
    """One session's live recorder; `evidence` is `None` when the sample runs without an evidence session (recording and the store cast still happen).

    `environment` is the sandbox resolved at open time: the pane-discovery poller runs as a background task, outside the tool call's context, so it must carry the handle rather than resolve the ambient one. `panes` holds one tailer per agent-created pane the poller has discovered.
    """

    session: str
    state: SessionState
    evidence: "EvidenceSession | None"
    opener: SessionOpener | None = None
    environment: SandboxEnvironment | None = None
    process: ExecRemoteProcess | None = None
    stopped: bool = False
    pane_hooks: bool = True
    drained: anyio.Event = field(default_factory=anyio.Event)
    closed: anyio.Event = field(default_factory=anyio.Event)
    panes: dict[str, _PaneCapture] = field(default_factory=dict[str, _PaneCapture])


@dataclass
class _SampleCaptures:
    """All of one sample's recorders, with the finalize producer registered once (evidence path) and the sample store held weakly for cast writes."""

    evidence: "EvidenceSession | None"
    on_finalize: "Callable[[], None]"
    store_ref: "weakref.ref[Any] | None" = None
    captures: dict[str, _Capture] = field(default_factory=dict[str, _Capture])


_SAMPLES: dict[int, _SampleCaptures] = {}

_PROJECTS: dict[str, int] = {}
"""Project name to the sample's capture registry id, so the provider's teardown can finalize by project (the deferred-teardown path runs outside the sample's store context)."""


def _capture_target() -> "tuple[bool, EvidenceSession | None, str | None]":
    """Whether this sample records at all (any range sandbox does), plus its evidence session (optional: mirroring and cast files need it, recording does not) and project name."""
    try:
        from .._provider.provider import sample_handle_for

        handle = sample_handle_for(sandbox())
    except Exception:  # noqa: BLE001  (not a range sandbox: capture off)
        return False, None, None
    evidence: EvidenceSession | None = getattr(handle, "evidence", None)
    project: str | None = getattr(handle, "project", None)
    return True, evidence, project


def _current_store() -> object | None:
    """The sample's store object, held by weakref for the cast's store write (an interrupted sample's deferred teardown finds it dead and skips the write, by decision)."""
    try:
        from inspect_ai.util import store as inspect_store

        return inspect_store()
    except Exception:  # noqa: BLE001
        return None


async def start_capture(
    store_id: int,
    session: str,
    state: SessionState,
    on_finalize: "Callable[[], None]",
    opener: SessionOpener | None = None,
    pane_hooks: bool = True,
) -> None:
    """Start recording an open session; quietly a no-op outside a range sandbox.

    `on_finalize` runs once at sample finalize after every recorder stops (the tool passes its state cleanup). `opener` is the agent context that opened the session, captured by the tool at open time; it rides the cast header so playback can group sessions by agent. `pane_hooks=False` says the tool could not install the pane-capture hooks on this session, so no per-pane sink can ever appear and the recorder skips pane discovery entirely.
    """
    recording, evidence, project = _capture_target()
    if not recording:
        return
    try:
        sample = _SAMPLES.get(store_id)
        if sample is None:
            sample_store = _current_store()
            sample = _SampleCaptures(
                evidence=evidence,
                on_finalize=on_finalize,
                store_ref=weakref.ref(sample_store)
                if sample_store is not None
                else None,
            )
            _SAMPLES[store_id] = sample
            if project is not None:
                _PROJECTS[project] = store_id

            async def finalize() -> None:
                await stop_all_captures(store_id)

            if evidence is not None:
                evidence.register_producer(finalize)
        environment = sandbox()
        capture = _Capture(
            session=session,
            state=state,
            evidence=sample.evidence,
            opener=opener,
            environment=environment,
            pane_hooks=pane_hooks,
        )
        sample.captures[session] = capture
        process = await environment.exec_remote(
            [
                "sh",
                "-c",
                f"touch {sink_path(session)} && tail -c +1 -F {sink_path(session)}",
            ],
            stream=True,
        )
        capture.process = process
        background(_consume, capture, process)
        if pane_hooks:
            background(_discover_panes, capture)
    except Exception as error:  # noqa: BLE001  (observability, never load-bearing)
        logger.info("terminal capture for %r is off: %s", session, error)


async def _consume(capture: _Capture, process: ExecRemoteProcess) -> None:
    """Drain the recorder's output events: timestamp, retain for the cast, mirror to evidence."""
    stream = f"terminal/{capture.session}"
    try:
        async for event in process:
            if isinstance(event, ExecStdout) and event.data:
                data = event.data.encode(errors="replace")
                capture.state.chunks.append((time.monotonic(), data))
                if capture.evidence is not None:
                    await capture.evidence.append_driver(stream, data)
    except Exception as error:  # noqa: BLE001
        logger.info("terminal capture stream for %r ended: %s", capture.session, error)
    finally:
        capture.drained.set()


_PANE_POLL_S = 5.0
"""How often the recorder sweeps for per-pane sinks the session's tmux hooks created. The cadence buys evidence-mirror timeliness and finer sibling-cast timestamps, never completeness: `stop_capture` reads any still-undiscovered sink whole, and a tailer the sweep does attach reads its sink from byte one."""

_PANE_EXEC_TIMEOUT_S = 30
"""Bound on the discovery and collection execs (the tool layer's exec convention): a wedged guest must not hang the poller, a close, or sample finalize."""


async def _discover_panes(capture: _Capture) -> None:
    """Sweep for agent-created panes' sinks on a fixed cadence until the recorder stops; `stop_capture` wakes the wait so a stop never idles out the cadence."""
    while not capture.stopped:
        try:
            await _sweep_pane_sinks(capture)
        except Exception as error:  # noqa: BLE001
            logger.info("terminal pane sweep for %r: %s", capture.session, error)
        with anyio.move_on_after(_PANE_POLL_S):
            await capture.closed.wait()


async def _list_pane_sinks(capture: _Capture) -> list[tuple[str, str]]:
    """The life's per-pane sinks on the guest right now, as `(pane id, sink path)` pairs; the glob embeds the life token, so a dead life's leftovers are invisible."""
    if capture.environment is None:
        return []
    glob = pane_sink_glob(capture.session, capture.state.token)
    listed = await capture.environment.exec(
        ["sh", "-c", f"ls {glob} 2>/dev/null || true"], timeout=_PANE_EXEC_TIMEOUT_S
    )
    pairs: list[tuple[str, str]] = []
    for line in listed.stdout.splitlines():
        sink = line.strip()
        pane_id = pane_id_from_sink(sink, capture.session, capture.state.token)
        if pane_id is not None:
            pairs.append((pane_id, sink))
    return pairs


async def _sweep_pane_sinks(capture: _Capture) -> None:
    """One discovery pass: attach a tailer to every sink not yet tailed.

    A stopped capture attaches nothing (the gate is re-checked after the listing's await, so a sweep in flight when the stop lands cannot slip a tailer in). An agent replacing a hooked pane's `pipe-pane` with its own (one pipe per pane is tmux's rule) merely stops the sink growing, which a `tail -F` tolerates by design.
    """
    for pane_id, sink in await _list_pane_sinks(capture):
        if pane_id in capture.panes or capture.stopped or capture.environment is None:
            continue
        pane = _PaneCapture(pane_id=pane_id, sink=sink)
        capture.panes[pane_id] = pane
        pane.process = await capture.environment.exec_remote(
            ["sh", "-c", f"tail -c +1 -F {sink}"], stream=True
        )
        background(_consume_pane, capture, pane, pane.process)


async def _collect_late_panes(capture: _Capture) -> None:
    """Stop-time completeness: read any still-undiscovered pane sink whole, in one bounded exec per sink, rather than spawning a tailer just to kill it (deterministic beats racy at close). The read lands as one chunk, timestamped now, and mirrors to the pane's evidence stream like tailed output."""
    if capture.environment is None:
        return
    for pane_id, sink in await _list_pane_sinks(capture):
        if pane_id in capture.panes:
            continue
        pane = _PaneCapture(pane_id=pane_id, sink=sink)
        capture.panes[pane_id] = pane
        pane.drained.set()
        read = await capture.environment.exec(
            ["sh", "-c", f"cat {sink}"], timeout=_PANE_EXEC_TIMEOUT_S
        )
        if read.success and read.stdout:
            data = read.stdout.encode(errors="replace")
            pane.chunks.append((time.monotonic(), data))
            if capture.evidence is not None:
                stream = f"terminal/{capture.session}.{pane_label(pane.pane_id)}"
                await capture.evidence.append_driver(stream, data)


async def _consume_pane(
    capture: _Capture, pane: _PaneCapture, process: ExecRemoteProcess
) -> None:
    """Drain one pane tailer's output events: timestamp, retain for the sibling cast, mirror to evidence (the dot joint keeps the stream clear of every session name, whose grammar has no dots)."""
    stream = f"terminal/{capture.session}.{pane_label(pane.pane_id)}"
    try:
        async for event in process:
            if isinstance(event, ExecStdout) and event.data:
                data = event.data.encode(errors="replace")
                pane.chunks.append((time.monotonic(), data))
                if capture.evidence is not None:
                    await capture.evidence.append_driver(stream, data)
    except Exception as error:  # noqa: BLE001
        logger.info(
            "terminal pane capture stream for %r pane %s ended: %s",
            capture.session,
            pane.pane_id,
            error,
        )
    finally:
        pane.drained.set()


async def stop_capture(store_id: int, session: str) -> None:
    """Stop one session's recorder and write its cast; idempotent.

    `kill` enqueues output buffered since the recorder's last poll, so the cast waits (bounded) for the consume task to drain those final events before assembly.
    """
    sample = _SAMPLES.get(store_id)
    if sample is None:
        return
    capture = sample.captures.pop(session, None)
    if capture is None or capture.stopped:
        return
    capture.stopped = True
    capture.closed.set()
    if capture.pane_hooks:
        try:
            # a pane created since the poller's last pass is read whole here
            # (the stopped flag above keeps the poller from racing new tailers
            # in); without hooks no pane sink can exist, so no exec is spent
            await _collect_late_panes(capture)
        except Exception as error:  # noqa: BLE001
            logger.info("terminal pane collect for %r: %s", capture.session, error)
    if capture.process is not None:
        try:
            with anyio.move_on_after(30):
                await capture.process.kill()
        except Exception:  # noqa: BLE001
            pass
        with anyio.move_on_after(10):
            await capture.drained.wait()
    panes = list(capture.panes.values())
    for pane in panes:
        if pane.process is not None:
            try:
                with anyio.move_on_after(30):
                    await pane.process.kill()
            except Exception:  # noqa: BLE001
                pass
    with anyio.move_on_after(10):
        for pane in panes:
            await pane.drained.wait()
    _write_cast(sample, capture)


def discard_sample_captures(store_id: int) -> None:
    """Drop a sample's capture registry entry without stopping anything (GC-time cleanup when the sample's store was collected before finalize ran, so the id can be reused safely)."""
    _SAMPLES.pop(store_id, None)
    for project in [p for p, sid in _PROJECTS.items() if sid == store_id]:
        _PROJECTS.pop(project, None)


async def finalize_terminal_captures(project: str) -> None:
    """Stop the project's recorders and write their casts; the provider's teardown hook, idempotent, never raises.

    Keyed by project rather than the ambient store because an interrupted sample's deferred teardown runs at task cleanup, outside the sample's store context; there the casts still reach evidence (when present) while the store write is skipped (the weakref resolves dead), by decision.
    """
    store_id = _PROJECTS.get(project)
    if store_id is not None:
        await stop_all_captures(store_id)


async def stop_all_captures(store_id: int) -> None:
    """The finalize path: stop every live recorder, write their casts, run the tool cleanup; never raises."""
    sample = _SAMPLES.get(store_id)
    if sample is None:
        return
    for session in list(sample.captures):
        try:
            await stop_capture(store_id, session)
        except Exception as error:  # noqa: BLE001
            logger.info("terminal capture finalize for %r: %s", session, error)
    _SAMPLES.pop(store_id, None)
    for project in [p for p, sid in _PROJECTS.items() if sid == store_id]:
        _PROJECTS.pop(project, None)
    try:
        sample.on_finalize()
    except Exception:  # noqa: BLE001
        pass


def _write_cast(sample: _SampleCaptures, capture: _Capture) -> None:
    """Assemble the session's asciicasts (with the blocking signal's echo scrubbed, as tool results are) and deliver them: into the sample store always (capped), and beside the sample's evidence when a local evidence location exists. The evidence mirrors (`terminal/<session>` and its pane streams) stay raw.

    The primary cast assembles exactly as it always has, so a session with no agent-created panes records byte-identically. Each discovered pane that produced output gets a sibling cast named `<session>.p<N>` (the dot joint can never collide with another session's name, whose grammar has no dots), carrying the same `ir_session` and opener header so playback groups it under the session, and the same echo scrub (a no-op in a pane the signal never echoed in). Siblings share the session's store cap: the primary clips to the full cap as before, and each sibling takes what remains, so a many-pane session cannot blow the store.

    A session name can record more than one life (close then reopen, or reopen after dying), each with its own cast: later lives get a numbered suffix rather than overwriting the earlier record, in the store and on disk alike.
    """
    channel_prefix = wait_channel_prefix(capture.session, capture.state.token)
    try:
        cast = assemble_cast(
            chunks=capture.state.chunks,
            markers=capture.state.markers,
            start_monotonic=capture.state.opened_monotonic,
            start_wall=capture.state.opened_wall,
            title=f"terminal session {capture.session}",
            session=capture.session,
            opener=capture.opener,
            channel_prefix=channel_prefix,
        )
    except Exception as error:  # noqa: BLE001
        logger.info("terminal cast for %r not assembled: %s", capture.session, error)
        return
    cap = cast_store_cap_bytes()
    stored = _store_cast(sample, capture.session, cast, cap)
    _evidence_cast(capture, capture.session, cast)
    panes = sorted(capture.panes.values(), key=lambda pane: int(pane.pane_id[1:]))
    for pane in panes:
        if not pane.chunks:
            continue
        try:
            sibling = assemble_cast(
                chunks=pane.chunks,
                # the session's tool-call markers are session-level context
                # (open/send/read), so every pane's playback carries them
                markers=capture.state.markers,
                start_monotonic=capture.state.opened_monotonic,
                start_wall=capture.state.opened_wall,
                title=f"terminal session {capture.session} pane {pane.pane_id}",
                session=capture.session,
                opener=capture.opener,
                channel_prefix=channel_prefix,
            )
        except Exception as error:  # noqa: BLE001
            logger.info(
                "terminal cast for %r pane %s not assembled: %s",
                capture.session,
                pane.pane_id,
                error,
            )
            continue
        name = f"{capture.session}.{pane_label(pane.pane_id)}"
        stored += _store_cast(sample, name, sibling, max(cap - stored, 0))
        _evidence_cast(capture, name, sibling)


def _evidence_cast(capture: _Capture, name: str, cast: str) -> None:
    """Write one cast file beside the sample's evidence when a local evidence location exists; never raises."""
    if capture.evidence is None:
        return
    location = capture.evidence.location
    if "://" in location:
        logger.info("terminal cast for %r not written: remote evidence location", name)
        return
    try:
        directory = Path(location)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"terminal-{name}.cast"
        serial = 2
        while path.exists():
            path = directory / f"terminal-{name}-{serial}.cast"
            serial += 1
        path.write_text(cast)
    except Exception as error:  # noqa: BLE001
        logger.info("terminal cast for %r not written: %s", name, error)


def _store_cast(sample: _SampleCaptures, name: str, cast: str, cap_bytes: int) -> int:
    """Write the cast into the sample store under the `asciinema:<name>` convention, clipped to `cap_bytes`, and report the bytes written (zero when skipped) so a session's sibling casts can share its cap; never raises.

    The key convention is what the viewer-side asciicast rendering binds to; until that lands the keys are inert store entries. The store write targets the sample's own store object (weakly held), so an interrupted sample's deferred teardown skips it rather than writing into another context's store.
    """
    try:
        sample_store = sample.store_ref() if sample.store_ref is not None else None
        if sample_store is None:
            return 0
        clipped = clip_cast(cast, cap_bytes)
        base = f"asciinema:terminal-{name}"
        key = base
        serial = 2
        while sample_store.get(key) is not None:
            key = f"{base}-{serial}"
            serial += 1
        sample_store.set(key, clipped)
        return len(clipped.encode(errors="replace"))
    except Exception as error:  # noqa: BLE001
        logger.info("terminal cast for %r not stored: %s", name, error)
        return 0


def captures_for_tests(store_id: int) -> dict[str, Any]:
    """Test visibility into the live registry (sessions currently recording)."""
    sample = _SAMPLES.get(store_id)
    return dict(sample.captures) if sample is not None else {}
