#!/usr/bin/env python3
"""Performance battery for the Windows vsock daemon. Stdlib only.

Measures: channel RTT (ping op; comparable to the Linux spike's transport figure), exec RTT (includes Windows process creation), and 100 MB file write/read throughput (the number that retires the 0.6 MB/s qemu-ga file plane).

Usage: python3 harness/perf.py [cid] [full]
"""

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from v2client import request  # noqa: E402

CID = int(sys.argv[1]) if len(sys.argv) > 1 else 9


def main() -> int:
    times = []
    for _ in range(1000):
        t0 = time.perf_counter()
        request(CID, {"op": "ping"})
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    print(f"channel RTT (ping x1000): median {statistics.median(times):.2f} ms, p95 {times[949]:.2f} ms")

    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        request(CID, {"op": "exec", "cmd": ["cmd.exe", "/c", "exit 0"], "cwd": None, "env": None, "user": None, "timeout": 60})
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    print(f"exec RTT (cmd /c exit 0, x50): median {statistics.median(times):.1f} ms, p95 {times[47]:.1f} ms")

    data = os.urandom(100 * (1 << 20))
    t0 = time.perf_counter()
    reply, _ = request(CID, {"op": "write", "path": "C:\\vsockd\\work\\perf100.bin", "size": len(data)}, data)
    assert reply.get("ok"), reply
    w = time.perf_counter() - t0
    t0 = time.perf_counter()
    _, body = request(CID, {"op": "read", "path": "C:\\vsockd\\work\\perf100.bin"})
    r = time.perf_counter() - t0
    assert body == data, "100 MB round trip corrupt"
    print(f"file plane (100 MB): write {100 / w:.0f} MB/s, read {100 / r:.0f} MB/s (bytes verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
