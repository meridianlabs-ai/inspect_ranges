---
type: document
title: Upstream licenses and attribution
status: draft
tags: [inspect-ranges, licenses]
timestamp: 2026-09-30
---

# Upstream licenses and attribution

Each example range vendors verbatim copies of its source's configuration (and, where available, task/prompt) files under `ranges/<name>/upstream/`, for provenance and so tooling can read the originals alongside our `range.yaml` translation. All were fetched 2026-09-30. Copyright remains with the upstream authors; each project's full license text is at the linked repository root.

| Vendored under | Upstream project | Copyright | License |
|---|---|---|---|
| `ranges/vulhub-zabbix/upstream/` | [vulhub](https://github.com/vulhub/vulhub) (`zabbix/CVE-2016-10134/`) | Vulhub contributors | MIT |
| `ranges/kypo-demo/upstream/` | [kypo-crp-demo-training](https://gitlab.ics.muni.cz/muni-kypo-crp/prototypes-and-examples/sandbox-definitions/kypo-crp-demo-training) | 2020 Masaryk University | MIT |
| `ranges/cyris-basic/upstream/` | [CyRIS](https://github.com/crond-jaist/cyris) (`examples/`) | 2016–2021 Japan Advanced Institute of Science and Technology | BSD-3-Clause |
| `ranges/mhbench-equifax-small/upstream/` (topology, specs, playbook) | [MHBench](https://github.com/bsinger98/MHBench) | 2025 Brian Singer | MIT |
| `ranges/mhbench-equifax-small/upstream/incalmo-prompts/` | [Incalmo](https://github.com/cylabcyberautonomy/Incalmo) | 2025 Brian Singer | MIT |
| `ranges/goad-light/upstream/` (inventory, config.json, provider files) | [GOAD](https://github.com/Orange-Cyberdefense/GOAD) (`ad/GOAD-Light/`) | Orange Cyberdefense | GPL-3.0 |
| `ranges/goad-light/upstream/cochise/` | [cochise](https://github.com/andreashappe/cochise) | 2025 Andreas Happe | MIT |
| `ranges/attack-range-windows/upstream/` | [attack_range](https://github.com/splunk/attack_range) (`templates/aws/`) | Splunk Inc. | Apache-2.0 |

Notes:

- The GOAD files are unmodified copies of configuration data distributed under GPL-3.0; this folder redistributes them with attribution and this notice. Our `range.yaml`/`tasks.yaml`/`notes.md` are independent factual descriptions, not derivative code.
- `ranges/vulhub-zabbix/upstream/README.txt` and `ranges/goad-light/upstream/cochise/scenario.txt` are upstream Markdown files renamed to `.txt` (kept byte-identical).
- Our own files in this folder (every `range.yaml`, `tasks.yaml`, `notes.md`, and the documents at the folder root) carry this repository's license.
