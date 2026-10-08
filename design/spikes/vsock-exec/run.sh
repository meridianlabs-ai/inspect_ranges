#!/bin/bash
# vsock exec spike: boot a NIC-less VM under the range container, control it
# purely over virtio-vsock, benchmark exec/poll/file-transfer. See README.md.
#
# Usage: ./run.sh [down]
set -euo pipefail
cd "$(dirname "$0")"

export IMAGE_CACHE="${IMAGE_CACHE:-$HOME/.cache/inspect-ranges/images}"
CID=3

if [[ "${1:-}" == "down" ]]; then
  docker compose down -v
  exit 0
fi

grep -q vhost_vsock /proc/modules || { echo "need: sudo modprobe vhost_vsock"; exit 1; }

# derived golden image: daemon baked in, cloud-init and wait-online disabled
# (the "standard agent image" story — see README.md)
mkdir -p tmp
DERIVED="$IMAGE_CACHE/noble-vsockd.qcow2"
if [[ ! -f "$DERIVED" ]]; then
  cat > tmp/vsockd.service <<'EOF'
[Unit]
Description=vsock exec daemon (spike)
[Service]
ExecStart=/usr/bin/python3 /opt/vsockd.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF
  qemu-img create -f qcow2 -F qcow2 -b "$IMAGE_CACHE/noble-server-cloudimg-amd64.img" "$DERIVED" 10G
  virt-customize -a "$DERIVED" \
    --no-network \
    --mkdir /opt \
    --copy-in guest/vsockd.py:/opt \
    --chmod 0755:/opt/vsockd.py \
    --copy-in tmp/vsockd.service:/etc/systemd/system \
    --link /etc/systemd/system/vsockd.service:/etc/systemd/system/multi-user.target.wants/vsockd.service \
    --link /dev/null:/etc/systemd/system/systemd-networkd-wait-online.service \
    --touch /etc/cloud/cloud-init.disabled \
    --hostname agentvm
fi

T0=$(date +%s.%N)
docker compose up -d --build --wait
docker compose exec range bash /assets/boot-vm.sh
python3 host/client.py $CID wait
T1=$(date +%s.%N)
python3 -c "print(f'compose up + VM boot -> daemon ready: {$T1-$T0:.1f}s')"

echo "=== exec round-trip: vsock vs docker exec ==="
python3 host/client.py $CID bench-rtt 200
python3 - <<'EOF'
import statistics, subprocess, time
times = []
for _ in range(50):
    t0 = time.monotonic()
    subprocess.run(["docker", "exec", "vsock-exec-range-1", "true"], check=True)
    times.append((time.monotonic() - t0) * 1000)
times.sort()
print(f"docker exec rtt over 50 calls: median {statistics.median(times):.1f}ms, "
      f"mean {statistics.mean(times):.1f}ms, p95 {times[47]:.1f}ms")
EOF

echo "=== exec_remote-style start+poll (2s command, 0.2s interval) ==="
python3 host/client.py $CID poll-run 'sleep 2 && echo done' 0.2

echo "=== file transfer: 100MB each way ==="
head -c 100000000 /dev/urandom > tmp/blob
sha256sum tmp/blob | cut -c1-16
python3 host/client.py $CID put tmp/blob /root/blob
python3 host/client.py $CID get /root/blob tmp/blob.back
cmp tmp/blob tmp/blob.back && echo "round-trip content identical"

echo "=== background process survival ==="
python3 host/client.py $CID bg-test

echo "=== loopback present in NIC-less guest (proxy injection) ==="
python3 host/client.py $CID exec "ip -brief addr show lo && python3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\",9999)); s.listen(1); socket.create_connection((\"127.0.0.1\",9999)); print(\"lo tcp works\")'"

echo "OK. Tear down with: ./run.sh down"
