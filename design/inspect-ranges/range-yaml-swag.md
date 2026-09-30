---
type: document
title: range.yaml — draft schema swag (v0.1)
audience: inspect-ranges development
status: draft
tags: [inspect-ranges, range-yaml, schema, networking]
timestamp: 2026-09-30
---

# range.yaml — draft schema swag (v0.1)

*A working strawman, not a design. Its job is to be rich enough to faithfully express the six example ranges (see the index in this folder) and to make explicit what a range definition must be able to say — especially about networking. Every section was forced into existence by at least one example; nothing here is speculative. The target substrate is a new libvirt-based Inspect sandbox: Docker/Compose compatibility is a non-goal.*

## 0. Two working vocabularies

The schema leans on two decompositions we use throughout this folder, stated here so the document is self-contained.

**Range anatomy, L1–L9** — the layers any range facility must supply, each with a distinct failure mode:

| Layer | Concern | Failure mode if missing |
|---|---|---|
| L1 | Topology definition (machines, networks, trust) | unvalidatable spec |
| L2 | Generation policy (how new instances are minted, at what difficulty) | variety without calibration |
| L3 | Compilation & provisioning (definition → booted, resettable machines) | flake, drift, image sprawl |
| L4 | Guest config & vulnerability injection | unrealistic vuln density |
| L5 | Attack-path planting (objective reachable *by construction*) | uninterpretable zeros |
| L6 | Attacker interface (how the agent acts on the network) | measuring the scaffold, not the model |
| L7 | Ground truth & oracle (what actually happened, independent of self-report) | LLM-judged outcomes |
| L8 | Lifecycle: reset, isolation, containment | cross-run contamination; escapes |
| L9 | Defense | non-reproducibility |

**Defense spectrum, D0–D5** — how much the environment fights back, ordered by reproducibility cost:

