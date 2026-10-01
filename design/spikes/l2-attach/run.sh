#!/bin/bash
# End-to-end spike: range container (libvirtd+QEMU) boots vm1 on an in-netns
# bridge; agent container is veth-attached at L2; test ARP, SSH, broadcast
# receive, and containment. See README.md for findings.
#
# Usage: ./run.sh [down]
set -euo pipefail
cd "$(dirname "$0")"

export IMAGE_CACHE="${IMAGE_CACHE:-$HOME/.cache/inspect-ranges/images}"
GOLDEN="$IMAGE_CACHE/noble-server-cloudimg-amd64.img"

if [[ "${1:-}" == "down" ]]; then
  docker compose down -v
  exit 0
fi

[[ -f "$GOLDEN" ]] || {
  echo "Golden image missing; fetching to $GOLDEN"
  mkdir -p "$IMAGE_CACHE"
  curl -fsSL -o "$GOLDEN" https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
}

if [[ ! -f tmp/spike_key ]]; then
  mkdir -p tmp
  ssh-keygen -t ed25519 -N '' -C spike -f tmp/spike_key -q
  sed -i "s|^      - ssh-ed25519.*|      - $(cat tmp/spike_key.pub)|" assets/user-data
fi

T0=$(date +%s.%N)
docker compose up -d --build --wait
T1=$(date +%s.%N)

docker compose exec range bash /assets/boot-vm.sh
T2=$(date +%s.%N)

RANGE_PID=$(docker inspect -f '{{.State.Pid}}' l2-attach-range-1)
AGENT_PID=$(docker inspect -f '{{.State.Pid}}' l2-attach-agent-1)
docker run --rm --privileged --pid=host --network=host \
  -v "$PWD/attach-veth.sh:/attach.sh:ro" \
  --entrypoint bash l2-attach-range /attach.sh \
  "$RANGE_PID" "$AGENT_PID" br-lab 10.80.10.2/24
T3=$(date +%s.%N)

docker cp tmp/spike_key l2-attach-agent-1:/root/.ssh_key
docker compose exec agent bash -c '
  chmod 600 /root/.ssh_key
  until ssh -i /root/.ssh_key -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null -o ConnectTimeout=1 \
      ubuntu@10.80.10.10 true 2>/dev/null; do sleep 0.5; done'
T4=$(date +%s.%N)

echo "=== timings ==="
python3 -c "print(f'compose up: {$T1-$T0:.1f}s | vm define+start: {$T2-$T1:.1f}s | veth attach: {$T3-$T2:.1f}s | vm ssh-able: {$T4-$T3:.1f}s | total: {$T4-$T0:.1f}s')"

echo "=== L2: arping ==="
docker compose exec agent arping -c 3 10.80.10.10

echo "=== L2: broadcast receive (VM -> agent) ==="
docker compose exec agent bash -c '
  timeout 10 tcpdump -i range0 -c 2 "ether broadcast and src host 10.80.10.10" -nn 2>/dev/null >/tmp/bcast.log &
  TCPDUMP=$!
  sleep 1
  ssh -i /root/.ssh_key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      ubuntu@10.80.10.10 "ping -b -c 2 -W1 10.80.10.255 >/dev/null 2>&1 || true" 2>/dev/null
  wait $TCPDUMP
  cat /tmp/bcast.log'

echo "=== containment: agent must reach nothing but the lab segment ==="
RANGE_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' l2-attach-range-1)
docker compose exec agent bash -c "
  ip route show
  nc -w1 -z 169.254.169.254 80 2>&1 || echo 'metadata: unreachable (good)'
  nc -w1 -z $RANGE_IP 22 2>&1 || echo 'range mgmt ip: unreachable (good)'
  nc -w1 -z 8.8.8.8 53 2>&1 || echo 'internet: unreachable (good)'"

echo "=== teardown check: virsh destroy must not leave a zombie ==="
docker compose exec range bash -c '
  virsh -c qemu:///system destroy vm1
  virsh -c qemu:///system list --all'

echo "OK. Tear down with: ./run.sh down"
