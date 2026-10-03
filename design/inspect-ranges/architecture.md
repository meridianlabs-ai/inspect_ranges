---
type: document
title: "inspect_ranges — design and architecture review (draft 1)"
audience: broader review (eng, security, Inspect maintainers)
status: draft-for-review
tags: [inspect-ranges, architecture, review]
timestamp: 2026-10-01
---

# inspect_ranges — design and architecture review (draft 1)

*First full draft for broader review. Everything claimed as **measured** was run on an m6i.metal EC2 devbox (Ubuntu 24.04, Docker 29.8.1) on 2026-09-30/10-01 and is reproducible from a spike directory in this repo (`design/spikes/*/run.sh`). The document distinguishes throughout between what is **implemented and demonstrated** and what is **designed but unbuilt** — see the ledger in §11. Detailed decision records are linked per section; this document is the synthesis, not the only source.*

## 1. What this is and why

`inspect_ranges` is an [Inspect AI](https://inspect.aisi.org.uk) extension that lets eval authors define multi-host cyber ranges — including Active Directory networks — in a single `range.yaml`, and run them as Inspect sandboxes with strong containment and a fast iteration loop. The product thesis (from practitioner feedback): ranges fail as evals because they are cumbersome to build and maintain, so **developer experience is the product** — one spec, compiled (never hand-configured) realization, tooling to validate/render/inspect, and the same spec portable across deployment backends.

The design baseline is six real public ranges translated from fetched upstream configs (vulhub CVE stack, KYPO routed demo, CyRIS firewalled segments, MHBench breach-derived enterprise, GOAD-Light AD forest, Splunk attack_range telemetry lab) — chosen so every schema field and networking requirement is *forced by a real artifact*, not invented ([survey](survey.md), [requirements table](range-yaml-swag.md)).

## 2. System overview

```
Inspect eval (controller)
  └─ sharding layer: dispatches samples, one resident sample per Nitro instance
       └─ EC2 Nitro instance  ──────────────  the inter-sample security boundary
            └─ Inspect worker + inspect_ranges provider (local Docker daemon)
                 └─ "range" container (unprivileged; libvirtd + QEMU; init: true)
                      ├─ bridges + generated nftables  (in the container's netns only)
                      ├─ router VM(s)   ─ generated nftables = the declared ACL
                      ├─ target VMs     ─ Linux: vsockd │ Windows: qemu-ga
                      └─ agent VM       ─ always a VM; controlled ONLY via vsock
```

Key properties, each elaborated below: the **agent is always a VM** (§6); the **control plane is virtio-vsock, not a network** (§5); **all networking is compiled from the spec** into inspectable artifacts (§4); **nothing runs privileged** anywhere in the runtime (§6); the **host netns carries zero range state** even while a range runs (§4); **Nitro one-sample-per-instance is the only inter-tenant boundary**, and the layers inside exist for eval validity, not tenant isolation (§6).

## 3. The spec layer: `range.yaml` schema v0.1 — implemented

([schema-v0.1-scope](schema-v0.1-scope.md); code: `src/inspect_ranges/schema.py`; CLI: `inspect-ranges validate`, `inspect-ranges schema`.)

v0.1 covers **only what the runtime consumes** — `range` (identity/provenance), `networks`, `routers` (with the ACL), `hosts`, `attacker` — validated strictly (unknown keys are errors; pydantic `extra="forbid"` plus cross-reference checks). Everything half-designed is **excluded entirely**, parked verbatim in each example's `deferred.yaml`, with a deferral table recording what unblocks each (attack_path → AD edge vocabulary; variables/generation → the L2 layer; goals/oracles → real scorers; defense → D-tier experience; guest config → the provisioning pipeline). All six example ranges validate green; sentinels like `to-verify` live in comments, never in typed values.

A complete valid range (the smoke-test example, abridged):

```yaml
range:
  name: vulhub-zabbix
  schema_version: "0.1"
  description: >
    A realistic 4-host Zabbix monitoring stack on one flat network ...
  # upstream provenance lives in source.md beside the spec (convention, not schema)

networks:
  - name: lab
    cidr: 10.10.10.0/24
    mode: isolated                  # isolated | nat | routed
    dns: { records: [{ name: server }, { name: web }, ...] }

hosts:
  - name: web
    os: { type: linux }
    image: vulhub/zabbix:3.0.3-web
    interfaces: [{ network: lab }]  # ip omitted → deterministic IPAM

attacker:
  interfaces: [{ network: lab }]    # a dedicated attack VM on the segment
  entry: external
  egress: none                      # default
```

Inter-segment policy is **one vocabulary, on routers**, default-deny and stateful — the shape the networking spike proved end to end:

```yaml
routers:
  - name: router_external
    interfaces: [{ network: dmz }, { network: internal }]
    acl:
      - { from: dmz, to: internal, allow: [tcp/5432] }   # proto/port or proto/lo-hi
```

Cross-validators enforce: unique names, every interface/ACL endpoint references a declared network, explicit IPs within their subnet, attacker foothold rules. The JSON Schema is exported for editor completion (`inspect-ranges schema`).

## 4. Networking: compiled, never configured — demonstrated

([net-compile spike](../spikes/net-compile/README.md); design principle: handoff §8a "one source of truth".)

The known failure mode of libvirt-based ranges is firewall/network config drifting apart from the spec. Our answer: **every networking artifact is generated** — deterministic IPAM (IPs, MACs, vsock CIDs, emitted as `allocation.json`), bridge plan, per-VM cloud-init seeds, the router's nftables ruleset, hypervisor-netns invariants, and the boot plan. Nothing downstream of the spec is hand-written; NIC naming via MAC-match + `set-name` makes the generated firewall and the generated interfaces consistent by construction. The generated router ruleset for the ACL above:

```
table inet fw {
  chain forward {
    type filter hook forward priority 0; policy drop;
    ct state established,related accept
    iifname "dmz0" oifname "internal0" tcp dport 5432 accept
  }
}
```

**Demonstrated** (two-segment range: router, two targets, agent — all booted from a 40-line spec): same-segment L2 intact; allowed cross-segment port reachable (fast RST proves routing + accept + stateful return in one observation); **denied-but-listening** port drops (enforcement, not absence of listener); asymmetric deny holds against a live listener; cross-segment ICMP blocked; segments are separate broadcast domains (forced ARP gets no reply); **zero range bridges visible in the host netns while the range runs**; teardown leaves the host link table exactly as found. Bridges live in the range container's network namespace and die with it — rules never touch the host firewall.

Realization choices: router-as-guest (ordinary nftables a defender could inspect in-range — realism), bridges carry no IP (hypervisor not addressable from any segment), the range netns carries only generated invariants (FORWARD drop), `br_netfilter` off (doctor-enforced).

## 5. Guests and the control plane

### The agent is always a VM, controlled over vsock — demonstrated

([agent-containment](agent-containment.md); [vsock-exec spike](../spikes/vsock-exec/README.md).)

The agent boots as an ordinary libvirt guest from a standard image (Kali for attack, Debian for generic) with a small exec/file daemon baked in. The harness drives it over **virtio-vsock — a hypervisor channel, not a network**: no management NIC exists, nothing in-range can discover or firewall the control plane, and a NIC-less guest is fully controllable (demonstrated). Loopback exists in the guest, so injected proxies (inspect_swe-style runtime binary injection) work; their upstream leg rides a vsock `forward` op.

Measured (metal): exec round-trip **1.1 ms median** (vs 44.5 ms for `docker exec` — the VM path is ~40× faster than the container path it replaced); file inject/extract **~400/~700 MB/s**; exec_remote-style polling overhead is noise; background processes survive exec returns; boot-to-daemon-ready **9.6 s** with the daemon baked into the image (cloud-init delivery costs +2 min on NIC-less guests — hence baked images are a requirement, not a preference).

### Windows targets: qemu-ga, by necessity — demonstrated

([win-guest spike](../spikes/win-guest/README.md); [guest-exec-lessons](guest-exec-lessons.md).)

**virtio-vsock has no Windows guest driver** (confirmed empirically: the vsock PCI device stays unbound in Error state after a full virtio-win install). So the exec plane splits by guest OS: **vsock for the agent and Linux targets; QEMU guest agent for Windows targets**, with ISO/disk hot-plug as the Windows bulk-transfer path (qemu-ga files measured at ~0.6 MB/s — unusable for bulk).

Windows economics measured on metal: unattended Server 2022 install → finalized golden image **189 s**; boot from golden overlay to exec-responsive **6.5 s**; memory snapshot save **10.1 s** (4 GB → 1.16 GB state), **restore 1.3 s** with the agent responsive 0.1 s later. Snapshot-after-AD-converges is the Windows boot-storm answer.

### The exec/file contract (the hard-won part)

The Proxmox provider (MIT) encodes the qemu-ga edge cases we would otherwise rediscover, and its lessons bind our vsock daemon as *contract* even where the transport dodges the mechanics ([guest-exec-lessons](guest-exec-lessons.md)):

- Never run the user's command directly: a generated wrapper applies cwd/env/user/stdin, enforces the timeout **in-guest** (`timeout -k`), and writes results to durable storage — because qemu-ga's `exec-status` is **single-shot** (output is discarded after one read) and retried launches can double-run (their flock guard; our request IDs).
- The virtio-serial channel fails **~5–7% of calls on Windows** — retry with transient/permanent classification and layered budgets is a protocol layer, not an afterthought.
- **Every reply from a guest is attacker-controlled** (an agent that roots a VM owns its daemon): strict schema validation, tamper errors, reader-side byte caps, and a hostile-daemon shim in the conformance tests.
- Inspect's sandbox `self_check` suite is the acceptance test for both planes.

### Images

Pinned upstream cloud images → derived goldens via offline `virt-customize` (daemon baked in; package installation belongs in Packer CI — `--install` is broken on noble hosts); qcow2 overlays per guest on read-only goldens, never in a container layer; backing references must be relative (cache mounts at a different path in-container); publication as **content-addressed qcow2 delta layers over OCI/ORAS** — Docker's distribution model with backing chains in place of overlayfs — with EBS-snapshot/FSR caches as the fleet cold-start path and lazy HTTP backing (`curl` driver + copy-on-read; measured: 0.4 s boot penalty, chains resolve over HTTP, self-warming cache) as the registry-direct path ([image-distribution](image-distribution.md), [lazy-pull spike](../spikes/lazy-pull/README.md)). Standard agent/guest images ship **zero network listeners** (`ss -tlnp` empty at boot — access is vsock-only); the current spike images violate this (cloud-image sshd), recorded as hardening backlog item 9.

## 6. Security posture

([agent-containment](agent-containment.md) is the full record; this is the synthesis.)

**Threat model.** The untrusted principal is the agent (potentially a frontier model) with root and raw-network tooling inside its VM — `NET_ADMIN`/`NET_RAW`-class capabilities are the product, not a privilege to withhold. Targets become attacker-controlled *by design* once compromised, so their daemons' outputs are untrusted too. Assets: (inter-sample) other tenants' samples; (intra-sample) eval validity — scoring artifacts, flags, evidence.

**Boundary stack and escape chain.** The agent faces, in order: (1) **KVM** — a hypervisor escape through a minimal virtio device model is the only opening move; commodity container escapes don't apply. (2) Landing in the QEMU process means landing in an **unprivileged, credential-free container** (no Docker socket, read-only goldens, IMDS blocked by hop-limit-1, `NET_ADMIN` scoped to its own netns; the l2-attach/vsock spikes ran it with zero-to-one capabilities and no `--privileged` anywhere — the previously-privileged veth helper is deleted by the always-VM design). (3) Host root requires a *second, independent* kernel/runc exploit. (4) The host is deliberately **asset-free**: no secrets, evidence streamed off-instance, Nitro caps the blast radius at one invalidated sample.

**Honest tier grading.** Nitro (no public escape; carries EC2 multi-tenancy) > Firecracker (~50 K lines Rust, tiny device model, production multi-tenant boundary) > QEMU/KVM (large C codebase, recurring contest escapes — but nearly all land in the QEMU *process*, i.e. our jailed container, and the practical surface is the *configured* device model). The architecture pairs boundary strength to stakes: Nitro guards tenants; QEMU guards one sample's validity, where a breach is detectable and discardable.

**Comparison to the existing Nitro → Firecracker → Docker sandbox stack.** Equivalent at the tenant boundary (both reduce to Nitro with single-tenancy); honestly weaker in composition relative to the host kernel (their strongest software boundary sits closest to the host; ours inverts that, and QEMU is C, not Rust); stronger at the first boundary (hardware virt first — the workload is more hostile and still never faces runc as the opening move); and the only stack that can host virtualization-as-workload at all (Firecracker exposes no KVM to guests — which also rules out running ranges inside the Firecracker tier of the existing runtime; range samples route to instances directly).

**Why the VM boundary earns its cost: eval validity.** An agent that escapes a *container* on the eval host gets the Docker socket — and with it the range spec, planted flags, and the answer key: the ability to cheat quietly rather than solve. Behind KVM, that costs a hypervisor escape first. Detection (evidence streaming) covers tampering; the VM boundary covers *reading the answers*, which is quieter than tampering.

**vsock-plane security.** CIDs are host-kernel-global (not namespaced): allocation is deterministic per host, guests' daemons accept only CID 2 (the hypervisor host), and isolation of the control plane between samples leans on one-sample-per-instance — restated as a dispatch constraint in §7. Guest daemons are untrusted endpoints (above).

**Defender→agent isolation.** In-range defenders cannot *connect* to the agent (the control plane has no IP endpoint; standard images ship zero network listeners — the only connectable surface is a port the agent opened as tradecraft), can *detect* only its transmitted traffic (interior, control channel, and oracle are invisible to in-guest defenders; fingerprinting is homogeneous with targets), and cannot *own* it remotely except by hack-back through the agent's own tooling — a per-range D5 policy decision; even then an owned agent box cannot pivot (vsock is host↔guest only) and costs one detectable sample. Defender→agent port scans returning zero open ports are mandatory range conformance checks. Full analysis in [agent-containment](agent-containment.md).

**Precondition, stated loudly: one sample per instance.** The entire posture is derived from this asset layout. If multi-sample packing is ever proposed, the container boundary becomes load-bearing between tenants and everything in this section must be re-derived.

**Dev vs prod.** The devbox (shared, holds a repo-scoped GitHub token, 443 egress) runs the identical containment stack, so routine dev-grade runs are fine; genuinely adversarial runs belong on production instances. Isolation level is a **logged per-sample claim** (`instance` vs `shared`), with warnings for untrusted-model evals on shared hosts.

**Hardening backlog** (ranked; items 3 and 6 are "make QEMU-in-a-jail approximate Firecracker-in-a-jailer"):
1. Branch protection + required review on `main` (blunts the one asset that reaches beyond any box — the devbox GitHub token).
2. Evidence streaming off-instance implemented early (it *is* the integrity story).
3. QEMU surface reduction — **not yet done**: spike guests carry virt-install defaults (USB controller, memballoon, SATA cdrom; verified by `--print-xml` probe) and `seccomp_sandbox` is unset. Two device profiles: agent VM strict-minimal; targets minimal-consistent-with-realism. The compiler must emit every device explicitly — tool defaults must never decide attack surface.
4. Deny `AF_VSOCK` to non-range containers on dev boxes.
5. Tripwires: alert on abnormal QEMU exits; canary credentials in the range container.
6. Tailored AppArmor profile for the range container (currently `apparmor=unconfined` — spike convenience, not a decision).
7. Devbox egress allowlisting; burn-after-risky-run practice.
8. Evaluate Docker userns-remap (container root → unprivileged host uid); rootless Podman via its Docker-compatible socket is the recorded fallback.

**Residual risks, accepted with eyes open:** a QEMU 0-day unwinds the intra-sample boundary (mitigated by 3/5; blast radius capped by Nitro); the devbox always holds richer assets than prod (mitigated by 1 and run placement). If the agent boundary ever needs Firecracker-class strength, the recorded upgrade path is a rust-vmm hypervisor (cloud-hypervisor) for the agent VM only — possible because the vsock plane doesn't care which VMM is underneath.

## 7. Deployment: sharded Inspect, strictly local realization

([host-provider](host-provider.md).)

Inspect's sharding layer dispatches samples to instances; a worker runs on each instance and drives `inspect_ranges` against the **local** Docker daemon — the vsock fast path everywhere, no remote plumbing. Both target environments converge: the orchestration environment's integration is "provision a Nitro instance (our bootstrap/AMI: Docker + host prerequisites, gated by `inspect-ranges doctor --json`, fixable by `doctor --fix-script`) → run the worker on it"; the run-inside-Nitro environment already works this way. Docker's role is precisely scoped: packaging/lifecycle/netns-scoping/cgroups for the hypervisor stack — never agent isolation (alternatives analysis in [agent-containment](agent-containment.md): host-libvirtd, Podman, containerd, gVisor/Kata all weighed and rejected or deferred).

What we require from the sharding layer: at most one resident sample per instance; the worker told its isolation level (for the logged claim); **mid-run log/evidence sync** off-instance — *open external dependency: confirm Inspect sharding supports mid-run sync; if end-of-shard only, evidence streaming needs its own channel.*

A second, fully supported topology (revised 2026-10-03) separates the scaffold from the range: a pluggable `HostProvider` lets an orchestration layer allocate a machine per sandbox, with exec bridged over a held-open `docker exec`↔vsock stream. This is the **stronger posture** — the worker's model credentials and eval state live outside the attackable instance — and is preferred for untrusted-model runs; co-resident sharding remains the simpler default. The vsock client sits behind a thin channel interface; nothing above it may know its transport.

## 8. Host story: `doctor`

Implemented: `inspect-ranges doctor` verifies a host end to end (KVM/tun/vhost-net/**vhost-vsock** devices, Docker/Compose versions, cgroup v2, br_netfilter off, IPv6, image tooling, kernel readability), with exact fixes; `doctor --fix-script | sudo sh` applies the runnable subset (root-guarded, `SUDO_USER`-aware, review-first by construction — doctor itself never runs privileged, or its user-scoped checks would lie). Supported hosts: metal instances and c8i/m8i/r8i nested-virt (both devbox-provisionable); any Linux x86_64 with KVM for workstations; Mac develops via Remote-SSH to a devbox. Only `up` needs KVM — `validate`/`render`/authoring run anywhere.

## 9. Evidence and scoring integrity (designed, mostly unbuilt)

The oracle sees everything; defenders see only what the agent transmits. pcap capture happens on bridges in the range container — outside every VM including the agent's — giving the eval-correct asymmetry: the agent's sanctuary is invisible to in-range defenders (no management NIC to discover) but fully observed by scoring. Evidence (pcaps, consoles, artifacts) streams off-instance as generated, which is what makes the security posture's detection-over-prevention stance a property rather than a plan — hence backlog item 2 and the §7 dependency. Scoring material stays off-instance where range content allows; readiness gates on cloud-init completion per VM, not daemon-up (a daemon-up range can be an *unenforced* range — observed directly in the networking spike).

## 10. Performance envelope (all measured, metal)

| Operation | Measured |
|---|---|
| 1 Linux VM range: compose up → SSH-able | 15.3 s cold |
| 4-VM two-segment range: up → all daemons | 16 s |
| 4-VM range fully enforced (cloud-init done) | 50 s |
| vsock exec round-trip (median / p95) | 1.1 ms / 3.5 ms |
| `docker exec` (comparison) | 44.5 ms / 47.2 ms |
| vsock file inject / extract (100 MB) | 398 / 696 MB/s |
| qemu-ga file transfer (Windows) | ~0.6 MB/s (bulk → ISO hot-plug) |
| Windows Server 2022 unattended install → golden | 189 s |
| Windows boot → exec-responsive | 6.5 s |
| Windows 4 GB snapshot save / restore | 10.1 s / 1.4 s |
| Agent VM boot → daemon ready (baked image) | 9.6 s |
| Full `inspect eval` vs 2-VM range (boot→solve→score→teardown) | 15–16 s |
| Lazy-pull boot (HTTP backing, no pre-download) vs local | 10.2 s vs 9.8 s; warm reboot 7.2 s (+11 MB) |

Not yet measured: boot storms / gp3 saturation, nested-virt (c8i) vs metal deltas, cold-start economics (warm pools, Fast Snapshot Restore) — handoff §13 experiments 3–5.

## 11. Implemented vs designed — the ledger

| Component | Status | Evidence |
|---|---|---|
| Schema v0.1 + `validate` + JSON Schema | **Implemented** | `schema.py`, 58 tests, six examples green |
| `doctor` + `--fix-script` | **Implemented** | CLI + tests; in daily use on the devbox |
| Devbox tooling (metal + nested) | **Implemented** | `devbox/` |
| Unprivileged libvirt-in-Docker runtime | **Demonstrated** (spike) | l2-attach, net-compile |
| Compiled networking (IPAM→nftables) | **Demonstrated** (spike-grade compiler) | net-compile, 9/9 checks |
| vsock exec/file plane | **Demonstrated** (prototype daemon) | vsock-exec |
| Windows guests + qemu-ga + snapshots | **Demonstrated** | win-guest |
| Sandbox provider (`SandboxEnvironment`) + `self_check` | **Demonstrated** (spike): `inspect eval` end-to-end, accuracy 1.0 in ~15 s; `self_check` 41/44 (all 3 failures = daemon-as-root permission semantics) | [e2e-provider spike](../spikes/e2e-provider/README.md) |
| Production vsockd (idempotent, validated, hostile-tested) | Designed | guest-exec-lessons punch list |
| Evidence streaming off-instance | Designed | backlog item 2; §7 dependency |
| Image pipeline (Packer CI, ORAS registry) | Designed | handoff §7 |
| QEMU device minimization + seccomp + AppArmor | Designed | backlog items 3, 6 |
| Deferred schema sections (attack_path, goals, variables, defense, guest config) | Deliberately deferred | schema-v0.1-scope deferral table |
| Remote HostProvider path | Deferred with triggers | host-provider |
| KubeVirt / Proxmox / EC2-routed backends | Future | handoff §9 (capability declarations) |

## 12. Open questions for reviewers

1. **Inspect sharding mid-run sync** (§7) — the one external dependency load-bearing for the security posture.
2. **ACL expressiveness**: v0.1's single router-level vocabulary deliberately drops subnet NACL semantics (translated at carve time) — is that the right v1 cut for ranges you want to run?
3. **libvirtd itself**: we use a thin slice of a heavyweight daemon; driving QEMU directly would shrink the range container's surface at reimplementation cost. Parked until the provider's real libvirt usage is known.
4. **Agent-boundary strength**: is jailed-minimal-QEMU acceptable for the threat models you care about, or should the rust-vmm agent-VM option be scheduled rather than recorded?
5. **The deferral table** (schema-v0.1-scope): does any deferred section need to move up for your use cases — particularly `goals`/oracles for scoring?
6. **Dual-use posture** (handoff §12): tooling public, generation pipelines/held-out content controlled — unchanged by this architecture, but review-worthy alongside it.

## 13. Queued confirmation spikes

Architecture claims that are believed sound but not yet demonstrated; each gets a spike once the review copy settles.

1. **Active Directory range** — boot `goad-light` (or a minimal DC + member join) through our pipeline. The risk is not KVM (AD forests run on it routinely) but our own inventions: golden-image clones vs `sysprep /generalize` (and its interaction with memory-snapshot restore), cross-host provisioning ordering (DC promoted and ready before members join, reboots included), compiled DNS delegating to the in-range DC, and qemu-ga reliability across promotion reboots.
2. **Inspect sharding mid-run log sync** — the open question in §12 item 1, confirmable with a small sharded run; load-bearing for continuous off-instance evidence in the co-resident topology.
3. **Evidence streaming path** — §9 is designed, unbuilt; spike the minimal version (per-segment pcap + console to durable append-only storage, bypassing the scaffold).
4. **EBS/FSR cold start** — the fleet distribution path (image-distribution.md) is designed from documented AWS behavior; measure an actual lazy-start boot, since only the HTTP lazy-pull path has numbers.

## 14. Reading map

Decision records: [agent-containment](agent-containment.md) (security), [host-provider](host-provider.md) (deployment), [docker-provider-reuse](docker-provider-reuse.md) (what we port), [schema-v0.1-scope](schema-v0.1-scope.md) (spec), [guest-exec-lessons](guest-exec-lessons.md) (exec contract). Evidence: [l2-attach](../spikes/l2-attach/README.md), [vsock-exec](../spikes/vsock-exec/README.md), [net-compile](../spikes/net-compile/README.md), [win-guest](../spikes/win-guest/README.md) — each reproducible via its `run.sh`. Background: [the design handoff](../inspect_ranges_handoff.md), [survey](survey.md), [range-yaml-swag](range-yaml-swag.md), the six examples under [ranges/](ranges/).
