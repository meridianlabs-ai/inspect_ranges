#!/usr/bin/env python3
"""qemu-ga file transfer benchmark against the wintest guest (spike)."""

import base64
import json
import subprocess
import time

CHUNK = 64 * 1024  # virsh passes JSON as one CLI arg; Linux caps args at 128KB
PAYLOAD = bytes(range(256)) * 4096 * 5  # 5 MB deterministic


def ga(cmd: dict) -> dict:
    p = subprocess.run(
        ["docker", "compose", "exec", "range", "virsh", "-c", "qemu:///system",
         "qemu-agent-command", "wintest", json.dumps(cmd)],
        capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip())
    return json.loads(p.stdout)["return"]


def main() -> None:
    path = f"C:\\spike-{int(time.time())}.bin"  # fresh name: crashed runs leak open handles
    handle = ga({"execute": "guest-file-open", "arguments": {"path": path, "mode": "wb"}})
    t0 = time.monotonic()
    for i in range(0, len(PAYLOAD), CHUNK):
        ga({"execute": "guest-file-write",
            "arguments": {"handle": handle,
                          "buf-b64": base64.b64encode(PAYLOAD[i:i + CHUNK]).decode()}})
    ga({"execute": "guest-file-close", "arguments": {"handle": handle}})
    write_s = time.monotonic() - t0

    handle = ga({"execute": "guest-file-open", "arguments": {"path": path, "mode": "rb"}})
    t0 = time.monotonic()
    back = b""
    while True:
        r = ga({"execute": "guest-file-read", "arguments": {"handle": handle, "count": CHUNK}})
        back += base64.b64decode(r["buf-b64"])
        if r["eof"]:
            break
    ga({"execute": "guest-file-close", "arguments": {"handle": handle}})
    read_s = time.monotonic() - t0

    mb = len(PAYLOAD) / 1e6
    print(f"write: {mb:.0f}MB in {write_s:.1f}s ({mb/write_s:.2f} MB/s); "
          f"read: {read_s:.1f}s ({mb/read_s:.2f} MB/s); intact: {back == PAYLOAD}")


if __name__ == "__main__":
    main()
