#!/usr/bin/env python3
"""vsock exec/file daemon, spike v2: enough contract for Inspect's self_check.

Adds over the vsock-exec spike's prototype: argv exec (no implicit shell),
stdin, cwd, env, user (via runuser), in-daemon timeout with process-GROUP kill,
output caps with truncated flags, and errno-tagged file errors. Protocol
unchanged: one connection per request; JSON header line, then raw bytes for
file payloads.
"""

import base64
import errno as errno_mod
import json
import os
import signal
import socket
import subprocess
import threading

PORT = 5000
OUTPUT_CAP = 16 * 1024 * 1024  # per stream


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


def errno_name(err):
    try:
        return errno_mod.errorcode.get(err, str(err))
    except Exception:
        return str(err)


def do_exec(req):
    cmd = req["cmd"]
    if req.get("user"):
        cmd = ["runuser", "-u", req["user"], "--"] + cmd
    stdin = base64.b64decode(req["input"]) if req.get("input") is not None else None
    env = dict(os.environ)
    env.update(req.get("env") or {})
    cwd = req.get("cwd")
    timeout = req.get("timeout")
    try:
        p = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,  # own process group: timeout kills the tree
        )
    except FileNotFoundError:
        return {"rc": 127, "stdout": "", "stderr": base64.b64encode(f"command not found: {cmd[0]}".encode()).decode()}
    except NotADirectoryError as e:
        return {"error": str(e), "errno": "ENOTDIR"}
    except PermissionError:
        return {"rc": 126, "stdout": "", "stderr": base64.b64encode(f"permission denied: {cmd[0]}".encode()).decode()}
    except OSError as e:
        return {"error": str(e), "errno": errno_name(e.errno)}
    try:
        out, err = p.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.wait()
        return {"timeout": True}
    return {
        "rc": p.returncode,
        "stdout": base64.b64encode(out[:OUTPUT_CAP]).decode(),
        "stderr": base64.b64encode(err[:OUTPUT_CAP]).decode(),
        "stdout_truncated": len(out) > OUTPUT_CAP,
        "stderr_truncated": len(err) > OUTPUT_CAP,
    }


def handle(conn):
    try:
        line = recv_line(conn)
        if line is None:
            return
        req = json.loads(line)
        op = req["op"]
        if op == "ping":
            send_json(conn, {"ok": True})
        elif op == "exec":
            send_json(conn, do_exec(req))
        elif op == "stat":
            try:
                st = os.stat(req["path"])
                send_json(conn, {"size": st.st_size, "isdir": os.path.isdir(req["path"])})
            except OSError as e:
                send_json(conn, {"error": str(e), "errno": errno_name(e.errno)})
        elif op == "write":
            remaining = req["size"]
            try:
                parent = os.path.dirname(req["path"])
                if parent:
                    os.makedirs(parent, exist_ok=True)
                f = open(req["path"], "wb")
            except OSError as e:
                # drain the stream so the client doesn't block, then report
                while remaining:
                    chunk = conn.recv(min(1 << 20, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                send_json(conn, {"error": str(e), "errno": errno_name(e.errno)})
                return
            with f:
                while remaining:
                    chunk = conn.recv(min(1 << 20, remaining))
                    if not chunk:
                        raise ConnectionError("short write stream")
                    f.write(chunk)
                    remaining -= len(chunk)
            send_json(conn, {"ok": True})
        elif op == "read":
            try:
                if os.path.isdir(req["path"]):
                    send_json(conn, {"error": "Is a directory", "errno": "EISDIR"})
                    return
                size = os.path.getsize(req["path"])
                f = open(req["path"], "rb")
            except OSError as e:
                send_json(conn, {"error": str(e), "errno": errno_name(e.errno)})
                return
            send_json(conn, {"size": size})
            with f:
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
