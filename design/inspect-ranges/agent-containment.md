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

**The vsock-exec spike removed the performance case for a container agent** (measured on m6i.metal, 2026-10-01): exec round-trip 1.1 ms median over vsock vs 44.5 ms for `docker exec`; file inject/extract at ~400/~700 MB/s (so runtime binary injection into standard images is cheap); exec_remote-style polling overhead is noise; background processes survive exec returns; boot-to-ready 9.6 s with the daemon baked into the image. One exec/file mechanism then serves the agent and Linux targets alike. (**Windows exception**, confirmed by [the win-guest spike](../spikes/win-guest/README.md): virtio-vsock has no Windows guest driver — `DEV_1053` stays unbound even after a full virtio-win install — so Windows targets use the QEMU guest agent for exec and ISO/disk hotplug for bulk file transfer. The agent box is Linux, so the agent's control plane is unaffected.)

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
- The production daemon needs (beyond the spike prototype): timeout enforcement with process-tree kill and kill-grace, stdout/stderr separation, output limits, cwd/env/user/stdin support, careful write semantics, a vsock↔loopback `forward` op for injected proxies, **idempotent retry-safe launches** (request IDs so a reconnect never double-runs), **durable results held until acknowledged** (a lost reply must be re-readable), strict schema validation of daemon replies with reader-side byte caps, a **hostile-daemon shim** in the conformance tests, and Inspect's sandbox `self_check` conformance in CI. These requirements are derived from the Proxmox provider's encoded qemu-ga experience — see [guest-exec-lessons](guest-exec-lessons.md).
- Hosts need the `vhost_vsock` module (doctor checks `/dev/vhost-vsock`; devbox bootstrap loads it).
- **Windows guests are outside the vsock plane** (no guest driver exists): exec via qemu-ga `guest-exec` (acceptable latency; drive it through the libvirt API, not virsh CLI, whose argument limit caps payloads at ~64 KB), bulk files via ISO/disk hotplug (~0.6 MB/s over qemu-ga makes it unusable for bulk). Memory snapshots (1.4 s restore measured) are the Windows boot-storm answer.

## L2 exposure: rules

Bridge adjacency adds little kernel surface beyond what the agent's in-VM root already has; what it changes is who the agent can talk to:

1. **Bridges stay dumb.** No IP on agent-facing bridges (the hypervisor is not addressable from the segment), no daemons listening on them, STP off.
2. **The expected attack chain is agent → target VM (by design) → attempted QEMU escape → range container.** The range container is a semi-trusted zone: unprivileged, no credentials, golden images read-only, guest-agent/vsock responses treated as untrusted input.
3. **Prefer static addressing (cloud-init/IPAM) over DHCP.** A dnsmasq on an agent-facing segment is agent-reachable userspace attack surface (DNSpooq-class history); where DHCP/DNS is required, scope it per segment and prefer a router *guest*.
4. **Within-segment L2 games (MAC spoofing, CAM flooding) are in-scope agent behavior**; cross-segment isolation comes from separate bridges with no trunking.
5. `br_netfilter` stays off (doctor checks). For `nat`-mode segments, egress policy is enforced in the range netns nftables *and* the security group; "agent reaches the internet through a NAT'd segment" is a mandatory negative test.

## What Docker still provides (none of it is agent isolation) — and the alternatives considered

After always-`kind: vm`, Docker touches exactly one thing — the range container — in five roles: (1) packaging/distribution of the hypervisor stack as a pinned, content-addressed OCI image, decoupled from the host OS and sharing registry infrastructure with the VM golden images; (2) lifecycle atomicity — `compose up/down` is the sample boundary, QEMU dies with the container, scratch volumes die with the project; (3) netns scoping of the whole range network, so bridges/nftables are created and destroyed atomically and never touch the host firewall (the §8a single-source-of-truth story); (4) **the second escape boundary** — the jail that turns a QEMU escape into "unprivileged process" rather than "host root" (device allowlist, zero-to-one capabilities, seccomp, tailored AppArmor per backlog item 6); (5) per-sample cgroup limits. Runtime weight is negligible: one container per sample, ~3 s `compose up` (spikes), no measurable QEMU overhead (handoff §6).

Alternatives weighed (2026-10-01), and why Docker stays:

- **libvirtd on the host (no container)** — lighter, and strictly worse on all five roles; collapses the escape chain to guest→QEMU→host. Rejected.
- **Podman, especially rootless** — the one alternative with a real security argument: daemonless (no root dockerd/socket) and container-root-as-unprivileged-uid. Device access works via the `kvm` group. Rejected for now because the ecosystem speaks Docker (fleet integration, inspect_ai's ported Docker CLI resilience code, devbox, compose fidelity), and both gains have in-place equivalents: the socket is already unreachable from the range container, and **Docker userns-remap** (backlog item 8) delivers unprivileged container root without leaving the ecosystem. If userns-remap proves painful and the post-escape position still needs demotion, Podman's Docker-compatible socket makes this a swap at the seam, not a redesign.
- **containerd/nerdctl, systemd-nspawn, raw runc** — remove dockerd, then reimplement image distribution, lifecycle, and limits with less tooling. Rejected.
- **gVisor / Kata / Firecracker / outer VM as the container layer** — structurally unfit: gVisor cannot pass KVM ioctls; the others reintroduce nesting or cannot expose KVM at all. Rejected above.

**Open question (not an action): libvirtd itself.** The heavyweight surface inside the range container is libvirtd, of which we use a thin slice (domain lifecycle, console, screenshot, hotplug). Driving QEMU directly would shrink the container's daemon surface at the cost of reimplementing that slice. Same trade-off structure as the Docker question; park until the sandbox provider's real libvirt usage is known.

## How hard is the QEMU boundary? (grading the escape tiers)

Not all VM boundaries are equal, and we should not claim otherwise. The honest ordering, hardest first: **Nitro** (hardware/firmware hypervisor, no public escape ever documented, carries EC2's entire multi-tenant business) > **Firecracker** (~50K lines of Rust, deliberately tiny device model, seccomp jailer, proven as a production multi-tenant boundary in Lambda/Fargate) > **QEMU/KVM** (large C codebase with a long device-emulation CVE history; escapes are demonstrated at security contests on a recurring basis). Two qualifiers keep the QEMU tier acceptable here: (1) nearly all historical escapes land in the **QEMU userspace process** — which for us is inside an unprivileged, credential-free container, not the host — while KVM-module escapes (straight to host kernel) are far rarer; (2) the practical surface is the *configured* device model — minimal for us once backlog item 3 lands. (Not yet true: the spike guests carry virt-install defaults — USB controller, memballoon, SATA cdrom for seed ISOs — and `seccomp_sandbox` is unset. Verified by `--print-xml` probe, 2026-10-01.) The architecture then pairs boundary strength to stakes: the hardest boundary (Nitro) guards the highest stakes (inter-sample/tenant isolation); QEMU guards intra-sample stakes (eval validity), where a breach costs one sample, detectably. If the agent boundary ever needs a Firecracker-class upgrade, the candidate is running the *agent* VM under a rust-vmm hypervisor (e.g. cloud-hypervisor) while targets stay on QEMU — noted, not planned.




## Hardening backlog (2026-10-01, ranked)

1. **Branch protection + required review on `main`, signed commits** (org/GitHub settings). The devbox GitHub token is the one asset reaching beyond any single box; this converts token theft from silent supply-chain compromise into a noisy failed attempt.
2. **Evidence streaming off-instance implemented early.** It is the integrity story for the whole posture; until it exists, detection-over-prevention is a plan, not a property.
3. **QEMU surface reduction in the range container** — not yet done (spike guests have virt-install defaults: USB controller, memballoon, SATA cdrom). Two profiles, because minimality and realism pull apart by role: the **agent VM** gets strict-minimal (virtio disk/net/vsock + serial console + virtio-rng; no USB, no video, no memballoon, no cdrom once the daemon is baked in); **target VMs** get minimal-consistent-with-realism (video only where the scenario needs screenshots/console, seed data via virtio disk rather than SATA cdrom where the OS allows). Plus `seccomp_sandbox = 1` in qemu.conf, QEMU pinned and current, and the range.yaml compiler emitting every device explicitly (single-source-of-truth: no tool defaults deciding the attack surface).
4. **Deny `AF_VSOCK` to non-range containers on dev boxes** (seccomp): CIDs are host-global, so this closes "some other container connects to a guest CID". Prod is covered by one-sample-per-instance.
5. **Tripwires:** alert on abnormal QEMU exits (a failed escape looks like a crash); canary credentials inside the range container that phone home on use.
6. **Replace `apparmor=unconfined` on the range container with a tailored profile** (unconfined was spike convenience, not a decision).
7. **Devbox egress tightening** (allowlist proxy for GitHub/apt/PyPI rather than all of 443) and the burn-after-risky-run practice (`destroy`/`up`) as documented habit.
8. **Evaluate Docker userns-remap for the range container**: container root becomes an unprivileged host uid, demoting the post-QEMU-escape position further. The work is device-access plumbing (group ACLs on `/dev/kvm`, `/dev/vhost-net`, `/dev/vhost-vsock`, `/dev/net/tun` for the remapped uid) — contained and testable. If it proves painful, rootless Podman via its Docker-compatible socket is the recorded fallback.

Residual risks accepted, with eyes open: a QEMU 0-day unwinds the main intra-sample boundary (mitigated by items 3 and 5, blast radius capped at one sample by Nitro); the devbox always holds richer assets than prod (mitigated by item 1 and by keeping adversarial runs on prod).

## Revisit if

- Multi-sample-per-instance packing is proposed — boundary re-derivation from scratch, including the global CID space.
- Per-call exec cost ever dominates eval cost in a way vsock doesn't explain — only then consider a `kind: container` agent as an optimization.
- Evidence streaming off-instance is weakened or batched — detection is the integrity story, so its latency matters.
- vsock namespacing lands in mainline kernels — the CID-allocation and peer-check rules simplify.
