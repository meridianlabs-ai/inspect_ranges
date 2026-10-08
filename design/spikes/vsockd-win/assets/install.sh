#!/bin/bash
# Run inside the range container: unattended Windows Server 2022 install.
# Blank virtio disk (viostor injected in WinPE) + install ISO + virtio-win ISO
# + a small unattend ISO. BIOS boot: --boot hd,cdrom falls through the blank
# disk to the install CD without a keypress prompt; after the first reboot the
# disk is bootable and wins. Install finalizes by shutting itself down.
set -euxo pipefail

genisoimage -quiet -o /scratch/unattend.iso -J -R /assets/autounattend.xml

qemu-img create -f qcow2 /scratch/win-golden.qcow2 40G

virt-install \
  --connect qemu:///system \
  --name wininstall \
  --memory 4096 --vcpus 4 \
  --cpu host-passthrough \
  --disk path=/scratch/win-golden.qcow2,format=qcow2,bus=virtio \
  --disk path=/images/ws2022-eval.iso,device=cdrom,readonly=on \
  --disk path=/images/virtio-win.iso,device=cdrom,readonly=on \
  --disk path=/scratch/unattend.iso,device=cdrom,readonly=on \
  --network none \
  --boot hd,cdrom \
  --graphics vnc,listen=127.0.0.1 \
  --osinfo win2k22 \
  --import --noautoconsole

virsh -c qemu:///system domstate wininstall
