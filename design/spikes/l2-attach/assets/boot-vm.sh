#!/bin/bash
# Run inside the range container (docker exec): overlay on the read-only golden
# image, cloud-init NoCloud seed with a static IP, boot vm1 onto br-lab.
set -euxo pipefail

GOLDEN=/images/noble-server-cloudimg-amd64.img
SCRATCH=/scratch

# overlay, never the container writable layer (handoff §6)
qemu-img create -f qcow2 -F qcow2 -b "$GOLDEN" "$SCRATCH/vm1.qcow2" 10G

cloud-localds -N /assets/network-config "$SCRATCH/seed.iso" \
  /assets/user-data /assets/meta-data

virt-install \
  --connect qemu:///system \
  --name vm1 \
  --memory 2048 --vcpus 2 \
  --cpu host-passthrough \
  --disk path="$SCRATCH/vm1.qcow2",format=qcow2,bus=virtio \
  --disk path="$SCRATCH/seed.iso",device=cdrom \
  --network bridge=br-lab,model=virtio \
  --osinfo ubuntu24.04 \
  --import --graphics none --noautoconsole \
  --console pty,target_type=serial

virsh -c qemu:///system domstate vm1
