# Spike: spec → compiled networking → enforced topology

*Validates the central novel claim of the architecture — [handoff §8a](../../inspect_ranges_handoff.md)'s "one source of truth for networking": a `range.yaml`-shaped spec is **compiled** into every networking artifact (IPAM allocation, bridges, per-VM cloud-init seeds, the router's nftables ruleset, hypervisor-netns invariants, boot plan), the topology boots under the range container, and the declared ACLs demonstrably hold. Handoff §13 experiment 9. Run on the m6i.metal devbox, 2026-10-01. `./run.sh` reproduces everything; `./run.sh down` tears down.*

## Verdict

**The compile-don't-configure model works end to end.** A 40-line spec produced a running two-segment topology (router, two targets, agent VM — all four vsock-controlled) where every declared allow and deny was enforced, nothing was hand-configured downstream of the spec, and the host network namespace showed zero range artifacts even while the range ran.

## What was demonstrated

- **Topology**: `dmz` (10.80.10.0/24: agent .2, web .10) and `internal` (10.80.20.0/24: db .10), joined by a **router guest** (.1 on each) with a generated asymmetric ACL: dmz→internal `tcp/5432` only; internal→dmz nothing; stateful returns allowed. The MHBench-style pattern.
- **Deterministic IPAM**: addresses, MACs, and vsock CIDs allocated by the compiler and emitted as `allocation.json`. MAC-match + `set-name` in the generated netplan makes NIC names (`dmz0`, `internal0`) stable, which is what lets the *generated nftables reference interfaces symbolically* — the two artifacts are consistent by construction.
- **Every test passed, including the negatives** (the ones that catch broken ACL compilers):
  - allowed cross-segment port: fast `connection refused` from db — proving routing, the ACL accept, *and* the stateful return path in one observation (the RST traversed internal→dmz);
  - **denied-but-listening**: db's sshd is up, agent's connection to it times out — enforcement, not absence of listener;
  - asymmetry: db cannot open connections to dmz despite web's live listener;
  - cross-segment ICMP blocked; same-segment L2 intact; forced ARP for an internal IP on the dmz bridge gets no reply (segments are separate broadcast domains);
  - **host invisibility mid-run**: zero range bridges in the host netns while the range is live; teardown leaves the host link table exactly as found.
- **Timings (4 VMs, shared golden overlay, metal)**: all vsock daemons ready **16s** after `compose up`; full range-ready (cloud-init complete, router firewall live) **50s**.

## Findings with design consequences

1. **Readiness must gate on cloud-init completion, not daemon-up.** The router's forwarding sysctl and nftables load in cloud-init's *final* stage; the vsock daemon comes up earlier. A health model that pings daemons would declare an unenforced range "ready" (we hit exactly this: `ip_forward=0` when probed early). The sandbox's readiness check must wait for per-VM provisioning completion — and the ~34s cloud-init tail (ssh keygen, seeding) is a boot-time optimization target for production images.
2. **Backing-file references in the image cache must be relative.** The cache mounts at a different path inside the range container (`/images`); an absolute host path in a qcow2 backing reference breaks every overlay. Rule for the image pipeline: create derived images with relative backing paths (or rebase on publish).
3. **`virt-customize --install` is broken on Ubuntu 24.04 hosts** (libguestfs' `passt` network backend exits 1 — the noble unprivileged-userns AppArmor restriction). Offline customization (`--no-network --copy-in`) is unaffected. Consequence: runtime image *derivation* stays offline-only; package installation belongs in the Packer CI pipeline, not on eval hosts. (Also: the noble cloud image already ships `nft` and `tcpdump`, which is why this spike needed no installs at all.)
4. **Router-as-guest is the right ACL realization** (vs nwfilter/host rules): the generated ruleset is ordinary nftables a defender could also inspect in-range (realism), and the hypervisor netns carries only *invariants* (FORWARD drop — belt-and-braces, since bridged frames bypass that hook with br_netfilter off and no bridge has an IP).
5. The vsock control plane scaled to 4 concurrent guests (CIDs 3–6) with per-VM exec throughout — including driving tests *from inside* the agent and db VMs — previewing Linux targets using the same exec plane as the agent.

## Files

- `spec.yaml` — the 40-line two-segment spec (v0.1-subset shape)
- `compile.py` — spike-grade compiler: spec → `tmp/render/` (allocation.json, bridges.txt, range-netns.nft, per-VM seeds, boot-vms.sh); nothing downstream is hand-written
- `range/` — range container (libvirtd+QEMU+nftables); entrypoint realizes bridges + netns ruleset from `/render`
- `run.sh` — image build (first run), compile, boot, cloud-init gate, 9-test battery
