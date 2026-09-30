---
type: document
title: vulhub-zabbix — source note
status: draft
tags: [inspect-ranges, range-example, provenance]
timestamp: 2026-09-30
---

# vulhub-zabbix — source note

Translation of `vulhub/zabbix/CVE-2016-10134` (`github.com/vulhub/vulhub`, MIT, cloned 2026-09-30). Chosen as the minimal/smoke-test example over a single-container CVE because it is a genuine 4-host service stack (web, server, agent, database) while still booting in seconds upstream. Upstream is docker-compose; per the project decision (2026-09-30), we express it substrate-agnostically — the images/services are what we replicate, not the container runtime.

## Where each fact comes from (vendored in `upstream/`)

| range.yaml section | Source | Detail |
|---|---|---|
| four hosts, images, commands | `docker-compose.yml` | server + agent from `vulhub/zabbix:3.0.3-server` (commands `server`/`agent`), `mysql:5`, `vulhub/zabbix:3.0.3-web` |
| service wiring + credentials | `docker-compose.yml` env vars | DATABASE_HOST=mysql, root/root, db `zabbix`; web's ZBX_SRV_HOST=server:10051; agent's ZBX_SRV_HOST=server |
| mysql seeding | `docker-compose.yml` | `./database/` mounted to `/docker-entrypoint-initdb.d/` |
| exposed web port | `docker-compose.yml` | `8080:80` (web UI on container port 80) |
| CVE, guest login, exploit chain | `README.txt` | SQLi in latest.php `toggle_ids`, unauth via jsrpc.php; guest/empty login; session hijack → RCE per exploit-db 40237/40353 |

## Tagged defaults (invented, not upstream)

- Network `lab` with CIDR 10.10.10.0/24, DHCP, `mode: isolated` — upstream uses the default docker bridge with name-based DNS.
- Zabbix server port 10051 and agent port 10050 (standard Zabbix ports; compose relies on defaults — only web's `ZBX_SRV_PORT=10051` env var states one of them).
- Guest OS "linux" per host — upstream pins container images, not distros.
- Attacker host, `egress: none`, and the RCE goal/canary oracle — upstream has no attacker or scoring.

## To-verify

- Nothing load-bearing; the range is fully specified by the two upstream files. (If rebuilt as VMs rather than containers, the vulhub images' internal build steps — Zabbix 3.0.3 from source with guest login enabled — would need porting; see the vulhub `zabbix` base image.)

## What this example exercises in the schema

The **minimal case**: one flat network, name-based service discovery (DNS records instead of static IPs), inter-service credentials as config, a **real public CVE** as the entry vuln, no defense, and a canary-style oracle. The floor every schema draft must express trivially.