- **D0** — no defenders (MHBench, vulhub, CyRIS examples here)
- **D1** — static hardening (host AV baseline, disabled legacy protocols)
- **D2** — passive detection: telemetry logged, not acted on (KYPO command logging, attack_range's Sysmon→Splunk)
- **D3** — deterministic scripted response (event-handler defenders; reproducible)
- **D4** — real autonomous EDR (GOAD with Microsoft Defender on; realistic, not reproducible run-to-run)
- **D5** — adaptive/LLM defender (co-scales with the attacker; least reproducible)

## 1. Shape

```yaml
range:        # identity + provenance (name, title, schema_version, description, source, seed)
variables:    # per-instance randomization (ports, flags, credentials, ip_range)
networks:     # subnets: name, cidr, mode, dhcp, dns, acl, user_accessible, ingress
routers:      # explicit gateways: interfaces (network+ip), forwarding rules; may be a guest VM
hosts:        # guests: os/image/resources, interfaces (network+ip), users, services,
              #   vulnerabilities, misconfigurations, provisioning, data, defense toggles
active_directory:  # (windows ranges) domains, DCs, identity data, ACLs, SPNs
attacker:     # foothold: entry (external|assumed-breach|operator), host/interfaces, egress, tools
defense:      # tier D0–D5, description, telemetry (source→collector→sink), per-host toggles
goals:        # objectives + oracles (flag, exfiltrate, privilege, execute, detection)
attack_path:  # planted path as a first-class machine-readable edge list
management:   # harness plumbing that exists but is out of play
replication:  # instance/clone counts
lifecycle:    # isolation, reset, clock_sync, notes
```

Mapping to the L1–L9 decomposition (§0): `networks`+`routers`+`hosts.interfaces` = L1 topology; `variables` = the hook for L2 generation policy; `hosts.image`/`resources` = L3 provisioning; `hosts.{users,services,vulnerabilities,misconfigurations,provisioning,data}` = L4 guest config (keeping exploitable vulns and misconfigurations as distinct lists — real intrusions lean heavily on the second); `attack_path` = L5 (as an edge list, not "a path exists"); `attacker` = L6; `goals[].oracle` = L7; `lifecycle`+`management` = L8; `defense` = L9 with the D0–D5 vocabulary.

**Companion file — `tasks.yaml`.** Each example range ships a sibling `tasks.yaml`: the task prompts an agent is given against this range, as example-dataset seeds. Where the upstream ecosystem defines tasks they are verbatim (KYPO's `training.json` levels with answers and reference solutions; Incalmo's bash/Incalmo attacker pre-prompts for MHBench; cochise's `scenario.md` pentest objective for GOAD); where it doesn't (vulhub, CyRIS, attack_range), tasks are tagged as ours and grounded in what the definition actually plants. Kept separate from `range.yaml` deliberately: one range serves many tasks/datasets (KYPO's milestone ladder, MHBench's two elicitation arms, attack_range's technique-per-sample family), and the range/dataset split mirrors Inspect's sandbox/task split.

Two conventions worth keeping from the start: **provenance in the definition** (`range.source` names the artifact, license, and files a definition derives from — and `seed` + generator version pin generated ranges so any instance regenerates bit-for-bit), and **tagged defaults** (`# default:` / `to-verify` comments distinguish sourced values from invented ones).

## 2. What networking must be expressible — and its libvirt realization

Each row is forced by at least one example (right column). This is the requirements list for the sandbox's network layer.

| Requirement | libvirt realization | Forced by |
|---|---|---|
| Multiple named subnets with **CIDRs** | one `<network>` per subnet; `<ip address netmask>` | all six |
| **Static IP per guest per network** | `<host mac ip>` DHCP reservations, or guest-side config; MAC assignment implied | KYPO (`net_mappings`), MHBench (`fixed_ip_v4`), GOAD (DCs), attack_range (`ip_last_octet`) |
| Sequential IPs under `count:` expansion | reservation generator (base + index) | MHBench (`192.168.200.${index+10}`) |
| **DHCP vs static** per network | `<dhcp>` element present/absent | vulhub (DHCP fine) vs GOAD (DHCP breaks AD) |
| **Egress posture per network** (`isolated` / `nat` / `routed` / `open`) | `<forward mode>` absent (isolated), `nat`, `route`; `open`/bridged | vulhub+cyris (isolated) vs GOAD/attack_range (need egress at least at build) |
| **Explicit routers/gateways with per-network IPs** | a router *guest* with one NIC per network (KYPO/CyRIS style), or libvirt routed networks; router-as-guest is more faithful | KYPO (router object), CyRIS (firewall guest), MHBench (external router) |
| **Forwarding/firewall rules between segments** | iptables/nftables on the router guest; libvirt `nwfilter` for host-level rules | CyRIS (`src=office dst=servers dport=25,53`) |
| **Per-subnet ACLs** (default allow/deny + rules keyed by source/dest CIDR) | nwfilter per guest NIC, or router-guest firewall; OpenStack secgroups have no direct libvirt equivalent — must be compiled | MHBench (`security_rules.tf` asymmetric DMZ/corporate) |
| **Interface-level attachment** (`guest.eth0` on network X; multi-NIC/dual-homing) | multiple `<interface>` elements per domain | CyRIS (`members: desktop.eth0`), MHBench router, Incalmo's dual-homed webserver |
| **DNS**: per-network nameservers, name records, **guest-provided authoritative DNS chains** | dnsmasq per network (`<dns><host>` records, `<domain>`); for AD the *DC is the DNS server* — network DNS must point at a guest, and the chain (srv02→dc02→dc01→forwarder) must be expressible | vulhub (name-based discovery), MHBench (8.8.8.8), GOAD (AD-integrated chain + forwarder 1.1.1.1) |
| `/etc/hosts`-style aliases as guest config | provisioning layer, not network layer | KYPO (both roles) |
| **Network accessibility flags** (which networks the agent may attach to / see) | placement of the agent guest; no substrate primitive — a schema-level assertion the harness enforces | KYPO (`accessible_by_user: False`) |
| **Management plane** present but out of play | separate libvirt network + extra NIC per guest; excluded from scoring/visibility | MHBench (`manage_network` 192.168.198.0/24 + talk_to_manage), CyRIS (virbr0 mgmt bridge), KYPO (syslog to man host) |
| **Inbound allowlist from outside the range** (operator/management ingress) | host firewall on the libvirt bridge; or don't expose at all (Inspect exec replaces Guacamole-style access) | attack_range (`ip_whitelist`) |
| **Per-sample isolation** of the whole network set | unique libvirt network names/bridges per sample; the libvirt equivalent of the per-sample-SDN pattern UK AISI describes for its Proxmox ranges (arXiv:2603.11214) | all — mandatory (L8) |

Not yet needed by any example (defer, note only): VLANs on shared bridges (Ludus's `vlan:` model), multiple NICs on one network, IPv6, traffic shaping, inter-hypervisor overlay networking (CyRIS `basic-multi_host.yml` places guests on two KVM hosts — relevant at scale, not for these six).

### Background: why the current sandboxes can't express this

Inspect's existing sandbox providers (docker compose; `inspect_k8s_sandbox`'s compose→Helm/Cilium path) express *who can talk to whom* (named networks, `internal: true`, FQDN/CIDR egress allowlists) but none of the left column above: no CIDRs/IPAM, no static IPs, no routers, no multi-NIC, no custom DNS records, no per-subnet ACLs — the k8s converter rejects any compose network key beyond `driver: bridge`, and Docker's default local-network pool caps concurrent per-sample networks at ~30. That gap is the motivation for the libvirt sandbox; it is not a constraint on this schema.

## 3. `attack_path` — the load-bearing concept, and where it appears

Across everything surveyed, only one public runnable artifact emits the planted attack path as a first-class machine-readable object: **MHBench**, whose generated definitions carry `attack_paths` (per-step from/to host *and user* IDs), an `attack_graph`, and the goal each path terminates in — planted by `attack_path_generator.py` during generation, so solvability holds by construction (L5 satisfied by inspection of the corpus, not by trusting the paper). The concept recurs everywhere else in weaker forms, and the gradient is instructive:

| Form | Who | What it gives you |
|---|---|---|
| **Generated artifact** (edge list shipped with the range) | MHBench (alone) | solvability by construction + ground truth for scoring |
| **Pre-deploy validation** (path proved reachable, not emitted) | CRACK (TOSCA→Datalog), VSDL (SMT) — literature only | catches broken ranges before boot |
| **Scoring rubric** (human-authored step/milestone ladder) | UK AISI (32 steps / 9 milestones; private), KYPO (`training.json` level ladder with gated answers) | graded progress, but path not tied to topology objects |
| **The environment itself** (the sim *is* an attack graph) | CyberBattleSim, NASim | no separate artifact needed — and no emulation |
| **Scripted attacker** (path encoded procedurally) | Perry (five strategy state machines) | replayable, but data is implicit in code |
| **Absent** | GOAD (many seeded paths, none named), vulhub, CyRIS, attack_range | why `cyris-basic/tasks.yaml` must flag its cross-segment task's solvability as to-verify |

Why it earns a top-level schema section — it does four jobs at once: **constructive solvability** (a zero is a model failure, not a broken range); **graded scoring** (edges traversed beats binary capture); **defender scoring** (a working hypothesis: hold the planted path invariant and score defenders as edge closures against it — the only proposed answer we know of to "responsive defenders destroy solvability"); **difficulty calibration** (MHBench's path lengths, 2–15 steps, are a ready-made difficulty axis). And because range.yaml makes both the topology ACLs and the path machine-readable, `inspect_ranges` gets the CRACK idea nearly free as a lint pass: *every declared `attack_path` edge must be reachable under the declared `networks[].acl` and forwarding rules — before anything boots.*

Vocabulary caveat: MHBench's edges are only credential-reuse and privesc; no surveyed format has edge types for AD tradecraft (kerberoast-SPN, ADCS-ESC1, relay), which GOAD-class ranges need. The edge-type vocabulary is ours to define — the seeded-vuln `exercises:` cross-references in the six examples' `attack_path` sections are the starting point.

## 4. Ideas borrowed, with credit

- **KYPO** `topology.yml`: the backbone — `hosts`/`routers`/`networks(cidr, accessible_by_user)` + explicit IP mappings; also the `variables:` randomization layer (APG).
- **CyRIS**: `entry_point` foothold marker; `members: guest.eth0` interface-level attachment; the `tasks:` guest-config layer; forwarding rules; whole-range replication; BSD-3, libvirt-native.
- **MHBench/Perry**: asymmetric per-subnet security rules; `count:` + sequential IPs; management plane; planted credential-reuse paths distinct from exploitable vulns; environment-verified oracles.
- **GOAD**: identity data (users/groups/ACLs/SPNs) as configuration; per-host defender toggles; the DNS-chain pattern.
- **CybORG CAGE-2** (not among the six, CC0): per-subnet NACLs keyed by source subnet — the cleanest ACL *syntax* seen; our `networks[].acl` is shaped after it.
- **CRACK/VSDL** (literature): validate pre-deploy that the declared `attack_path` is reachable under the declared ACLs — a natural `inspect_ranges` lint pass, since both are machine-readable here.

## 5. Open questions (deliberately unresolved in v0.1)

1. **Vuln vocabulary**: CVE ids (vulhub), abstract classes (SecGen-style constraints), or named roles with vars (GOAD) — the six examples use all three; v0.1 lets `vulnerabilities[]` carry any, which is honest but unvalidatable.
2. **Windows/AD block**: `active_directory:` as a top-level section (current swag) vs per-host `domain:` fields. Identity data is range-scoped (users exist in the domain, not on a host), which argues top-level.
3. **Provisioning layer**: reference ansible roles by name (GOAD/attack_range/Ludus style) vs inline task lists (CyRIS style). Probably both, like the examples force.
4. **Goal/oracle language**: flags, environment checks (group membership), canary files, and Splunk-search detections all appear; the oracle likely stays code (a scorer ref), with `goals[]` declaring intent + target.
5. **How `variables:` interacts with generation** — KYPO randomizes values within a fixed topology; MHBench generates whole topologies (30 JSON networks in the repo). v0.1 covers the first; the second is the L2 layer and stays out of scope.
