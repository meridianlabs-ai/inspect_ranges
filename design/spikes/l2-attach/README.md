# Spike: libvirt-in-container + L2 agent attach

*Validates the core runtime architecture bet from [the design handoff §4](../../inspect_ranges_handoff.md): a `range` container running libvirtd+QEMU with bridges in its own network namespace, and an agent container (started with `network_mode: none`) attached to a lab bridge at L2 via a veth pair moved in by a short-lived privileged helper. Run on an m6i.metal EC2 devbox (Ubuntu 24.04, Docker 29.8.1), 2026-10-01. `./run.sh` reproduces everything; `./run.sh down` tears it down.*

## Verdict

The architecture works as designed. No blocker found; every workaround needed is a config line, not a design change.

## What was demonstrated

- **libvirtd+QEMU run in an ordinary container without `--privileged`**: just `/dev/kvm`, `/dev/net/tun`, `/dev/vhost-net`, `cap_add: [NET_ADMIN]`, and `apparmor=unconfined`. KVM acceleration confirmed (`-accel kvm` on the QEMU process).
- **Full L2 adjacency for the agent**, which is what Responder/mitm6-class attacks need: ARP broadcast → unicast reply (~0.6–0.9 ms RTT), and — the strong direction — the agent *receives* broadcast frames emitted by the VM (tcpdump on `range0` captures the VM's ICMP broadcast ping).
- **The veth attach pattern from the handoff works verbatim**: a helper container with `--pid=host --network=host --privileged` creates the pair, pushes one end into each container's netns via `/proc/<pid>/ns/net`, enslaves the range side to `br-lab`. 0.3 s.
- **Containment held by construction**: the agent's only route is the lab segment; EC2 metadata (169.254.169.254), the range container's Docker-network IP, and the internet are all unreachable. `br-lab` carries no IP, so the hypervisor is not addressable from the lab segment.
- **Timings (metal, warm image cache)**: compose up 3.0 s, VM define+start 0.9 s, veth attach 0.3 s, cloud-init first boot to SSH-able 11 s — **~15 s cold total** for a 1-VM range.

## Gotchas found (each is a required config line)

1. **libvirt's DAC driver needs `CAP_SYS_ADMIN` to set `trusted.*` xattrs** (`Unable to set XATTR trusted.libvirt.security.dac`). Fix in `qemu.conf`: `dynamic_ownership = 0`, `remember_owner = 0` (plus `security_driver = "none"`, `user`/`group = root`, `cgroup_controllers = []` — the container is the isolation and resource boundary, not libvirt).
2. **The range container needs an init process** (`init: true` in compose). libvirt's QEMU gets reparented to PID 1; with `sleep` as PID 1 a destroyed VM stays a zombie and `virsh destroy` fails with `Failed to terminate process ... Device or resource busy`.
3. `apparmor=unconfined` on the range container: the host's AppArmor otherwise interferes with libvirtd's own profile management inside the container.

## What this does not yet validate (follow-ups)

- **VM exec path** (QEMU guest agent) — handoff §13 experiment 6. The lab segment is isolated, so installing the guest agent needs it baked into a derived image (the planned approach) rather than cloud-init `packages:`.
- Windows guests, boot storms, multi-segment topologies with routers, gp3 vs NVMe — handoff §13 experiments 2–5.
- Nested-virt instances (c8i/m8i/r8i): same architecture, but timings and stability under VM-exit load need their own measurement; this spike establishes the metal baseline.
- Capability floor: `NET_ADMIN` was sufficient here; a multi-VM/multi-bridge range with nftables inside the netns may need more (likely still short of `--privileged`).

## Files

- `compose.yaml` — the two-service topology (range + agent), devices/caps as above
- `range/` — range container image: libvirtd+QEMU, in-container `qemu.conf`, bridge-creating entrypoint
- `assets/` — cloud-init NoCloud seed inputs (static IP 10.80.10.10/24 on `br-lab`) and `boot-vm.sh` (overlay → seed ISO → `virt-install`)
- `attach-veth.sh` — the privileged helper's attach logic
- `run.sh` — end-to-end: up, boot, attach, test battery (ARP, broadcast receive, SSH, containment, teardown), with timings
