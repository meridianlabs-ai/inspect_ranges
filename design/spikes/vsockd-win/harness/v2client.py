#!/usr/bin/env python3
"""Minimal stdlib host client for the v2 vsock daemon protocol (one newline-terminated JSON header per connection, sized raw streams), matching `design/spikes/e2e-provider/guest/vsockd2.py` / the Windows port.

CLI:
    v2client.py wait <cid> [timeout]
    v2client.py exec <cid> <argv...>
    v2client.py put <cid> <local> <remote>
    v2client.py get <cid> <remote> <local>
    v2client.py rtt <cid> <n>          # ping round trips, prints median/p95 ms
"""

import base64
import hashlib
import json
import socket
import statistics
import sys
import time
from typing import Any

PORT = 5000
CHUNK = 1 << 20


def request(cid: int, obj: dict[str, Any], payload: bytes | None = None) -> tuple[dict[str, Any], bytes]:
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    try:
        s.connect((cid, PORT))
        s.sendall(json.dumps(obj).encode() + b"\n")
        if payload is not None:
            s.sendall(payload)
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(CHUNK)
            if not chunk:
                raise ConnectionError("eof from daemon")
            buf += chunk
        line, rest = buf.split(b"\n", 1)
        reply = json.loads(line)
        body = b""
        if "size" in reply and obj.get("op") == "read":
            size = int(reply["size"])
            parts = [rest]
            got = len(rest)
            while got < size:
                chunk = s.recv(min(CHUNK, size - got))
                if not chunk:
                    raise ConnectionError("short read stream")
                parts.append(chunk)
                got += len(chunk)
            body = b"".join(parts)
        return reply, body
    finally:
        s.close()


def wait(cid: int, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reply, _ = request(cid, {"op": "ping"})
            if reply.get("ok"):
                print("daemon ready")
                return
        except OSError:
            pass
        time.sleep(0.3)
    sys.exit(f"daemon on cid {cid} not ready after {timeout:.0f}s")


def run_exec(cid: int, argv: list[str]) -> int:
    reply, _ = request(cid, {"op": "exec", "cmd": argv, "cwd": None, "env": None, "user": None, "timeout": 60})
    if "error" in reply:
        sys.exit(f"error: {reply}")
    if reply.get("timeout"):
        sys.exit("timeout")
    sys.stdout.write(base64.b64decode(reply["stdout"]).decode(errors="replace"))
    sys.stderr.write(base64.b64decode(reply["stderr"]).decode(errors="replace"))
    return int(reply["rc"])


def main() -> None:
    cmd, cid = sys.argv[1], int(sys.argv[2])
    if cmd == "wait":
        wait(cid, float(sys.argv[3]) if len(sys.argv) > 3 else 120.0)
    elif cmd == "exec":
        sys.exit(run_exec(cid, sys.argv[3:]))
    elif cmd == "put":
        data = open(sys.argv[3], "rb").read()
        reply, _ = request(cid, {"op": "write", "path": sys.argv[4], "size": len(data)}, data)
        if "error" in reply:
            sys.exit(f"error: {reply}")
        print(f"put {len(data)} bytes sha256={hashlib.sha256(data).hexdigest()[:16]}")
    elif cmd == "get":
        reply, body = request(cid, {"op": "read", "path": sys.argv[3]})
        if "error" in reply:
            sys.exit(f"error: {reply}")
        open(sys.argv[4], "wb").write(body)
        print(f"got {len(body)} bytes sha256={hashlib.sha256(body).hexdigest()[:16]}")
    elif cmd == "rtt":
        n = int(sys.argv[3])
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            request(cid, {"op": "ping"})
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        print(f"ping RTT over {n}: median {statistics.median(times):.2f} ms, p95 {times[int(n * 0.95) - 1]:.2f} ms")
    else:
        sys.exit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
