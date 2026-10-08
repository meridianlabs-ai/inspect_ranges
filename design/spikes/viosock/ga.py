#!/usr/bin/env python3
"""qemu-ga driver for the ad-domain spike.

Runs PowerShell inside Windows guests through the range container's virsh (the transport the win-guest spike validated), polls `guest-exec-status` to completion, and provides a race-free reboot barrier: capture `LastBootUpTime` before issuing a reboot, then wait until it changes (watching for the agent to drop is racy — a Windows reboot can complete between two orchestration steps).

Usage (always from the spike directory, so `docker compose` finds the project):

    python3 ga.py ps <domain> <timeout-seconds> < script.ps1
    python3 ga.py wait <domain> [timeout]            # until guest-ping answers
    python3 ga.py boottime <domain>                  # print LastBootUpTime (FILETIME)
    python3 ga.py wait-newboot <domain> <old> [timeout]
    python3 ga.py settime <domain>                   # push host time into the guest

`ps` prints guest stdout, sends guest stderr to our stderr, and exits with the guest exit code (124 on timeout). Scripts arrive via stdin and are sent as `-EncodedCommand` (UTF-16LE base64), which sidesteps all quoting across the shell -> docker -> virsh -> JSON -> cmd chain. Payloads stay far below the ~64 KB virsh argv limit the win-guest spike hit.
"""

import base64
import json
import subprocess
import sys
import time
from typing import Any

BOOTTIME_PS = "$ProgressPreference='SilentlyContinue'; (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToFileTimeUtc()"


def virsh_ga(dom: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """One qemu-agent-command round trip; None if the agent is unreachable."""
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "range", "virsh", "-c", "qemu:///system", "qemu-agent-command", dom, json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)["return"]


def ping(dom: str) -> bool:
    return virsh_ga(dom, {"execute": "guest-ping"}) is not None


def wait_up(dom: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ping(dom):
            return
        time.sleep(1)
    sys.exit(f"ga.py: {dom}: guest agent not up after {timeout:.0f}s")


def run_ps(dom: str, script: str, timeout: float) -> tuple[int, str, str]:
    """Execute PowerShell in the guest. Exit code 125 means the agent was unreachable (e.g. mid-reboot), 124 means timeout."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    ret = virsh_ga(
        dom,
        {
            "execute": "guest-exec",
            "arguments": {
                "path": "powershell.exe",
                "arg": ["-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                "capture-output": True,
            },
        },
    )
    if ret is None:
        return 125, "", f"{dom}: guest-exec failed (agent unreachable)"
    pid = ret["pid"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = virsh_ga(dom, {"execute": "guest-exec-status", "arguments": {"pid": pid}})
        if status is not None and status.get("exited"):
            out = base64.b64decode(status.get("out-data", "")).decode(errors="replace")
            err = base64.b64decode(status.get("err-data", "")).decode(errors="replace")
            return status.get("exitcode", 1), out, err
        time.sleep(2)
    return 124, "", f"{dom}: pid {pid} still running after {timeout:.0f}s"


def wait_newboot(dom: str, old: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code, out, _ = run_ps(dom, BOOTTIME_PS, min(60, deadline - time.monotonic()))
        if code == 0 and out.strip() and out.strip() != old.strip():
            return
        time.sleep(3)
    sys.exit(f"ga.py: {dom}: no new boot observed within {timeout:.0f}s")


def set_time(dom: str) -> None:
    """Push host wall-clock into the guest (post-restore clock fix, as the provider would)."""
    ret = virsh_ga(dom, {"execute": "guest-set-time", "arguments": {"time": time.time_ns()}})
    if ret is None:
        sys.exit(f"ga.py: {dom}: guest-set-time failed")


def cli_ps(dom: str, script: str, timeout: float) -> None:
    code, out, err = run_ps(dom, script, timeout)
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, file=sys.stderr, end="" if err.endswith("\n") else "\n")
    sys.exit(code)


def main() -> None:
    cmd, dom = sys.argv[1], sys.argv[2]
    if cmd == "ps":
        cli_ps(dom, sys.stdin.read(), float(sys.argv[3]))
    elif cmd == "wait":
        wait_up(dom, float(sys.argv[3]) if len(sys.argv) > 3 else 300)
    elif cmd == "boottime":
        cli_ps(dom, BOOTTIME_PS, 120)
    elif cmd == "wait-newboot":
        wait_newboot(dom, sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 600)
    elif cmd == "settime":
        set_time(dom)
    else:
        sys.exit(f"ga.py: unknown command {cmd}")


if __name__ == "__main__":
    main()
