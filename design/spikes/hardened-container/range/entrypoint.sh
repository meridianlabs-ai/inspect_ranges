#!/bin/bash
# Same realization as net-compile's entrypoint (bridges + netns nftables +
# libvirtd), plus device-node ownership for the non-root QEMU: the nodes
# docker creates in this container's /dev are container-local, so chowning
# them touches nothing on the host.
set -euo pipefail

chown root:kvm /dev/kvm /dev/vhost-net /dev/vhost-vsock
chmod 660 /dev/kvm /dev/vhost-net /dev/vhost-vsock

while read -r name; do
  ip link add "$name" type bridge
  ip link set "$name" up
done < /render/bridges.txt
# no IPs on bridges: the hypervisor is not addressable from any segment

nft -f /render/range-netns.nft

mkdir -p /run/libvirt
/usr/sbin/virtlogd -d
/usr/sbin/libvirtd -d
until virsh -c qemu:///system version >/dev/null 2>&1; do sleep 0.2; done
touch /run/range-ready
echo "hardened range container ready: $(wc -l < /render/bridges.txt) bridges, netns nftables loaded"
exec sleep infinity
