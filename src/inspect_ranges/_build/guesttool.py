"""Guest connection helper handed to recipe entrypoints (`IR_EXEC` / `IR_PUSH`).

Online recipes run on the host; this tool is their connection to the target guest, invoked through the generated wrappers the executor exports. The executor sets `IR_GUEST` (target name), `IR_GUEST_CIDS` (JSON name-to-CID map), `IR_GUEST_OS` (JSON name-to-os map; absent entries are linux), and `IR_EXEC_BUDGET_MS` (default per-exec budget); `exec` runs an argv or an uploaded script in the guest as root by default with an explicit `command_ms` budget, and `push` installs a local file into the guest, root-owned at the given mode (staged through `/tmp` because the daemon file plane acts as the agent user; recipes needing other ownership chown via `exec`). Every exec carries a budget because an unbudgeted exec that leaves live background children holds the exec plane (the challenges-v1 lesson); recipes that launch services should still redirect fds and use short budgets.

Windows targets (windows-ad-v1 slice 2): `--script` stages a PowerShell script to the Windows temp directory and runs it with `-ExecutionPolicy Bypass`; `push` stages and promotes via PowerShell (NTFS has no POSIX mode, so `--mode` is ignored); the contract default user "root" maps to the daemon's own identity, SYSTEM (the Windows daemon's file plane already acts as SYSTEM, and "root" is not a Windows principal — an explicit `--user` passes through).

Exit status: the in-guest rc passes through (signal deaths map to 128+signal); a budget expiry exits 124; any other channel failure exits 125 with the error on stderr.
"""

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path
from typing import cast

from .._channel.channel import (
    ChannelBudgetError,
    ChannelError,
    MessageChannel,
    request_id,
)
from .._channel.protocol import DAEMON_INBOUND_BULK_CAP, Budget, ExecRequest
from .._channel.vsock import HybridEndpoint, VsockTransport

EXIT_BUDGET = 124
EXIT_CHANNEL = 125
EXIT_USAGE = 2


