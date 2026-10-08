"""Run inspect_ai's sandbox self_check against the Windows vsock daemon.

Reuses the e2e-provider spike's `SandboxEnvironment` implementation unchanged (same host-side code that scored 41/44 against the Linux daemon), pointed at the Windows guest's CID. The guest image carries busybox-w32 applets in `C:\\usr\\bin` (on PATH) so the suite's POSIX userland (`sh`, `cat`, `ls`, ...) resolves; expected failures that are POSIX-semantics-bound on NTFS/Windows are declared in XFAIL and justified in the spike README.

Usage: ../../../.venv/bin/python harness/run_self_check_win.py [cid]
"""

import inspect as pyinspect
import sys
from pathlib import Path

import anyio

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "e2e-provider"))

import inspect_ai.util._sandbox.self_check as self_check_module  # noqa: E402
from provider import RangesSpikeSandboxEnvironment  # noqa: E402

CID = int(sys.argv[1]) if len(sys.argv) > 1 else 9

XFAIL: dict[str, str] = {
    # (the write-permission siblings PASS: busybox chmod -w maps to the
    # read-only attribute, which Windows honors even for SYSTEM writes)
    "test_read_file_not_allowed": "no POSIX read-permission bit on NTFS; chmod -r cannot deny reads",
    # user management is Windows-native, not adduser/userdel; the user= exec
    # path itself is covered by the native supplement (rangeuser)
    "test_exec_as_user": "suite provisions its user via adduser/userdel, absent on Windows",
    # genuine platform limits
    "test_exec_large_command": "Windows caps the command line at 32,767 UTF-16 chars (vs ARG_MAX 2 MiB); the suite's ~1 MiB argv exceeds it; daemon replies E2BIG",
    "test_exec_timeout_not_raised_on_fast_signal_death": "no POSIX signals on Windows; busybox's kill emulation exits 0, not 143",
}


async def main() -> int:
    env = RangesSpikeSandboxEnvironment("win", CID)
    tests = sorted(
        (name, fn)
        for name, fn in pyinspect.getmembers(self_check_module, pyinspect.iscoroutinefunction)
        if name.startswith("test_")
    )
    passed, xfailed, xpassed, failed = [], [], [], []
    for name, fn in tests:
        try:
            await fn(env)
        except Exception as e:
            if name in XFAIL:
                xfailed.append(name)
                print(f"XFAIL {name} ({XFAIL[name]})")
            else:
                failed.append((name, repr(e)))
                print(f"FAIL  {name}: {e!r}")
        else:
            if name in XFAIL:
                xpassed.append(name)
                print(f"XPASS {name} (expected to fail; revisit the xfail list)")
            else:
                passed.append(name)
                print(f"pass  {name}")

    print(
        f"\nself_check vs Windows daemon: {len(passed)} passed, {len(xfailed)} xfailed, "
        f"{len(xpassed)} xpassed, {len(failed)} FAILED of {len(tests)}"
    )
    for name, err in failed:
        print(f"  UNEXPECTED: {name}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(anyio.run(main))
