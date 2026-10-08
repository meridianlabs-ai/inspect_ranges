#!/usr/bin/env python3
"""Host-side vsock client + benchmarks for the vsockd spike daemon.

Usage: client.py <cid> <command> [args...]
Commands: wait | exec <cmd> | bench-rtt <n> | poll-run <cmd> <interval> |
          put <local> <remote> | get <remote> <local> | bg-test
"""

import base64
import hashlib
import json
import os
import socket
import statistics
import sys
import time

PORT = 5000


def connect(cid):
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    s.connect((cid, PORT))
    return s


def recv_line(s):
    buf = b""
    while not buf.endswith(b"\n"):
        c = s.recv(1)
        if not c:
            raise ConnectionError("eof")
        buf += c
    return json.loads(buf)


def request(cid, obj):
    s = connect(cid)
    s.sendall((json.dumps(obj) + "\n").encode())
    resp = recv_line(s)
    s.close()
    return resp


def run_exec(cid, cmd):
    r = request(cid, {"op": "exec", "cmd": cmd})
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["rc"], base64.b64decode(r["stdout"]).decode(errors="replace")


def main():
    cid, command = int(sys.argv[1]), sys.argv[2]

    if command == "wait":
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if request(cid, {"op": "ping"}).get("ok"):
                    print("daemon ready")
                    return
            except OSError:
                time.sleep(0.3)
        sys.exit("daemon not reachable within 120s")

    elif command == "exec":
        rc, out = run_exec(cid, sys.argv[3])
        print(out, end="")
        sys.exit(rc)

    elif command == "bench-rtt":
        n = int(sys.argv[3])
        times = []
        for _ in range(n):
            t0 = time.monotonic()
            run_exec(cid, "true")
            times.append((time.monotonic() - t0) * 1000)
        times.sort()
        print(
            f"vsock exec rtt over {n} calls: "
            f"median {statistics.median(times):.1f}ms, "
            f"mean {statistics.mean(times):.1f}ms, "
            f"p95 {times[int(n * 0.95)]:.1f}ms"
        )

    elif command == "poll-run":
        cmd, interval = sys.argv[3], float(sys.argv[4])
        t0 = time.monotonic()
        jid = request(cid, {"op": "start", "cmd": cmd})["id"]
        polls = 0
        while True:
            time.sleep(interval)
            r = request(cid, {"op": "poll", "id": jid})
            polls += 1
            if not r["running"]:
                break
        elapsed = time.monotonic() - t0
        out = base64.b64decode(r["stdout"]).decode(errors="replace").strip()
        print(
            f"start+poll({interval}s): rc={r['rc']} output={out!r} "
            f"polls={polls} wall={elapsed:.2f}s"
        )

    elif command in ("put", "get"):
        src, dst = sys.argv[3], sys.argv[4]
        if command == "put":
            size = os.path.getsize(src)
            s = connect(cid)
            s.sendall((json.dumps({"op": "write", "path": dst, "size": size}) + "\n").encode())
            t0 = time.monotonic()
            sha = hashlib.sha256()
            with open(src, "rb") as f:
                while chunk := f.read(1 << 20):
                    sha.update(chunk)
                    s.sendall(chunk)
            resp = recv_line(s)
            elapsed = time.monotonic() - t0
            assert resp.get("ok"), resp
        else:
            s = connect(cid)
            s.sendall((json.dumps({"op": "read", "path": src}) + "\n").encode())
            t0 = time.monotonic()
            size = recv_line(s)["size"]
            sha = hashlib.sha256()
            remaining = size
            with open(dst, "wb") as f:
                while remaining:
                    chunk = s.recv(min(1 << 20, remaining))
                    if not chunk:
                        raise ConnectionError("short read stream")
                    sha.update(chunk)
                    f.write(chunk)
                    remaining -= len(chunk)
            elapsed = time.monotonic() - t0
        s.close()
        print(
            f"{command} {size / 1e6:.0f}MB in {elapsed:.2f}s "
            f"({size / 1e6 / elapsed:.0f} MB/s), sha256 {sha.hexdigest()[:16]}"
        )

    elif command == "bg-test":
        rc, _ = run_exec(cid, "sleep 300 >/dev/null 2>&1 & echo spawned")
        assert rc == 0
        time.sleep(1)
        rc, out = run_exec(cid, "pgrep -f 'sleep 300' | wc -l")
        survived = int(out.strip()) >= 1
        print(f"background process survives exec return: {survived}")
        run_exec(cid, "pkill -f 'sleep 300' || true")
        sys.exit(0 if survived else 1)


if __name__ == "__main__":
    main()