def sockets_from_env(environ: dict[str, str]) -> dict[str, HybridEndpoint]:
    """Cloud Hypervisor guests' hybrid-vsock endpoints from `IR_GUEST_SOCKETS` (JSON name to [socket path, VMM uid]); empty when unset (pre-hybrid executors).

    Raises:
        ValueError: when the variable is present but malformed.
    """
    raw = environ.get("IR_GUEST_SOCKETS", "")
    if not raw:
        return {}
    try:
        parsed: object = json.loads(raw)
    except ValueError as error:
        raise ValueError(f"IR_GUEST_SOCKETS is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("IR_GUEST_SOCKETS must map guest names to [path, uid]")
    sockets: dict[str, HybridEndpoint] = {}
    for name, value in cast(dict[object, object], parsed).items():
        if (
            not isinstance(name, str)
            or not isinstance(value, list)
            or len(cast(list[object], value)) != 2
            or not isinstance(cast(list[object], value)[0], str)
            or not isinstance(cast(list[object], value)[1], int)
        ):
            raise ValueError("IR_GUEST_SOCKETS must map guest names to [path, uid]")
        path, uid = cast(list[object], value)
        sockets[name] = HybridEndpoint(Path(cast(str, path)), cast(int, uid))
    return sockets


def guest_os_from_env(environ: dict[str, str]) -> dict[str, str]:
    """Per-guest OS from `IR_GUEST_OS` (JSON name to `"linux"`/`"windows"`); empty when unset, and absent guests are linux (pre-windows executors set no map).

    Raises:
        ValueError: when the variable is present but malformed.
    """
    raw = environ.get("IR_GUEST_OS", "")
    if not raw:
        return {}
    try:
        parsed: object = json.loads(raw)
    except ValueError as error:
        raise ValueError(f"IR_GUEST_OS is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("IR_GUEST_OS must map guest names to os strings")
    guest_os: dict[str, str] = {}
    for name, value in cast(dict[object, object], parsed).items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("IR_GUEST_OS must map guest names to os strings")
        guest_os[name] = value
    return guest_os


def ps_quote(value: str) -> str:
    """Quote a value as a PowerShell literal string (embedded single quotes double): the one quoting rule every build-side PowerShell interpolation shares (slice-2 review)."""
    return "'" + value.replace("'", "''") + "'"


def cids_from_env(environ: dict[str, str]) -> tuple[str, dict[str, int]]:
    """The target guest and CID map from the `IR_*` contract environment.

    Raises:
        ValueError: when the contract variables are absent or malformed (the tool was run outside a recipe).
    """
    guest = environ.get("IR_GUEST", "")
    raw = environ.get("IR_GUEST_CIDS", "")
    if not guest or not raw:
        raise ValueError(
            "IR_GUEST / IR_GUEST_CIDS are not set; this tool runs inside a recipe entrypoint"
        )
    try:
        parsed: object = json.loads(raw)
    except ValueError as error:
        raise ValueError(f"IR_GUEST_CIDS is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("IR_GUEST_CIDS must map guest names to integer CIDs")
    cids: dict[str, int] = {}
    for name, cid in cast(dict[object, object], parsed).items():
        if (
            not isinstance(name, str)
            or isinstance(cid, bool)
            or not isinstance(cid, int)
        ):
            raise ValueError("IR_GUEST_CIDS must map guest names to integer CIDs")
        cids[name] = cid
    if guest not in cids:
        raise ValueError(f"IR_GUEST {guest!r} is not in IR_GUEST_CIDS")
    return guest, cids


def exit_code(rc: int) -> int:
    """Map a signed in-guest rc to a shell exit status (killed-by-signal becomes 128+signal)."""
    return 128 - rc if rc < 0 else rc


async def _run_exec(args: argparse.Namespace) -> int:
    guest, cids = cids_from_env(dict(os.environ))
    sockets = sockets_from_env(dict(os.environ))
    channel = MessageChannel(
        VsockTransport(cids, hybrid_sockets=sockets), label="recipe"
    )
    budget = Budget(command_ms=int(args.budget_ms))
    windows = guest_os_from_env(dict(os.environ)).get(guest) == "windows"
    script: str | None = args.script
    if script is not None:
        if args.argv:
            # silently ignoring trailing argv hid authoring mistakes (round-1)
            print("ir-exec: --script and argv are mutually exclusive", file=sys.stderr)
            return EXIT_USAGE
        if windows:
            # PowerShell parses the whole file before running it, so the
            # self-delete leads exactly like the sh prologue below
            remote = f"C:\\Windows\\Temp\\.ir-recipe-{request_id()}.ps1"
            body = (
                b"Remove-Item -LiteralPath $PSCommandPath -Force"
                b" -ErrorAction SilentlyContinue\n" + Path(script).read_bytes()
            )
            await channel.write_file(guest, remote, body)
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                remote,
            ]
        else:
            # the staged script is written by the daemon file plane (agent
            # user, 0700), so --script runs as root or the agent only; other
            # --user principals cannot read it (documented restriction)
            remote = f"/tmp/.ir-recipe-{request_id()}.sh"
            body = b'rm -f -- "$0"\n' + Path(script).read_bytes()
            await channel.write_file(guest, remote, body, mode=0o700)
            cmd = ["sh", remote]
    else:
        cmd = [str(part) for part in args.argv]
        if not cmd:
            print("ir-exec: no command given (argv or --script)", file=sys.stderr)
            return EXIT_USAGE
    user: str | None = str(args.user)
    if windows and user == "root":
        # the contract default, not a Windows principal: the daemon's own
        # identity (SYSTEM) is the Windows analogue
        user = None
    outcome = await channel.exec(
        guest,
        ExecRequest(
            id=request_id(),
            cmd=cmd,
            cwd=args.cwd,
            user=user,
            budget=budget,
        ),
    )
    sys.stdout.buffer.write(outcome.stdout)
    sys.stderr.buffer.write(outcome.stderr)
    return exit_code(outcome.rc)


PUSH_CHUNK_BYTES = DAEMON_INBOUND_BULK_CAP // 2
"""Large pushes stream in chunks of this size: half the daemon's inbound bulk cap by construction, so a chunk can never flirt with the refusal while the chunk count (and per-chunk request overhead) stays low. One knob for both guest OS paths."""

PUSH_PROMOTE_BASE_MS = 60_000
PUSH_PROMOTE_PER_GIB_MS = 30_000
"""The promote budget scales with payload size: reassembly plus digest plus install is three sequential full-file passes, so a fixed bound would time out exactly the appliance-sized pushes chunking exists for. The per-GiB allowance assumes a conservative effective pass rate."""


async def _sweep_staging(
    channel: MessageChannel, guest: str, staging: str, *, windows: bool
) -> None:
    """Best-effort removal of staged chunks after a mid-stream failure, so repeated large-push failures cannot fill the guest's temp space; the push's own error still propagates."""
    try:
        if windows:
            script = (
                f"Remove-Item -Path ({ps_quote(staging)} + '*') "
                "-Force -ErrorAction SilentlyContinue"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
            user: str | None = None
        else:
            cmd = [
                "sh",
                "-c",
                f"rm -f -- {shlex.quote(staging)} {shlex.quote(staging)}.*",
            ]
            user = "root"
        await channel.exec(
            guest,
            ExecRequest(
                id=request_id(), cmd=cmd, user=user, budget=Budget(command_ms=30_000)
            ),
        )
    except Exception:
        pass


async def _stage(
    channel: MessageChannel,
    guest: str,
    local: Path,
    size: int,
    staging: str,
    *,
    windows: bool,
) -> tuple[str, int] | None:
    """Stage `local` at `staging` in the guest: one write for small files (returns `None`), else streamed chunks `staging.NNNN` (returns the file's sha256 and the chunk count for the caller's reassemble-and-verify promote). Streaming bounds host memory to one chunk regardless of file size."""
    mode = None if windows else 0o600
    if size <= PUSH_CHUNK_BYTES:
        await channel.write_file(guest, staging, local.read_bytes(), mode=mode)
        return None
    hasher = hashlib.sha256()
    count = 0
    with local.open("rb") as handle:
        while chunk := handle.read(PUSH_CHUNK_BYTES):
            if count >= 10_000:
                # the linux reassembly orders parts by glob, which the 4-digit
                # suffix guarantees only up to here; refuse clearly instead of
                # failing the digest check after staging over a tebibyte
                raise ValueError(
                    f"{local} exceeds the chunked-push bound "
                    f"(10000 chunks of {PUSH_CHUNK_BYTES} bytes)"
                )
            hasher.update(chunk)
            await channel.write_file(guest, f"{staging}.{count:04d}", chunk, mode=mode)
            count += 1
    return hasher.hexdigest(), count


async def _run_push(args: argparse.Namespace) -> int:
    # The daemon file plane acts as the agent user, so privileged destinations
    # stage through /tmp and promote via a root exec (install creates parents
    # and applies the mode atomically with the copy).
    guest, cids = cids_from_env(dict(os.environ))
    sockets = sockets_from_env(dict(os.environ))
    channel = MessageChannel(
        VsockTransport(cids, hybrid_sockets=sockets), label="recipe"
    )
    local = Path(str(args.local))
    size = local.stat().st_size
    windows = guest_os_from_env(dict(os.environ)).get(guest) == "windows"
    user: str | None
    if windows:
        # the Windows daemon's file plane already acts as SYSTEM; the promote
        # only creates parents and moves (NTFS has no POSIX mode to apply)
        staging = f"C:\\Windows\\Temp\\.ir-push-{request_id()}"
        try:
            parts = await _stage(channel, guest, local, size, staging, windows=True)
        except BaseException:
            await _sweep_staging(channel, guest, staging, windows=True)
            raise
        if parts is None:
            promote_ps = (
                "$ErrorActionPreference='Stop'; "
                f"$parent = Split-Path -Parent {ps_quote(str(args.remote))}; "
                "if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }; "
                f"Move-Item -LiteralPath {ps_quote(staging)} "
                f"-Destination {ps_quote(str(args.remote))} -Force"
            )
        else:
            digest, count = parts
            part_list = ", ".join(
                ps_quote(f"{staging}.{index:04d}") for index in range(count)
            )
            # the finally sweeps parts and any partial assembly on every
            # outcome, the linux promote's unconditional-rm parity
            promote_ps = (
                "$ErrorActionPreference='Stop'; "
                f"$parts = @({part_list}); "
                f"$assembled = {ps_quote(staging)}; "
                "try { "
                "$out = [System.IO.File]::Create($assembled); "
                "try { foreach ($p in $parts) { $bytes = [System.IO.File]::ReadAllBytes($p); "
                "$out.Write($bytes, 0, $bytes.Length) } } finally { $out.Close() }; "
                "$hash = (Get-FileHash -LiteralPath $assembled -Algorithm SHA256).Hash.ToLower(); "
                f"if ($hash -ne '{digest}') "
                "{ throw ('reassembled push hash ' + $hash + ' does not match the source') }; "
                f"$parent = Split-Path -Parent {ps_quote(str(args.remote))}; "
                "if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }; "
                f"Move-Item -LiteralPath $assembled -Destination {ps_quote(str(args.remote))} -Force "
                "} finally { "
                "foreach ($p in $parts) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }; "
                "if (Test-Path -LiteralPath $assembled) "
                "{ Remove-Item -LiteralPath $assembled -Force -ErrorAction SilentlyContinue } }"
            )
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", promote_ps]
        user = None
    else:
        mode = int(str(args.mode), 8)
        staging = f"/tmp/.ir-push-{request_id()}"
        try:
            parts = await _stage(channel, guest, local, size, staging, windows=False)
        except BaseException:
            await _sweep_staging(channel, guest, staging, windows=False)
            raise
        quoted = shlex.quote(staging)
        if parts is None:
            promote = (
                f"rc=0; install -D -m {mode:o} -- {quoted} {shlex.quote(str(args.remote))}"
                f" || rc=$?; rm -f -- {quoted}; exit $rc"
            )
        else:
            digest, count = parts
            # zero-padded suffixes keep the glob in write order; the digest
            # check proves the reassembly before anything lands at the target
            promote = (
                # umask keeps the reassembled file 0600 like its parts;
                # parts are removed right after a good digest to halve the
                # disk high-water a large push demands
                f"umask 077; rc=0; cat -- {quoted}.* > {quoted} "
                f"&& printf '%s  %s\\n' {digest} {quoted} | sha256sum -c --quiet "
                f"&& rm -f -- {quoted}.* "
                f"&& install -D -m {mode:o} -- {quoted} {shlex.quote(str(args.remote))} "
                f"|| rc=$?; rm -f -- {quoted} {quoted}.*; exit $rc"
            )
        cmd = ["sh", "-c", promote]
        user = "root"
    promote_ms = PUSH_PROMOTE_BASE_MS + PUSH_PROMOTE_PER_GIB_MS * (
        size // (1024 * 1024 * 1024)
    )
    outcome = await channel.exec(
        guest,
        ExecRequest(
            id=request_id(),
            cmd=cmd,
            user=user,
            budget=Budget(command_ms=promote_ms),
        ),
    )
    if outcome.rc != 0:
        sys.stderr.buffer.write(outcome.stderr)
        print(
            f"ir-push: install to {args.remote!r} exited {outcome.rc}", file=sys.stderr
        )
    return exit_code(outcome.rc)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: `exec [--user U] [--budget-ms N] [--cwd DIR] (--script FILE | -- ARGV...)` or `push LOCAL REMOTE [--mode 644]`."""
    parser = argparse.ArgumentParser(prog="ir-guesttool", add_help=True)
    commands = parser.add_subparsers(dest="verb", required=True)
    from .recipes import DEFAULT_EXEC_BUDGET_MS

    default_budget = int(
        os.environ.get("IR_EXEC_BUDGET_MS", str(DEFAULT_EXEC_BUDGET_MS))
    )
    run = commands.add_parser("exec", help="run a command in the target guest")
    run.add_argument("--user", default="root")
    run.add_argument("--budget-ms", dest="budget_ms", type=int, default=default_budget)
    run.add_argument("--cwd", default=None)
    run.add_argument(
        "--script", default=None, help="upload and run a local script file"
    )
    run.add_argument("argv", nargs="*", help="command argv (after --)")
    push = commands.add_parser("push", help="write a local file into the target guest")
    push.add_argument("local")
    push.add_argument("remote")
    push.add_argument(
        "--mode",
        default="644",
        help="octal file mode, default 644 (ignored on Windows targets)",
    )
    args = parser.parse_args(argv)
    try:
        if args.verb == "exec":
            return asyncio.run(_run_exec(args))
        return asyncio.run(_run_push(args))
    except ChannelBudgetError as error:
        print(f"ir-guesttool: exec budget expired: {error}", file=sys.stderr)
        return EXIT_BUDGET
    except ChannelError as error:
        print(f"ir-guesttool: channel failure: {error}", file=sys.stderr)
        return EXIT_CHANNEL
    except ValueError as error:
        print(f"ir-guesttool: {error}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as error:
        # a typoed local path (--script, push LOCAL) must not traceback into
        # the pass-through rc space where it reads as a guest failure (round-1)
        print(f"ir-guesttool: {error}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover - exercised by the battery
    sys.exit(main())
