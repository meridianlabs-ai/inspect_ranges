#!/usr/bin/env python3
"""vsock exec/file daemon prototype (spike).

Listens on AF_VSOCK port 5000 inside the guest; the hypervisor side connects
from CID 2 (the host). One connection per request. Protocol: a JSON header
line, then (for write) `size` raw bytes; response is a JSON line, then (for
read) `size` raw bytes.

Ops: ping | exec (blocking, 16KB-truncated output) | start/poll (exec_remote
style) | write | read.
"""

import base64
import json
import os
import socket
import subprocess
import tempfile
import threading

PORT = 5000
OUTPUT_LIMIT = 16384  # mirror the harness's tool-output truncation

jobs: dict[int, tuple[subprocess.Popen, str]] = {}
jobs_lock = threading.Lock()
next_id = 0


def recv_line(conn):
    buf = b""
    while not buf.endswith(b"\n"):
        c = conn.recv(1)
        if not c:
            return None
        buf += c
    return buf


def send_json(conn, obj):
    conn.sendall((json.dumps(obj) + "\n").encode())


def b64(data):
    return base64.b64encode(data[-OUTPUT_LIMIT:]).decode()


def handle(conn):
    global next_id
    try:
        line = recv_line(conn)
        if line is None:
            return
        req = json.loads(line)
        op = req["op"]
        if op == "ping":
            send_json(conn, {"ok": True})
        elif op == "exec":
            p = subprocess.run(
                ["/bin/sh", "-c", req["cmd"]],
                capture_output=True,
                timeout=req.get("timeout", 60),
                start_new_session=True,
            )
            send_json(
                conn,
                {"rc": p.returncode, "stdout": b64(p.stdout), "stderr": b64(p.stderr)},
            )
        elif op == "start":
            out = tempfile.NamedTemporaryFile(delete=False, prefix="job-")
            p = subprocess.Popen(
                ["/bin/sh", "-c", req["cmd"]],
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            with jobs_lock:
                next_id += 1
                jid = next_id
                jobs[jid] = (p, out.name)
            send_json(conn, {"id": jid})
        elif op == "poll":
            p, path = jobs[req["id"]]
            rc = p.poll()
            with open(path, "rb") as f:
                output = f.read()
            send_json(conn, {"running": rc is None, "rc": rc, "stdout": b64(output)})
        elif op == "write":
            remaining = req["size"]
            with open(req["path"], "wb") as f:
                while remaining:
                    chunk = conn.recv(min(1 << 20, remaining))
                    if not chunk:
                        raise ConnectionError("short write stream")
                    f.write(chunk)
                    remaining -= len(chunk)
            send_json(conn, {"ok": True})
        elif op == "read":
            size = os.path.getsize(req["path"])
            send_json(conn, {"size": size})
            with open(req["path"], "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    conn.sendall(chunk)
        else:
            send_json(conn, {"error": f"unknown op {op}"})
    except Exception as e:  # spike: report, don't die
        try:
            send_json(conn, {"error": str(e)})
        except Exception:
            pass
    finally:
        conn.close()


def main():
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    s.bind((socket.VMADDR_CID_ANY, PORT))
    s.listen(16)
    while True:
        conn, (cid, _port) = s.accept()
        if cid != 2:  # only the hypervisor host may speak to us
            conn.close()
            continue
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
