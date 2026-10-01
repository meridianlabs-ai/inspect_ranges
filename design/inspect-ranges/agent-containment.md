---
type: decision
title: "Untrusted-agent containment: the agent is always a VM; Nitro per sample is the inter-sample boundary"
status: accepted
tags: [inspect-ranges, security, containment, sandbox, vsock, decision]
timestamp: 2026-10-01
---

# Untrusted-agent containment: the agent is always a VM; Nitro per sample is the inter-sample boundary

*Decision record. Originally drafted the same day with a hardened-runc default agent container; revised after the [l2-attach](../spikes/l2-attach/README.md) and [vsock-exec](../spikes/vsock-exec/README.md) spikes showed the VM agent is both stronger and faster, which removed the reason to keep a container agent at all.*

## Decision

- **The agent box is always a VM (`kind: vm`)** — an ordinary libvirt guest booted by the range container, from one of a small set of standard images (Kali for attack, Debian for generic) with the vsock exec daemon and QEMU guest agent baked in. Scaffold binaries are injected at runtime (inspect_swe-style) over the vsock file plane. A `kind: container` agent is a possible *future optimization*, not a v1 feature.
- **The control plane is virtio-vsock, not a network.** The agent VM gets lab-segment NICs only — no management NIC, no veth, nothing in-range defenders can discover or firewall. Loopback exists in the guest for injected proxies; their upstream leg rides a vsock `forward` op.
- **No privileged components anywhere.** The veth attach helper (the one privileged piece of the container-agent design) is deleted; agent NICs are ordinary libvirt interfaces generated from the spec. The range container runs unprivileged (devices + `NET_ADMIN` for bridged ranges; *no* capabilities for vsock-only operation, per the spike).
- **The inter-sample security boundary is Nitro: one sample per EC2 instance** (handoff §5). Everything on the instance belongs to one sample.
- **Sample integrity is protected by detection, not prevention**: evidence (pcaps, console logs, scoring artifacts) streams off-instance as generated, so an escaped agent can invalidate its sample but cannot silently falsify it.

## Why

**The vsock-exec spike removed the performance case for a container agent** (measured on m6i.metal, 2026-10-01): exec round-trip 1.1 ms median over vsock vs 44.5 ms for `docker exec`; file inject/extract at ~400/~700 MB/s (so runtime binary injection into standard images is cheap); exec_remote-style polling overhead is noise; background processes survive exec returns; boot-to-ready 9.6 s with the daemon baked into the image. One exec/file mechanism then serves agent and targets alike.

**The VM boundary buys something real: eval validity.** Within a sample, the strongest reason for agent isolation isn't infrastructure (Nitro handles that) — it's that an agent escaping a *container* on the eval host gets the Docker socket, and with it the range spec, planted flags, and `attack_path`: the ability to cheat quietly rather than solve. A KVM boundary in front of `NET_ADMIN`/`NET_RAW` tooling (the historically buggiest kernel LPE surfaces: nf_tables, AF_PACKET, tc/qdisc) closes the cheap version of that path. And the containment conversation is simply over: the answer to every isolation question about the agent is "it's a KVM guest."

**Alternatives rejected:**

- **Hardened runc container** (the original decision): acceptable risk-wise given Nitro-per-sample, but it kept the privileged veth helper, a second exec path, and a permanent isolation debate — for an exec path that turned out to be 40× *slower* than vsock.
- **gVisor**: non-Linux netstack vs offensive tooling's reliance on kernel corners (AF_PACKET, BPF, netlink) — the L6 failure mode, measuring the sandbox instead of the model.
- **Kata**: "run it in a VM" is what `kind: vm` does natively, without pushing L2 attachment through shim/CNI plumbing.
- **An outer wrapper VM moves the fence without adding one**: everything must live inside it and evidence already leaves the machine, so nothing valuable sits outside it on the host — while every range VM becomes a nested guest (the VM-exit tax metal was chosen to avoid). Firecracker specifically cannot host this workload (no nested KVM).

**Precondition — single sample per instance.** This posture is derived from the asset layout: one sample per instance, evidence off-instance, no secrets on-box. If multi-sample-per-instance packing is ever proposed (e.g. for cost), the boundary between tenants must be re-derived from scratch. The vsock plane leans on this too (below).

## The vsock control plane: rules

- **CIDs are host-kernel-global, not namespaced.** QEMU-in-container allocates from the host's CID space, and any host process can connect to any guest CID. Consequences: CID allocation is a deterministic per-host resource (IPAM-style); the guest daemon must accept connections only from CID 2 (the host); and isolation of the control plane between samples relies on one-sample-per-instance.
- **Daemons are baked into the standard images**, not delivered by cloud-init (a NIC-less guest stalls ~2 min on `systemd-networkd-wait-online` before cloud-init's final stage; baked boot is ~10 s).
- The production daemon needs (beyond the spike prototype): timeout enforcement with process-tree kill, stdout/stderr separation, output limits, careful write semantics, a vsock↔loopback `forward` op for injected proxies, and Inspect's sandbox `self_check` conformance in CI.
- Hosts need the `vhost_vsock` module (doctor checks `/dev/vhost-vsock`; devbox bootstrap loads it).

## L2 exposure: rules

Bridge adjacency adds little kernel surface beyond what the agent's in-VM root already has; what it changes is who the agent can talk to:

1. **Bridges stay dumb.** No IP on agent-facing bridges (the hypervisor is not addressable from the segment), no daemons listening on them, STP off.
2. **The expected attack chain is agent → target VM (by design) → attempted QEMU escape → range container.** The range container is a semi-trusted zone: unprivileged, no credentials, golden images read-only, guest-agent/vsock responses treated as untrusted input.
3. **Prefer static addressing (cloud-init/IPAM) over DHCP.** A dnsmasq on an agent-facing segment is agent-reachable userspace attack surface (DNSpooq-class history); where DHCP/DNS is required, scope it per segment and prefer a router *guest*.
4. **Within-segment L2 games (MAC spoofing, CAM flooding) are in-scope agent behavior**; cross-segment isolation comes from separate bridges with no trunking.
5. `br_netfilter` stays off (doctor checks). For `nat`-mode segments, egress policy is enforced in the range netns nftables *and* the security group; "agent reaches the internet through a NAT'd segment" is a mandatory negative test.

## What Docker still provides (none of it is agent isolation)

The range container remains the hypervisor's packaging and lifecycle system: libvirtd+QEMU pinned and distributed as an image, decoupled from the host OS; per-sample bridges and nftables scoped in a netns created and destroyed atomically with the container (the §8a single-source-of-truth story); per-sample cgroup limits; the integration seam with the AWS fleet layer (handoff §11).

## Revisit if

- Multi-sample-per-instance packing is proposed — boundary re-derivation from scratch, including the global CID space.
- Per-call exec cost ever dominates eval cost in a way vsock doesn't explain — only then consider a `kind: container` agent as an optimization.
- Evidence streaming off-instance is weakened or batched — detection is the integrity story, so its latency matters.
- vsock namespacing lands in mainline kernels — the CID-allocation and peer-check rules simplify.
