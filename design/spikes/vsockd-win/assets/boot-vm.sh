#!/bin/bash
# Run inside the range container: build the payload ISO (daemon source,
# installer, busybox) and boot the test guest with a vsock device (CID 9),
# the virtio-win ISO (driver source), and the payload ISO.
set -euxo pipefail

CID="${CID:-9}"

rm -rf /tmp/payload && mkdir -p /tmp/payload
cp /assets/guest/VsockDaemon.cs /assets/guest/install-daemon.ps1 /tmp/payload/
[ -f /images/busybox.exe ] && cp /images/busybox.exe /tmp/payload/
genisoimage -quiet -o /scratch/payload.iso -J -R -V PAYLOAD /tmp/payload

virsh -c qemu:///system destroy winvsd 2>/dev/null || true
virsh -c qemu:///system undefine winvsd 2>/dev/null || true
rm -f /scratch/winvsd.qcow2
qemu-img create -f qcow2 -F qcow2 -b /scratch/win-golden.qcow2 /scratch/winvsd.qcow2 40G

virt-install \
  --connect qemu:///system \
  --name winvsd \
  --memory 4096 --vcpus 4 \
  --cpu host-passthrough \
  --disk path=/scratch/winvsd.qcow2,format=qcow2,bus=virtio \
  --disk path=/images/virtio-win.iso,device=cdrom,readonly=on \
  --disk path=/scratch/payload.iso,device=cdrom,readonly=on \
  --network none \
  --vsock cid.address="$CID" \
  --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
  --boot hd \
  --graphics vnc,listen=127.0.0.1 \
  --osinfo win2k22 \
  --import --noautoconsole
