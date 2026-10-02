#!/bin/bash
# Lazy image pull spike: boot a VM whose qcow2 backing file is an HTTP URL
# (qemu curl driver) with copy-on-read populating a local overlay. Measures
# boot time + bytes actually fetched vs a local-backing baseline, and the
# second-boot cost once copy-on-read has warmed the overlay.
# Usage: ./run.sh [down]
set -euo pipefail
cd "$(dirname "$0")"

export IMAGE_CACHE="${IMAGE_CACHE:-$HOME/.cache/inspect-ranges/images}"
C="python3 ../vsock-exec/host/client.py"
IMG=noble-e2e.qcow2

if [[ "${1:-}" == "down" ]]; then
  docker compose down -v
  exit 0
fi

grep -q vhost_vsock /proc/modules || { echo "need: sudo modprobe vhost_vsock"; exit 1; }

# render inputs for the range entrypoint + a cloud-init seed (hostname only)
mkdir -p tmp/render/vms/vm
: > tmp/render/bridges.txt
printf 'flush ruleset\ntable inet rangehost {\n  chain forward { type filter hook forward priority 0; policy drop; }\n}\n' > tmp/render/range-netns.nft
printf 'instance-id: lazy-spike\nlocal-hostname: vm\n' > tmp/render/vms/vm/meta-data
printf '#cloud-config\nhostname: vm\n' > tmp/render/vms/vm/user-data

docker compose up -d --build --wait
SERVER_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' lazy-pull-imageserver-1)

boot() {  # boot <name> <cid> <backing-spec>
  docker compose exec range bash -euc "
    qemu-img create -f qcow2 -F qcow2 -b '$3' /scratch/$1.qcow2 10G >/dev/null
    cloud-localds /scratch/$1-seed.iso /render/vms/vm/user-data /render/vms/vm/meta-data
    virt-install --connect qemu:///system --name $1 --memory 1024 --vcpus 1 \
      --cpu host-passthrough \
      --disk path=/scratch/$1.qcow2,format=qcow2,bus=virtio,driver.copy_on_read=on \
      --disk path=/scratch/$1-seed.iso,device=cdrom \
      --network none --vsock cid.address=$2 \
      --osinfo ubuntu24.04 --import --graphics none --noautoconsole >/dev/null"
}

fetched_bytes() {
  docker compose logs imageserver 2>/dev/null \
    | { grep -oE '" (200|206) [0-9]+' || true; } | awk '{ sum += $3 } END { print sum+0 }'
}

echo "=== baseline: local backing file ==="
T0=$(date +%s.%N)
boot localvm 8 /images/$IMG
$C 8 wait >/dev/null
T1=$(date +%s.%N)
python3 -c "print(f'local boot -> daemon ready: {$T1-$T0:.1f}s')"

echo "=== lazy: HTTP backing (curl driver) + copy-on-read ==="
B0=$(fetched_bytes)
T0=$(date +%s.%N)
boot lazyvm 9 "json:{\"file.driver\":\"http\",\"file.url\":\"http://$SERVER_IP/$IMG\"}"
$C 9 wait >/dev/null
T1=$(date +%s.%N)
B1=$(fetched_bytes)
# the lazy chain is TWO layers over HTTP: noble-e2e (delta) + its relative
# backing (the noble cloud image), both resolved against the URL base
SIZE=$(( $(stat -c %s "$IMAGE_CACHE/$IMG") + $(stat -c %s "$IMAGE_CACHE/noble-server-cloudimg-amd64.img") ))
docker compose exec range bash -c 'echo "overlay size after boot: $(du -h /scratch/lazyvm.qcow2 | cut -f1)"'
python3 -c "print(f'lazy boot -> daemon ready: {$T1-$T0:.1f}s; fetched {($B1-$B0)/1e6:.0f} MB of {$SIZE/1e6:.0f} MB image ({100*($B1-$B0)/$SIZE:.0f}%)')"

echo "=== second boot: same overlay, copy-on-read warmed ==="
docker compose exec range virsh -c qemu:///system destroy lazyvm >/dev/null
docker compose exec range virsh -c qemu:///system undefine lazyvm >/dev/null
B2=$(fetched_bytes)
T0=$(date +%s.%N)
docker compose exec range bash -euc "
  virt-install --connect qemu:///system --name lazyvm2 --memory 1024 --vcpus 1 \
    --cpu host-passthrough \
    --disk path=/scratch/lazyvm.qcow2,format=qcow2,bus=virtio,driver.copy_on_read=on \
    --disk path=/scratch/lazyvm-seed.iso,device=cdrom \
    --network none --vsock cid.address=10 \
    --osinfo ubuntu24.04 --import --graphics none --noautoconsole >/dev/null"
$C 10 wait >/dev/null
T1=$(date +%s.%N)
B3=$(fetched_bytes)
python3 -c "print(f'warm second boot: {$T1-$T0:.1f}s; additional fetch: {($B3-$B2)/1e6:.1f} MB')"

echo "OK. Tear down with: ./run.sh down"
