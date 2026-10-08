#!/bin/bash
# Run inside the range container: isolated L2 bridge plus two Windows guests
# cloned from the golden image. Unlike the ad-domain spike, guests run on a
# NAMED CPU model (not host-passthrough) so the resulting checkpoint has a
# compatibility statement a different host could be checked against.
set -euxo pipefail

CPU_MODEL="${CPU_MODEL:-Skylake-Server-noTSX-IBRS}"

ip link add br-ad type bridge 2>/dev/null || true
ip link set br-ad up

for vm in dc01 ws01; do
  virsh -c qemu:///system destroy "$vm" 2>/dev/null || true
  virsh -c qemu:///system undefine "$vm" 2>/dev/null || true
  rm -f "/scratch/$vm.qcow2"
  qemu-img create -f qcow2 -F qcow2 -b /scratch/win-golden.qcow2 "/scratch/$vm.qcow2" 40G
  virt-install \
    --connect qemu:///system \
    --name "$vm" \
    --memory 4096 --vcpus 4 \
    --cpu "$CPU_MODEL" \
    --disk "path=/scratch/$vm.qcow2,format=qcow2,bus=virtio" \
    --network bridge=br-ad,model=virtio \
    --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
    --boot hd \
    --graphics vnc,listen=127.0.0.1 \
    --osinfo win2k22 \
    --import --noautoconsole
done
