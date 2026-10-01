---
type: decision
title: "Schema v0.1 scope: strict runtime core only; everything half-designed is excluded, not quarantined"
status: accepted
tags: [inspect-ranges, range-yaml, schema, decision]
timestamp: 2026-10-01
---

# Schema v0.1 scope: strict runtime core only; everything half-designed is excluded, not quarantined

*Decision record for the first implemented `range.yaml` schema (`src/inspect_ranges/schema.py`, `inspect-ranges validate` / `inspect-ranges schema`). Supersedes the scoping question left open by [range-yaml-swag](range-yaml-swag.md): the swag described everything a range must eventually express; v0.1 commits only to what the runtime demonstrably consumes (per [the net-compile spike](../spikes/net-compile/README.md)).*

## Decision

- **v0.1 sections: `range` (identity + provenance), `networks`, `routers` (with the ACL), `hosts`, `attacker`.** Validation is uniformly strict: unknown keys are errors everywhere, no reserved-key tier, no passthrough. Everything in the schema is consumed by the runtime; nothing is decorative.
- **Deferred material is excluded entirely** — not parsed, not warned about. The six example ranges were purified to validate cleanly; carved content sits verbatim (comments preserved) in each example's `deferred.yaml`, clearly headed as not-valid-range.yaml, for mechanical migration when the real designs land. `schema_version` (enforced, literal `"0.1"`) is the migration seam.
- **No sentinels in typed values**: `to-verify` and friends live in comments only; typed slots carry real (possibly `default:`-tagged) values.

## Deferred sections — why, and what unblocks each

| Deferred | Why not now | Unblocking input |
|---|---|---|
| `attack_path` | Edge-type vocabulary doesn't exist (MHBench covers only credential-reuse/privesc; AD tradecraft edges are ours to define) | Building GOAD-class ranges; scoring experience |
| `variables` / generation | The whole L2 layer (randomization → topology generation) needs real thinking | Range-building experience; the generation-policy design effort |
| `goals` / oracles | Oracle language unclear (flags, env checks, Splunk searches all appear); scorers live in Inspect tasks anyway, so nothing blocks on it | Real scorers written against running ranges |
| `defense` (incl. per-host toggles, telemetry) | D0–D5 is a vocabulary, not yet an implementable schema | Implementing D2+ ranges |
| `vulnerabilities` / `misconfigurations` | Vocabulary question (CVE ids vs classes vs named roles) open since swag §5 | A provisioning layer that consumes them |
| guest config (`users`, `services`, `provisioning`, `data`, host `dns`, `roles`, `scheduled_activity`) | The L4 provisioning layer doesn't exist; schema would be fiction | The image/provisioning pipeline design |
| `management`, `lifecycle`, `replication` | Operator/runtime policy, not range semantics; partially owned by the sandbox/deployment layer | Sandbox provider implementation |
| `count:`/`ip_start:` expansion | Deliberately out (user decision): v0.1 has zero expansion semantics; mhbench is unrolled by hand | Revisit with the generation layer |
| `networks[].acl` (subnet NACLs), `ingress`, `user_accessible` | One ACL vocabulary chosen for v0.1 (below); operator ingress and attacker-placement flags are policy, not substrate | Backend capability work; operator-access design |

## Normalizations applied to the core (each tagged in the examples with provenance comments)

- **One ACL vocabulary, on routers**: `routers[].acl: [{from, to, allow: ["proto/port" | "proto/lo-hi"]}]` — default-deny, stateful; the enforcement point the net-compile spike proved (generated nftables on the router guest). cyris's `forwarding` and mhbench's subnet NACLs are translated into it (originals parked in deferred.yaml). Port *ranges* were forced into the syntax by mhbench's `tcp 1-65535`.
- **Backend-neutral resources**: `{cpus, memory_mb, disk_gb?}`; OpenStack flavors and EC2 instance types translated, upstream names kept as comments.
- **Explicit attachment**: `interfaces` required on every guest (vulhub's implicit docker-bridge attachment made explicit).
- **`image` required on hosts** (goad/attack-range values promoted from comments); routers may omit it (default router appliance).
- **Attacker**: `host:` foothold XOR a dedicated box (`interfaces` required, `name` defaults to `attacker`); `entry ∈ {external, assumed-breach, operator}`; `egress ∈ {none, open}`, default `none`.
- **DNS stays in core as the union of the three observed shapes** (`records` / `nameservers` / `authoritative`+`forwarder`) — all three are substrate networking the compiler must realize, forced by vulhub, mhbench, and goad respectively.

## Consequences

- The architecture document's spec section can state: *the core is normative and demonstrated; these are the deliberately open design questions* — inviting review on the hard parts instead of defending premature answers.
- Anyone reading an example `range.yaml` sees only committed, validated, runtime-backed schema; everything else is explicitly labeled as awaiting design in `deferred.yaml`.
- The JSON Schema (`inspect-ranges schema`) can be published for editor completion/validation without committing to anything unbuilt.
