---
type: document
title: goad-light — source note
status: draft
tags: [inspect-ranges, range-example, provenance]
timestamp: 2026-09-30
---

# goad-light — source note

Translation of GOAD-Light from `github.com/Orange-Cyberdefense/GOAD` (`ad/GOAD-Light/`, GPL-3.0, cloned 2026-09-30). This is the testbed behind the cochise autonomous-AD-pentest evaluation (arXiv:2502.04227, ACM TOSEM — that paper used full GOADv3; Light is the 3-VM variant). It is the example that forces AD realities into the format: static DC addressing, AD-integrated DNS chains, identity data (users/groups/ACLs/SPNs) as first-class configuration, and per-host defender toggles.

## Where each fact comes from (vendored in `upstream/`)

| range.yaml section | Source file | Detail |
|---|---|---|
| host groups, role tags (adcs/iis/mssql/webdav), defender_on/off, update on/off | `inventory.ini` | dc01+dc02 defender_on, srv02 defender_off; adcs→dc01; iis/mssql/mssql_ssms/webdav→srv02; parent_dc dc01, child_dc dc02 |
| hostnames, domains, per-host vulns + vuln vars, local admin passwords, MSSQL config | `config.json` | kingslanding/winterfell/castelblack; vulns lists quoted per host; sa password, executeas chains |
| domain data: users, passwords, groups, SPNs, OUs, ACL-abuse chain, anonymous RPC | `config.json` `domains` | ACL chain quoted in range.yaml comment; SPNs on sql_svc/sansa/jon |
| IPs and DNS chain | `provider-vmware-inventory.ini` | .10/.11/.22; `dns_domain=dc01` for dc01+dc02, `dns_domain=dc02` for srv02; forwarder 1.1.1.1 (from `inventory.ini` [all:vars]) |
| VM images and sizing | `Vagrantfile` | StefanScherer/windows_2019 v2021.05.15; 2cpu/3GB (DCs), 2cpu/6GB (srv02) |
| task prompt + OSINT username list (`tasks.yaml`) | `upstream/cochise/` (from github.com/andreashappe/cochise, MIT) | verbatim `scenario.md` pentest objective + rules, and the 80-name `osint_users.txt` planted on the attacker host |

## Tagged defaults / judgment calls

- `ip_range: 192.168.56` — the inventory templates `{{ip_range}}`; 192.168.56 is the VirtualBox host-only convention. Any /24 works if all three octet-suffixes and the DNS chain move together.
- `goals:` — GOAD defines no scoring; domain-admin objectives follow the assumed-breach framing of the cochise evaluation (arXiv:2502.04227).
- `attacker:` — GOAD ships no attacker VM; assumed-breach Kali on the lab subnet is the standard usage.
- `attack_path:` — GOAD seeds many paths by design; the listed one is a canonical example, each edge traceable to a seeded vuln. Not a unique solution.
- `defense.tier: D4` is our classification (real Defender, autonomous), per the D0–D5 spectrum in [../../range-yaml-swag.md](../../range-yaml-swag.md) §0.

## To-verify

- Runtime egress requirements (build needs internet; play-time posture is an eval decision).
- Which principal `asrep_roasting.ps1` targets (script vendored upstream but not in our sparse checkout; do not name the AS-REP-roastable user without reading it).
- Account-lockout policy: active in the cochise paper's runs; not confirmed in these GOAD-Light files.

## License note

GOAD is GPL-3.0. `upstream/` files are verbatim copies for provenance (GPL permits copying with notice; LICENSE at repo root). Our `range.yaml` is a factual description of the lab's configuration.

## What this example exercises in the schema

An `active_directory:` block (domains, trust shape, identity data), **static addressing + authoritative DNS chain** as hard constraints, per-host **defender toggles** (D1↔D4 within one range), **scheduled bot activity** (dc02's scripts), vulns expressed as **named roles with variables** rather than CVEs, and the Kerberos **clock-sync lifecycle constraint** (snapshot/resume clock skew produces auth failures that masquerade as agent failure).

> Schema v0.1 carve-out (2026-10-01): sections awaiting schema design (goals, attack_path, guest config, ...) moved verbatim from `range.yaml` to [`deferred.yaml`](deferred.yaml); see [schema-v0.1-scope](../../schema-v0.1-scope.md).
