---
type: document
title: attack-range-windows — source note
status: draft
tags: [inspect-ranges, range-example, provenance]
timestamp: 2026-09-30
---

# attack-range-windows — source note

Translation of Splunk attack_range v5's AWS `splunk_windows` template (`github.com/splunk/attack_range`, Apache-2.0, fetched 2026-09-30). The instrumented/blue example: its entire purpose is telemetry (endpoint logs → Splunk), which forces a `defense.telemetry` section and a detection-flavored oracle that none of the red-only examples need.

## Where each fact comes from (vendored in `upstream/`)

| range.yaml section | Source | Detail |
|---|---|---|
| shared password, ip_whitelist, provider | `splunk_windows_aws.yml` `general`/`aws` | changeme123!, 0.0.0.0/0, eu-central-1 |
| splunk host (AMI, t3.xlarge, .10, ubuntu) | server entry `splunk` | ami ubuntu-jammy-22.04 owner 099720109477; `ip_last_octet: 10` |
| Splunk version + role | role `P4T12ICK.ludus_ar_splunk` vars | splunk 10.2.2 tgz URL |
| guacamole brokering (ssh→splunk:22, rdp→win:3389) | role `P4T12ICK.ar_guacamole` vars | hostnames 10.0.2.10/.11, users ubuntu/Administrator |
| win host (AMI, t3.large, .11) | server entry `win` | Windows_Server-2022-English-Full-Base, owner 801119661308 |
| log forwarding target | role `P4T12ICK.ludus_ar_windows` vars | `ludus_ar_windows_splunk_ip: 10.0.2.10` |

## Tagged defaults / judgment calls

- Subnet 10.0.2.0/24 marked to-verify: both hosts sit at 10.0.2.x via `ip_last_octet` and the guacamole vars, but the VPC/subnet CIDR itself is set in attack_range's terraform, not this template.
- Telemetry source list "Sysmon/WinEventLog/PowerShell" is attack_range's documented behavior (v5 blog + role name), to-verify against the `ludus_ar_windows` role — the template only shows the role reference and Splunk IP.
- Splunk web port 8000: product default, not in the template.
- The detection-oriented goal/oracle is ours; attack_range scores nothing.
- `defense.tier: D2` is our classification (telemetry recorded, not acted on).

## To-verify

- Exact telemetry sources installed by `P4T12ICK.ludus_ar_windows` (read the role).
- v5 cloud-only claim (Splunk v5 blog; local Vagrant deprecated) — confirm before assuming no local build path.

## What this example exercises in the schema

**Telemetry as first-class config** (source → collector → sink), a **management-plane ingress allowlist** (`ip_whitelist` — outside-in access, the inverse of egress posture), single-template **shared-credential variables**, cloud AMI-style image references alongside box/ISO styles in other examples, and an oracle that inverts the usual direction (did the *defense* see it).
