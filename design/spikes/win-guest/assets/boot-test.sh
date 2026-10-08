#!/bin/bash
# Run inside the range container: boot a test VM from the golden image with a
# vsock device attached (to probe Windows driver support) and the qemu-ga
# channel (the expected Windows exec path).
set -euxo pipefail

qemu-img create -f qcow2 -F qcow2 -b /scratch/win-golden.qcow2 /scratch/wintest.qcow2 40G

virt-install \
  --connect qemu:///system \
  --name wintest \
  --memory 4096 --vcpus 4 \
  --cpu host-passthrough \
  --disk path=/scratch/wintest.qcow2,format=qcow2,bus=virtio \
  --network none \
  --vsock cid.address=7 \
  --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
  --boot hd \
  --graphics vnc,listen=127.0.0.1 \
  --osinfo win2k22 \
  --import --noautoconsole

virsh -c qemu:///system domstate wintest
