---
type: document
title: cyris-basic — source note
status: draft
tags: [inspect-ranges, range-example, provenance]
timestamp: 2026-09-30
---

# cyris-basic — source note

Translation of CyRIS's annotated reference definition `examples/full.yml` (`github.com/crond-jaist/cyris`, BSD-3-Clause, fetched 2026-09-30), with `examples/basic-multi_host.yml` vendored alongside for the multi-hypervisor-host pattern. CyRIS is KVM/libvirt-native — the closest substrate precedent for the inspect_ranges sandbox — and contributes three schema ideas: `entry_point`, interface-level network membership (`members: guest.eth0`), and a per-guest `tasks:` layer.

## Where each fact comes from (vendored in `upstream/`)

| range.yaml section | Source | Detail |
|---|---|---|
| hypervisor hosts, virbr 192.168.122.1, cyuser | `full.yml` `host_settings` | one KVM host (localhost) |
| base images + management IPs | `full.yml` `guest_settings` | desktop .122.50, webserver .122.51, firewall .122.10; libvirt XML configs |
| all users/passwords | `full.yml` tasks | daniel/danielpass + root abcd1234 (desktop); daniel/JamesBond + root new-root-password (webserver); robot.abc/abcrb1357 (firewall) |
| packages, pcap/malware/ssh-attack emulation, content copies, program execution, iptables rulesets | `full.yml` tasks | verbatim, in task order |
| segments, gateways, forwarding rule | `full.yml` `clone_settings.topology` | office=desktop.eth0 gw firewall.eth0; servers=webserver.eth0 gw firewall.eth1; `src=office dst=servers dport=25,53` |
| entry point, clone counts, range_id | `full.yml` `clone_settings` | desktop `entry_point: yes`; `instance_number: 2`; range_id 125 |

## Tagged defaults / judgment calls

- `goals:` — full.yml plants `flag.txt` at /root on desktop and webserver but defines no scoring; flag capture is our (conventional) reading.
- `mode: isolated` on both segments — CyRIS routes inter-segment traffic through the firewall guest; the libvirt network mode is our realization choice.

## To-verify

- Cloned-range subnet CIDRs (CyRIS auto-assigns per range_id/instance; format documented in the CyRIS paper, not in this file).
- Guest OS distro (tasks use `yum`, so RPM-based; exact distro lives in the referenced base-image XML, not the definition).
- Attack path from desktop to webserver given only ports 25/53 are forwarded — the reference file is a feature demo, not necessarily a solvable range.

## What this example exercises in the schema

A **gateway/firewall as a guest VM** (vs KYPO's dedicated router object) with **explicit forwarding rules**, the `entry_point` foothold marker, **interface-level network membership**, a rich **provisioning-tasks layer** (accounts, packages, content, execution order incl. `after_clone`), **planted forensic noise** (pcap traces, dummy malware, attack logs), and **whole-range replication** (`instances: 2`) — plus multi-hypervisor placement (`basvm_host`) from the basic-multi_host variant.

> Schema v0.1 carve-out (2026-10-01): sections awaiting schema design (goals, attack_path, guest config, ...) moved verbatim from `range.yaml` to [`deferred.yaml`](deferred.yaml); see [schema-v0.1-scope](../../schema-v0.1-scope.md).
