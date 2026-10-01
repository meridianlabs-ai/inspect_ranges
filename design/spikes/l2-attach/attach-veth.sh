#!/bin/bash
# Veth attach, run inside a short-lived privileged helper container
# (--pid=host --network=host, /var/run/netns not needed: we address netns via
# /proc/<pid>/ns/net). Args: <range-pid> <agent-pid> <bridge> <agent-ip/cidr>.
set -euxo pipefail

RANGE_PID=$1
AGENT_PID=$2
BRIDGE=$3
AGENT_ADDR=$4

# create the pair in this (host) netns, then push each end where it belongs
ip link add spike-veth0 type veth peer name range0
ip link set spike-veth0 netns "$RANGE_PID"
ip link set range0 netns "$AGENT_PID"

# range side: enslave to the lab bridge
nsenter -t "$RANGE_PID" -n ip link set spike-veth0 master "$BRIDGE"
nsenter -t "$RANGE_PID" -n ip link set spike-veth0 up

# agent side: address + up
nsenter -t "$AGENT_PID" -n ip addr add "$AGENT_ADDR" dev range0
nsenter -t "$AGENT_PID" -n ip link set range0 up

nsenter -t "$AGENT_PID" -n ip -brief addr show range0
