"""Spike Inspect sandbox provider: compiled range + vsock exec plane.

Registers `ranges_spike`. Scoped deliberately: single sample at a time, blocking
vsock I/O pushed to threads, no kept-alive ranges, no Windows path. The point is
to validate the chain eval -> provider -> schema -> compiled range -> booted VMs
-> vsock, and to run Inspect's self_check against it.
"""

import asyncio
import base64
import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Union

from inspect_ai.util import (
    ExecResult,
    OutputLimitExceededError,
    SandboxEnvironment,
    sandboxenv,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironmentConfigType
from inspect_ai.util._sandbox.limits import SandboxEnvironmentLimits

from compiler import compile_range
from inspect_ranges.schema import load_range

HERE = Path(__file__).parent
PROJECT = "e2espike"
PORT = 5000

_ERRNO_EXC: dict[str, type[Exception]] = {
    "ENOENT": FileNotFoundError,
    "EISDIR": IsADirectoryError,
    "ENOTDIR": NotADirectoryError,
    "EACCES": PermissionError,
    "EPERM": PermissionError,
}


def _compose(*args: str) -> None:
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", str(HERE / "compose.yaml"), *args],
        check=True,
        cwd=HERE,
        capture_output=True,
        text=True,
    )


def _vsock_request(cid: int, header: dict[str, Any], payload: bytes = b"") -> tuple[dict[str, Any], bytes]:
    """One blocking request: send header (+payload), read JSON reply (+stream if sized)."""
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    try:
        s.connect((cid, PORT))
        s.sendall((json.dumps(header) + "\n").encode())
        if payload:
            s.sendall(payload)
        line = b""
        while not line.endswith(b"\n"):
            c = s.recv(1)
            if not c:
                raise ConnectionError("eof from daemon")
            line += c
        reply: dict[str, Any] = json.loads(line)
        body = b""
        if header["op"] == "read" and "size" in reply:
            remaining = reply["size"]
            chunks = []
            while remaining:
                chunk = s.recv(min(1 << 20, remaining))
                if not chunk:
                    raise ConnectionError("short read stream")
                chunks.append(chunk)
                remaining -= len(chunk)
            body = b"".join(chunks)
        return reply, body
    finally:
        s.close()


def _raise_for_errno(reply: dict[str, Any], path: str) -> None:
    if "error" in reply:
        exc = _ERRNO_EXC.get(reply.get("errno", ""))
        if exc is not None:
            raise exc(reply["error"] + f": {path}")
        raise RuntimeError(f"{path}: {reply['error']}")


@sandboxenv(name="ranges_spike")
class RangesSpikeSandboxEnvironment(SandboxEnvironment):
    """One vsock-controlled VM in a compiled range."""

    def __init__(self, name: str, cid: int) -> None:
        self.name = name
        self.cid = cid

    @classmethod
    def config_files(cls) -> list[str]:
        return ["range.yaml"]

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        spec_path = Path(config) if isinstance(config, str) else HERE / "range.yaml"
        if not spec_path.is_absolute():
            spec_path = HERE / spec_path
        spec = load_range(spec_path)
        allocation = compile_range(spec, HERE / "tmp" / "render")

        def up() -> None:
            _compose("up", "-d", "--build", "--wait")
            _compose("exec", "range", "bash", "/render/boot-vms.sh")

        await asyncio.to_thread(up)

        envs: dict[str, SandboxEnvironment] = {}
        for name, guest in allocation.items():
            env = cls(name, guest["cid"])
            await env._wait_ready()
            envs[name] = env
        # Inspect's "default" is the agent's box
        attacker_name = spec.attacker.host or spec.attacker.name
        envs = {"default": envs[attacker_name], **envs}
        return envs

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        await asyncio.to_thread(_compose, "down", "-v")

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        pass

    async def _wait_ready(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                reply, _ = await asyncio.to_thread(_vsock_request, self.cid, {"op": "ping"})
                if reply.get("ok"):
                    return
            except OSError:
                await asyncio.sleep(0.3)
        raise TimeoutError(f"guest {self.name} (cid {self.cid}) daemon not reachable")

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        header: dict[str, Any] = {"op": "exec", "cmd": cmd, "cwd": cwd, "env": env, "user": user, "timeout": timeout}
        if input is not None:
            raw = input.encode() if isinstance(input, str) else input
            header["input"] = base64.b64encode(raw).decode()
        reply, _ = await asyncio.to_thread(_vsock_request, self.cid, header)
        if reply.get("timeout"):
            raise TimeoutError("Command timed out")
        if "error" in reply:
            exc = _ERRNO_EXC.get(reply.get("errno", ""))
            if exc is not None:
                raise exc(reply["error"])
            raise RuntimeError(reply["error"])
        stdout = base64.b64decode(reply["stdout"]).decode("utf-8", errors="replace")
        stderr = base64.b64decode(reply["stderr"]).decode("utf-8", errors="replace")
        if reply.get("stdout_truncated") or reply.get("stderr_truncated"):
            raise OutputLimitExceededError("16 MiB", stdout)
        rc = reply["rc"]
        if rc == 126 and "permission denied" in stderr.lower():
            raise PermissionError(stderr.strip())
        return ExecResult(success=rc == 0, returncode=rc, stdout=stdout, stderr=stderr)

    async def write_file(self, file: str, contents: str | bytes) -> None:
        data = contents.encode() if isinstance(contents, str) else contents
        reply, _ = await asyncio.to_thread(
            _vsock_request, self.cid, {"op": "write", "path": file, "size": len(data)}, data
        )
        _raise_for_errno(reply, file)

    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:  # type: ignore[override]
        stat, _ = await asyncio.to_thread(_vsock_request, self.cid, {"op": "stat", "path": file})
        _raise_for_errno(stat, file)
        if stat.get("isdir"):
            raise IsADirectoryError(f"Is a directory: {file}")
        limit = SandboxEnvironmentLimits.MAX_READ_FILE_SIZE
        if stat["size"] > limit:
            raise OutputLimitExceededError(SandboxEnvironmentLimits.MAX_READ_FILE_SIZE_STR, None)
        reply, body = await asyncio.to_thread(_vsock_request, self.cid, {"op": "read", "path": file})
        _raise_for_errno(reply, file)
        return body.decode("utf-8") if text else body
