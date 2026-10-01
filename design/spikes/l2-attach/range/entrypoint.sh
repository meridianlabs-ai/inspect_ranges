#!/bin/bash
# Create the lab bridge inside this container's netns, then run libvirt daemons.
set -euo pipefail

ip link add br-lab type bridge
ip link set br-lab up
# deliberately no IP on br-lab: the hypervisor host is not reachable from the
# lab segment (handoff §5)

mkdir -p /run/libvirt
/usr/sbin/virtlogd -d
/usr/sbin/libvirtd -d

# readiness marker for the healthcheck/orchestrator
until virsh -c qemu:///system version >/dev/null 2>&1; do sleep 0.2; done
touch /run/range-ready
echo "range container ready: br-lab up, libvirtd running"
exec sleep infinity
