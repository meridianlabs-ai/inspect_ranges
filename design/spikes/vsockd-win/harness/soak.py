#!/usr/bin/env python3
"""Soak the Windows vsock daemon: 500 sequential execs, 50 parallel execs, and 20 file round trips. Target: zero failures (qemu-ga baseline was ~5-7% flake). Stdlib only.

Usage: python3 harness/soak.py [cid]
"""

import base64
import concurrent.futures
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from v2client import request  # noqa: E402

CID = int(sys.argv[1]) if len(sys.argv) > 1 else 9


def one_exec(i: int) -> str | None:
    try:
        reply, _ = request(CID, {"op": "exec", "cmd": ["cmd.exe", "/c", f"echo s{i}"], "cwd": None, "env": None, "user": None, "timeout": 60})
        out = base64.b64decode(reply.get("stdout", "")).decode(errors="replace").strip()
        if int(reply.get("rc", -1)) != 0 or out != f"s{i}":
            return f"exec {i}: bad reply {reply}"
        return None
    except Exception as e:
        return f"exec {i}: {e!r}"


def main() -> int:
    failures: list[str] = []

    t0 = time.monotonic()
    for i in range(500):
        err = one_exec(i)
        if err:
            failures.append(err)
    seq = time.monotonic() - t0
    print(f"500 sequential execs: {seq:.1f}s ({seq / 500 * 1000:.1f} ms/exec), {len(failures)} failures")

    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        for err in pool.map(one_exec, range(1000, 1050)):
            if err:
                failures.append(err)
    print(f"50 parallel execs (10 workers): {time.monotonic() - t0:.1f}s, total failures now {len(failures)}")

    data = os.urandom(1 << 20)
    for i in range(20):
        try:
            path = f"C:\\vsockd\\work\\soak{i}.bin"
            reply, _ = request(CID, {"op": "write", "path": path, "size": len(data)}, data)
            assert reply.get("ok"), reply
            reply, body = request(CID, {"op": "read", "path": path})
            assert body == data, f"round trip {i}: bytes differ"
        except Exception as e:
            failures.append(f"file {i}: {e!r}")
    print(f"20 x 1 MiB file round trips: {len([f for f in failures if f.startswith('file')])} failures")

    if failures:
        print(f"\nSOAK FAILURES ({len(failures)}):")
        for f in failures[:20]:
            print(f"  {f}")
        return 1
    print("\nsoak: 570/570 operations, zero failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
