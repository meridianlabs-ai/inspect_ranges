#!/bin/bash
# Run inside the range container: boot the NIC-less agent VM with vsock CID 3.
# The daemon is baked into the derived golden image (see run.sh); no cloud-init.
set -euxo pipefail

GOLDEN=/images/noble-vsockd.qcow2
SCRATCH=/scratch

qemu-img create -f qcow2 -F qcow2 -b "$GOLDEN" "$SCRATCH/agentvm.qcow2" 10G

virt-install \
  --connect qemu:///system \
  --name agentvm \
  --memory 2048 --vcpus 2 \
  --cpu host-passthrough \
  --disk path="$SCRATCH/agentvm.qcow2",format=qcow2,bus=virtio \
  --network none \
  --vsock cid.address=3 \
  --osinfo ubuntu24.04 \
  --import --graphics none --noautoconsole

virsh -c qemu:///system domstate agentvm
